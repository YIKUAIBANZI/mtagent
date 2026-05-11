"""Unit tests for v1.6 per-day streaming + coords (parse_partial_stops, build_one_day_payload, compose_one_day)."""



from agents.planner import _parse_partial_stops


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
