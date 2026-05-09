"""SSE protocol tests for v1.5 planner.rationale events.

Verifies event positions and field schema relative to v1 anchors / day_done events.
Uses the shared sse_app_client fixture from conftest.py.
"""

from __future__ import annotations

import json


def _parse_events(raw: str) -> list[dict]:
    """Parse SSE wire-format text into list of {event, data} dicts."""
    events: list[dict] = []
    for block in raw.strip().split("\n\n"):
        ev_name = None
        ev_data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                ev_name = line[len("event: ") :]
            elif line.startswith("data: "):
                ev_data = json.loads(line[len("data: ") :])
        if ev_name is not None:
            events.append({"event": ev_name, "data": ev_data})
    return events


def test_anchors_rationale_emitted_after_anchors_event(sse_app_client):
    """planner.rationale (stage=anchors) must follow planner.anchors immediately."""
    resp = sse_app_client.post(
        "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳预算 3000 爱拍照"},
    )
    assert resp.status_code == 200

    events = _parse_events(resp.text)
    names = [e["event"] for e in events]

    assert "planner.anchors" in names
    anchor_idx = names.index("planner.anchors")

    assert anchor_idx + 1 < len(names), "no event after planner.anchors"
    next_ev = events[anchor_idx + 1]
    assert next_ev["event"] == "planner.rationale"
    assert next_ev["data"]["stage"] == "anchors"
    assert next_ev["data"]["day_index"] is None
    assert isinstance(next_ev["data"]["text"], str)
    assert len(next_ev["data"]["text"]) > 0
    assert isinstance(next_ev["data"]["key_factors"], list)


def test_day_rationale_follows_each_day_done(sse_app_client):
    """Each planner.day_done must be immediately followed by planner.rationale (compose)."""
    resp = sse_app_client.post(
        "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳预算 3000 爱拍照"},
    )
    assert resp.status_code == 200

    events = _parse_events(resp.text)
    day_done_indices = [
        i for i, e in enumerate(events) if e["event"] == "planner.day_done"
    ]
    assert len(day_done_indices) >= 1, "expected at least one planner.day_done"

    for di in day_done_indices:
        assert di + 1 < len(events), f"no event after day_done at index {di}"
        next_ev = events[di + 1]
        assert next_ev["event"] == "planner.rationale", (
            f"event after day_done is {next_ev['event']}, expected planner.rationale"
        )
        assert next_ev["data"]["stage"] == "compose"
        assert next_ev["data"]["day_index"] == events[di]["data"]["day_index"]
        assert isinstance(next_ev["data"]["text"], str)
        assert len(next_ev["data"]["text"]) > 0


def test_total_rationale_count_equals_one_plus_days(sse_app_client):
    """Should have 1 anchors rationale + 1 compose rationale per day_done."""
    resp = sse_app_client.post(
        "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳预算 3000 爱拍照"},
    )
    events = _parse_events(resp.text)
    rationales = [e for e in events if e["event"] == "planner.rationale"]
    stages = [r["data"]["stage"] for r in rationales]

    assert stages.count("anchors") == 1
    day_done_count = sum(1 for e in events if e["event"] == "planner.day_done")
    assert stages.count("compose") == day_done_count
