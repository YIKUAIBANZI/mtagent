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
