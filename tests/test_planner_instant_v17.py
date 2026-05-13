"""v1.7 即时出发: planner_instant 集成测试.

不打真 LLM, 用 stub_planner_llm_stream (returns empty stops → fallback path).
验证:
  1. is_instant_window 路由判断正确
  2. make_instant_template 按 time_window 生成正确 slot
  3. load_city_pois_from_mock 真数据全 attach enriched
  4. flatten_candidate_pool 三 variant 顺序确实有差异
  5. plan_one_variant 跑通 (fallback path 因 stub LLM empty)
  6. plan_three_variants 三个 variant 都有结果, day_plan.stops 非空
"""

from __future__ import annotations

import asyncio
import os

import pytest

from agents.planner import Planner
from agents.planner_instant import (
    flatten_candidate_pool,
    is_instant_window,
    load_city_pois_from_mock,
    make_instant_template,
    plan_one_variant,
    plan_three_variants,
)
from api.stub_llm import stub_planner_llm_stream
from dianping.client import DianpingClient
from dianping.schemas import ParsedIntent


def _intent(**over) -> ParsedIntent:
    base = dict(
        city="西安",
        days=1,
        traveler_type="情侣",
        time_window="半日_下午",
        interests=["拍照"],
        constraints={"avoid_queue": True},
        estimated_hours=4,
    )
    base.update(over)
    return ParsedIntent(**base)


def test_is_instant_window():
    assert is_instant_window(_intent(time_window="半日_下午"))
    assert is_instant_window(_intent(time_window="一日"))
    assert not is_instant_window(_intent(time_window="多日"))
    assert not is_instant_window(_intent(time_window=None))


def test_make_instant_template_half_afternoon():
    t = make_instant_template("半日_下午")
    names = [s.name for s in t.slots]
    assert names == ["下午", "下午茶", "晚饭"]


def test_make_instant_template_full_day():
    t = make_instant_template("一日")
    names = [s.name for s in t.slots]
    assert names == ["上午景点", "午饭", "下午", "晚饭"]


def test_make_instant_template_unknown_fallback():
    t = make_instant_template(None)
    assert len(t.slots) == 4


@pytest.mark.skipif(
    not os.path.exists("data/mock_dianping/西安.json"),
    reason="mock data not present",
)
def test_load_city_pois_attaches_enriched():
    pois = load_city_pois_from_mock("西安")
    assert len(pois) > 100
    with_enriched = [p for p in pois if p.enriched]
    # 全城 POI 都 attach enriched (数据底座 100% 覆盖)
    assert len(with_enriched) > 100


@pytest.mark.skipif(
    not os.path.exists("data/mock_dianping/西安.json"),
    reason="mock data not present",
)
def test_flatten_pool_variant_differs():
    """3 个 variant flat top-5 不应完全相同."""
    pois = load_city_pois_from_mock("西安")
    intent = _intent()
    flat_main = [p.openshopid for p in flatten_candidate_pool(intent, "main", pois)[:8]]
    flat_low = [
        p.openshopid for p in flatten_candidate_pool(intent, "low_queue", pois)[:8]
    ]
    flat_int = [
        p.openshopid for p in flatten_candidate_pool(intent, "interest_first", pois)[:8]
    ]
    # low_queue 必须跟 main 顶位不同 (walk_heavy 大景点被 -30 排走)
    assert flat_main[:5] != flat_low[:5], "low_queue 跟 main 顶位完全相同, scorer 失效"
    # interest_first 跟 main 可以一样 (top tier 都被 city_essential 占据), 但跟 low_queue 不能完全一样
    assert flat_low != flat_int


class _StubAmap:
    """Minimal amap stub for tests. _compute_day_transits doesn't actually call amap
    when we use this — we need get_transit_options + _client.aclose()."""

    def __init__(self):
        self._client = self  # 兼容 amap._client.aclose()

    async def get_transit_options(self, *, origin, dest, city, traveler_type):
        from dianping.schemas import TransitInfo

        opts = {
            m: TransitInfo(mode=m, minutes=15, distance_km=2.0, source="estimated")
            for m in ("drive", "walk", "transit", "bicycle")
        }
        return opts, "walk"

    async def aclose(self):
        pass


@pytest.mark.skipif(
    not os.path.exists("data/mock_dianping/西安.json"),
    reason="mock data not present",
)
def test_plan_one_variant_fallback_path():
    """stub_planner_llm_stream 返回 empty stops → 走 fallback → day_plan.stops 非空."""
    pois = load_city_pois_from_mock("西安")
    intent = _intent()
    client = DianpingClient()  # unused in instant path, but Planner needs it
    planner = Planner(client=client, llm_call_stream=stub_planner_llm_stream)
    amap = _StubAmap()
    vp = asyncio.run(
        plan_one_variant(
            intent=intent,
            variant="main",
            planner=planner,
            amap=amap,
            pois=pois,
        )
    )
    assert vp.variant == "main"
    # fallback synth 应该产出至少 1 个 stop (因为 template 有 3 个 slot, pool 有 30 POI)
    assert len(vp.day_plan.stops) >= 1
    # transit_segments 应跟 stops-1 一致
    assert len(vp.transit_segments) == max(0, len(vp.day_plan.stops) - 1)


@pytest.mark.skipif(
    not os.path.exists("data/mock_dianping/西安.json"),
    reason="mock data not present",
)
def test_plan_three_variants_all_succeed():
    """3 个 variant 都跑通, 每个都有 day_plan 和 (可能为空的) segments."""
    pois = load_city_pois_from_mock("西安")
    intent = _intent()
    client = DianpingClient()
    planner = Planner(client=client, llm_call_stream=stub_planner_llm_stream)
    amap = _StubAmap()
    result = asyncio.run(
        plan_three_variants(intent=intent, planner=planner, amap=amap, pois=pois)
    )
    assert set(result.keys()) == {"main", "low_queue", "interest_first"}
    for v, vp in result.items():
        assert vp.day_plan is not None, f"{v} day_plan missing"
        # fallback 也应该有 stops
        assert len(vp.day_plan.stops) >= 1, f"{v} 没产出任何 stop"


@pytest.mark.skipif(
    not os.path.exists("data/mock_dianping/西安.json"),
    reason="mock data not present",
)
def test_plan_three_variants_routes_differ():
    """Smoke (stub LLM 下): main 和 low_queue 至少有 1 个 stop POI 不同."""
    pois = load_city_pois_from_mock("西安")
    intent = _intent()
    client = DianpingClient()
    planner = Planner(client=client, llm_call_stream=stub_planner_llm_stream)
    amap = _StubAmap()
    result = asyncio.run(
        plan_three_variants(intent=intent, planner=planner, amap=amap, pois=pois)
    )
    main_ids = {s.poi.openshopid for s in result["main"].day_plan.stops}
    low_ids = {s.poi.openshopid for s in result["low_queue"].day_plan.stops}
    # 至少有 1 个 POI 不同
    diff = main_ids ^ low_ids
    assert len(diff) >= 1, f"main 和 low_queue stops 完全相同: {main_ids}"
