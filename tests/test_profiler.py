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
    from agents.context import TripContext
    from agents.profiler import Profiler
    from dianping.schemas import UserInput

    fake_response = json.dumps(
        {
            "city": "深圳",
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
    ctx = TripContext.create(user_input=UserInput(free_text="深圳"))
    out = await profiler.run(ctx)

    assert out.ready_to_plan is False
    assert "days" in out.missing_fields
    assert "traveler_type" in out.missing_fields
