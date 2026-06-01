"""调整某 stop 的 SSE 流编排 (stream_adjust_events).

由 routers/trip.py adjust_trip endpoint 调用.
"""

from __future__ import annotations

import os
from typing import AsyncIterator

from agents.context import TripContext
from api.sse import format_event
from api.stub_llm import resolve_planner_llm, resolve_planner_llm_stream


async def stream_adjust_events(ctx: TripContext, req) -> AsyncIterator[str]:
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
                target_poi_id=req.target_poi_id,
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
