"""Profiler city regex 兜底 (bug fix 2026-05-20).

真 qwen 受 prompt 5-城枚举影响, 偶尔对哈尔滨这种非内置 POI 库的城市返 null.
后端架构通过 amap text_search/fetch_around 已支持任意城市, prompt 已放宽; 这里
再加 python regex 兜底, 防 LLM 输出不稳定时陷入 clarify 死路.
"""

import pytest

from agents.context import TripContext
from agents.profiler import Profiler, _scan_city_fallback
from dianping.schemas import UserInput


def test_scan_city_fallback_finds_harbin():
    assert _scan_city_fallback("明天去哈尔滨玩一天") == "哈尔滨"


def test_scan_city_fallback_finds_chengdu_with_distractors():
    assert _scan_city_fallback("我想去成都吃火锅，住宽窄巷子附近") == "成都"


def test_scan_city_fallback_returns_none_when_no_match():
    assert _scan_city_fallback("明天去玩一天") is None
    assert _scan_city_fallback("") is None
    assert _scan_city_fallback(None) is None  # type: ignore[arg-type]


def test_scan_city_fallback_returns_first_match():
    """多城市命中时返第一个 (按用户原文出现顺序)."""
    assert _scan_city_fallback("从北京飞上海") == "北京"


@pytest.mark.asyncio
async def test_profiler_recovers_city_when_llm_returns_null():
    """LLM 返 city=null 时, 应被 user_input regex 兜底救回."""
    import json as _json

    async def _llm_call(system: str, user: str) -> str:
        # 模拟 qwen 受 5-城 prompt 影响对哈尔滨返 null
        return _json.dumps(
            {
                "city": None,
                "days": 1,
                "traveler_type": "情侣",
            },
            ensure_ascii=False,
        )

    profiler = Profiler(llm_call=_llm_call)
    ctx = TripContext.create(
        user_input=UserInput(free_text="明天去哈尔滨玩一天，想去中央大街，情侣")
    )
    out = await profiler.run(ctx)
    assert out.understood.city == "哈尔滨"
    # city 不该出现在 missing fields 里
    assert "city" not in out.missing_fields


@pytest.mark.asyncio
async def test_profiler_still_clarifies_when_city_truly_missing():
    """user_input 没城市名时, 兜底失效, 走 clarifying 是对的."""
    import json as _json

    async def _llm_call(system: str, user: str) -> str:
        return _json.dumps(
            {"city": None, "days": 1, "traveler_type": "情侣"},
            ensure_ascii=False,
        )

    profiler = Profiler(llm_call=_llm_call)
    ctx = TripContext.create(user_input=UserInput(free_text="明天玩一天，情侣"))
    out = await profiler.run(ctx)
    assert "city" in out.missing_fields
