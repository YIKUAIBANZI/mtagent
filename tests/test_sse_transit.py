"""SSE protocol tests for v2 transit.updated events."""

import json


def _parse_events(raw: str) -> list[dict]:
    out = []
    for block in raw.strip().split("\n\n"):
        ev = data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                ev = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if ev:
            out.append({"event": ev, "data": data})
    return out


def test_one_transit_updated_per_day(sse_app_client):
    resp = sse_app_client.post(
        "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳预算 3000 爱拍照"},
    )
    assert resp.status_code == 200
    events = _parse_events(resp.text)
    transits = [e for e in events if e["event"] == "transit.updated"]
    day_dones = [e for e in events if e["event"] == "planner.day_done"]

    assert len(transits) == len(day_dones)
    transit_days = sorted(t["data"]["day_index"] for t in transits)
    day_done_days = sorted(d["data"]["day_index"] for d in day_dones)
    assert transit_days == day_done_days


def test_transit_segments_have_4_modes_each(sse_app_client):
    resp = sse_app_client.post(
        "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳预算 3000 爱拍照"},
    )
    events = _parse_events(resp.text)
    for t in (e for e in events if e["event"] == "transit.updated"):
        for seg in t["data"]["segments"]:
            assert set(seg["options"].keys()) == {"drive", "walk", "transit", "bicycle"}
            assert seg["recommended"] in {"drive", "walk", "transit", "bicycle"}


def test_transit_segments_count_equals_stops_minus_one(sse_app_client):
    resp = sse_app_client.post(
        "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳预算 3000 爱拍照"},
    )
    events = _parse_events(resp.text)
    day_done_by_idx = {
        e["data"]["day_index"]: e for e in events if e["event"] == "planner.day_done"
    }
    for t in (e for e in events if e["event"] == "transit.updated"):
        di = t["data"]["day_index"]
        n_stops = len(day_done_by_idx[di]["data"]["stops"])
        assert len(t["data"]["segments"]) == max(0, n_stops - 1)
