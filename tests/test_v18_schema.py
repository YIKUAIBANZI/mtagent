"""v1.8 ParsedIntent 新字段单测."""

from dianping.schemas import ParsedIntent


def test_parsed_intent_has_v18_trip_mode_default_none():
    intent = ParsedIntent(city="深圳", days=1, traveler_type="情侣")
    assert intent.trip_mode is None
    assert intent.anchor_radius_km is None
    assert intent.hub_type is None
    assert intent.safety_margin_min is None
    assert intent.anchor_lng is None
    assert intent.anchor_lat is None
    assert intent.anchor_resolved_name is None


def test_parsed_intent_accepts_v18_anchor_explore():
    intent = ParsedIntent(
        city="深圳",
        days=1,
        traveler_type="情侣",
        trip_mode="anchor_explore",
        anchor_radius_km=3.0,
        anchor_lng=114.057,
        anchor_lat=22.541,
        anchor_resolved_name="深圳万象天地",
    )
    assert intent.trip_mode == "anchor_explore"
    assert intent.anchor_radius_km == 3.0


def test_parsed_intent_accepts_v18_layover_eat():
    intent = ParsedIntent(
        city="上海",
        days=1,
        traveler_type="独行",
        trip_mode="layover_eat",
        hub_type="train",
        safety_margin_min=30,
        anchor_lng=121.456,
        anchor_lat=31.249,
        anchor_resolved_name="上海站",
    )
    assert intent.trip_mode == "layover_eat"
    assert intent.hub_type == "train"
    assert intent.safety_margin_min == 30


def test_parsed_intent_backward_compat_no_v18_fields():
    """老 v1.7 路径不带 v1.8 字段, 仍能构造."""
    intent = ParsedIntent(city="西安", days=2, traveler_type="情侣")
    dumped = intent.model_dump()
    assert "trip_mode" in dumped
    assert dumped["trip_mode"] is None
