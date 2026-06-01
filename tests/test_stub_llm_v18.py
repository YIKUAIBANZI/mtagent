"""v1.8 stub_profiler_llm 加 trip_mode / hub_type / start_location 关键词识别."""

import json

import pytest

from api.stub_llm import stub_profiler_llm


@pytest.mark.asyncio
async def test_stub_extracts_wanxiang_tiandi_as_anchor():
    out = json.loads(await stub_profiler_llm("", "深圳明天我想去万象天地附近转一转"))
    assert out["city"] == "深圳"
    assert out["start_location_text"] == "万象天地"


@pytest.mark.asyncio
async def test_stub_extracts_shanghai_station_as_anchor():
    out = json.loads(
        await stub_profiler_llm("", "上海中转 7 小时 想吃吃吃 然后赶火车 在上海站")
    )
    assert out["start_location_text"] == "上海站"


@pytest.mark.asyncio
async def test_stub_extracts_estimated_hours_from_x_hours():
    out = json.loads(await stub_profiler_llm("", "上海中转 7 小时 想转转"))
    assert out["estimated_hours"] == 7
