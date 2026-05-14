"""v1.9.2 M5: 多样性 second-pass 扣分 — 同 city_zone 同 categories 第 2 起 -10."""

from agents.candidate_pool import build_candidate_pool
from dianping.schemas import POI, EnrichedLabel, ParsedIntent


def _poi(name, oid, *, zone, role="city_essential", priority=80, cats=None):
    p = POI(
        openshopid=oid,
        name=name,
        city="深圳",
        latitude=22.541,
        longitude=114.057,
        categories=cats or ["景点"],
        avgprice=100,
        star=4.5,
        business_hour="09:00-21:00",
    )
    p.enriched = EnrichedLabel(poi_role=role, manual_priority=priority, city_zone=zone)
    return p


def _intent(**kw):
    d = dict(city="深圳", days=1, traveler_type="情侣")
    d.update(kw)
    return ParsedIntent(**d)


def test_second_poi_same_zone_same_category_demoted():
    """同桶内 sort 后: 同 (zone, cat) 第 2 起的 POI 被 diversity 扣 10,
    应排到不同 zone POI 之后 (即使原 priority 高)."""
    # 注: 桶内先 sort by score (priority 主导), 再扫描标记第 2 起 — 所以
    # priority 较高的占"第 1", priority 较低的占"第 2" (被扣).
    pois = [
        _poi("A1", "id_a1", zone="福田", priority=87, cats=["景点"]),  # 同 zone 第 1
        _poi(
            "A2", "id_a2", zone="福田", priority=85, cats=["景点"]
        ),  # 同 zone 第 2 — 被扣
        _poi("C1", "id_c1", zone="罗湖", priority=80, cats=["景点"]),
    ]
    # 老逻辑 (无 diversity): A1 (87+18=105) > A2 (85+18=103) > C1 (80+18=98)
    # 新逻辑: A1 (105) > C1 (98) > A2 (103-10=93)  — A2 跌到末位
    pool = build_candidate_pool(pois=pois, intent=_intent(), variant="main")
    ce_names = [p.name for p in pool.city_essential]
    assert ce_names == ["A1", "C1", "A2"], (
        f"diversity 应让 A2 (同 zone 同 cat 第 2) 跌到 C1 后, 实际: {ce_names}"
    )


def test_must_visit_not_affected_by_diversity_penalty():
    """must_visit POI 即使触发多样性也保持 city_essential 头部."""
    pois = [
        _poi("钟楼景区", "id_must", zone="福田", priority=50, cats=["景点"]),
        _poi("A1", "id_a", zone="福田", priority=95, cats=["景点"]),
    ]
    pool = build_candidate_pool(
        pois=pois, intent=_intent(must_visit=["钟楼"]), variant="main"
    )
    ce_names = [p.name for p in pool.city_essential]
    assert ce_names[0] == "钟楼景区"


def test_no_penalty_when_each_zone_or_cat_unique():
    """每个 POI city_zone 都不同 → 无扣分, 老 score 排序."""
    pois = [
        _poi("X", "id1", zone="福田", priority=80, cats=["景点"]),
        _poi("Y", "id2", zone="罗湖", priority=75, cats=["景点"]),
        _poi("Z", "id3", zone="南山", priority=70, cats=["景点"]),
    ]
    pool = build_candidate_pool(pois=pois, intent=_intent(), variant="main")
    ce_names = [p.name for p in pool.city_essential]
    assert ce_names == ["X", "Y", "Z"]
