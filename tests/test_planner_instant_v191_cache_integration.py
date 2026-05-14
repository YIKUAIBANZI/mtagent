"""v1.9.1: planner_instant 调 poi_cache.lookup_and_enrich 验证."""


import pytest

from agents.planner_instant import plan_one_variant
from dianping.schemas import POI, EnrichedLabel, ParsedIntent


def _make_local_poi(name, openshopid, lat, lng):
    p = POI(
        openshopid=openshopid,
        name=name,
        city="深圳",
        latitude=lat,
        longitude=lng,
        categories=["景点"],
        avgprice=100,
        star=4.5,
        business_hour="09:00-21:00",
    )
    p.enriched = EnrichedLabel(
        poi_role="city_essential", manual_priority=80, city_zone="福田"
    )
    return p


def _make_cache_poi(name, oid, lat, lng):
    """模拟从 cache 来的高德 POI (已 enriched)."""
    p = POI(
        openshopid=oid,
        name=name,
        city="深圳",
        latitude=lat,
        longitude=lng,
        categories=["美食"],
        avgprice=0,
        star=0,
        business_hour="",
    )
    p.enriched = EnrichedLabel(
        poi_role="meal",
        manual_priority=75,
        city_zone="福田",
        planning_tags=["food_quality", "local_food"],
        risk_tags=[],
        min_stay_minutes=45,
        max_stay_minutes=90,
    )
    return p


@pytest.mark.asyncio
async def test_plan_one_variant_calls_lookup_and_enrich_when_anchor(monkeypatch):
    """anchor + trip_mode → 应调 lookup_and_enrich, pool 含 cache POI."""
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
    local_pois = [_make_local_poi("local-A", "id_l", 22.541, 114.058)]

    from agents.anchor import AroundPOI

    fake_around = [
        AroundPOI(
            name="高德新店",
            lng=114.060,
            lat=22.540,
            typecode="050000",
            distance_m=300,
            address="x",
        )
    ]

    async def _fake_fetch(**kw):
        return fake_around

    cache_call_count = {"n": 0}

    async def _fake_cache(around, *, city, cache_path=None):
        cache_call_count["n"] += 1
        # 模拟 cache 命中, 返回 1 个 enriched POI
        return [_make_cache_poi("高德新店", "amap_x", 22.540, 114.060)]

    monkeypatch.setattr("agents.anchor.fetch_around", _fake_fetch)
    monkeypatch.setattr("agents.poi_cache.lookup_and_enrich", _fake_cache)

    captured = {"pool_size": 0, "pool_names": []}

    class _FakePlanner:
        async def compose_one_day(self, **kw):
            from dianping.schemas import DayPlan

            captured["pool_size"] = len(kw.get("day_cluster_pois", []))
            captured["pool_names"] = [p.name for p in kw.get("day_cluster_pois", [])]
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
            pois=local_pois,
        )
    except Exception:
        pass

    assert cache_call_count["n"] == 1
    # pool 应含本地 local-A + cache 来的 "高德新店"
    assert "local-A" in captured["pool_names"]
    assert "高德新店" in captured["pool_names"]


@pytest.mark.asyncio
async def test_plan_one_variant_skips_lookup_when_no_anchor(monkeypatch):
    """无 anchor → 不调 lookup_and_enrich."""
    intent = ParsedIntent(
        city="深圳",
        days=1,
        traveler_type="情侣",
        time_window="一日",
    )
    local_pois = [_make_local_poi("local-A", "id_l", 22.541, 114.058)]

    cache_call_count = {"n": 0}

    async def _fake_cache(around, *, city, cache_path=None):
        cache_call_count["n"] += 1
        return []

    monkeypatch.setattr("agents.poi_cache.lookup_and_enrich", _fake_cache)

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
            pois=local_pois,
        )
    except Exception:
        pass

    assert cache_call_count["n"] == 0
