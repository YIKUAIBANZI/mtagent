"""即时出发 (instant trip mode) variant 串行流编排 (stream_instant_variants).

由 routers/plan.py 调用. ctx.variants 持久化结果.
"""

from __future__ import annotations

import os
from typing import AsyncIterator

from api.sse import format_event
from api.stub_llm import resolve_planner_llm, resolve_planner_llm_stream
from api.services.variants import run_variants


async def stream_instant_variants(
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

    async for chunk in run_variants(ctx, intent, pois, amap, planner):
        yield chunk
