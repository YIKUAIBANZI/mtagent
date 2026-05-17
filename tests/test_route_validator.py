"""Route validator unit tests. 不依赖 mock data, 全部合成 DayPlan."""

from __future__ import annotations


import pytest

from agents.route_validator import (
    GOAL_STOPS_BY_PACE,
    CheckResult,
    ValidationReport,
)


def test_goal_stops_by_pace_matches_teammate_doc():
    """队友调研: 暴走=5, 适中=4, 佛系=3."""
    assert GOAL_STOPS_BY_PACE["暴走"] == 5
    assert GOAL_STOPS_BY_PACE["适中"] == 4
    assert GOAL_STOPS_BY_PACE["佛系"] == 3


def test_validation_report_score_basic():
    r = ValidationReport(
        checks=[
            CheckResult(name="a", passed=True),
            CheckResult(name="b", passed=False, detail="oops"),
            CheckResult(name="c", passed=True),
        ]
    )
    assert r.total == 3
    assert r.passed_count == 2
    assert r.score == pytest.approx(2 / 3)
    assert [c.name for c in r.failed] == ["b"]


from datetime import time as _t

from dianping.schemas import DayPlan, ParsedIntent, POI, Stop, TimeSlot


def _poi(
    name: str = "x",
    lat: float = 30.0,
    lng: float = 120.0,
    cats: list[str] | None = None,
) -> POI:
    return POI(
        openshopid=f"id_{name}",
        name=name,
        city="测试市",
        latitude=lat,
        longitude=lng,
        categories=cats or ["景点"],
    )


def _stop(slot_name: str, start_h: int, end_h: int, poi: POI | None = None) -> Stop:
    return Stop(
        poi=poi or _poi(),
        slot=TimeSlot(name=slot_name, start=_t(start_h, 0), end=_t(end_h, 0)),
        arrival_time=_t(start_h, 0),
        leave_time=_t(end_h, 0),
        transport_to_next_minutes=20,
    )


def _day(stops: list[Stop]) -> DayPlan:
    return DayPlan(day_index=0, stops=stops)


def _intent(traveler_type: str = "情侣", pace=None, **over) -> ParsedIntent:
    return ParsedIntent(
        city="测试市",
        days=1,
        traveler_type=traveler_type,
        pace=pace,
        **over,
    )


def test_stop_count_ok_passes_for_4_stops_balanced_traveler():
    from agents.route_validator import validate_day

    day = _day(
        [
            _stop("上午景点", 9, 12),
            _stop("午饭", 12, 13),
            _stop("下午", 13, 17),
            _stop("晚饭", 18, 19),
        ]
    )
    report = validate_day(day, _intent(traveler_type="情侣"))
    chk = next(c for c in report.checks if c.name == "stop_count_ok")
    assert chk.passed, chk.detail


def test_stop_count_ok_fails_for_2_stops_balanced_traveler():
    """当前南昌 bug 的真实形态: 情侣(适中=4) 但只跑出 2-3 stops."""
    from agents.route_validator import validate_day

    day = _day([_stop("上午景点", 9, 12), _stop("午饭", 12, 13)])
    report = validate_day(day, _intent(traveler_type="情侣"))
    chk = next(c for c in report.checks if c.name == "stop_count_ok")
    assert not chk.passed
    assert "2" in chk.detail and "4" in chk.detail


def test_stop_count_ok_uses_intent_pace_override():
    from agents.route_validator import validate_day

    day = _day([_stop("上午景点", 9, 12)] * 4)
    report = validate_day(day, _intent(traveler_type="情侣", pace="暴走"))
    chk = next(c for c in report.checks if c.name == "stop_count_ok")
    assert not chk.passed


_MEAL_CATS = ["美食"]  # _infer_role_from_categories 会把它判为 meal
_ATTRACTION_CATS = ["景点"]


def test_has_lunch_passes_when_meal_stop_at_noon():
    from agents.route_validator import validate_day

    day = _day(
        [
            _stop("上午景点", 9, 12, poi=_poi("morning", cats=_ATTRACTION_CATS)),
            _stop("午饭", 12, 13, poi=_poi("lunch", cats=_MEAL_CATS)),
            _stop("下午", 13, 17, poi=_poi("aft", cats=_ATTRACTION_CATS)),
            _stop("晚饭", 18, 19, poi=_poi("dinner", cats=_MEAL_CATS)),
        ]
    )
    report = validate_day(day, _intent())
    assert next(c for c in report.checks if c.name == "has_lunch").passed
    assert next(c for c in report.checks if c.name == "has_dinner").passed


def test_has_lunch_fails_when_only_attractions_at_noon():
    from agents.route_validator import validate_day

    day = _day(
        [
            _stop("上午景点", 9, 12, poi=_poi("a", cats=_ATTRACTION_CATS)),
            _stop("午饭", 12, 13, poi=_poi("not_meal", cats=_ATTRACTION_CATS)),
            _stop("下午", 13, 17, poi=_poi("b", cats=_ATTRACTION_CATS)),
            _stop("晚饭", 18, 19, poi=_poi("dinner", cats=_MEAL_CATS)),
        ]
    )
    report = validate_day(day, _intent())
    assert not next(c for c in report.checks if c.name == "has_lunch").passed


def test_has_dinner_fails_when_no_evening_meal():
    from agents.route_validator import validate_day

    day = _day(
        [
            _stop("上午景点", 9, 12, poi=_poi("a", cats=_ATTRACTION_CATS)),
            _stop("午饭", 12, 13, poi=_poi("lunch", cats=_MEAL_CATS)),
        ]
    )
    report = validate_day(day, _intent())
    assert not next(c for c in report.checks if c.name == "has_dinner").passed
