"""Test the /api/plan/stream endpoint emits the v1 spec §5 event protocol."""

import json

import pytest


@pytest.fixture(scope="module")
def app_client(sse_app_client):
    return sse_app_client


def parse_sse_stream(content: bytes) -> list[dict]:
    """Parse raw SSE bytes into a list of {event, data} dicts."""
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


def test_stream_returns_sse_content_type(app_client):
    with app_client.stream(
        "POST",
        "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳"},
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]


def test_stream_emits_full_event_sequence(app_client):
    with app_client.stream(
        "POST",
        "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳预算 3000 爱拍照"},
    ) as resp:
        body = b"".join(resp.iter_bytes())
    events = parse_sse_stream(body)
    names = [e["event"] for e in events]

    assert "trip.started" in names
    assert "profiler.start" in names
    assert "profiler.understood" in names
    assert "profiler.ready" in names
    assert "planner.start" in names
    assert "planner.anchors" in names
    assert "planner.candidates_loaded" in names
    assert "planner.clusters_ready" in names
    assert "planner.compose_start" in names
    assert "planner.done" in names
    assert "critic.start" in names
    assert "critic.done" in names
    assert "trip.complete" in names

    assert names.index("trip.started") == 0
    assert names.index("trip.complete") == len(names) - 1


def test_understood_event_has_parsed_intent(app_client):
    with app_client.stream(
        "POST",
        "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳"},
    ) as resp:
        body = b"".join(resp.iter_bytes())
    events = parse_sse_stream(body)
    understood = next(e for e in events if e["event"] == "profiler.understood")
    assert understood["data"]["city"] == "深圳"
    assert understood["data"]["days"] == 3
    assert understood["data"]["traveler_type"] == "情侣"


def test_planner_done_event_has_route(app_client):
    with app_client.stream(
        "POST",
        "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳"},
    ) as resp:
        body = b"".join(resp.iter_bytes())
    events = parse_sse_stream(body)
    done = next(e for e in events if e["event"] == "planner.done")
    assert "route" in done["data"]
    route = done["data"]["route"]
    assert "days" in route
    assert len(route["days"]) == 3
