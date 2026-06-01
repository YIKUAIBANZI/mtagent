"""Test SSE event serialization helpers."""


def test_format_event_basic():
    from api.sse import format_event

    out = format_event("trip.started", {"trip_id": "trip_abc"})
    assert out.startswith("event: trip.started\n")
    assert "data: " in out
    assert out.endswith("\n\n")
    assert '"trip_id":"trip_abc"' in out or '"trip_id": "trip_abc"' in out


def test_format_event_chinese_unescaped():
    """Chinese must NOT be \\uXXXX-escaped — UTF-8 should be raw in the data line."""
    from api.sse import format_event

    out = format_event("profiler.understood", {"city": "深圳"})
    assert "深圳" in out


def test_format_event_data_is_single_line():
    """Per SSE protocol: data: must be on a single line."""
    from api.sse import format_event

    out = format_event("planner.token", {"chunk": "今天\n上午"})
    data_line = [ln for ln in out.split("\n") if ln.startswith("data:")][0]
    assert "\n" not in data_line[6:]


def test_format_event_with_empty_data():
    from api.sse import format_event

    out = format_event("trip.complete", {})
    assert out.startswith("event: trip.complete\n")
    assert "data: {}" in out
