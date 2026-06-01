"""v1.9: score_poi 应通过 tag_mapping 计算 interest match, 不再硬编码."""

from agents.candidate_pool import score_poi
from dianping.schemas import POI, EnrichedLabel, ParsedIntent


def _make_poi(name, openshopid, planning_tags=None, risk_tags=None):
    p = POI(
        openshopid=openshopid,
        name=name,
        city="深圳",
        latitude=22.541,
        longitude=114.057,
        categories=["景点"],
        avgprice=100,
        star=4.5,
        business_hour="09:00-21:00",
    )
    p.enriched = EnrichedLabel(
        poi_role="city_essential",
        manual_priority=80,
        city_zone="福田",
        planning_tags=planning_tags or [],
        risk_tags=risk_tags or [],
    )
    return p


def _intent(**kw):
    d = dict(city="深圳", days=1, traveler_type="情侣")
    d.update(kw)
    return ParsedIntent(**d)


def test_score_with_photo_interest_boosts_photo_friendly_poi():
    poi = _make_poi("photo POI", "id1", planning_tags=["photo_friendly"])
    no_interest = score_poi(poi, _intent(), variant="main")
    with_interest = score_poi(poi, _intent(interests=["拍照"]), variant="main")
    assert with_interest > no_interest


def test_score_with_avoid_queue_penalizes_queue_heavy():
    poi = _make_poi("排队 POI", "id2", risk_tags=["queue_heavy"])
    poi.enriched.poi_role = "meal"
    poi.categories = ["美食"]
    no_constraint = score_poi(poi, _intent(), variant="main")
    with_constraint = score_poi(
        poi, _intent(constraints={"avoid_queue": True}), variant="main"
    )
    assert with_constraint < no_constraint


def test_legacy_preferences_still_work():
    """v1.6 preferences=["美食"] 老语义保持."""
    poi = _make_poi("食店", "id3", planning_tags=["food_quality"])
    boosted = score_poi(poi, _intent(preferences=["美食"]), variant="main")
    base = score_poi(poi, _intent(), variant="main")
    assert boosted > base
