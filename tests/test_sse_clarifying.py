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


def test_minimal_input_uses_defaults_and_proceeds(app_client):
    """v1.7 默认行为: 仅城市输入也不应让用户补 days/traveler_type.

    backfill 规则: days 缺 → time_window=一日, traveler_type 缺 → 情侣.
    用户期望: 发一个'西安'就能直接出方案, 不要再追问.
    """
    with app_client.stream(
        "POST",
        "/api/plan/stream",
        json={"free_text": "深圳"},
    ) as resp:
        body = b"".join(resp.iter_bytes())
    events = parse_sse(body)
    names = [e["event"] for e in events]

    # 不应阻塞用户补充信息
    assert "profiler.clarifying" not in names
    # 走完正常 pipeline
    assert "profiler.ready" in names
    assert "planner.start" in names
    # trip 完成状态正常
    complete = next(e for e in events if e["event"] == "trip.complete")
    assert complete["data"]["status"] == "ok"


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
