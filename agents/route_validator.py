"""Route quality validator.

队友 2026-05-11 调研 "行程规划规律与人群模板" → 7 条可执行硬规则。
纯只读, 不改 planner 任何逻辑. 输入 DayPlan + ParsedIntent, 输出 ValidationReport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time as _t

from agents.anchor import _haversine_km
from agents.candidate_pool import _infer_role_from_categories
from agents.tools import default_pace_for_traveler
from dianping.schemas import DayPlan, PaceLevel, ParsedIntent, Stop


# 队友调研: 一天 stops 数 = 节奏档位
GOAL_STOPS_BY_PACE: dict[PaceLevel, int] = {
    "佛系": 3,
    "适中": 4,
    "暴走": 5,
}

_LUNCH_WINDOW = (_t(11, 30), _t(13, 30))
_DINNER_WINDOW = (_t(18, 0), _t(20, 0))

_CLUSTER_KM_DEFAULT = 5.0
_CLUSTER_KM_CROSS_DISTRICT = 10.0
_TRANSIT_MAX_MIN = 30


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class ValidationReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def score(self) -> float:
        return self.passed_count / self.total if self.total else 0.0

    @property
    def failed(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]


def _goal_stops(intent: ParsedIntent) -> int:
    pace: PaceLevel = intent.pace or default_pace_for_traveler(intent.traveler_type)
    return GOAL_STOPS_BY_PACE.get(pace, 4)


def _check_stop_count(day: DayPlan, intent: ParsedIntent) -> CheckResult:
    goal = _goal_stops(intent)
    n = len(day.stops)
    passed = goal <= n <= goal + 1
    detail = (
        ""
        if passed
        else f"got {n} stops, expect [{goal}, {goal + 1}] for pace={intent.pace or default_pace_for_traveler(intent.traveler_type)}"
    )
    return CheckResult(name="stop_count_ok", passed=passed, detail=detail)


def _is_meal_stop(stop: Stop) -> bool:
    return _infer_role_from_categories(stop.poi.categories) == "meal"


def _arrival_in(stop: Stop, lo: _t, hi: _t) -> bool:
    return lo <= stop.arrival_time <= hi


def _check_has_meal(day: DayPlan, window: tuple[_t, _t], name: str) -> CheckResult:
    lo, hi = window
    hit = any(_is_meal_stop(s) and _arrival_in(s, lo, hi) for s in day.stops)
    detail = "" if hit else f"no meal stop arrives in [{lo}, {hi}]"
    return CheckResult(name=name, passed=hit, detail=detail)


def _cluster_radius_km(intent: ParsedIntent) -> float:
    """避免跨区约束 = False 时放宽到 10km, 默认 5km."""
    constraints = intent.constraints or {}
    # avoid_cross_district = True means user wants to stay in one district → keep 5km
    # avoid_cross_district = False (explicitly) means user is OK with multi-district → 10km
    if constraints.get("avoid_cross_district") is False:
        return _CLUSTER_KM_CROSS_DISTRICT
    return _CLUSTER_KM_DEFAULT


def _check_cluster(day: DayPlan, intent: ParsedIntent) -> CheckResult:
    pts = [(s.poi.longitude, s.poi.latitude) for s in day.stops]
    if len(pts) < 2:
        return CheckResult(name="cluster_ok", passed=True)
    max_d = max(
        _haversine_km(pts[i], pts[j])
        for i in range(len(pts))
        for j in range(i + 1, len(pts))
    )
    limit = _cluster_radius_km(intent)
    passed = max_d <= limit
    detail = "" if passed else f"max pairwise {max_d:.2f} km > {limit} km"
    return CheckResult(name="cluster_ok", passed=passed, detail=detail)


def _check_transit(day: DayPlan, intent: ParsedIntent) -> CheckResult:
    over = [
        (i, s.transport_to_next_minutes)
        for i, s in enumerate(day.stops[:-1])
        if s.transport_to_next_minutes > _TRANSIT_MAX_MIN
    ]
    passed = not over
    detail = (
        ""
        if passed
        else "legs over 30min: " + ", ".join(f"#{i}={m}min" for i, m in over)
    )
    return CheckResult(name="transit_ok", passed=passed, detail=detail)


def validate_day(day: DayPlan, intent: ParsedIntent) -> ValidationReport:
    """运行规则集. Task 4: stop_count + meal windows + cluster + transit."""
    return ValidationReport(
        checks=[
            _check_stop_count(day, intent),
            _check_has_meal(day, _LUNCH_WINDOW, "has_lunch"),
            _check_has_meal(day, _DINNER_WINDOW, "has_dinner"),
            _check_cluster(day, intent),
            _check_transit(day, intent),
        ]
    )
