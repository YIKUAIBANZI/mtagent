"""Unit tests for v1.6 per-day streaming + coords (parse_partial_stops, build_one_day_payload, compose_one_day)."""

import json

from agents.planner import Planner, _parse_partial_stops
from agents.tools import default_pace_for_traveler, generate_day_template
from dianping.client import DianpingClient
from dianping.schemas import POI, ParsedIntent, ReviewTag


def test_parse_partial_stops_extracts_names_from_complete_json():
    buf = '{"stops":[{"name":"钟楼","slot_name":"上午景点"},{"name":"回民街","slot_name":"午饭"}]}'
    assert _parse_partial_stops(buf) == ["钟楼", "回民街"]


def test_parse_partial_stops_extracts_partial_from_incomplete_json():
    buf = '{"stops":[{"name":"钟楼","slot_name":"上午景点"},{"name":"回'
    assert _parse_partial_stops(buf) == ["钟楼"]


def test_parse_partial_stops_returns_empty_on_garbage():
    assert _parse_partial_stops("not-json-at-all") == []
    assert _parse_partial_stops("") == []
    assert _parse_partial_stops('{"summary":"xxx"}') == []


def test_parse_partial_stops_tolerates_whitespace_and_newlines():
    buf = '{\n  "stops": [\n    { "name" : "兵马俑" }\n  ]'
    assert _parse_partial_stops(buf) == ["兵马俑"]


def test_parse_partial_stops_extracts_multiple_in_order():
    buf = '{"stops":[{"name":"A"},{"name":"B"},{"name":"C"}]}'
    assert _parse_partial_stops(buf) == ["A", "B", "C"]


# ===== Task 2: _build_one_day_payload tests =====


def _make_intent(**kwargs):
    defaults = dict(
        city="西安",
        days=3,
        traveler_type="家庭亲子",
        budget_level="性价比",
        pace=None,
        preferences=["拍照"],
        must_visit=[],
        avoid=[],
    )
    defaults.update(kwargs)
    return ParsedIntent(**defaults)


def _make_poi(name: str, openshopid: str, categories: list[str]) -> POI:
    return POI(
        openshopid=openshopid,
        name=name,
        city="西安",
        latitude=34.26,
        longitude=108.94,
        categories=categories,
        avgprice=150,
        star=4.5,
        reviewTags=[ReviewTag(tag="好玩", hit=3)],
        business_hour="09:00-21:00",
    )


def _planner() -> Planner:
    return Planner(
        client=DianpingClient(base_url="http://test", appkey="x", secret="x")
    )


def test_build_one_day_payload_only_contains_one_day_candidates():
    p = _planner()
    intent = _make_intent()
    pace = default_pace_for_traveler(intent.traveler_type)
    templates = generate_day_template(
        days=3, traveler_type=intent.traveler_type, pace=pace
    )
    anchor = ("钟楼", 34.26, 108.94)
    day_cluster = [_make_poi(f"poi_{i}", f"id_{i}", ["景点"]) for i in range(5)]
    # control cluster (intentionally not passed to payload — verifies isolation)
    _ = [_make_poi(f"OTHER_{i}", f"oid_{i}", ["景点"]) for i in range(5)]

    payload_str = p._build_one_day_payload(
        day_idx=0,
        intent=intent,
        template=templates[0],
        anchor=anchor,
        day_cluster_pois=day_cluster,
    )
    payload = json.loads(payload_str)

    candidate_names = [c["name"] for c in payload["candidates"]]
    assert all(n.startswith("poi_") for n in candidate_names)
    assert not any(n.startswith("OTHER_") for n in candidate_names)


def test_build_one_day_payload_uses_correct_slot_template():
    p = _planner()
    intent = _make_intent()
    pace = default_pace_for_traveler(intent.traveler_type)
    templates = generate_day_template(
        days=3, traveler_type=intent.traveler_type, pace=pace
    )
    anchor = ("钟楼", 34.26, 108.94)
    day_cluster = [_make_poi("钟楼", "id_z", ["景点"])]

    payload_str = p._build_one_day_payload(
        day_idx=2,
        intent=intent,
        template=templates[2],
        anchor=anchor,
        day_cluster_pois=day_cluster,
    )
    payload = json.loads(payload_str)

    assert payload["day_index"] == 2
    expected_slot_names = [s.name for s in templates[2].slots]
    actual_slot_names = [s["name"] for s in payload["slots"]]
    assert actual_slot_names == expected_slot_names


def test_build_one_day_payload_caps_candidates_at_30():
    p = _planner()
    intent = _make_intent()
    pace = default_pace_for_traveler(intent.traveler_type)
    templates = generate_day_template(
        days=3, traveler_type=intent.traveler_type, pace=pace
    )
    anchor = ("钟楼", 34.26, 108.94)
    large_cluster = [_make_poi(f"poi_{i}", f"id_{i}", ["景点"]) for i in range(50)]

    payload_str = p._build_one_day_payload(
        day_idx=0,
        intent=intent,
        template=templates[0],
        anchor=anchor,
        day_cluster_pois=large_cluster,
    )
    payload = json.loads(payload_str)

    assert len(payload["candidates"]) == 30
