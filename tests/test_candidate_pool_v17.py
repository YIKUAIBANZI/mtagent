"""v1.7: candidate_pool + score_poi 单测.

验证:
1. 4 桶按 poi_role 分类正确
2. city_essential 不被 traveler_type 过滤
3. variant=low_queue 时 queue_heavy POI score 显著低
4. interest_first 时 interest 命中 POI score 显著高
5. 兜底: 无 enriched POI 不进任何桶
6. cap 上限生效
"""

from __future__ import annotations

import json

import pytest

from agents.candidate_pool import (
    DEFAULT_POOL_CAPS,
    build_candidate_pool,
    score_poi,
)
from dianping.schemas import POI, EnrichedLabel, ParsedIntent


def _poi(
    shopid: str,
    name: str,
    *,
    role: str = "persona_preferred",
    priority: int = 50,
    planning_tags: list[str] | None = None,
    risk_tags: list[str] | None = None,
    traveler_types: list[str] | None = None,
    star: float = 4.0,
    city: str = "深圳",
) -> POI:
    return POI(
        openshopid=shopid,
        name=name,
        city=city,
        latitude=22.5,
        longitude=114.0,
        star=star,
        enriched=EnrichedLabel(
            poi_role=role,  # type: ignore
            universal_level="medium",
            manual_priority=priority,
            planning_tags=planning_tags or [],
            risk_tags=risk_tags or [],
            traveler_types=traveler_types or [],  # type: ignore
        ),
    )


def _intent(**over) -> ParsedIntent:
    defaults = dict(city="深圳", days=1, traveler_type="情侣")
    defaults.update(over)
    return ParsedIntent(**defaults)


def test_pool_bucket_assignment_by_role():
    pois = [
        _poi("e1", "钟楼", role="city_essential", priority=100),
        _poi("p1", "拍照点", role="persona_preferred"),
        _poi("m1", "餐厅", role="meal"),
        _poi("c1", "商场", role="connector"),
        _poi("f1", "兜底", role="fallback"),
    ]
    pool = build_candidate_pool(pois=pois, intent=_intent())
    assert [p.openshopid for p in pool.city_essential] == ["e1"]
    assert [p.openshopid for p in pool.persona_preferred] == ["p1"]
    assert [p.openshopid for p in pool.meal] == ["m1"]
    assert [p.openshopid for p in pool.connector] == ["c1"]
    # fallback 不进任何桶
    all_ids = {
        p.openshopid
        for bucket in (
            pool.city_essential,
            pool.persona_preferred,
            pool.meal,
            pool.connector,
        )
        for p in bucket
    }
    assert "f1" not in all_ids


def test_city_essential_not_filtered_by_traveler_type():
    """钟楼 traveler_types=[] (任何人都该考虑), 情侣 intent 下仍进 city_essential 桶."""
    pois = [_poi("e1", "钟楼", role="city_essential", priority=100, traveler_types=[])]
    pool = build_candidate_pool(pois=pois, intent=_intent(traveler_type="情侣"))
    assert len(pool.city_essential) == 1


def test_pool_filters_other_city():
    pois = [
        _poi("a", "深圳点", city="深圳"),
        _poi("b", "上海点", city="上海"),
    ]
    pool = build_candidate_pool(pois=pois, intent=_intent(city="深圳"))
    assert pool.persona_preferred[0].openshopid == "a"
    assert all(p.city == "深圳" for bucket in (pool.persona_preferred,) for p in bucket)


def test_pool_caps_respected():
    pois = [
        _poi(f"e{i}", f"e{i}", role="city_essential", priority=100 - i)
        for i in range(20)
    ]
    pool = build_candidate_pool(pois=pois, intent=_intent())
    assert len(pool.city_essential) == DEFAULT_POOL_CAPS["city_essential"]
    # 高 priority 先
    assert pool.city_essential[0].openshopid == "e0"


def test_score_traveler_type_match_boosts():
    p_match = _poi("a", "情侣点", traveler_types=["情侣"])
    p_other = _poi("b", "亲子点", traveler_types=["家庭亲子"])
    intent = _intent(traveler_type="情侣")
    assert score_poi(p_match, intent) > score_poi(p_other, intent)


def test_score_interest_match_boosts():
    p_photo = _poi("a", "拍照点", planning_tags=["photo_friendly"])
    p_other = _poi("b", "购物点", planning_tags=["shopping_friendly"])
    intent = _intent(interests=["拍照"])
    assert score_poi(p_photo, intent) > score_poi(p_other, intent)


def test_score_low_queue_variant_penalizes_queue_heavy():
    p_queue = _poi("a", "排队店", risk_tags=["queue_heavy"], priority=80)
    intent = _intent()
    main_s = score_poi(p_queue, intent, variant="main")
    low_q_s = score_poi(p_queue, intent, variant="low_queue")
    assert low_q_s < main_s - 30  # 至少 -50 differential


def test_score_interest_first_variant_extra_boost():
    p_photo = _poi("a", "拍照点", planning_tags=["photo_friendly"])
    intent = _intent(interests=["拍照"])
    main_s = score_poi(p_photo, intent, variant="main")
    if_s = score_poi(p_photo, intent, variant="interest_first")
    assert if_s > main_s  # 兴趣命中再叠加 +15


def test_avoid_queue_constraint_penalizes_under_main_variant():
    p_queue = _poi("a", "排队店", risk_tags=["queue_heavy"], priority=80)
    intent_no = _intent()
    intent_avoid = _intent(constraints={"avoid_queue": True})
    s_no = score_poi(p_queue, intent_no, variant="main")
    s_avoid = score_poi(p_queue, intent_avoid, variant="main")
    assert s_avoid < s_no


def test_no_enriched_poi_skipped():
    p_no = POI(
        openshopid="x", name="无 enriched", city="深圳", latitude=22.5, longitude=114.0
    )
    pool = build_candidate_pool(pois=[p_no], intent=_intent())
    assert pool.total_size() == 0


# === 真数据 smoke test (跑 enriched_labels + mock_dianping) ===


@pytest.mark.skipif(
    not __import__("pathlib").Path("data/poi_enriched_labels.json").exists(),
    reason="enriched labels file not present",
)
def test_real_data_smoke_xian_couple_pool_has_city_essentials():
    """真数据: 西安 情侣 intent → city_essential 桶有 钟楼/大雁塔/大唐不夜城 等."""
    enriched = json.loads(open("data/poi_enriched_labels.json").read())
    xian_data = json.loads(open("data/mock_dianping/西安.json").read())
    pois: list[POI] = []
    for raw in xian_data:
        try:
            poi = POI(**raw)
        except Exception:
            continue
        label = enriched.get("西安", {}).get(poi.openshopid)
        if label:
            poi.enriched = EnrichedLabel(**label)
        pois.append(poi)
    intent = _intent(city="西安", traveler_type="情侣")
    pool = build_candidate_pool(pois=pois, intent=intent)
    assert len(pool.city_essential) > 0
    names = [p.name for p in pool.city_essential]
    # 至少西安钟楼 / 大雁塔 / 大唐不夜城 出现一个 (manual_priority=100 的)
    hit = any(kw in n for kw in ["钟楼", "大雁塔", "大唐不夜城"] for n in names)
    assert hit, f"city_essential 没含核心地标: {names}"
    # 餐饮桶非空
    assert len(pool.meal) > 0
    # 已降级的"终南山钟楼"不能出现在 city_essential
    assert all("终南山" not in n for n in names)
