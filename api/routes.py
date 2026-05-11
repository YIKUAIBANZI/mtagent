"""HTTP routes — v1 streaming endpoint per spec §5."""

from __future__ import annotations

import asyncio
import os
import time
import traceback
from datetime import datetime, time as dt_time, timedelta
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.context import TripContext
from agents.critic import Critic
from agents.planner import Planner, _pick_anchors, _synthesize_fallback_route
from agents.profiler import Profiler
from agents.rationale import build_rationale_for_anchors, build_rationale_for_day
from agents.tools import (
    batch_get_poi_details,
    check_business_hours,
    cluster_anchor_orbit,
    default_pace_for_traveler,
    filter_by_intent_constraints,
    generate_day_template,
    rank_by_traveler_type,
    search_pois,
)
from api import deps
from api.sse import format_event
from api.stub_llm import (
    resolve_planner_llm,
    resolve_planner_llm_stream,
    resolve_profiler_llm,
)
from dianping.client import DianpingClient
from dianping.schemas import DayPlan, RouteDraft, UserInput

router = APIRouter(prefix="/api")


class StreamRequest(BaseModel):
    free_text: str
    extra: Optional[dict] = None


@router.post("/plan/stream")
async def plan_stream(
    body: StreamRequest,
    client: DianpingClient = Depends(deps.get_client),
):
    """Run the full pipeline (Profiler → Planner → Critic) emitting SSE events
    per spec §5.2."""

    async def event_stream() -> AsyncIterator[str]:
        ctx = TripContext.create(user_input=UserInput(free_text=body.free_text))
        start_time = time.time()
        t0 = time.perf_counter()
        phases: dict[str, float] = {}

        def _stamp(name: str) -> None:
            phases[name] = round(time.perf_counter() - t0, 3)

        yield format_event("trip.started", {"trip_id": ctx.trip_id})

        # ----- Profiler -----
        try:
            yield format_event("profiler.start", {"phase": "正在理解需求..."})

            profiler = Profiler(llm_call=resolve_profiler_llm())
            profiler_out = await profiler.run(ctx)
            _stamp("profiler_done")

            yield format_event(
                "profiler.understood",
                profiler_out.understood.model_dump(mode="json"),
            )

            if body.extra and not profiler_out.ready_to_plan:
                _merge_extra(ctx, body.extra)
                if all(
                    getattr(ctx.intent, k) not in (None, "", 0)
                    for k in ("city", "days", "traveler_type")
                ):
                    profiler_out.ready_to_plan = True
                    profiler_out.missing_fields = []

            if not profiler_out.ready_to_plan:
                yield format_event(
                    "profiler.clarifying",
                    {"missing_fields": profiler_out.missing_fields},
                )
                yield format_event(
                    "trip.complete",
                    {
                        "trip_id": ctx.trip_id,
                        "duration_ms": int((time.time() - start_time) * 1000),
                        "status": "awaiting_clarification",
                    },
                )
                return

            yield format_event("profiler.ready", {})
        except Exception as exc:
            yield format_event(
                "error",
                {
                    "phase": "profiler",
                    "message": str(exc),
                    "stack_trace": traceback.format_exc()[-500:],
                },
            )
            return

        # ----- Planner (orchestrated step-by-step for fine-grained events) -----
        try:
            yield format_event("planner.start", {"phase": "正在挑选 POI..."})

            planner_llm = resolve_planner_llm()
            planner = Planner(
                client=client,
                llm_call=planner_llm,
                llm_call_stream=resolve_planner_llm_stream(),
            )

            intent = ctx.intent
            pace = intent.pace or default_pace_for_traveler(intent.traveler_type)
            templates = generate_day_template(
                days=intent.days,
                traveler_type=intent.traveler_type,
                pace=pace,
            )
            anchors = _pick_anchors(intent.city, intent.days, intent.must_visit)
            yield format_event(
                "planner.anchors",
                {
                    "anchors": [
                        {"name": a[0], "lat": a[1], "lng": a[2]} for a in anchors
                    ],
                },
            )
            yield format_event(
                "planner.rationale",
                build_rationale_for_anchors(intent, anchors),
            )

            all_categories = {
                c
                for tmpl in templates
                for slot in tmpl.slots
                for c in slot.category_pool
            }
            search_tasks = []
            for anchor_name, lat, lng in anchors:
                for cat in all_categories:
                    search_tasks.append(
                        search_pois(
                            client,
                            city=intent.city,
                            latitude=lat,
                            longitude=lng,
                            radius=5000,
                            categories=cat,
                            limit=25,
                        )
                    )
            results = await asyncio.gather(*search_tasks, return_exceptions=True)
            all_ids = set()
            for r in results:
                if isinstance(r, Exception):
                    continue
                all_ids.update(rec.openshopid for rec in r)

            _stamp("search_done")

            details = await batch_get_poi_details(client, list(all_ids))
            pois = list(details.values())
            _stamp("batch_get_done")
            yield format_event(
                "planner.candidates_loaded",
                {
                    "count": len(pois),
                    "preview": [
                        {
                            "openshopid": p.openshopid,
                            "name": p.name,
                            "categories": p.categories,
                        }
                        for p in pois[:6]
                    ],
                },
            )

            clusters = cluster_anchor_orbit(pois, k=intent.days, max_radius_km=5.0)
            start_date = intent.start_date or datetime.now().date()
            filtered_clusters = []
            for di, cluster in enumerate(clusters):
                day_date = start_date + timedelta(days=di)
                mid = datetime.combine(day_date, dt_time(12, 30))
                kept = [p for p in cluster if check_business_hours(p, mid)]
                kept = filter_by_intent_constraints(kept, intent)
                filtered_clusters.append(kept)
            ranked_clusters = [
                rank_by_traveler_type(c, intent.traveler_type)
                for c in filtered_clusters
            ]
            ctx.candidate_pois = [p for c in ranked_clusters for p in c]
            _stamp("cluster_done")
            yield format_event(
                "planner.clusters_ready",
                {"per_day_count": [len(c) for c in ranked_clusters]},
            )

            yield format_event(
                "planner.compose_start",
                {"phase": "正在编排路线...", "days": intent.days},
            )

            from agents.amap import AmapClient as _AmapClient
            from agents.planner import PlannerLLMError as _PlannerLLMError

            amap = _AmapClient(key=os.environ.get("AMAP_KEY", ""))

            # ----- v1.6: per-day concurrent compose with as_completed + on_partial -----
            partial_queue: asyncio.Queue = asyncio.Queue()

            async def _on_partial(day_idx: int, names: list[str]):
                await partial_queue.put((day_idx, names))

            sem = asyncio.Semaphore(3)

            async def _wrap(d: int):
                async with sem:
                    return await planner.compose_one_day(
                        day_idx=d,
                        intent=intent,
                        template=templates[d],
                        anchor=anchors[d],
                        day_cluster_pois=ranked_clusters[d],
                        amap=amap,
                        on_partial=_on_partial,
                    )

            try:
                tasks = [asyncio.create_task(_wrap(d)) for d in range(intent.days)]
                days_out: list[DayPlan] = [None] * intent.days  # type: ignore[list-item]
                segments_by_day: dict[int, list[dict]] = {}

                for fut in asyncio.as_completed(tasks):
                    # Drain any queued partials (best-effort, interleaves)
                    while not partial_queue.empty():
                        try:
                            pd, pn = partial_queue.get_nowait()
                            yield format_event(
                                "planner.day_partial",
                                {"day_index": pd, "names": pn},
                            )
                        except asyncio.QueueEmpty:
                            break

                    try:
                        d_idx, day_plan, segs = await fut
                    except _PlannerLLMError as plerr:
                        d_idx = plerr.day_idx
                        fallback_reason = str(plerr)
                        day_plan_list = _synthesize_fallback_route(
                            [templates[d_idx]],
                            [anchors[d_idx]],
                            [ranked_clusters[d_idx]],
                            intent,
                        )
                        day_plan = (
                            day_plan_list[0]
                            if day_plan_list
                            else DayPlan(
                                day_index=d_idx,
                                anchor_district=anchors[d_idx][0]
                                if d_idx < len(anchors)
                                else "",
                                stops=[],
                            )
                        )
                        day_plan.day_index = d_idx
                        _, segs = await _compute_day_transits(day_plan, intent, amap)
                        yield format_event(
                            "planner.day_done_fallback",
                            {"day_index": d_idx, "reason": fallback_reason},
                        )

                    days_out[d_idx] = day_plan
                    segments_by_day[d_idx] = segs

                    # Final drain before day_done
                    while not partial_queue.empty():
                        try:
                            pd, pn = partial_queue.get_nowait()
                            yield format_event(
                                "planner.day_partial",
                                {"day_index": pd, "names": pn},
                            )
                        except asyncio.QueueEmpty:
                            break

                    yield format_event(
                        "planner.day_done",
                        {
                            "day_index": day_plan.day_index,
                            "anchor_district": day_plan.anchor_district,
                            "stops": [
                                {
                                    "poi_name": s.poi.name,
                                    "poi_openshopid": s.poi.openshopid,
                                    "categories": s.poi.categories,
                                    "slot_name": s.slot.name,
                                    "arrival_time": s.arrival_time.strftime("%H:%M"),
                                    "leave_time": s.leave_time.strftime("%H:%M"),
                                    "avgprice": s.poi.avgprice,
                                    "star": s.poi.star,
                                    "longitude": s.poi.longitude,
                                    "latitude": s.poi.latitude,
                                }
                                for s in day_plan.stops
                            ],
                            "transit_segments": segs,
                        },
                    )
                    yield format_event(
                        "planner.rationale",
                        build_rationale_for_day(
                            intent,
                            day_plan.day_index,
                            day_plan,
                            anchors[day_plan.day_index][0]
                            if day_plan.day_index < len(anchors)
                            else "",
                        ),
                    )

                for d_idx, segs in segments_by_day.items():
                    if days_out[d_idx] is not None:
                        days_out[d_idx].transit_segments = segs

                days_out = [d for d in days_out if d is not None]
            finally:
                await amap._client.aclose()
            _stamp("compose_llm_done")
            _stamp("amap_done")
            yield format_event("planner.compose_done", {})

            # ----- v2: emit transit.updated for backward compat (old clients) -----
            for d_idx, segs in segments_by_day.items():
                yield format_event(
                    "transit.updated",
                    {"day_index": d_idx, "segments": segs},
                )

            # llm_data unused in stream path; keep stub for RouteDraft below.
            llm_data = {"summary": ""}

            route = RouteDraft(days=days_out, summary=llm_data.get("summary", ""))
            ctx.draft_route = route
            ctx.save()

            yield format_event(
                "planner.done",
                {
                    "summary": route.summary,
                    "route": route.model_dump(mode="json"),
                },
            )
        except Exception as exc:
            yield format_event(
                "error",
                {
                    "phase": "planner",
                    "message": str(exc),
                    "stack_trace": traceback.format_exc()[-500:],
                },
            )
            return

        # ----- Critic stub -----
        try:
            yield format_event("critic.start", {})
            critic = Critic()
            patches = await critic.run(ctx)
            _stamp("critic_done")
            yield format_event("critic.done", {"patches_count": len(patches)})
        except Exception as exc:
            yield format_event(
                "error",
                {"phase": "critic", "message": str(exc)},
            )

        yield format_event(
            "trip.complete",
            {
                "trip_id": ctx.trip_id,
                "duration_ms": int((time.time() - start_time) * 1000),
                "status": "ok",
                "phases": phases,
            },
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _merge_extra(ctx: TripContext, extra: dict) -> None:
    """Apply user-provided clarifying answers to ctx.intent."""
    if ctx.intent is None:
        return
    for k in ("city", "days", "traveler_type", "budget_level", "pace"):
        v = extra.get(k)
        if v not in (None, "", 0):
            setattr(ctx.intent, k, v)


@router.get("/plan/{trip_id}")
async def get_trip(trip_id: str):
    """Retrieve a saved TripContext by trip_id."""
    try:
        ctx = TripContext.load(trip_id)
        return ctx.model_dump(mode="json")
    except FileNotFoundError:
        raise HTTPException(404, f"trip not found: {trip_id}")


async def _compute_day_transits(day_plan, intent, amap):
    """Compute 4-mode transit for each consecutive stop pair in a day."""
    segments = []
    stops = day_plan.stops
    for i in range(len(stops) - 1):
        a = stops[i].poi
        b = stops[i + 1].poi
        options, recommended = await amap.get_transit_options(
            origin=(a.longitude, a.latitude),
            dest=(b.longitude, b.latitude),
            city=intent.city or "",
            traveler_type=intent.traveler_type,
        )
        segments.append(
            {
                "from_index": i,
                "to_index": i + 1,
                "options": {m: v.model_dump(mode="json") for m, v in options.items()},
                "recommended": recommended,
            }
        )
    return day_plan.day_index, segments
