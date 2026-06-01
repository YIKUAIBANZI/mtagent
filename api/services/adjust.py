"""调整某 stop 的 SSE 流编排 (stream_adjust_events).

由 routers/trip.py adjust_trip endpoint 调用.
"""

from __future__ import annotations

import os
from typing import AsyncIterator

from agents.context import TripContext
from api.sse import format_event
from api.stub_llm import resolve_planner_llm, resolve_planner_llm_stream


def _capture_rejection(cookie_key, old_poi) -> None:
    """删/换 stop 时, 把被换掉 POI 的 risk_tags 记为用户拒绝信号。

    best-effort: 任何失败都不能影响改路线主流程。
    """
    if not cookie_key or old_poi is None:
        return
    try:
        from agents.user_profile_store import apply_signal

        apply_signal(cookie_key, "reject", poi=old_poi)
    except Exception:
        pass


def _find_stop_poi(ctx: TripContext, day_index: int, slot_name: str):
    """从 ctx.draft_route 取指定 day/slot 的 stop POI; 找不到返 None。"""
    route = ctx.draft_route
    if not route or day_index < 0 or day_index >= len(route.days):
        return None
    for s in route.days[day_index].stops:
        if s.slot.name == slot_name:
            return s.poi
    return None


async def stream_adjust_events(
    ctx: TripContext, req, cookie_key: str | None = None
) -> AsyncIterator[str]:
    """Yield `adjust.*` SSE events for one AdjustRequest.

    不包含 adjust.thinking / adjust.done 包裹 — 调用方负责.
    refine endpoint 复用同一 generator.
    """
    from agents.adjuster import Adjuster, AdjusterError

    adjuster = Adjuster(llm_call=resolve_planner_llm())
    try:
        if req.operation == "replace_stop":
            old_poi = _find_stop_poi(ctx, req.day_index, req.slot_name)
            result = await adjuster.replace_stop(
                ctx,
                day_index=req.day_index,
                slot_name=req.slot_name,
                user_hint=req.user_hint,
                target_poi_id=req.target_poi_id,
            )
            _capture_rejection(cookie_key, old_poi)
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
            old_poi = _find_stop_poi(ctx, req.day_index, req.slot_name)
            day_plan = await adjuster.remove_stop(
                ctx, day_index=req.day_index, slot_name=req.slot_name
            )
            _capture_rejection(cookie_key, old_poi)
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
