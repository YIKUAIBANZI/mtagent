"""Test Profiler with a mock LLM client."""

import json
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_profiler_complete_input_returns_ready():
    from agents.context import TripContext
    from agents.profiler import Profiler
    from dianping.schemas import UserInput

    fake_response = json.dumps(
        {
            "city": "深圳",
            "days": 3,
            "traveler_type": "情侣",
            "budget_level": "适中",
            "pace": None,
            "preferences": ["拍照", "打卡"],
            "must_visit": [],
            "avoid": [],
            "start_date": None,
        }
    )
    fake_llm = AsyncMock(return_value=fake_response)

    profiler = Profiler(llm_call=fake_llm)
    ctx = TripContext.create(
        user_input=UserInput(free_text="情侣 3 天深圳预算 3000 爱拍照")
    )
    out = await profiler.run(ctx)

    assert out.ready_to_plan is True
    assert out.missing_fields == []
    assert out.understood.city == "深圳"
    assert out.understood.days == 3
    assert ctx.intent is not None
    assert ctx.intent.city == "深圳"


@pytest.mark.asyncio
async def test_profiler_partial_input_returns_missing_fields():
    """v1.7.3: traveler_type 默认情侣 + time_window=一日 时 days 默认 1.
    所以只有 city 缺失才会进 clarifying. 这里 city 也给了, 不再触发 clarify."""
    from agents.context import TripContext
    from agents.profiler import Profiler
    from dianping.schemas import UserInput

    fake_response = json.dumps(
        {
            "city": None,  # 现在只有 city 真缺失才能触发 clarifying
            "days": None,
            "traveler_type": None,
            "budget_level": None,
            "pace": None,
            "preferences": [],
            "must_visit": [],
            "avoid": [],
            "start_date": None,
        }
    )
    fake_llm = AsyncMock(return_value=fake_response)

    profiler = Profiler(llm_call=fake_llm)
    ctx = TripContext.create(user_input=UserInput(free_text="想出去玩"))
    out = await profiler.run(ctx)

    assert out.ready_to_plan is False
    assert "city" in out.missing_fields
    # v1.7.3: traveler_type 已 backfill 为情侣, 不应在 missing 里
    assert "traveler_type" not in out.missing_fields
