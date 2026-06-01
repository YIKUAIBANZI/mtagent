"""v1.8: candidate_pool 加 anchor distance_penalty 单测."""

from agents.candidate_pool import build_candidate_pool, score_poi
from dianping.schemas import POI, EnrichedLabel, ParsedIntent


def _make_poi(name, openshopid, lat, lng, role="city_essential", priority=80):
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
        poi_role=role, manual_priority=priority, city_zone="福田"
    )
    return p


def _intent(**kw):
    d = dict(city="深圳", days=1, traveler_type="情侣")
    d.update(kw)
    return ParsedIntent(**d)


def test_score_poi_anchor_within_half_radius_no_penalty():
    """半径一半内距离不扣分."""
    poi = _make_poi("近 POI", "id1", 22.541, 114.057)
    intent_with = _intent(anchor_lat=22.5405, anchor_lng=114.0565, anchor_radius_km=3.0)
    no_anchor = score_poi(poi, _intent(), variant="main")
    with_anchor = score_poi(poi, intent_with, variant="main")
    assert with_anchor == no_anchor


def test_score_poi_anchor_beyond_radius_heavy_penalty():
    """超出半径 (3km) 后硬扣分 ≥ 50."""
    poi = _make_poi("远 POI", "id2", 22.6, 114.2)  # ~ 17km
    intent_with = _intent(anchor_lat=22.541, anchor_lng=114.057, anchor_radius_km=3.0)
    s = score_poi(poi, intent_with, variant="main")
    s_no_anchor = score_poi(poi, _intent(), variant="main")
    assert s_no_anchor - s >= 50.0


def test_build_candidate_pool_filters_out_of_radius_when_anchor_set():
    """有 anchor 时, 远 POI 直接被过滤出候选池."""
    pois = [
        _make_poi("近 1", "n1", 22.541, 114.057),
        _make_poi("近 2", "n2", 22.542, 114.058),
        _make_poi("远 1", "f1", 22.60, 114.30),  # 30km 外
    ]
    intent = _intent(anchor_lat=22.541, anchor_lng=114.057, anchor_radius_km=3.0)
    pool = build_candidate_pool(pois=pois, intent=intent, variant="main")
    all_names = [
        p.name
        for bucket in (
            pool.city_essential,
            pool.persona_preferred,
            pool.meal,
            pool.connector,
        )
        for p in bucket
    ]
    assert "远 1" not in all_names
    assert "近 1" in all_names


def test_build_candidate_pool_no_anchor_keeps_old_behavior():
    """没 anchor 时, 城市范围内全保留 (老 v1.7 行为)."""
    pois = [
        _make_poi("近", "n1", 22.541, 114.057),
        _make_poi("远", "f1", 22.6, 114.3),
    ]
    intent = _intent()  # 无 anchor
    pool = build_candidate_pool(pois=pois, intent=intent, variant="main")
    all_names = [
        p.name
        for bucket in (
            pool.city_essential,
            pool.persona_preferred,
            pool.meal,
            pool.connector,
        )
        for p in bucket
    ]
    assert "近" in all_names
    assert "远" in all_names
