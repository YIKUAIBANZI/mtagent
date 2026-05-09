"""HTTP routes — v1 streaming endpoint per spec §5."""

from __future__ import annotations

import asyncio
import json
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
from api.stub_llm import resolve_planner_llm, resolve_profiler_llm
from dianping.client import DianpingClient
from dianping.schemas import DayPlan, RouteDraft, Stop, TimeSlot, UserInput

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
        yield format_event("trip.started", {"trip_id": ctx.trip_id})

        # ----- Profiler -----
        try:
            yield format_event("profiler.start", {"phase": "正在理解需求..."})

            profiler = Profiler(llm_call=resolve_profiler_llm())
            profiler_out = await profiler.run(ctx)

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
            planner = Planner(client=client, llm_call=planner_llm)

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

            details = await batch_get_poi_details(client, list(all_ids))
            pois = list(details.values())
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
            yield format_event(
                "planner.clusters_ready",
                {"per_day_count": [len(c) for c in ranked_clusters]},
            )

            yield format_event("planner.compose_start", {"phase": "正在编排路线..."})

            payload = planner._build_compose_payload(
                intent, templates, anchors, ranked_clusters
            )
            raw_llm = await planner.llm_call(planner._system_prompt, payload)
            try:
                llm_data = json.loads(raw_llm)
            except json.JSONDecodeError:
                llm_data = {"days": [], "summary": ""}

            poi_index = {p.openshopid: p for p in ctx.candidate_pois}
            days_out = []
            for d, day_data in enumerate(llm_data.get("days", [])):
                stops = []
                for s in day_data.get("stops") or []:
                    pid = s.get("poi_openshopid")
                    poi = poi_index.get(pid)
                    if poi is None:
                        continue
                    slot_name = s.get("slot_name", "上午景点")
                    slot_def = next(
                        (slot for slot in templates[d].slots if slot.name == slot_name),
                        templates[d].slots[0],
                    )
                    stops.append(
                        Stop(
                            poi=poi,
                            slot=TimeSlot(
                                name=slot_name,
                                start=slot_def.start,
                                end=slot_def.end,
                            ),
                            arrival_time=slot_def.start,
                            leave_time=slot_def.end,
                        )
                    )
                days_out.append(
                    DayPlan(
                        day_index=day_data.get("day_index", d),
                        anchor_district=day_data.get(
                            "anchor_district",
                            anchors[d][0] if d < len(anchors) else "",
                        ),
                        stops=stops,
                    )
                )
            if not days_out or all(len(d.stops) == 0 for d in days_out):
                if any(ranked_clusters):
                    days_out = _synthesize_fallback_route(
                        templates, anchors, ranked_clusters, intent
                    )

            for d in days_out:
                yield format_event(
                    "planner.day_done",
                    {
                        "day_index": d.day_index,
                        "anchor_district": d.anchor_district,
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
                            }
                            for s in d.stops
                        ],
                    },
                )
                yield format_event(
                    "planner.rationale",
                    build_rationale_for_day(
                        intent,
                        d.day_index,
                        d,
                        anchors[d.day_index][0] if d.day_index < len(anchors) else "",
                    ),
                )

            # ----- v2: amap transit options for each day -----
            from agents.amap import AmapClient

            amap = AmapClient(key=os.environ.get("AMAP_KEY", ""))
            try:
                transit_tasks = [
                    _compute_day_transits(d, intent, amap) for d in days_out
                ]
                for coro in asyncio.as_completed(transit_tasks):
                    day_index, segments = await coro
                    yield format_event(
                        "transit.updated",
                        {"day_index": day_index, "segments": segments},
                    )
            finally:
                await amap._client.aclose()

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
