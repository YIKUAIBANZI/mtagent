"""Route quality validator.

队友 2026-05-11 调研 "行程规划规律与人群模板" → 7 条可执行硬规则。
纯只读, 不改 planner 任何逻辑. 输入 DayPlan + ParsedIntent, 输出 ValidationReport.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dianping.schemas import PaceLevel


# 队友调研: 一天 stops 数 = 节奏档位
GOAL_STOPS_BY_PACE: dict[PaceLevel, int] = {
    "佛系": 3,
    "适中": 4,
    "暴走": 5,
}


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


from agents.tools import default_pace_for_traveler
from dianping.schemas import DayPlan, ParsedIntent


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


def validate_day(day: DayPlan, intent: ParsedIntent) -> ValidationReport:
    """运行 7 条规则. 当前 Task 2: 仅 stop_count_ok."""
    return ValidationReport(checks=[_check_stop_count(day, intent)])
