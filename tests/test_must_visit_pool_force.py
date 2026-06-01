"""v1.9.2 M3: build_candidate_pool 强制 must_visit POI 进 city_essential head."""

from agents.candidate_pool import _match_must_visit_name, build_candidate_pool
from dianping.schemas import POI, EnrichedLabel, ParsedIntent


def _poi(name, oid, role="persona_preferred", priority=70, lat=22.541, lng=114.057):
    p = POI(
        openshopid=oid,
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


def _intent(must_visit=None, **kw):
    d = dict(
        city="深圳",
        days=1,
        traveler_type="情侣",
        must_visit=must_visit or [],
    )
    d.update(kw)
    return ParsedIntent(**d)


def test_match_must_visit_substring():
    assert _match_must_visit_name("深圳钟楼景区", ["钟楼"]) == "钟楼"


def test_match_must_visit_alias():
    """'故宫' 别名命中 '紫禁城博物院'."""
    # 假设别名表里有 故宫 → [紫禁城]
    res = _match_must_visit_name("紫禁城博物院", ["故宫"])
    assert res == "故宫"


def test_match_must_visit_no_hit():
    assert _match_must_visit_name("XYZ 店", ["钟楼", "兵马俑"]) is None


def test_must_visit_poi_forced_into_city_essential_head():
    """普通 persona_preferred POI + must_visit 命中 → 进 city_essential 顶部."""
    pois = [
        _poi("深圳钟楼景区", "id_must", role="persona_preferred", priority=50),
        _poi("地标A", "id_a", role="city_essential", priority=85),
        _poi("地标B", "id_b", role="city_essential", priority=90),
    ]
    pool = build_candidate_pool(
        pois=pois, intent=_intent(must_visit=["钟楼"]), variant="main"
    )
    ce_names = [p.name for p in pool.city_essential]
    # 必去点必须排在最前面
    assert ce_names[0] == "深圳钟楼景区"
    # 原 city_essential 仍在桶里
    assert "地标A" in ce_names
    assert "地标B" in ce_names


def test_must_visit_overrides_anchor_radius_filter():
    """anchor 半径外但 must_visit 命中 → 仍保留 (不受 2x 过滤影响)."""
    pois = [
        _poi(
            "远点必去",
            "id_far",
            role="city_essential",
            priority=80,
            lat=22.700,
            lng=114.300,
        ),  # 远点
        _poi(
            "近点A",
            "id_near",
            role="city_essential",
            priority=85,
            lat=22.541,
            lng=114.057,
        ),
    ]
    intent = _intent(
        must_visit=["远点必去"],
        anchor_lat=22.541,
        anchor_lng=114.057,
        anchor_radius_km=1.0,
    )
    pool = build_candidate_pool(pois=pois, intent=intent, variant="main")
    ce_names = [p.name for p in pool.city_essential]
    assert "远点必去" in ce_names
    assert ce_names[0] == "远点必去"  # 仍优先


def test_no_must_visit_keeps_old_behavior():
    """没 must_visit → 老逻辑不变 (高 manual_priority 在前)."""
    pois = [
        _poi("X", "id1", role="city_essential", priority=70),
        _poi("Y", "id2", role="city_essential", priority=90),
    ]
    pool = build_candidate_pool(pois=pois, intent=_intent(), variant="main")
    ce_names = [p.name for p in pool.city_essential]
    assert ce_names[0] == "Y"
