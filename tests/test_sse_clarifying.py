"""Test Profiler clarifying flow."""

import json

import pytest


@pytest.fixture(scope="module")
def app_client(sse_app_client):
    return sse_app_client


def parse_sse(body: bytes) -> list[dict]:
    events = []
    for chunk in body.decode("utf-8").split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        ev = {"event": None, "data": None}
        for line in chunk.splitlines():
            if line.startswith("event: "):
                ev["event"] = line[len("event: ") :]
            elif line.startswith("data: "):
                ev["data"] = json.loads(line[len("data: ") :])
        events.append(ev)
    return events


def test_partial_input_emits_clarifying(app_client):
    """Input without days+traveler_type → clarifying event + early close."""
    with app_client.stream(
        "POST",
        "/api/plan/stream",
        json={"free_text": "深圳"},
    ) as resp:
        body = b"".join(resp.iter_bytes())
    events = parse_sse(body)
    names = [e["event"] for e in events]

    assert "profiler.clarifying" in names
    clarifying = next(e for e in events if e["event"] == "profiler.clarifying")
    assert "days" in clarifying["data"]["missing_fields"]
    assert "traveler_type" in clarifying["data"]["missing_fields"]

    assert "planner.start" not in names
    assert "trip.complete" in names
    complete = next(e for e in events if e["event"] == "trip.complete")
    assert complete["data"]["status"] == "awaiting_clarification"


def test_extra_fields_complete_clarifying(app_client):
    """Re-submit with extra fields → full pipeline runs."""
    with app_client.stream(
        "POST",
        "/api/plan/stream",
        json={
            "free_text": "深圳",
            "extra": {"days": 2, "traveler_type": "情侣"},
        },
    ) as resp:
        body = b"".join(resp.iter_bytes())
    events = parse_sse(body)
    names = [e["event"] for e in events]

    assert "profiler.ready" in names
    assert "planner.start" in names
    assert "planner.done" in names
