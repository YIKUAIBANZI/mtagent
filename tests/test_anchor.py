"""v1.8 anchor.py: 高德 geocode + around + merge 本地 POI."""

from unittest.mock import AsyncMock, patch

import pytest

from agents.anchor import (
    AnchorResolution,
    AroundPOI,
    _norm_name,
    _within_100m,
    fetch_around,
    merge_with_local_pool,
    resolve_anchor,
)
from dianping.schemas import POI, EnrichedLabel


def _make_poi(name, openshopid, lat, lng, categories=None, has_enriched=True):
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
    if has_enriched:
        p.enriched = EnrichedLabel(
            poi_role="city_essential", manual_priority=90, city_zone="福田"
        )
    return p


def test_norm_name_strips_branch_and_parens():
    assert _norm_name("万象天地(福田店)") == "万象天地"
    assert _norm_name("老孙家总店") == "老孙家"
    assert _norm_name("万象天地") == "万象天地"


def test_within_100m_true_when_close():
    assert _within_100m((114.057, 22.541), (114.0571, 22.5411)) is True


def test_within_100m_false_when_far():
    assert _within_100m((114.057, 22.541), (114.07, 22.55)) is False


@pytest.mark.asyncio
async def test_resolve_anchor_returns_resolution_on_success():
    """高德 geocode 命中: 返回标准化地名 + 坐标."""
    mock_response = {
        "status": "1",
        "geocodes": [
            {
                "formatted_address": "广东省深圳市福田区万象天地",
                "location": "114.057000,22.541000",
                "adcode": "440304",
                "level": "兴趣点",
            }
        ],
    }

    with patch("agents.anchor._amap_get", new=AsyncMock(return_value=mock_response)):
        result = await resolve_anchor("万象天地", city="深圳")

    assert result is not None
    assert result.lng == 114.057
    assert result.lat == 22.541
    assert result.adcode == "440304"
    assert "万象天地" in result.name
    assert result.confidence == "high"


@pytest.mark.asyncio
async def test_resolve_anchor_returns_none_when_geocode_empty():
    mock_response = {"status": "1", "geocodes": []}
    with patch("agents.anchor._amap_get", new=AsyncMock(return_value=mock_response)):
        result = await resolve_anchor("不存在地名XYZ", city="深圳")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_around_returns_around_pois():
    mock_response = {
        "status": "1",
        "pois": [
            {
                "name": "老孙家泡馍",
                "location": "114.058,22.542",
                "typecode": "050000",
                "distance": "120",
                "address": "深圳市福田区某街",
            },
            {
                "name": "深圳书城",
                "location": "114.060,22.540",
                "typecode": "080000",
                "distance": "300",
                "address": "深圳市福田区福华一路",
            },
        ],
    }
    with patch("agents.anchor._amap_get", new=AsyncMock(return_value=mock_response)):
        pois = await fetch_around(lng=114.057, lat=22.541, radius_m=3000, limit=50)

    assert len(pois) == 2
    assert pois[0].name == "老孙家泡馍"
    assert pois[0].distance_m == 120
    assert pois[0].lng == 114.058


def test_merge_dedupes_by_name_and_coord():
    """高德 POI 跟本地同名+100m 内坐标 → 视为同一, 保本地 (有 enriched)."""
    anchor = AnchorResolution(
        text="万象天地",
        name="深圳万象天地",
        lng=114.057,
        lat=22.541,
        adcode="440304",
        formatted_address="...",
        confidence="high",
    )
    local = [_make_poi("老孙家泡馍", "id_1", 22.5420, 114.0581)]
    amap = [
        AroundPOI(
            name="老孙家泡馍",
            lng=114.058,
            lat=22.542,
            typecode="050000",
            distance_m=120,
            address="...",
        ),
        AroundPOI(
            name="深圳书城",
            lng=114.060,
            lat=22.540,
            typecode="080000",
            distance_m=300,
            address="...",
        ),
    ]
    merged = merge_with_local_pool(amap, local, anchor, radius_m=3000)
    names = [p.name for p in merged]
    assert "老孙家泡馍" in names
    assert "深圳书城" in names
    assert len(merged) == 2
    laoshun = next(p for p in merged if p.name == "老孙家泡馍")
    assert laoshun.enriched is not None


def test_merge_filters_out_of_radius():
    anchor = AnchorResolution(
        text="x",
        name="x",
        lng=114.057,
        lat=22.541,
        adcode="440304",
        formatted_address="...",
        confidence="high",
    )
    local = [_make_poi("远 POI", "id_far", 22.55, 114.30)]
    merged = merge_with_local_pool([], local, anchor, radius_m=3000)
    assert merged == []
