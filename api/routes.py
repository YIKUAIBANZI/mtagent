"""HTTP routes — v1 streaming endpoint per spec §5."""

from __future__ import annotations

import asyncio
import os
import time
import traceback
from datetime import datetime, time as dt_time, timedelta
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
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
    request: Request,
    client: DianpingClient = Depends(deps.get_client),
):
    """Run the full pipeline (Profiler → Planner → Critic) emitting SSE events
    per spec §5.2."""
    # v1.9 Stage 2: 注入 cookie 关联的 UserProfile (没有则 None, 走老路径)
    from agents.user_profile_store import get_profile

    cookie_key = _cookie_key(request)
    loaded_profile = get_profile(cookie_key) if cookie_key else None

    async def event_stream() -> AsyncIterator[str]:
        ctx = TripContext.create(user_input=UserInput(free_text=body.free_text))
        ctx.profile = loaded_profile
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

            # ── v1.10 Clarify Round ──────────────────────────────────────────
            from agents.questioner import QuestionGenerator
            from api.stub_llm import resolve_questioner_llm

            qg = QuestionGenerator(llm_call=resolve_questioner_llm())

            # 并行：生成问题 + 预取 POI
            q_task = asyncio.create_task(
                qg.generate(intent=ctx.intent, user_input=body.free_text)
            )
            prefetch_task = asyncio.create_task(_prefetch_amap_pois(ctx.intent, []))

            try:
                questions = await q_task
            except Exception:
                prefetch_task.cancel()
                questions = []
            ctx.clarify_questions = questions

            pre_pois_result = await prefetch_task
            if pre_pois_result:
                ctx.pre_fetched_pois = pre_pois_result
            ctx.save()

            if questions:
                yield format_event(
                    "clarify.question",
                    {
                        "idx": 0,
                        "text": questions[0].text,
                        "options": questions[0].options,
                    },
                )
                yield format_event(
                    "trip.complete",
                    {
                        "trip_id": ctx.trip_id,
                        "duration_ms": int((time.time() - start_time) * 1000),
                        "status": "awaiting_clarification",
                    },
                )
                return  # 等待 POST /answer
            # ── 无问题：直接进 variant 生成 ──────────────────────────────────
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

        # ----- v1.7 即时出发分流 (单日 / 半日 走三方案路径) -----
        # inline import 避免 formatter 删未引用 import
        from agents.planner_instant import (
            is_instant_window as _is_instant,
            load_city_pois_from_mock as _load_pois_instant,
            plan_one_variant as _plan_one_variant,
        )

        if _is_instant(ctx.intent):
            async for ev in _stream_instant_variants(
                ctx,
                start_time=start_time,
                phases=phases,
                stamp=_stamp,
                load_pois=_load_pois_instant,
                plan_one_variant=_plan_one_variant,
            ):
                yield ev
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
                    # P1.1: per-stop rationale, 主推荐 variant 默认 "main"
                    from agents.rationale import build_rationale_for_stop

                    for stop in day_plan.stops:
                        yield format_event(
                            "planner.stop_rationale",
                            build_rationale_for_stop(intent, stop, variant="main"),
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

        # ----- Critic (P1.2: real rule-based check) -----
        try:
            yield format_event("critic.start", {})
            critic = Critic()
            patches = await critic.run(ctx)
            _stamp("critic_done")
            if patches:
                yield format_event(
                    "critic.findings",
                    {
                        "count": len(patches),
                        "items": [
                            {"day": p.day, "stop_idx": p.stop_idx, "issue": p.issue}
                            for p in patches[:5]
                        ],
                    },
                )
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


class ClarifyAnswerRequest(BaseModel):
    idx: int
    choice: Optional[str] = None
    skipped: bool = False


@router.post("/plan/{trip_id}/answer")
async def submit_clarify_answer(
    trip_id: str,
    body: ClarifyAnswerRequest,
):
    """接收一条澄清回答。还有问题则返回下一条；全答完则触发 variant 生成。"""
    from agents.amap import AmapClient as _AmapClient
    from agents.planner import Planner as _Planner
    from dianping.schemas import ClarifyAnswer

    try:
        ctx = TripContext.load(trip_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="trip not found")

    ctx.clarify_answers.append(
        ClarifyAnswer(idx=body.idx, choice=body.choice, skipped=body.skipped)
    )

    answered = len(ctx.clarify_answers)
    total = len(ctx.clarify_questions)

    async def event_stream() -> AsyncIterator[str]:
        if answered < total:
            next_q = ctx.clarify_questions[answered]
            ctx.save()
            yield format_event(
                "clarify.question",
                {"idx": next_q.idx, "text": next_q.text, "options": next_q.options},
            )
            return

        yield format_event("clarify.done", {})

        intent = ctx.intent
        if ctx.clarify_answers:
            notes = []
            for ans in ctx.clarify_answers:
                if not ans.skipped and ans.choice:
                    q_text = (
                        ctx.clarify_questions[ans.idx].text
                        if ans.idx < len(ctx.clarify_questions)
                        else ""
                    )
                    notes.append(f"{q_text}→{ans.choice}")
            if notes:
                extra = "【用户补充偏好】" + "；".join(notes)
                intent = intent.model_copy(update={"extra_clarify_context": extra})

        amap = _AmapClient(key=os.environ.get("AMAP_KEY", ""))
        planner = _Planner(
            client=None,
            llm_call=resolve_planner_llm(),
            llm_call_stream=resolve_planner_llm_stream(),
        )
        ctx.save()

        # 若无 Amap 预取结果（landmark_must 模式），从 mock 加载本地 POI
        from agents.planner_instant import load_city_pois_from_mock as _load_mock

        base_pois = ctx.pre_fetched_pois or _load_mock(intent.city) or []

        try:
            async for chunk in _run_variants(ctx, intent, base_pois, amap, planner):
                yield chunk
        except Exception as exc:
            yield format_event("error", {"phase": "variants", "message": str(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# v1.9 Stage 2: UserProfile endpoints ---------------------------------------


def _cookie_key(request) -> str:
    return getattr(request.state, "cookie_key", "") or request.cookies.get(
        "mtagent_cid", ""
    )


@router.get("/user/profile")
async def get_user_profile(request: Request):
    """Return current cookie's UserProfile, or null if first visit."""
    from agents.user_profile_store import get_profile

    cookie_key = _cookie_key(request)
    profile = get_profile(cookie_key)
    return profile.model_dump(mode="json") if profile else None


class _UpdateProfileBody(BaseModel):
    modifiers: Optional[dict[str, bool]] = None
    interests_text: Optional[str] = None


@router.put("/user/profile")
async def update_user_profile(body: _UpdateProfileBody, request: Request):
    from agents.user_profile_store import upsert_profile

    cookie_key = _cookie_key(request)
    if not cookie_key:
        raise HTTPException(400, "no cookie_key — middleware not active?")
    profile = upsert_profile(
        cookie_key,
        modifiers=body.modifiers,
        interests_text=body.interests_text,
    )
    return profile.model_dump(mode="json")


# v1.9 Stage 3: Adjuster v1 SSE endpoint -----------------------------------


@router.post("/plan/{trip_id}/adjust")
async def adjust_trip(trip_id: str, body: dict):
    """Adjust an existing trip: replace_stop / remove_stop / regenerate_day / switch_variant.

    Stream SSE: adjust.thinking → adjust.<op>_xxx → adjust.done.
    """
    from dianping.schemas import AdjustRequest

    try:
        req = AdjustRequest.model_validate(body)
    except Exception as e:
        raise HTTPException(400, f"invalid adjust request: {e}")

    try:
        ctx = TripContext.load(trip_id)
    except FileNotFoundError:
        raise HTTPException(404, f"trip not found: {trip_id}")

    async def _gen():
        yield format_event(
            "adjust.thinking",
            {"operation": req.operation, "day_index": req.day_index},
        )
        async for ev in _stream_adjust_events(ctx, req):
            yield ev
        yield format_event("adjust.done", {"trip_id": ctx.trip_id})

    return StreamingResponse(_gen(), media_type="text/event-stream")


async def _stream_adjust_events(ctx: TripContext, req) -> AsyncIterator[str]:
    """Yield `adjust.*` SSE events for one AdjustRequest.

    不包含 adjust.thinking / adjust.done 包裹 — 调用方负责.
    refine endpoint 复用同一 generator.
    """
    from agents.adjuster import Adjuster, AdjusterError

    adjuster = Adjuster(llm_call=resolve_planner_llm())
    try:
        if req.operation == "replace_stop":
            result = await adjuster.replace_stop(
                ctx,
                day_index=req.day_index,
                slot_name=req.slot_name,
                user_hint=req.user_hint,
            )
            yield format_event(
                "adjust.stop_replaced",
                {
                    "day_index": req.day_index,
                    "slot_name": req.slot_name,
                    "old_oid": result["old_oid"],
                    "source": result["source"],
                    "new_stop": result["new_stop"].model_dump(mode="json"),
                },
            )
        elif req.operation == "remove_stop":
            day_plan = await adjuster.remove_stop(
                ctx, day_index=req.day_index, slot_name=req.slot_name
            )
            yield format_event(
                "adjust.stop_removed",
                {
                    "day_index": req.day_index,
                    "slot_name": req.slot_name,
                    "new_day_plan": day_plan.model_dump(mode="json"),
                },
            )
        elif req.operation == "regenerate_day":
            from agents.amap import AmapClient as _AmapClient
            from agents.planner import Planner as _Planner

            amap = _AmapClient(key=os.environ.get("AMAP_KEY", ""))
            planner = _Planner(
                client=None,
                llm_call=resolve_planner_llm(),
                llm_call_stream=resolve_planner_llm_stream(),
            )
            day_plan = await adjuster.regenerate_day(
                ctx,
                day_index=req.day_index,
                planner=planner,
                amap=amap,
                user_hint=req.user_hint,
            )
            yield format_event(
                "adjust.day_replaced",
                {
                    "day_index": req.day_index,
                    "new_day_plan": day_plan.model_dump(mode="json"),
                },
            )
        elif req.operation == "switch_variant":
            await adjuster.switch_variant(ctx, variant=req.variant)
            yield format_event(
                "adjust.variant_switched",
                {"variant": req.variant},
            )
        else:
            yield format_event(
                "adjust.error",
                {"reason": f"unknown operation: {req.operation}"},
            )
            return
        ctx.save()
    except AdjusterError as e:
        yield format_event("adjust.error", {"reason": str(e)})


# v1.9 Refine: 自由文本意图路由 SSE endpoint ----------------------------


class _RefineBody(BaseModel):
    user_text: str


@router.post("/plan/{trip_id}/refine")
async def refine_trip(trip_id: str, body: _RefineBody, request: Request):
    """自由文本 → A 偏好/B 调整/C 同句 路由.

    Stream SSE:
      refine.thinking → refine.routed
        → [refine.profile_updated]
        → [adjust.* 复用]
        → [refine.chat_reply]
      → refine.done
    """
    from agents.refiner import Refiner, build_trip_summary
    from agents.user_profile_store import get_profile, upsert_profile

    try:
        ctx = TripContext.load(trip_id)
    except FileNotFoundError:
        raise HTTPException(404, f"trip not found: {trip_id}")

    cookie_key = _cookie_key(request)
    user_text = (body.user_text or "").strip()
    if not user_text:
        raise HTTPException(400, "user_text empty")

    async def _gen():
        yield format_event("refine.thinking", {"phase": "解析中..."})

        # Read current profile (best-effort)
        current_profile = get_profile(cookie_key) if cookie_key else None
        trip_summary = build_trip_summary(ctx)

        refiner = Refiner(llm_call=resolve_profiler_llm())
        try:
            action = await refiner.run(
                user_text=user_text,
                trip_summary=trip_summary,
                current_profile=current_profile,
            )
        except Exception as e:
            yield format_event("refine.error", {"reason": f"refiner failed: {e}"})
            yield format_event("refine.done", {"trip_id": ctx.trip_id})
            return

        yield format_event("refine.thinking", {"reasoning": action.reasoning})

        routed = []
        if action.profile_update is not None:
            routed.append("profile")
        if action.adjust is not None:
            routed.append("adjust")
        if action.chat_reply and not routed:
            routed.append("chat")
        yield format_event(
            "refine.routed",
            {"actions": routed, "summary": action.reasoning},
        )

        # 1) profile update
        if action.profile_update is not None and cookie_key:
            mods = action.profile_update.modifiers_set or {}
            new_interest = action.profile_update.interests_text_append or ""
            # 拼到现有 interests_text 后 (去重)
            existing_text = (
                current_profile.interests_text
                if current_profile and current_profile.interests_text
                else ""
            )
            merged_text = _merge_interest_text(existing_text, new_interest)
            # 合并 modifiers (true 覆盖, false 也保留)
            merged_mods = dict(
                (current_profile.modifiers if current_profile else {}) or {}
            )
            merged_mods.update(mods)

            profile = upsert_profile(
                cookie_key,
                modifiers=merged_mods,
                interests_text=merged_text,
            )
            yield format_event(
                "refine.profile_updated",
                {
                    "modifiers": dict(profile.modifiers),
                    "interests_text": profile.interests_text,
                },
            )

        # 2) adjust path (复用 adjust.* 事件)
        if action.adjust is not None:
            async for ev in _stream_adjust_events(ctx, action.adjust):
                yield ev

        # 3) chat reply 兜底
        if action.chat_reply:
            yield format_event("refine.chat_reply", {"text": action.chat_reply})

        yield format_event("refine.done", {"trip_id": ctx.trip_id})

    return StreamingResponse(_gen(), media_type="text/event-stream")


def _merge_interest_text(existing: str, addition: str) -> str:
    """合并 interests_text — 用中文逗号分隔, 去重."""
    if not addition:
        return existing
    tokens: list[str] = []
    for chunk in (existing + "，" + addition).replace(",", "，").split("，"):
        t = chunk.strip()
        if t and t not in tokens:
            tokens.append(t)
    return "，".join(tokens)


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


async def _run_variants(
    ctx: "TripContext", intent, pois: list, amap, planner
) -> "AsyncIterator[str]":
    """Variant 生成 SSE 流（plan_stream 和 answer 端点共用）。

    ctx.pre_fetched_pois 不为空时跳过重复 Amap 抓取。
    """
    _start_time = time.time()

    variant_routes: dict[str, RouteDraft] = {}

    # ── 并行规划 3 个 variant (原串行 3×8s → 并行 ~8s) ──────────────────────
    _VARIANTS = ["main", "low_queue", "interest_first"]
    partial_bufs: dict[str, list] = {v: [] for v in _VARIANTS}

    def _make_partial_cb(v: str):
        async def _cb(day_idx: int, names: list[str]) -> None:
            partial_bufs[v].append((day_idx, names))

        return _cb

    # v1.9.4: 多 waypoint 时扩展 anchor_radius_km，避免 planner 把远处 waypoint 排除
    _gwps = getattr(intent, "geocoded_waypoints", [])
    if len(_gwps) >= 2:
        from agents.anchor import _haversine_km as _hv_pre

        _max_wp_dist = max(
            _hv_pre((_gwps[0].lng, _gwps[0].lat), (wp.lng, wp.lat)) for wp in _gwps[1:]
        )
        if _max_wp_dist > (intent.anchor_radius_km or 3.0):
            # v1.10: 同样改 mutate (对应 _prefetch_amap_pois 内 model_copy 修复)
            intent.anchor_radius_km = _max_wp_dist + 5.0

    from agents.planner_instant import plan_one_variant as _plan_one_variant

    try:
        yield format_event("variant.main_started", {"variant": "main", "index": 0})

        # v1.9.4: 预取 Amap POI 一次，避免 3 个并行任务各自重复抓（触发高德 QPS 限速）
        # ctx.pre_fetched_pois 不为空时复用，否则现抓
        pre_pois = (
            ctx.pre_fetched_pois
            if ctx.pre_fetched_pois
            else await _prefetch_amap_pois(intent, pois)
        )

        # 启动所有 3 个任务并行
        main_task = asyncio.create_task(
            _plan_one_variant(
                intent=intent,
                variant="main",
                planner=planner,
                amap=amap,
                pois=pois,
                on_partial=_make_partial_cb("main"),
                pre_fetched_pois=pre_pois,
            )
        )
        alt_tasks = {
            v: asyncio.create_task(
                _plan_one_variant(
                    intent=intent,
                    variant=v,
                    planner=planner,
                    amap=amap,
                    pois=pois,
                    on_partial=_make_partial_cb(v),
                    pre_fetched_pois=pre_pois,
                )
            )
            for v in ["low_queue", "interest_first"]
        }

        def _stops_payload(vp):
            return [
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
                for s in vp.day_plan.stops
            ]

        # ── 等 main 完成，立即 emit ──
        vp = await main_task
        for day_idx, names in partial_bufs["main"]:
            yield format_event(
                "planner.day_partial",
                {"day_index": day_idx, "names": names, "variant": "main"},
            )
        day = vp.day_plan
        yield format_event(
            "planner.day_done",
            {
                "day_index": day.day_index,
                "variant": "main",
                "anchor_district": day.anchor_district,
                "stops": _stops_payload(vp),
                "transit_segments": vp.transit_segments,
            },
        )
        if vp.error:
            yield format_event(
                "planner.day_done_fallback",
                {"day_index": day.day_index, "variant": "main", "reason": vp.error},
            )
        day.transit_segments = vp.transit_segments
        variant_routes["main"] = RouteDraft(days=[day], summary="main variant")
        ctx.variants = dict(variant_routes)
        ctx.draft_route = variant_routes["main"]
        ctx.save()
        yield format_event(
            "variant.main_done",
            {
                "variant": "main",
                "stop_count": len(day.stops),
                "stop_names": [s.poi.name for s in day.stops],
                "has_fallback": vp.error is not None,
            },
        )

        # ── 等备选（此时通常已完成），emit ──
        for vi, variant in enumerate(["low_queue", "interest_first"], 1):
            yield format_event(
                "variant.branch_started", {"variant": variant, "index": vi}
            )
            vp = await alt_tasks[variant]
            for day_idx, names in partial_bufs[variant]:
                yield format_event(
                    "planner.day_partial",
                    {"day_index": day_idx, "names": names, "variant": variant},
                )
            day = vp.day_plan
            yield format_event(
                "planner.day_done",
                {
                    "day_index": day.day_index,
                    "variant": variant,
                    "anchor_district": day.anchor_district,
                    "stops": _stops_payload(vp),
                    "transit_segments": vp.transit_segments,
                },
            )
            if vp.error:
                yield format_event(
                    "planner.day_done_fallback",
                    {
                        "day_index": day.day_index,
                        "variant": variant,
                        "reason": vp.error,
                    },
                )
            day.transit_segments = vp.transit_segments
            variant_routes[variant] = RouteDraft(
                days=[day], summary=f"{variant} variant"
            )
            ctx.variants = dict(variant_routes)
            if "main" in ctx.variants:
                ctx.draft_route = ctx.variants["main"]
            ctx.save()
            yield format_event(
                "variant.branch_done",
                {
                    "variant": variant,
                    "stop_count": len(day.stops),
                    "stop_names": [s.poi.name for s in day.stops],
                    "has_fallback": vp.error is not None,
                },
            )
    finally:
        if "alt_tasks" in locals():
            for t in alt_tasks.values():
                t.cancel()
        await amap._client.aclose()

    # P2: variant patches (alt variant vs main 的 stop diff, 给前端 chip+tag)
    # 局部 import 防 autoflake (同 build_rationale_for_stop / expand_keywords_for_traveler 的教训)
    from agents.variant_patches import build_variant_patch_set

    main_route = variant_routes.get("main")
    if main_route and main_route.days:
        main_stops = main_route.days[0].stops
        patch_sets = []
        for vk in ("low_queue", "interest_first"):
            vroute = variant_routes.get(vk)
            if not vroute or not vroute.days:
                continue
            vstops = vroute.days[0].stops
            try:
                ps = build_variant_patch_set(main_stops, vstops, vk)
            except Exception:
                continue
            if ps is not None:
                patch_sets.append(ps.model_dump(mode="json", by_alias=True))
        if patch_sets:
            yield format_event(
                "planner.variant_patches",
                {"variants": patch_sets},
            )

    yield format_event("planner.compose_done", {})
    yield format_event(
        "planner.done",
        {
            "summary": "三方案已完成",
            "variants": {
                v: r.model_dump(mode="json") for v, r in variant_routes.items()
            },
        },
    )
    yield format_event(
        "trip.complete",
        {
            "trip_id": ctx.trip_id,
            "duration_ms": int((time.time() - _start_time) * 1000),
            "status": "ok",
            "phases": {},
            "mode": "instant",
        },
    )


# v1.9.4: Amap POI 预取 helper — 供并行 variant 共享，避免各自重复抓触发 QPS 限速
async def _apply_text_search_keywords(intent, pois: list) -> list:
    """v1.10: 用 /v3/place/text 关键词搜补足 pool, 不依赖 anchor 坐标.

    对每个 intent.must_visit 和 required_slots[].categories 关键词调 amap text_search,
    命中 POI 标记 must_consider=True 豁免后续距离过滤. 对 must_visit 关键词命中的
    第一个具体 POI name 也 append 进 intent.must_visit (mutate), 让 candidate_pool
    的子串匹配能精确命中 — 解决 '南昌博物馆' (口语) vs '江西省博物馆' (amap 真名)
    字面对不上, LLM 找不到博物馆 POI 的根因.
    """
    must_visit_kws = [kw for kw in (intent.must_visit or []) if kw]
    slot_kws: list[str] = []
    for slot in intent.required_slots or []:
        for cat in slot.categories or []:
            if cat and cat not in slot_kws:
                slot_kws.append(cat)
    keywords: list[str] = []
    for kw in must_visit_kws + slot_kws:
        if kw not in keywords:
            keywords.append(kw)
    # P2: 按 traveler_type 自动扩 2-3 个类目词, 扩 variant 分流候选池.
    # 局部 import 防 autoflake (同 build_rationale_for_stop 的教训)
    from agents.text_search_keywords import expand_keywords_for_traveler

    keywords = expand_keywords_for_traveler(intent.traveler_type or "", keywords)
    if not keywords:
        return pois

    import asyncio as _asyncio

    from agents.anchor import text_search as _text_search
    from agents.candidate_pool import (
        _infer_role_from_categories as _infer_role,
    )
    from agents.poi_cache import _around_to_poi as _around_to_poi_kw
    from dianping.schemas import EnrichedLabel

    async def _ts(kw: str):
        try:
            r = await _text_search(kw, city=intent.city, limit=8)
            return (kw, r)
        except Exception:
            return (kw, [])

    kw_results = await _asyncio.gather(*(_ts(kw) for kw in keywords))
    existing_oids = {p.openshopid for p in pois}
    injected_names: list[str] = []
    for kw, ap_list in kw_results:
        is_must_kw = kw in must_visit_kws
        for idx, ap in enumerate(ap_list):
            p = _around_to_poi_kw(ap, intent.city, None)
            if p.openshopid in existing_oids:
                continue
            role = _infer_role(p.categories)
            p.enriched = EnrichedLabel(
                poi_role=role if role != "fallback" else "city_essential",
                must_consider=True,
                manual_priority=80,
            )
            pois.append(p)
            existing_oids.add(p.openshopid)
            if is_must_kw and idx == 0 and ap.name:
                injected_names.append(ap.name)
    # mutate intent.must_visit so candidate_pool 的子串匹配能精确命中
    # 必须 mutate (不能 model_copy/重新绑定), 否则 caller 的 ctx.intent 看不到
    if injected_names:
        current = list(intent.must_visit or [])
        for name in injected_names:
            if name not in current:
                current.append(name)
        intent.must_visit = current

    return pois


async def _prefetch_amap_pois(intent, base_pois: list) -> list | None:
    """执行 intent 对应的所有 Amap fetch_around + text_search, 返回合并 pois 列表.

    - anchor 模式 (anchor_explore/layover_*): 完整走 fetch_around (周边搜) + text_search (关键词搜)
    - 非 anchor 模式 (landmark_must 等): 只走 text_search 关键词搜 (不需要 anchor 坐标)
    - 无 anchor 也无 must_visit/required_slots 关键词: 返 None, caller 自处理
    """
    from agents.planner_instant import (
        _slot_typecodes,
    )
    from agents.anchor import (
        _haversine_km,
        _norm_name,
        fetch_around,
        DEFAULT_AROUND_TYPES,
    )
    from agents.poi_cache import _around_to_poi

    has_anchor = (
        intent.anchor_lng is not None
        and intent.anchor_lat is not None
        and intent.trip_mode in ("anchor_explore", "layover_eat", "layover_explore")
    )
    has_keywords = bool(intent.must_visit) or any(
        slot.categories for slot in (intent.required_slots or [])
    )
    if not has_anchor and not has_keywords:
        return None

    pois = list(base_pois)

    if not has_anchor:
        # 非 anchor 模式: 只能跑 text_search 关键词搜
        return await _apply_text_search_keywords(intent, pois)
    anchor_pt = (intent.anchor_lng, intent.anchor_lat)
    radius_m = int((intent.anchor_radius_km or 3.0) * 1000)
    radius_km = radius_m / 1000.0
    types = (
        "050000" if intent.trip_mode == "layover_eat" else "050000|060000|080000|110000"
    )

    seen_keys: set = set()

    def _key(p):
        return (_norm_name(p.name), round(p.latitude, 3), round(p.longitude, 3))

    # 主 anchor fetch
    try:
        around = await fetch_around(
            lng=intent.anchor_lng,
            lat=intent.anchor_lat,
            radius_m=radius_m,
            types=types,
            limit=50,
        )
    except Exception:
        around = []
    amap_enriched = [_around_to_poi(ap, intent.city, None) for ap in around]

    kept_local = [
        p
        for p in pois
        if _haversine_km(anchor_pt, (p.longitude, p.latitude)) <= radius_km
    ]
    for p in kept_local:
        seen_keys.add(_key(p))
    kept_amap = [
        ap
        for ap in amap_enriched
        if _haversine_km(anchor_pt, (ap.longitude, ap.latitude)) <= radius_km
        and _key(ap) not in seen_keys
    ]
    for ap in kept_amap:
        seen_keys.add(_key(ap))
    pois = kept_local + kept_amap

    # 额外 waypoint fetch + 强制注入 waypoint 本身为高优先级 POI
    extra_wps = getattr(intent, "geocoded_waypoints", [])
    if len(extra_wps) >= 2:
        existing_oids = {p.openshopid for p in pois}

        # 把所有 waypoint 合成 city_essential POI 强制进候选池（无论 mock 有没有）
        for wp in extra_wps:
            wp_oid = f"waypoint_{wp.name[:8]}"
            if wp_oid not in existing_oids:
                from dianping.schemas import EnrichedLabel, POI as _POI

                wp_poi = _POI(
                    openshopid=wp_oid,
                    name=wp.name,
                    city=intent.city,
                    latitude=wp.lat,
                    longitude=wp.lng,
                    categories=["旅游景点"],
                    star=4.8,
                    avgprice=0,
                    business_hour="09:00-18:00",
                )
                wp_poi.enriched = EnrichedLabel(
                    poi_role="city_essential",
                    universal_level="high",
                    must_consider=True,
                    manual_priority=99,  # 最高优先级，保证进 top-30
                    planning_tags=["landmark"],
                    min_stay_minutes=90,
                    max_stay_minutes=180,
                )
                pois.insert(0, wp_poi)  # 顶部插入
                existing_oids.add(wp_oid)

        for wp in extra_wps[1:]:
            try:
                extra = await fetch_around(
                    lng=wp.lng,
                    lat=wp.lat,
                    radius_m=int((intent.anchor_radius_km or 2.0) * 1000),
                    types=DEFAULT_AROUND_TYPES,
                    limit=20,
                )
            except Exception:
                extra = []
            for ap in extra:
                p = _around_to_poi(ap, intent.city, None)
                if p.openshopid not in existing_oids:
                    pois.append(p)
                    existing_oids.add(p.openshopid)
        # 扩展 anchor_radius_km 覆盖最远 waypoint，避免 planner 的 anchor 半径硬约束排除远处地点
        max_wp_dist = max(
            _haversine_km((extra_wps[0].lng, extra_wps[0].lat), (wp.lng, wp.lat))
            for wp in extra_wps[1:]
        )
        if max_wp_dist > (intent.anchor_radius_km or 3.0):
            # v1.10: mutate 而非 model_copy, 否则后续 inject 改的是副本, caller 看不到
            intent.anchor_radius_km = max_wp_dist + 5.0

    # category-targeted fetch
    target_tc = _slot_typecodes(getattr(intent, "required_slots", []))
    if target_tc:
        try:
            cat_around = await fetch_around(
                lng=intent.anchor_lng,
                lat=intent.anchor_lat,
                radius_m=radius_m,
                types=target_tc,
                limit=15,
            )
        except Exception:
            cat_around = []
        existing_oids = {p.openshopid for p in pois}
        for ap in cat_around:
            p = _around_to_poi(ap, intent.city, None)
            if p.openshopid not in existing_oids:
                pois.append(p)
                existing_oids.add(p.openshopid)

    pois = await _apply_text_search_keywords(intent, pois)
    return pois


# v1.7 即时出发: 三方案 SSE 流式 ----------------------------------------------------


async def _stream_instant_variants(
    ctx,
    *,
    start_time: float,
    phases: dict,
    stamp,
    load_pois,
    plan_one_variant,
) -> AsyncIterator[str]:
    """B 方案: main → low_queue → interest_first 串行流, ctx.variants 持久化.

    每个 variant 复用 v1.6 SSE 事件 (planner.day_partial / day_done), 但 payload
    加 variant 字段, 前端按 variant 维护三份 markers/polylines.

    Variant 边界事件 (v1.7 新增):
      - variant.queued: trip 开始前, 通知有 N 个 variant
      - variant.main_started / variant.main_done: 主方案边界
      - variant.branch_started / variant.branch_done: 分方案边界
    """
    intent = ctx.intent
    yield format_event("planner.start", {"phase": "正在准备即时出发方案..."})

    # 加载 POI + attach enriched, 三 variant 共享同一份
    pois = load_pois(intent.city)
    if not pois:
        yield format_event(
            "error",
            {
                "phase": "planner_instant",
                "message": f"未找到城市 {intent.city} 的本地 POI 数据 (data/mock_dianping/{intent.city}.json)",
            },
        )
        return
    stamp("instant_pois_loaded")
    yield format_event(
        "planner.candidates_loaded",
        {"count": len(pois), "city": intent.city, "mode": "instant"},
    )

    # v1.9.2 M6: must_visit 命中率检查, miss 的发 chat 警告
    must_visit_list = list(intent.must_visit or [])
    if must_visit_list:
        from agents.candidate_pool import _match_must_visit_name

        unmatched: list[str] = []
        for must in must_visit_list:
            hit = any(_match_must_visit_name(p.name, [must]) is not None for p in pois)
            if not hit:
                unmatched.append(must)
        if unmatched:
            yield format_event(
                "chat",
                {
                    "role": "assistant",
                    "text": (
                        f"⚠️ 本地 POI 库里没找到 {' / '.join(unmatched)}, "
                        f"我会先按你的其它偏好规划. 如有需要可换附近相似的地点."
                    ),
                    "kind": "must_visit_warning",
                    "unmatched": unmatched,
                },
            )

    yield format_event(
        "variant.queued",
        {
            "variants": ["main", "low_queue", "interest_first"],
            "labels": {
                "main": "主推荐",
                "low_queue": "少排队",
                "interest_first": "兴趣优先",
            },
        },
    )

    # 设置 amap + planner (复用 compose_one_day)
    from agents.amap import AmapClient as _AmapClient
    from agents.planner import Planner as _Planner

    amap = _AmapClient(key=os.environ.get("AMAP_KEY", ""))
    planner = _Planner(
        client=None,  # instant 路径不用 dianping client
        llm_call=resolve_planner_llm(),
        llm_call_stream=resolve_planner_llm_stream(),
    )

    async for chunk in _run_variants(ctx, intent, pois, amap, planner):
        yield chunk
