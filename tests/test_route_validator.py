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


def test_cluster_ok_passes_within_5km():
    from agents.route_validator import validate_day

    # 4 个 POI 都在深圳市中心 ~1km 内
    day = _day(
        [
            _stop(
                "上午景点",
                9,
                12,
                poi=_poi("a", lat=22.5400, lng=114.0500, cats=_ATTRACTION_CATS),
            ),
            _stop(
                "午饭",
                12,
                13,
                poi=_poi("b", lat=22.5405, lng=114.0510, cats=_MEAL_CATS),
            ),
            _stop(
                "下午",
                13,
                17,
                poi=_poi("c", lat=22.5450, lng=114.0480, cats=_ATTRACTION_CATS),
            ),
            _stop(
                "晚饭",
                18,
                19,
                poi=_poi("d", lat=22.5420, lng=114.0530, cats=_MEAL_CATS),
            ),
        ]
    )
    report = validate_day(day, _intent())
    assert next(c for c in report.checks if c.name == "cluster_ok").passed


def test_cluster_ok_fails_when_max_pairwise_exceeds_5km():
    from agents.route_validator import validate_day

    # b 跑到 10km 外
    day = _day(
        [
            _stop(
                "上午景点",
                9,
                12,
                poi=_poi("a", lat=22.5400, lng=114.0500, cats=_ATTRACTION_CATS),
            ),
            _stop(
                "午饭",
                12,
                13,
                poi=_poi("b", lat=22.6400, lng=114.0500, cats=_MEAL_CATS),
            ),
            _stop(
                "下午",
                13,
                17,
                poi=_poi("c", lat=22.5450, lng=114.0480, cats=_ATTRACTION_CATS),
            ),
            _stop(
                "晚饭",
                18,
                19,
                poi=_poi("d", lat=22.5420, lng=114.0530, cats=_MEAL_CATS),
            ),
        ]
    )
    report = validate_day(day, _intent())
    chk = next(c for c in report.checks if c.name == "cluster_ok")
    assert not chk.passed
    assert "km" in chk.detail


def test_transit_ok_passes_when_all_legs_under_30min():
    from agents.route_validator import validate_day

    day = _day(
        [
            _stop("上午景点", 9, 12, poi=_poi("a", cats=_ATTRACTION_CATS)),
            _stop("午饭", 12, 13, poi=_poi("b", cats=_MEAL_CATS)),
        ]
    )
    # 默认 _stop transport_to_next_minutes=20, 应通过
    assert next(
        c for c in validate_day(day, _intent()).checks if c.name == "transit_ok"
    ).passed


def test_transit_ok_fails_when_a_leg_exceeds_30min():
    from agents.route_validator import validate_day

    s1 = _stop("上午景点", 9, 12, poi=_poi("a", cats=_ATTRACTION_CATS))
    s1 = s1.model_copy(update={"transport_to_next_minutes": 45})
    day = _day([s1, _stop("午饭", 12, 13, poi=_poi("b", cats=_MEAL_CATS))])
    chk = next(c for c in validate_day(day, _intent()).checks if c.name == "transit_ok")
    assert not chk.passed
    assert "45" in chk.detail


def test_type_diversity_passes_with_mixed_roles():
    from agents.route_validator import validate_day

    day = _day(
        [
            _stop("上午景点", 9, 12, poi=_poi("a", cats=["景点"])),
            _stop("午饭", 12, 13, poi=_poi("b", cats=["美食"])),
            _stop("下午", 13, 17, poi=_poi("c", cats=["购物"])),
            _stop("晚饭", 18, 19, poi=_poi("d", cats=["美食"])),
        ]
    )
    assert next(
        c for c in validate_day(day, _intent()).checks if c.name == "type_diversity"
    ).passed


def test_type_diversity_fails_when_3_same_role():
    """3 个景点 (→role city_essential) -> 队友规律: 立即疲劳."""
    from agents.route_validator import validate_day

    day = _day(
        [
            _stop("上午景点", 9, 12, poi=_poi("a", cats=["景点"])),
            _stop("午饭", 12, 13, poi=_poi("b", cats=["美食"])),
            _stop("下午", 13, 17, poi=_poi("c", cats=["景点"])),
            _stop("晚饭", 18, 19, poi=_poi("d", cats=["景点"])),
        ]
    )
    chk = next(
        c for c in validate_day(day, _intent()).checks if c.name == "type_diversity"
    )
    assert not chk.passed
    # _infer_role_from_categories(['景点']) returns 'city_essential'
    assert "city_essential" in chk.detail


def test_no_lunch_skipped_passes_when_meal_in_window():
    from agents.route_validator import validate_day

    day = _day(
        [
            _stop("上午景点", 9, 12, poi=_poi("a", cats=["景点"])),
            _stop("午饭", 12, 13, poi=_poi("b", cats=["美食"])),
            _stop("晚饭", 18, 19, poi=_poi("d", cats=["美食"])),
        ]
    )
    assert next(
        c for c in validate_day(day, _intent()).checks if c.name == "no_lunch_skipped"
    ).passed


def test_no_lunch_skipped_fails_when_attraction_occupies_lunch_slot():
    from agents.route_validator import validate_day

    # 12:00-13:30 全段被景点占据, 且无餐饮在此窗口 → 跳餐
    day = _day(
        [
            _stop("上午景点", 9, 11, poi=_poi("a", cats=["景点"])),
            _stop("午饭", 12, 14, poi=_poi("museum", cats=["景点"])),
            _stop("晚饭", 18, 19, poi=_poi("d", cats=["美食"])),
        ]
    )
    chk = next(
        c for c in validate_day(day, _intent()).checks if c.name == "no_lunch_skipped"
    )
    assert not chk.passed
