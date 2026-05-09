"""Test agents/tools.py functions."""

from datetime import datetime, time


def test_generate_day_template_moderate_3_days():
    from agents.tools import generate_day_template

    templates = generate_day_template(days=3, traveler_type="情侣", pace="适中")
    assert len(templates) == 3
    for i, day in enumerate(templates):
        assert day.day_index == i
        slot_names = [s.name for s in day.slots]
        assert "上午景点" in slot_names
        assert "午饭" in slot_names
        assert "晚饭" in slot_names


def test_generate_day_template_baoxou_has_more_slots():
    from agents.tools import generate_day_template

    moderate = generate_day_template(days=1, traveler_type="情侣", pace="适中")
    baoxou = generate_day_template(days=1, traveler_type="情侣", pace="暴走")

    assert len(baoxou[0].slots) > len(moderate[0].slots)


def test_meal_slots_locked_to_canonical_times():
    from agents.tools import generate_day_template

    templates = generate_day_template(days=1, traveler_type="情侣", pace="适中")
    slots = templates[0].slots
    lunch = next(s for s in slots if s.name == "午饭")
    dinner = next(s for s in slots if s.name == "晚饭")

    assert lunch.start == time(12, 0)
    assert lunch.end == time(13, 30)
    assert dinner.start == time(18, 0)
    assert dinner.end == time(20, 0)


def test_default_pace_for_traveler_type():
    from agents.tools import default_pace_for_traveler

    assert default_pace_for_traveler("家庭亲子") == "佛系"
    assert default_pace_for_traveler("银发") == "佛系"
    assert default_pace_for_traveler("商务") == "暴走"
    assert default_pace_for_traveler("朋友团") == "暴走"
    assert default_pace_for_traveler("情侣") == "适中"
    assert default_pace_for_traveler("独行") == "适中"


def test_cluster_anchor_orbit_groups_pois_by_proximity():
    from agents.tools import cluster_anchor_orbit
    from dianping.schemas import POI

    pois = [
        POI(
            openshopid="a", name="A", city="深圳", latitude=22.5429, longitude=114.0596
        ),
        POI(
            openshopid="b", name="B", city="深圳", latitude=22.5500, longitude=114.0650
        ),
        POI(
            openshopid="c", name="C", city="深圳", latitude=22.7200, longitude=114.2500
        ),
    ]
    clusters = cluster_anchor_orbit(pois, k=2, max_radius_km=5.0)
    assert len(clusters) == 2
    sizes = sorted([len(c) for c in clusters])
    assert sizes == [1, 2]


def test_check_business_hours_open_at_lunch():
    from agents.tools import check_business_hours
    from dianping.schemas import POI

    poi = POI(
        openshopid="x",
        name="海底捞",
        city="深圳",
        latitude=22.5,
        longitude=114.0,
        business_hour="11:00-22:00",
    )
    assert check_business_hours(poi, datetime(2026, 5, 8, 12, 30))
    assert not check_business_hours(poi, datetime(2026, 5, 8, 9, 0))


def test_check_business_hours_split_session():
    from agents.tools import check_business_hours
    from dianping.schemas import POI

    poi = POI(
        openshopid="x",
        name="餐厅",
        city="深圳",
        latitude=22.5,
        longitude=114.0,
        business_hour="10:00-14:00, 17:00-22:00",
    )
    assert check_business_hours(poi, datetime(2026, 5, 8, 12, 0))
    assert not check_business_hours(poi, datetime(2026, 5, 8, 15, 0))
    assert check_business_hours(poi, datetime(2026, 5, 8, 18, 0))


def test_filter_by_intent_constraints_drops_avoid():
    from agents.tools import filter_by_intent_constraints
    from dianping.schemas import POI, ParsedIntent

    pois = [
        POI(
            openshopid="a",
            name="某夜店",
            city="深圳",
            latitude=22.5,
            longitude=114.0,
            categories=["休闲娱乐"],
        ),
        POI(
            openshopid="b",
            name="海底捞",
            city="深圳",
            latitude=22.5,
            longitude=114.0,
            categories=["美食"],
        ),
    ]
    intent = ParsedIntent(city="深圳", days=1, traveler_type="情侣", avoid=["夜店"])
    out = filter_by_intent_constraints(pois, intent)
    assert {p.openshopid for p in out} == {"b"}


def test_filter_by_intent_constraints_budget_match():
    from agents.tools import filter_by_intent_constraints
    from dianping.schemas import POI, ParsedIntent

    pois = [
        POI(
            openshopid="cheap",
            name="x",
            city="深圳",
            latitude=22.5,
            longitude=114.0,
            categories=["美食"],
            avgprice=30,
        ),
        POI(
            openshopid="mid",
            name="y",
            city="深圳",
            latitude=22.5,
            longitude=114.0,
            categories=["美食"],
            avgprice=200,
        ),
        POI(
            openshopid="lux",
            name="z",
            city="深圳",
            latitude=22.5,
            longitude=114.0,
            categories=["美食"],
            avgprice=800,
        ),
    ]
    intent = ParsedIntent(
        city="深圳", days=1, traveler_type="情侣", budget_level="适中"
    )
    out = filter_by_intent_constraints(pois, intent)
    ids = {p.openshopid for p in out}
    assert ids == {"mid"}
