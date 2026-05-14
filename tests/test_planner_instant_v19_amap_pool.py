"""v1.9: planner_instant 在锚点模式下拉高德 around POI 合进 pool."""

from unittest.mock import AsyncMock

import pytest

from agents.planner_instant import plan_one_variant
from dianping.schemas import POI, EnrichedLabel, ParsedIntent


def _make_poi(name, openshopid, lat, lng, categories=None):
    p = POI(
        openshopid=openshopid,
        name=name,
        city="深圳",
        latitude=lat,
        longitude=lng,
        categories=categories or ["景点"],
        avgprice=100,
        star=4.5,
        business_hour="09:00-21:00",
    )
    p.enriched = EnrichedLabel(
        poi_role="city_essential", manual_priority=80, city_zone="福田"
    )
    return p


@pytest.mark.asyncio
async def test_plan_one_variant_calls_fetch_around_when_anchor_set(monkeypatch):
    """anchor_lng/lat 已设 + trip_mode=anchor_explore → 应调用 fetch_around."""
    intent = ParsedIntent(
        city="深圳",
        days=1,
        traveler_type="情侣",
        time_window="一日",
        trip_mode="anchor_explore",
        anchor_lng=114.057,
        anchor_lat=22.541,
        anchor_radius_km=3.0,
    )
    local_pois = [_make_poi("local-A", "id_l", 22.541, 114.058)]

    from agents.anchor import AroundPOI

    fake_around = [
        AroundPOI(
            name="高德新 POI",
            lng=114.060,
            lat=22.540,
            typecode="050000",
            distance_m=300,
            address="...",
        )
    ]
    fetch_mock = AsyncMock(return_value=fake_around)

    captured = {"called": False, "pool_size": 0}

    class _FakePlanner:
        async def compose_one_day(
            self,
            *,
            day_idx,
            intent,
            template,
            anchor,
            day_cluster_pois,
            amap,
            on_partial=None,
        ):
            captured["pool_size"] = len(day_cluster_pois)
            from dianping.schemas import DayPlan

            return (
                day_idx,
                DayPlan(day_index=0, anchor_district=anchor[0], stops=[]),
                [],
            )

    async def _no_transit(*a, **kw):
        return 0, []

    monkeypatch.setattr("api.routes._compute_day_transits", _no_transit)
    monkeypatch.setattr("agents.anchor.fetch_around", fetch_mock)

    # v1.9.1: cache 层 mock 防止真 LLM 调用
    async def _stub_cache(around, *, city, cache_path=None):
        return []

    monkeypatch.setattr("agents.poi_cache.lookup_and_enrich", _stub_cache)

    class _FakeAmap:
        pass

    try:
        await plan_one_variant(
            intent=intent,
            variant="main",
            planner=_FakePlanner(),
            amap=_FakeAmap(),
            pois=local_pois,
        )
    except Exception:
        pass

    fetch_mock.assert_awaited_once()
    # 合并后 pool ≥ 本地 1 (cache mock 返空, 仅本地保留)
    assert captured["pool_size"] >= 1


@pytest.mark.asyncio
async def test_plan_one_variant_skips_fetch_around_when_no_anchor(monkeypatch):
    """没设 anchor → 不调用 fetch_around (兼容 v1.7 老路径)."""
    intent = ParsedIntent(
        city="深圳",
        days=1,
        traveler_type="情侣",
        time_window="一日",
    )
    local_pois = [_make_poi("local-A", "id_l", 22.541, 114.058)]
    fetch_mock = AsyncMock(return_value=[])

    class _FakePlanner:
        async def compose_one_day(self, **kw):
            from dianping.schemas import DayPlan

            return 0, DayPlan(day_index=0, anchor_district="", stops=[]), []

    async def _no_transit(*a, **kw):
        return 0, []

    monkeypatch.setattr("api.routes._compute_day_transits", _no_transit)
    monkeypatch.setattr("agents.anchor.fetch_around", fetch_mock)

    class _FakeAmap:
        pass

    try:
        await plan_one_variant(
            intent=intent,
            variant="main",
            planner=_FakePlanner(),
            amap=_FakeAmap(),
            pois=local_pois,
        )
    except Exception:
        pass

    fetch_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_plan_one_variant_layover_eat_uses_food_types(monkeypatch):
    """layover_eat 模式 fetch_around 应带 types 含 050000 (餐饮)."""
    intent = ParsedIntent(
        city="上海",
        days=1,
        traveler_type="独行",
        time_window="一日",
        trip_mode="layover_eat",
        anchor_lng=121.456,
        anchor_lat=31.249,
        anchor_radius_km=3.0,
    )
    captured_types = {"types": None}

    async def _fake_fetch(
        lng, lat, radius_m, types="050000|060000|080000|110000", limit=50
    ):
        captured_types["types"] = types
        return []

    monkeypatch.setattr("agents.anchor.fetch_around", _fake_fetch)

    async def _stub_cache(around, *, city, cache_path=None):
        return []

    monkeypatch.setattr("agents.poi_cache.lookup_and_enrich", _stub_cache)

    class _FakePlanner:
        async def compose_one_day(self, **kw):
            from dianping.schemas import DayPlan

            return 0, DayPlan(day_index=0, anchor_district="", stops=[]), []

    async def _no_transit(*a, **kw):
        return 0, []

    monkeypatch.setattr("api.routes._compute_day_transits", _no_transit)

    class _FakeAmap:
        pass

    try:
        await plan_one_variant(
            intent=intent,
            variant="main",
            planner=_FakePlanner(),
            amap=_FakeAmap(),
            pois=[],
        )
    except Exception:
        pass

    assert captured_types["types"] is not None
    assert "050000" in captured_types["types"]
