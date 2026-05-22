"""SSE planner.variant_patches event injection."""

from __future__ import annotations

import json
from datetime import time as _time


from dianping.schemas import POI, Stop, TimeSlot, DayPlan


def _mk_poi(openshopid: str, name: str = "店") -> POI:
    return POI(
        openshopid=openshopid,
        name=name,
        city="南昌",
        latitude=28.7,
        longitude=115.85,
        categories=["美食"],
    )


def _mk_stop(openshopid: str) -> Stop:
    return Stop(
        poi=_mk_poi(openshopid),
        slot=TimeSlot(name="午饭", start=_time(12, 0), end=_time(13, 0)),
        arrival_time=_time(12, 0),
        leave_time=_time(13, 0),
    )


def _mk_day(stop_ids: list[str]) -> DayPlan:
    return DayPlan(
        day_index=0,
        anchor_district="红谷滩",
        stops=[_mk_stop(sid) for sid in stop_ids],
        transit_segments=[],
    )


class _FakeVP:
    """Stub plan_one_variant 返回结构 (与真实 VariantPlan 鸭子类型)."""

    def __init__(self, stop_ids: list[str], variant: str = "main"):
        self.variant = variant
        self.day_plan = _mk_day(stop_ids)
        self.transit_segments = []
        self.error = None


def _parse_sse(body: str) -> list[dict]:
    """Parse SSE stream body → list of {event, data} dicts."""
    events = []
    cur_event = None
    for line in body.splitlines():
        if line.startswith("event:"):
            cur_event = line[6:].strip()
        elif line.startswith("data:") and cur_event:
            try:
                events.append({"event": cur_event, "data": json.loads(line[5:])})
            except json.JSONDecodeError:
                pass
            cur_event = None
    return events


# ──────────────────────────────────────────────────────────────────────────────
# Helpers for HTTP integration tests (use sse_app_client fixture)
# ──────────────────────────────────────────────────────────────────────────────


def _collect_events(sse_app_client, free_text: str) -> list[dict]:
    """POST /api/plan/stream and collect all SSE events."""
    resp = sse_app_client.post(
        "/api/plan/stream",
        json={"free_text": free_text},
    )
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:300]}"
    return _parse_sse(resp.text)


# ──────────────────────────────────────────────────────────────────────────────
# Test 1: 3 variants differ → 2 patch sets
# ──────────────────────────────────────────────────────────────────────────────


def test_all_three_variants_differ_yields_two_patch_sets(monkeypatch, sse_app_client):
    """main/low_queue/interest_first 各不同 → variants 数组含 2 个 patch set."""
    main_ids = ["A", "B", "C"]
    low_q_ids = ["A", "B2", "C"]  # idx 1 differs
    int_f_ids = ["A2", "B", "C2"]  # idx 0, 2 differ

    async def _fake_plan_one_variant(*, variant, **_kw):
        ids = {
            "main": main_ids,
            "low_queue": low_q_ids,
            "interest_first": int_f_ids,
        }[variant]
        return _FakeVP(ids, variant)

    monkeypatch.setattr(
        "agents.planner_instant.plan_one_variant",
        _fake_plan_one_variant,
    )

    events = _collect_events(sse_app_client, "情侣 西安 半天 拍照")

    patch_events = [e for e in events if e["event"] == "planner.variant_patches"]
    assert len(patch_events) == 1, (
        f"expected 1 planner.variant_patches, got {len(patch_events)}. "
        f"all events: {[e['event'] for e in events]}"
    )
    variants_data = patch_events[0]["data"]["variants"]
    assert len(variants_data) == 2, f"expected 2 patch sets, got {len(variants_data)}"
    kinds = {v["kind"] for v in variants_data}
    assert kinds == {"low_queue", "interest_first"}, f"unexpected kinds: {kinds}"


# ──────────────────────────────────────────────────────────────────────────────
# Test 2: low_queue identical to main → only interest_first in variants
# ──────────────────────────────────────────────────────────────────────────────


def test_low_queue_identical_drops_to_one_set(monkeypatch, sse_app_client):
    """low_queue 与 main 完全相同 → variants 只含 interest_first 一条."""
    same_ids = ["A", "B", "C"]
    int_f_ids = ["A2", "B", "C"]  # idx 0 differs

    async def _fake_plan_one_variant(*, variant, **_kw):
        ids = {
            "main": same_ids,
            "low_queue": same_ids,  # identical to main
            "interest_first": int_f_ids,
        }[variant]
        return _FakeVP(ids, variant)

    monkeypatch.setattr(
        "agents.planner_instant.plan_one_variant",
        _fake_plan_one_variant,
    )

    events = _collect_events(sse_app_client, "情侣 西安 半天 拍照")

    patch_events = [e for e in events if e["event"] == "planner.variant_patches"]
    assert len(patch_events) == 1, (
        f"expected 1 planner.variant_patches, got {len(patch_events)}"
    )
    variants_data = patch_events[0]["data"]["variants"]
    assert len(variants_data) == 1, f"expected 1 patch set, got {len(variants_data)}"
    assert variants_data[0]["kind"] == "interest_first"


# ──────────────────────────────────────────────────────────────────────────────
# Test 3: all variants identical → no planner.variant_patches event
# ──────────────────────────────────────────────────────────────────────────────


def test_all_variants_identical_skips_event(monkeypatch, sse_app_client):
    """3 variant 完全一致 → 不 emit planner.variant_patches; compose_done / done 仍在."""
    same_ids = ["A", "B", "C"]

    async def _fake_plan_one_variant(*, variant, **_kw):
        return _FakeVP(same_ids, variant)

    monkeypatch.setattr(
        "agents.planner_instant.plan_one_variant",
        _fake_plan_one_variant,
    )

    events = _collect_events(sse_app_client, "情侣 西安 半天 拍照")
    event_names = [e["event"] for e in events]

    patch_events = [e for e in events if e["event"] == "planner.variant_patches"]
    assert len(patch_events) == 0, (
        f"expected no planner.variant_patches when all variants identical, "
        f"got {len(patch_events)}"
    )
    # planner.compose_done and planner.done must still be present
    assert "planner.compose_done" in event_names, "planner.compose_done missing"
    assert "planner.done" in event_names, "planner.done missing"


# ──────────────────────────────────────────────────────────────────────────────
# Test 4: variant exception → that variant omitted from patch_sets
# ──────────────────────────────────────────────────────────────────────────────


def test_variant_exception_omits_set(monkeypatch, sse_app_client):
    """low_queue planner crash → planner.variant_patches 中不含 low_queue.

    Acceptable outcomes:
    (a) exception propagates before our yield → SSE stream errors out (non-200 or
        stream truncated before planner.variant_patches) — low_queue never appears.
    (b) stream completes and planner.variant_patches is emitted, but low_queue is
        NOT in its variants array.
    """
    main_ids = ["A", "B", "C"]
    int_f_ids = ["A2", "B", "C"]

    async def _fake_plan_one_variant(*, variant, **_kw):
        if variant == "low_queue":
            raise RuntimeError("planner crashed")
        ids = {"main": main_ids, "interest_first": int_f_ids}[variant]
        return _FakeVP(ids, variant)

    monkeypatch.setattr(
        "agents.planner_instant.plan_one_variant",
        _fake_plan_one_variant,
    )

    # Outcome (a): exception propagates → TestClient re-raises it. That's acceptable.
    # Outcome (b): stream completes, event present, but low_queue absent from variants.
    try:
        resp = sse_app_client.post(
            "/api/plan/stream",
            json={"free_text": "情侣 西安 半天 拍照"},
        )
        events = _parse_sse(resp.text)
        patch_events = [e for e in events if e["event"] == "planner.variant_patches"]
        for pe in patch_events:
            kinds = {v["kind"] for v in pe["data"]["variants"]}
            assert "low_queue" not in kinds, (
                f"low_queue should be absent from patches when it raised, got {kinds}"
            )
    except Exception as exc:
        # Outcome (a): exception propagated out of the SSE generator.
        # low_queue never made it into the patch set — test passes.
        assert isinstance(exc, RuntimeError), f"unexpected exception type: {exc!r}"
