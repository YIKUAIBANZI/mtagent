"""v1.9 bug fix: meal POI 强制 day-anchor 半径过滤.

bug 现场: 大雁塔 + 长安大牌档·建章宫宴 (凤城九路店, 距 14.5km) + 长安十二时辰,
跨城吃饭. 修复: plan_one_variant 内 anchor 选定后, meal-role POI 距 anchor
> 5km 的删掉, 非 meal POI 不动.
"""

from __future__ import annotations

from agents.planner_instant import (
    MEAL_ANCHOR_RADIUS_KM,
    _filter_meal_by_anchor_distance,
    _is_meal_poi,
)
from dianping.schemas import EnrichedLabel, POI


def _mk_meal(oid, name, lat, lng) -> POI:
    poi = POI(
        openshopid=oid,
        name=name,
        city="西安",
        latitude=lat,
        longitude=lng,
        categories=["美食"],
    )
    poi.enriched = EnrichedLabel(
        poi_role="meal",
        city_zone="A",
        manual_priority=50,
        planning_tags=[],
    )
    return poi


def _mk_landmark(oid, name, lat, lng) -> POI:
    poi = POI(
        openshopid=oid,
        name=name,
        city="西安",
        latitude=lat,
        longitude=lng,
        categories=["景点"],
    )
    poi.enriched = EnrichedLabel(
        poi_role="city_essential",
        city_zone="A",
        manual_priority=80,
        planning_tags=["landmark"],
    )
    return poi


# anchor: 大雁塔 (34.218, 108.964)
ANCHOR_LAT, ANCHOR_LNG = 34.218, 108.964


def test_far_meal_removed():
    """5km 内 >= min_keep 个近 meal → far 严格删."""
    # 5 个 near 触发严格过滤
    near = [
        _mk_meal(f"M_NEAR_{i}", f"近店{i}", 34.220 + 0.005 * i, 108.965)
        for i in range(5)
    ]
    far = _mk_meal("M_FAR", "长安大牌档·建章宫宴", 34.348, 108.933)  # 14.5km
    out = _filter_meal_by_anchor_distance(near + [far], ANCHOR_LAT, ANCHOR_LNG)
    oids = [p.openshopid for p in out]
    assert all(f"M_NEAR_{i}" in oids for i in range(5))
    assert "M_FAR" not in oids


def test_near_meal_kept():
    """距 anchor 2km 的 meal 应保留."""
    near = _mk_meal("M_NEAR", "近店", 34.235, 108.968)  # 距 anchor ~2km
    out = _filter_meal_by_anchor_distance([near], ANCHOR_LAT, ANCHOR_LNG)
    assert len(out) == 1
    assert out[0].openshopid == "M_NEAR"


def test_non_meal_kept_regardless_of_distance():
    """city_essential / 非 meal POI 即使距 anchor 20km 也保留."""
    far_landmark = _mk_landmark("L_FAR", "远景点", 34.400, 108.900)  # >20km
    near_landmark = _mk_landmark("L_NEAR", "近景点", 34.220, 108.965)
    out = _filter_meal_by_anchor_distance(
        [far_landmark, near_landmark], ANCHOR_LAT, ANCHOR_LNG
    )
    oids = [p.openshopid for p in out]
    assert "L_FAR" in oids
    assert "L_NEAR" in oids


def test_no_anchor_skips_filter():
    """anchor 坐标为 0 (无 anchor) → 不过滤, 全保留."""
    far = _mk_meal("M_FAR", "远店", 34.500, 108.500)
    out = _filter_meal_by_anchor_distance([far], 0.0, 0.0)
    assert len(out) == 1
    assert out[0].openshopid == "M_FAR"


def test_radius_boundary_inclusive():
    """距离恰好等于 radius_km → 应保留 (<=)."""
    # 用一个估算: 0.045 deg ≈ 5km (lat near equator)
    border = _mk_meal("M_BORDER", "边界店", ANCHOR_LAT + 0.044, ANCHOR_LNG)
    out = _filter_meal_by_anchor_distance(
        [border], ANCHOR_LAT, ANCHOR_LNG, radius_km=5.0
    )
    assert len(out) == 1


def test_mixed_list_preserves_order():
    """混合 list 过滤后, 保留的 POI 相对顺序不变. 5km 内 >= 3 meal 触发严格过滤."""
    a = _mk_landmark("A", "A", ANCHOR_LAT, ANCHOR_LNG)
    # 3 个近 meal 触发严格过滤
    near1 = _mk_meal("N1", "近1", ANCHOR_LAT + 0.005, ANCHOR_LNG)
    near2 = _mk_meal("N2", "近2", ANCHOR_LAT + 0.010, ANCHOR_LNG)
    near3 = _mk_meal("N3", "近3", ANCHOR_LAT + 0.015, ANCHOR_LNG)
    b = _mk_meal("B_FAR", "远饭店", 34.348, 108.933)  # 14.5km, 删
    d = _mk_landmark("D", "D", 34.400, 108.900)  # 远景点, 保留
    out = _filter_meal_by_anchor_distance(
        [a, near1, b, near2, near3, d], ANCHOR_LAT, ANCHOR_LNG
    )
    oids = [p.openshopid for p in out]
    assert oids == ["A", "N1", "N2", "N3", "D"]


def test_is_meal_poi_detects_enriched_role():
    p = _mk_meal("M", "店", 0, 0)
    assert _is_meal_poi(p) is True


def test_is_meal_poi_detects_categories_fallback():
    """无 enriched 时按 categories 兜底."""
    p = POI(
        openshopid="M2",
        name="店2",
        city="西安",
        latitude=0,
        longitude=0,
        categories=["美食", "川菜"],
    )
    p.enriched = None
    assert _is_meal_poi(p) is True


def test_is_meal_poi_rejects_non_meal():
    p = _mk_landmark("L", "景点", 0, 0)
    assert _is_meal_poi(p) is False


def test_is_meal_poi_mislabeled_role_but_food_category():
    """bug 现场: 建章宫宴 enriched.poi_role=city_essential 但 categories=['美食'].

    categories 是硬证据, 应识别为 meal.
    """
    poi = POI(
        openshopid="B0K2ZS031C",
        name="长安大牌档之建章宫宴",
        city="西安",
        latitude=34.347743,
        longitude=108.933112,
        categories=["美食"],
    )
    poi.enriched = EnrichedLabel(
        poi_role="city_essential",  # 错标
        city_zone="A",
        manual_priority=60,
        planning_tags=[],
    )
    assert _is_meal_poi(poi) is True


def test_filter_removes_mislabeled_far_food_strict():
    """bug 现场 integration: 建章宫宴 city_essential 标 + 距 anchor 14.5km → 删."""
    poi = POI(
        openshopid="B0K2ZS031C",
        name="长安大牌档之建章宫宴",
        city="西安",
        latitude=34.347743,
        longitude=108.933112,
        categories=["美食"],
    )
    poi.enriched = EnrichedLabel(
        poi_role="city_essential",
        city_zone="A",
        manual_priority=60,
        planning_tags=[],
    )
    out = _filter_meal_by_anchor_distance([poi], ANCHOR_LAT, ANCHOR_LNG)
    assert len(out) == 0  # 严格过滤, 不留远 meal


def test_all_far_meals_removed_strict():
    """所有 meal 都距 anchor > radius_km → 全删 (不 fallback). 跟用户偏好对齐:
    宁可删 stop 也不跨城吃饭. LLM 会 graceful 跳过该 slot."""
    meals = [
        _mk_meal("M1", "12km店", ANCHOR_LAT + 0.108, ANCHOR_LNG),
        _mk_meal("M2", "13km店", ANCHOR_LAT + 0.117, ANCHOR_LNG),
        _mk_meal("M3", "14km店", ANCHOR_LAT + 0.126, ANCHOR_LNG),
    ]
    out = _filter_meal_by_anchor_distance(meals, ANCHOR_LAT, ANCHOR_LNG)
    assert len(out) == 0


def test_default_radius_value():
    """MEAL_ANCHOR_RADIUS_KM 是 5.0."""
    assert MEAL_ANCHOR_RADIUS_KM == 5.0
