"""v1.9: build_candidate_pool 接受 amap POI (无 enriched) 加入桶."""

from agents.candidate_pool import build_candidate_pool
from dianping.schemas import POI, EnrichedLabel, ParsedIntent


def _local_poi(name, openshopid, lat, lng, role="city_essential", priority=80):
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


def _amap_poi(name, openshopid, lat, lng, categories):
    """高德来的 POI: 无 enriched."""
    return POI(
        openshopid=openshopid,
        name=name,
        city="深圳",
        latitude=lat,
        longitude=lng,
        categories=categories,
        avgprice=0,
        star=0,
        business_hour="",
    )


def _intent(**kw):
    d = dict(
        city="深圳",
        days=1,
        traveler_type="情侣",
        anchor_lat=22.541,
        anchor_lng=114.057,
        anchor_radius_km=3.0,
    )
    d.update(kw)
    return ParsedIntent(**d)


def test_amap_poi_with_food_categories_enters_meal_bucket():
    pois = [
        _local_poi("钟楼景区", "id_l", 22.541, 114.057),
        _amap_poi("老孙家泡馍(高德)", "amap_food_1", 22.542, 114.058, ["美食"]),
    ]
    pool = build_candidate_pool(pois=pois, intent=_intent(), variant="main")
    meal_names = [p.name for p in pool.meal]
    assert "老孙家泡馍(高德)" in meal_names


def test_amap_poi_with_landmark_enters_city_essential_bucket():
    pois = [
        _amap_poi("深圳书城(高德)", "amap_landmark_1", 22.541, 114.057, ["景点"]),
    ]
    pool = build_candidate_pool(pois=pois, intent=_intent(), variant="main")
    ce_names = [p.name for p in pool.city_essential]
    assert "深圳书城(高德)" in ce_names


def test_local_poi_priority_over_amap_in_same_bucket():
    """本地 POI 有 enriched (高 manual_priority), 应排 amap POI 之前."""
    pois = [
        _amap_poi("amap-A", "amap_1", 22.541, 114.057, ["景点"]),
        _local_poi("local-A", "id_l", 22.542, 114.058, "city_essential", 95),
    ]
    pool = build_candidate_pool(pois=pois, intent=_intent(), variant="main")
    assert pool.city_essential[0].name == "local-A"


def test_amap_poi_with_unknown_categories_excluded_from_main_buckets():
    """fallback 角色不进任何桶 (v1.7 不变量保持)."""
    pois = [
        _amap_poi("未知分类", "amap_x", 22.541, 114.057, ["其它"]),
    ]
    pool = build_candidate_pool(pois=pois, intent=_intent(), variant="main")
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
    assert "未知分类" not in all_names
