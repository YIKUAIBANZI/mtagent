"""End-to-end smoke test for v1.6 per-day streaming.

Hits in-process mock_server via sse_app_client fixture and asserts:
- 3 day_done events with longitude/latitude
- transit_segments persisted to /api/plan/{trip_id}
- wallclock under 25s (cold-start buffer; warm ≤ 20s target with real LLM)
"""

import json
import os
import time

import pytest


@pytest.fixture(scope="module")
def app_client(sse_app_client):
    return sse_app_client


def _parse_sse(content: bytes) -> list[dict]:
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


def test_e2e_3_day_trip_under_25s(app_client):
    if os.environ.get("MTAGENT_E2E_SMOKE_SKIP") == "1":
        pytest.skip("explicit skip")

    t0 = time.perf_counter()
    with app_client.stream(
        "POST",
        "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳预算 3000 爱拍照"},
    ) as resp:
        body = b"".join(resp.iter_bytes())
    elapsed = time.perf_counter() - t0

    events = _parse_sse(body)

    day_done = [e for e in events if e["event"] == "planner.day_done"]
    assert len(day_done) == 3
    for e in day_done:
        assert e["data"]["stops"], f"day {e['data']['day_index']} has empty stops"
        for stop in e["data"]["stops"]:
            assert "longitude" in stop
            assert "latitude" in stop

    trip_complete = next((e for e in events if e["event"] == "trip.complete"), None)
    assert trip_complete is not None

    assert elapsed < 25.0, f"e2e wallclock {elapsed:.2f}s exceeds 25s budget"


def test_get_trip_returns_persisted_transit_segments(app_client):
    with app_client.stream(
        "POST",
        "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳"},
    ) as resp:
        body = b"".join(resp.iter_bytes())

    text = body.decode("utf-8")
    trip_id = None
    for chunk in text.split("\n\n"):
        if "trip.started" in chunk:
            for line in chunk.splitlines():
                if line.startswith("data: "):
                    data = json.loads(line[len("data: ") :])
                    trip_id = data.get("trip_id")
                    break
            if trip_id:
                break

    assert trip_id is not None, "trip.started event missing trip_id"

    resp = app_client.get(f"/api/plan/{trip_id}")
    assert resp.status_code == 200
    body_json = resp.json()
    days = body_json.get("draft_route", {}).get("days", [])
    assert len(days) == 3
    for d in days:
        assert "transit_segments" in d
        assert isinstance(d["transit_segments"], list)
