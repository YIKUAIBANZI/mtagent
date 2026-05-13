"""v1.8 Profiler 集成 anchor + trip_router 单测."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from agents.context import TripContext
from agents.profiler import Profiler
from dianping.schemas import UserInput


@pytest.mark.asyncio
async def test_profiler_resolves_anchor_and_sets_trip_mode_explore():
    """用户说"万象天地附近" → trip_mode=anchor_explore + anchor 坐标已填."""
    fake_llm = AsyncMock(
        return_value=json.dumps(
            {
                "city": "深圳",
                "days": 1,
                "traveler_type": "情侣",
                "time_window": "一日",
                "start_location_text": "万象天地",
            }
        )
    )

    from agents.anchor import AnchorResolution

    fake_anchor = AnchorResolution(
        text="万象天地",
        name="深圳万象天地",
        lng=114.057,
        lat=22.541,
        adcode="440304",
        formatted_address="深圳市福田区万象天地",
        confidence="high",
    )
    with patch(
        "agents.profiler._resolve_anchor", new=AsyncMock(return_value=fake_anchor)
    ):
        profiler = Profiler(llm_call=fake_llm)
        ctx = TripContext.create(
            user_input=UserInput(free_text="深圳明天我想去万象天地附近转一转")
        )
        out = await profiler.run(ctx)

    assert out.understood.trip_mode == "anchor_explore"
    assert out.understood.anchor_lng == 114.057
    assert out.understood.anchor_lat == 22.541
    assert out.understood.anchor_resolved_name == "深圳万象天地"
    assert out.understood.anchor_radius_km == 4.0


@pytest.mark.asyncio
async def test_profiler_layover_sets_hub_type_and_safety_margin():
    """中转场景: hub_type=train + safety_margin=30."""
    fake_llm = AsyncMock(
        return_value=json.dumps(
            {
                "city": "上海",
                "days": 1,
                "traveler_type": "独行",
                "time_window": "一日",
                "start_location_text": "上海站",
                "estimated_hours": 7,
            }
        )
    )

    from agents.anchor import AnchorResolution

    fake_anchor = AnchorResolution(
        text="上海站",
        name="上海站",
        lng=121.456,
        lat=31.249,
        adcode="310101",
        formatted_address="上海站",
        confidence="high",
    )
    with patch(
        "agents.profiler._resolve_anchor", new=AsyncMock(return_value=fake_anchor)
    ):
        profiler = Profiler(llm_call=fake_llm)
        ctx = TripContext.create(
            user_input=UserInput(free_text="上海中转 7 小时 想吃吃吃 然后赶火车")
        )
        out = await profiler.run(ctx)

    assert out.understood.trip_mode == "layover_eat"
    assert out.understood.hub_type == "train"
    assert out.understood.safety_margin_min == 30


@pytest.mark.asyncio
async def test_profiler_anchor_failure_falls_back_to_landmark_must():
    """geocode 失败: trip_mode=landmark_must, anchor 坐标=None."""
    fake_llm = AsyncMock(
        return_value=json.dumps(
            {
                "city": "西安",
                "days": 1,
                "traveler_type": "情侣",
                "time_window": "半日_下午",
                "start_location_text": "不存在的地名XYZ",
            }
        )
    )
    with patch("agents.profiler._resolve_anchor", new=AsyncMock(return_value=None)):
        profiler = Profiler(llm_call=fake_llm)
        ctx = TripContext.create(
            user_input=UserInput(free_text="西安半天 想去不存在的地名XYZ 拍照")
        )
        out = await profiler.run(ctx)

    assert out.understood.trip_mode == "landmark_must"
    assert out.understood.anchor_lng is None


@pytest.mark.asyncio
async def test_profiler_no_anchor_text_routes_landmark_must():
    """用户没说任何锚点 → landmark_must."""
    fake_llm = AsyncMock(
        return_value=json.dumps(
            {
                "city": "西安",
                "days": 1,
                "traveler_type": "情侣",
                "time_window": "半日_下午",
            }
        )
    )
    profiler = Profiler(llm_call=fake_llm)
    ctx = TripContext.create(user_input=UserInput(free_text="西安半天拍照"))
    out = await profiler.run(ctx)
    assert out.understood.trip_mode == "landmark_must"
    assert out.understood.anchor_lng is None


@pytest.mark.asyncio
async def test_profiler_multi_day_routes_multi_day():
    fake_llm = AsyncMock(
        return_value=json.dumps(
            {
                "city": "西安",
                "days": 3,
                "traveler_type": "情侣",
            }
        )
    )
    profiler = Profiler(llm_call=fake_llm)
    ctx = TripContext.create(user_input=UserInput(free_text="情侣 西安 3 天"))
    out = await profiler.run(ctx)
    assert out.understood.trip_mode == "multi_day"
