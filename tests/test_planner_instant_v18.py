"""v1.8: planner_instant 用真实 anchor 坐标 (而非第一个 POI)."""

import pytest

from agents.planner_instant import plan_one_variant
from dianping.schemas import POI, EnrichedLabel, ParsedIntent


def _make_poi(name, openshopid, lat, lng):
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
        poi_role="city_essential", manual_priority=90, city_zone="福田"
    )
    return p


@pytest.mark.asyncio
async def test_plan_one_variant_uses_intent_anchor_lng_lat_when_set(monkeypatch):
    """anchor_lng/lat 在 intent 已设 → compose_one_day 收到真实 anchor."""
    intent = ParsedIntent(
        city="深圳",
        days=1,
        traveler_type="情侣",
        time_window="一日",
        trip_mode="anchor_explore",
        anchor_lng=114.057,
        anchor_lat=22.541,
        anchor_resolved_name="深圳万象天地",
        anchor_radius_km=3.0,
    )
    pois = [_make_poi("近 POI", "n1", 22.542, 114.058)]

    captured_anchor = {}

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
            variant="main",
        ):
            captured_anchor["a"] = anchor
            from dianping.schemas import DayPlan

            return (
                day_idx,
                DayPlan(day_index=0, anchor_district=anchor[0], stops=[]),
                [],
            )

    class _FakeAmap:
        pass

    async def _no_transit(*a, **kw):
        return 0, []

    monkeypatch.setattr("api.routes._compute_day_transits", _no_transit)

    try:
        await plan_one_variant(
            intent=intent,
            variant="main",
            planner=_FakePlanner(),
            amap=_FakeAmap(),
            pois=pois,
        )
    except Exception:
        pass

    assert captured_anchor["a"][0] == "深圳万象天地"
    assert captured_anchor["a"][1] == 22.541  # lat
    assert captured_anchor["a"][2] == 114.057  # lng


@pytest.mark.asyncio
async def test_plan_one_variant_falls_back_to_first_poi_when_no_anchor(monkeypatch):
    """没设 anchor_lng/lat → 仍用 POI[0] (v1.7 行为兼容)."""
    intent = ParsedIntent(
        city="深圳",
        days=1,
        traveler_type="情侣",
        time_window="一日",
    )
    pois = [_make_poi("第一 POI", "n1", 22.5, 114.0)]

    captured_anchor = {}

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
            variant="main",
        ):
            captured_anchor["a"] = anchor
            from dianping.schemas import DayPlan

            return (
                day_idx,
                DayPlan(day_index=0, anchor_district=anchor[0], stops=[]),
                [],
            )

    class _FakeAmap:
        pass

    async def _no_transit(*a, **kw):
        return 0, []

    monkeypatch.setattr("api.routes._compute_day_transits", _no_transit)

    try:
        await plan_one_variant(
            intent=intent,
            variant="main",
            planner=_FakePlanner(),
            amap=_FakeAmap(),
            pois=pois,
        )
    except Exception:
        pass

    assert captured_anchor["a"][1] == 22.5
    assert captured_anchor["a"][2] == 114.0
