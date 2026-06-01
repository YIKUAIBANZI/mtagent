"""variant 并发执行 + SSE 流编排 (run_variants).

由 routers/plan.py 和 routers/trip.py 调用. 内部协调 agents/planner_instant.plan_one_variant.
"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

from agents.amap_pool import prefetch_amap_pois
from agents.context import TripContext
from dianping.schemas import RouteDraft
from api.sse import format_event


async def run_variants(
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
            else await prefetch_amap_pois(intent, pois)
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
                    "recommended_duration_min": s.recommended_duration_min,
                    "avgprice": s.poi.avgprice,
                    "star": s.poi.star,
                    "longitude": s.poi.longitude,
                    "latitude": s.poi.latitude,
                    "decision_signals": s.decision_signals,
                    "decision_notes": s.decision_notes,
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
