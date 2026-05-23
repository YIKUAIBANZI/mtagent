"""build_rationale_for_stop with optional prev_squeeze_pct appends a meal-rush note."""

from datetime import time
from types import SimpleNamespace

from agents.rationale import build_rationale_for_stop
from dianping.schemas import POI, Stop, TimeSlot


def _stop_meal() -> Stop:
    return Stop(
        poi=POI(
            openshopid="x",
            name="测试餐厅",
            city="深圳",
            latitude=22.5,
            longitude=114.0,
            categories=["中餐厅"],
        ),
        slot=TimeSlot(name="午饭", start=time(11, 30), end=time(12, 30)),
        arrival_time=time(12, 30),
        leave_time=time(13, 40),
        recommended_duration_min=70,
    )


def test_squeeze_note_appended_when_pct_provided() -> None:
    intent = SimpleNamespace(
        traveler_type="情侣",
        must_visit=[],
        city="南昌",
        required_slots=[],
    )
    out = build_rationale_for_stop(
        intent,
        _stop_meal(),
        variant="main",
        prev_squeeze_pct=80,
        prev_stop_name="博物馆 A",
    )
    assert "为了赶" in out["text"]
    assert "博物馆 A" in out["text"]
    assert "80%" in out["text"]
    # Original text preserved (suffix appended, not replaced)
    assert "测试餐厅" in out["text"] or "午饭" in out["text"]


def test_no_note_when_pct_none() -> None:
    intent = SimpleNamespace(
        traveler_type="情侣",
        must_visit=[],
        city="南昌",
        required_slots=[],
    )
    out = build_rationale_for_stop(intent, _stop_meal(), variant="main")
    assert "为了赶" not in out["text"]


def test_no_note_when_pct_is_100() -> None:
    """prev_squeeze_pct=100 means no actual squeeze → no note."""
    intent = SimpleNamespace(
        traveler_type="情侣",
        must_visit=[],
        city="南昌",
        required_slots=[],
    )
    out = build_rationale_for_stop(
        intent,
        _stop_meal(),
        variant="main",
        prev_squeeze_pct=100,
        prev_stop_name="博物馆 A",
    )
    assert "为了赶" not in out["text"]
