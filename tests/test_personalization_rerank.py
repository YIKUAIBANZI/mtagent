from dianping.schemas import POI, ParsedIntent, EnrichedLabel
from agents.candidate_pool import score_poi, _exclude_been_there


def _poi(name, planning, risk, price=100):
    return POI(
        openshopid=name,
        name=name,
        city="上海",
        latitude=31.2,
        longitude=121.4,
        avgprice=price,
        star=4.0,
        enriched=EnrichedLabel(
            poi_role="city_essential", planning_tags=planning, risk_tags=risk
        ),
    )


def test_loved_tag_boosts_score():
    intent = ParsedIntent(
        city="上海", days=1, traveler_type="情侣", profile_loved_tags=["rest_friendly"]
    )
    base = score_poi(_poi("a", [], []), intent)
    loved = score_poi(_poi("b", ["rest_friendly"], []), intent)
    assert loved >= base + 18


def test_rejected_tag_penalizes_score():
    intent = ParsedIntent(
        city="上海", days=1, traveler_type="情侣", profile_rejected_tags=["queue_heavy"]
    )
    base = score_poi(_poi("a", [], []), intent)
    rej = score_poi(_poi("b", [], ["queue_heavy"]), intent)
    assert rej <= base - 35


def test_exclude_been_there_filters_by_name():
    pois = [_poi("外滩", [], []), _poi("豫园", [], [])]
    out = _exclude_been_there(pois, ["外滩"], [])
    assert [p.name for p in out] == ["豫园"]


def test_exclude_been_there_must_visit_exempt():
    pois = [_poi("外滩", [], [])]
    out = _exclude_been_there(pois, ["外滩"], ["外滩"])
    assert [p.name for p in out] == ["外滩"]
