"""SSE protocol tests for v1.6 per-day streaming + day_done coords."""

import json

import pytest


@pytest.fixture(scope="module")
def app_client(sse_app_client):
    return sse_app_client


def parse_sse_stream(content: bytes) -> list[dict]:
    text = content.decode("utf-8")
    events = []
    for chunk in text.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        ev_name = None
        ev_data = None
        for line in chunk.splitlines():
            if line.startswith("event: "):
                ev_name = line[len("event: ") :]
            elif line.startswith("data: "):
                ev_data = json.loads(line[len("data: ") :])
        if ev_name is not None:
            events.append({"event": ev_name, "data": ev_data})
    return events


def test_emits_n_day_done_events_for_n_days(app_client):
    with app_client.stream(
        "POST",
        "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳预算 3000 爱拍照"},
    ) as resp:
        body = b"".join(resp.iter_bytes())
    events = parse_sse_stream(body)
    day_done = [e for e in events if e["event"] == "planner.day_done"]
    assert len(day_done) == 3
    assert sorted(e["data"]["day_index"] for e in day_done) == [0, 1, 2]


def test_day_done_payload_includes_stop_longitude_latitude(app_client):
    with app_client.stream(
        "POST",
        "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳"},
    ) as resp:
        body = b"".join(resp.iter_bytes())
    events = parse_sse_stream(body)
    day_done = [e for e in events if e["event"] == "planner.day_done"]
    assert day_done
    for e in day_done:
        for stop in e["data"]["stops"]:
            assert "longitude" in stop and isinstance(stop["longitude"], (int, float))
            assert "latitude" in stop and isinstance(stop["latitude"], (int, float))
            assert "poi_openshopid" in stop
            assert "slot_name" in stop


def test_day_done_payload_includes_transit_segments(app_client):
    with app_client.stream(
        "POST",
        "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳"},
    ) as resp:
        body = b"".join(resp.iter_bytes())
    events = parse_sse_stream(body)
    day_done = [e for e in events if e["event"] == "planner.day_done"]
    for e in day_done:
        assert "transit_segments" in e["data"]
        assert isinstance(e["data"]["transit_segments"], list)


def test_compose_done_emits_after_all_day_done(app_client):
    with app_client.stream(
        "POST",
        "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳"},
    ) as resp:
        body = b"".join(resp.iter_bytes())
    events = parse_sse_stream(body)
    last_day_done_idx = max(
        (i for i, e in enumerate(events) if e["event"] == "planner.day_done"),
        default=-1,
    )
    compose_done_idx = next(
        (i for i, e in enumerate(events) if e["event"] == "planner.compose_done"),
        -1,
    )
    assert last_day_done_idx >= 0
    assert compose_done_idx > last_day_done_idx


def test_default_stub_path_triggers_fallback_per_day(sse_app_client):
    """Default sse_app_client removes DASHSCOPE_API_KEY so
    resolve_planner_llm_stream returns stub_planner_llm_stream which yields
    `{"stops":[]}`. compose_one_day detects empty stops → PlannerLLMError →
    routes.py catches → emits day_done_fallback then standard day_done
    (with longitude/latitude from _synthesize_fallback_route real POI objects).
    """
    with sse_app_client.stream(
        "POST",
        "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳"},
    ) as resp:
        body = b"".join(resp.iter_bytes())
    events = parse_sse_stream(body)
    fallback_events = [e for e in events if e["event"] == "planner.day_done_fallback"]
    day_done = [e for e in events if e["event"] == "planner.day_done"]

    assert len(fallback_events) == 3, (
        "stub stream returns empty stops; all 3 days fallback"
    )
    assert len(day_done) == 3
    for e in day_done:
        assert e["data"]["stops"], (
            f"day {e['data']['day_index']} should have synthesized stops"
        )
        for stop in e["data"]["stops"]:
            assert "longitude" in stop and "latitude" in stop
