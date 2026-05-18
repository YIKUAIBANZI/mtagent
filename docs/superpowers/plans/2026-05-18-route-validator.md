# Route Validator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the teammate's "什么是好行程" research doc into a 100-line `route_validator` that scores any generated plan against 7 hard rules (节奏/餐时段/聚簇/类型多样性/通勤)，从此 planner 调试有客观尺子，hackathon demo 也有可讲的卖点。

**Architecture:** 纯函数模块 + dataclass 报告。输入 `DayPlan + ParsedIntent`，输出 `ValidationReport(checks: list[CheckResult], score: float)`。复用 `_haversine_km` (agents/anchor.py:152) 和 `_infer_role_from_categories` (agents/candidate_pool.py:143)。不改任何 planner 逻辑，只读。配 baseline 测试（5 城 × 3 variant 一次性扫描）+ CLI 工具（看任意 trip JSON 报告）。

**Tech Stack:** Python 3.11, Pydantic v2 (已有 schemas), pytest, dataclass (frozen)。无新依赖。

---

## File Structure

| File | Responsibility |
|---|---|
| **Create** `agents/route_validator.py` | 验证器模块。定义 `GOAL_STOPS_BY_PACE`、`CheckResult`、`ValidationReport`、`validate_day`、`validate_route`。7 条规则函数全部模块内私有 `_check_*`。 |
| **Create** `tests/test_route_validator.py` | 单元测试。每条规则独立构造 fixture（合成 DayPlan），断言通过/失败两路径。不依赖 mock data。 |
| **Create** `tests/test_route_quality_baseline.py` | 集成基线测试。跑 `plan_three_variants(stub LLM, 5 cities)`，把每个 variant 的报告打成表，写入 `tests/snapshots/route_quality_baseline.json`。初始阈值低（≥3/7 PASS 即通过），后续修一条 rule 升一级阈值。 |
| **Create** `scripts/validate_trip.py` | CLI：`python scripts/validate_trip.py data/trips/trip_xxx.json` → 打印 5 行表（variant × 7 rules × PASS/FAIL）。本地调试用。 |
| **Create** `tests/snapshots/.gitkeep` | 保证 snapshot 目录纳管 git。 |

不改动任何已有文件。validator 是纯读端。

---

## Task 1: 模块骨架 + GOAL_STOPS + 数据类型

**Files:**
- Create: `agents/route_validator.py`
- Create: `tests/test_route_validator.py`

- [ ] **Step 1: 写 ValidationReport 骨架的第一个测试**

```python
# tests/test_route_validator.py
"""Route validator unit tests. 不依赖 mock data, 全部合成 DayPlan."""
from __future__ import annotations

from datetime import time

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


import pytest  # placed at bottom so test_goal_stops_by_pace... reads top-down
```

- [ ] **Step 2: 跑测试确认 FAIL**

Run: `cd /Users/yikuaibanz1/Desktop/sth/mtagent && PYTHONPATH=. venv/bin/pytest tests/test_route_validator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.route_validator'`

- [ ] **Step 3: 实现 route_validator 模块骨架**

```python
# agents/route_validator.py
"""Route quality validator.

队友 2026-05-11 调研 "行程规划规律与人群模板" → 7 条可执行硬规则。
纯只读, 不改 planner 任何逻辑. 输入 DayPlan + ParsedIntent, 输出 ValidationReport.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

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
```

- [ ] **Step 4: 跑测试确认 PASS**

Run: `cd /Users/yikuaibanz1/Desktop/sth/mtagent && PYTHONPATH=. venv/bin/pytest tests/test_route_validator.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 提交**

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
git add agents/route_validator.py tests/test_route_validator.py
git commit -m "feat(validator): scaffold route_validator with GOAL_STOPS + ValidationReport"
```

---

## Task 2: stop_count_ok 规则

> 队友规律 1: "一天 3-5 个景点是舒适区，5 个是黄金上限。超过 5 会觉得赶，2 个以下觉得不值"。
> 实现: `goal <= len(stops) <= goal + 1`。其中 `goal = GOAL_STOPS_BY_PACE[intent.pace 或 default_pace_for_traveler(traveler_type)]`。

**Files:**
- Modify: `agents/route_validator.py`
- Modify: `tests/test_route_validator.py`

- [ ] **Step 1: 写 stop_count 测试 (PASS/FAIL 两路径)**

追加到 `tests/test_route_validator.py` 末尾：

```python
from datetime import time as _t

from dianping.schemas import DayPlan, ParsedIntent, POI, Stop, TimeSlot


def _poi(name: str = "x", lat: float = 30.0, lng: float = 120.0,
         cats: list[str] | None = None) -> POI:
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
        city="测试市", days=1, traveler_type=traveler_type, pace=pace, **over,
    )


def test_stop_count_ok_passes_for_4_stops_balanced_traveler():
    from agents.route_validator import validate_day

    day = _day([
        _stop("上午景点", 9, 12),
        _stop("午饭", 12, 13),
        _stop("下午", 13, 17),
        _stop("晚饭", 18, 19),
    ])
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

    # 暴走 = 5 stops 起步, 4 个就 FAIL
    day = _day([_stop("上午景点", 9, 12)] * 4)
    report = validate_day(day, _intent(traveler_type="情侣", pace="暴走"))
    chk = next(c for c in report.checks if c.name == "stop_count_ok")
    assert not chk.passed
```

- [ ] **Step 2: 跑测试确认 FAIL**

Run: `cd /Users/yikuaibanz1/Desktop/sth/mtagent && PYTHONPATH=. venv/bin/pytest tests/test_route_validator.py -v`
Expected: FAIL with `ImportError: cannot import name 'validate_day'`

- [ ] **Step 3: 实现 validate_day + stop_count_ok 规则**

追加到 `agents/route_validator.py`：

```python
from dianping.schemas import DayPlan, ParsedIntent
from agents.tools import default_pace_for_traveler


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
```

- [ ] **Step 4: 跑测试确认 PASS**

Run: `cd /Users/yikuaibanz1/Desktop/sth/mtagent && PYTHONPATH=. venv/bin/pytest tests/test_route_validator.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 提交**

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
git add agents/route_validator.py tests/test_route_validator.py
git commit -m "feat(validator): add stop_count_ok rule (goal stops by pace)"
```

---

## Task 3: has_lunch + has_dinner 规则

> 队友规律 5: "午饭 12:00-13:30，晚饭 18:00-20:00 锚死不动，这是生理刚需"。
> 实现: 在窗口内必须存在一个 stop, 其 POI categories 命中"美食/餐饮服务/小吃/中餐厅/..."等餐饮关键词. 直接复用 `agents/candidate_pool._infer_role_from_categories` 判断 role=="美食"。

**Files:**
- Modify: `agents/route_validator.py`
- Modify: `tests/test_route_validator.py`

- [ ] **Step 1: 写 has_lunch / has_dinner 测试 (各 2 路径)**

追加到 `tests/test_route_validator.py`：

```python
_MEAL_CATS = ["美食"]  # _infer_role_from_categories 会把它判为 meal
_ATTRACTION_CATS = ["景点"]


def test_has_lunch_passes_when_meal_stop_at_noon():
    from agents.route_validator import validate_day

    day = _day([
        _stop("上午景点", 9, 12, poi=_poi("morning", cats=_ATTRACTION_CATS)),
        _stop("午饭", 12, 13, poi=_poi("lunch", cats=_MEAL_CATS)),
        _stop("下午", 13, 17, poi=_poi("aft", cats=_ATTRACTION_CATS)),
        _stop("晚饭", 18, 19, poi=_poi("dinner", cats=_MEAL_CATS)),
    ])
    report = validate_day(day, _intent())
    assert next(c for c in report.checks if c.name == "has_lunch").passed
    assert next(c for c in report.checks if c.name == "has_dinner").passed


def test_has_lunch_fails_when_only_attractions_at_noon():
    from agents.route_validator import validate_day

    day = _day([
        _stop("上午景点", 9, 12, poi=_poi("a", cats=_ATTRACTION_CATS)),
        _stop("午饭", 12, 13, poi=_poi("not_meal", cats=_ATTRACTION_CATS)),
        _stop("下午", 13, 17, poi=_poi("b", cats=_ATTRACTION_CATS)),
        _stop("晚饭", 18, 19, poi=_poi("dinner", cats=_MEAL_CATS)),
    ])
    report = validate_day(day, _intent())
    assert not next(c for c in report.checks if c.name == "has_lunch").passed


def test_has_dinner_fails_when_no_evening_meal():
    from agents.route_validator import validate_day

    day = _day([
        _stop("上午景点", 9, 12, poi=_poi("a", cats=_ATTRACTION_CATS)),
        _stop("午饭", 12, 13, poi=_poi("lunch", cats=_MEAL_CATS)),
    ])
    report = validate_day(day, _intent())
    assert not next(c for c in report.checks if c.name == "has_dinner").passed
```

- [ ] **Step 2: 跑测试确认 FAIL**

Run: `cd /Users/yikuaibanz1/Desktop/sth/mtagent && PYTHONPATH=. venv/bin/pytest tests/test_route_validator.py -v`
Expected: FAIL with `StopIteration` on `next(... has_lunch ...)`

- [ ] **Step 3: 实现 meal 窗口规则**

修改 `agents/route_validator.py`：

```python
# top imports 追加
from datetime import time as _t

from agents.candidate_pool import _infer_role_from_categories
from dianping.schemas import Stop


_LUNCH_WINDOW = (_t(11, 30), _t(13, 30))
_DINNER_WINDOW = (_t(18, 0), _t(20, 0))


def _is_meal_stop(stop: Stop) -> bool:
    return _infer_role_from_categories(stop.poi.categories) == "美食"


def _arrival_in(stop: Stop, lo: _t, hi: _t) -> bool:
    return lo <= stop.arrival_time <= hi


def _check_has_meal(day: DayPlan, window: tuple[_t, _t], name: str) -> CheckResult:
    lo, hi = window
    hit = any(_is_meal_stop(s) and _arrival_in(s, lo, hi) for s in day.stops)
    detail = "" if hit else f"no meal stop arrives in [{lo}, {hi}]"
    return CheckResult(name=name, passed=hit, detail=detail)


# 修改 validate_day:
def validate_day(day: DayPlan, intent: ParsedIntent) -> ValidationReport:
    return ValidationReport(checks=[
        _check_stop_count(day, intent),
        _check_has_meal(day, _LUNCH_WINDOW, "has_lunch"),
        _check_has_meal(day, _DINNER_WINDOW, "has_dinner"),
    ])
```

- [ ] **Step 4: 跑测试确认 PASS**

Run: `cd /Users/yikuaibanz1/Desktop/sth/mtagent && PYTHONPATH=. venv/bin/pytest tests/test_route_validator.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: 提交**

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
git add agents/route_validator.py tests/test_route_validator.py
git commit -m "feat(validator): add has_lunch + has_dinner meal-window rules"
```

---

## Task 4: cluster_ok + transit_ok 空间规则

> 队友规律 2 + 总结表"赶/乱"判定:
> - 同天所有 POI 必须在 5km 聚簇半径内 (例外: 用户明确"多区打卡" → 10km)。
> - 两 POI 间通勤 ≤ 30 分钟。
> 用现有 `_haversine_km` (agents/anchor.py:152, 输入 (lng, lat)) 算最大对距; transit_to_next_minutes 已存在 Stop 字段。

**Files:**
- Modify: `agents/route_validator.py`
- Modify: `tests/test_route_validator.py`

- [ ] **Step 1: 写 cluster + transit 测试 (PASS/FAIL)**

追加到 `tests/test_route_validator.py`：

```python
def test_cluster_ok_passes_within_5km():
    from agents.route_validator import validate_day

    # 4 个 POI 都在深圳市中心 ~1km 内
    day = _day([
        _stop("上午景点", 9, 12, poi=_poi("a", lat=22.5400, lng=114.0500, cats=_ATTRACTION_CATS)),
        _stop("午饭", 12, 13, poi=_poi("b", lat=22.5405, lng=114.0510, cats=_MEAL_CATS)),
        _stop("下午", 13, 17, poi=_poi("c", lat=22.5450, lng=114.0480, cats=_ATTRACTION_CATS)),
        _stop("晚饭", 18, 19, poi=_poi("d", lat=22.5420, lng=114.0530, cats=_MEAL_CATS)),
    ])
    report = validate_day(day, _intent())
    assert next(c for c in report.checks if c.name == "cluster_ok").passed


def test_cluster_ok_fails_when_max_pairwise_exceeds_5km():
    from agents.route_validator import validate_day

    # b 跑到 10km 外
    day = _day([
        _stop("上午景点", 9, 12, poi=_poi("a", lat=22.5400, lng=114.0500, cats=_ATTRACTION_CATS)),
        _stop("午饭", 12, 13, poi=_poi("b", lat=22.6400, lng=114.0500, cats=_MEAL_CATS)),
        _stop("下午", 13, 17, poi=_poi("c", lat=22.5450, lng=114.0480, cats=_ATTRACTION_CATS)),
        _stop("晚饭", 18, 19, poi=_poi("d", lat=22.5420, lng=114.0530, cats=_MEAL_CATS)),
    ])
    report = validate_day(day, _intent())
    chk = next(c for c in report.checks if c.name == "cluster_ok")
    assert not chk.passed
    assert "km" in chk.detail


def test_transit_ok_passes_when_all_legs_under_30min():
    from agents.route_validator import validate_day

    day = _day([
        _stop("上午景点", 9, 12, poi=_poi("a", cats=_ATTRACTION_CATS)),
        _stop("午饭", 12, 13, poi=_poi("b", cats=_MEAL_CATS)),
    ])
    # 默认 _stop transport=20min, 应通过
    assert next(c for c in validate_day(day, _intent()).checks if c.name == "transit_ok").passed


def test_transit_ok_fails_when_a_leg_exceeds_30min():
    from agents.route_validator import validate_day

    s1 = _stop("上午景点", 9, 12, poi=_poi("a", cats=_ATTRACTION_CATS))
    s1 = s1.model_copy(update={"transport_to_next_minutes": 45})
    day = _day([s1, _stop("午饭", 12, 13, poi=_poi("b", cats=_MEAL_CATS))])
    chk = next(c for c in validate_day(day, _intent()).checks if c.name == "transit_ok")
    assert not chk.passed
    assert "45" in chk.detail
```

- [ ] **Step 2: 跑测试确认 FAIL**

Run: `cd /Users/yikuaibanz1/Desktop/sth/mtagent && PYTHONPATH=. venv/bin/pytest tests/test_route_validator.py -v`
Expected: FAIL with `StopIteration` on cluster_ok / transit_ok lookups

- [ ] **Step 3: 实现 cluster + transit 规则**

追加到 `agents/route_validator.py`：

```python
# top imports 追加
from agents.anchor import _haversine_km


_CLUSTER_KM_DEFAULT = 5.0
_CLUSTER_KM_CROSS_DISTRICT = 10.0
_TRANSIT_MAX_MIN = 30


def _cluster_radius_km(intent: ParsedIntent) -> float:
    cross = (intent.constraints or {}).get("avoid_cross_district") is False
    return _CLUSTER_KM_CROSS_DISTRICT if cross else _CLUSTER_KM_DEFAULT


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


# 更新 validate_day:
def validate_day(day: DayPlan, intent: ParsedIntent) -> ValidationReport:
    return ValidationReport(checks=[
        _check_stop_count(day, intent),
        _check_has_meal(day, _LUNCH_WINDOW, "has_lunch"),
        _check_has_meal(day, _DINNER_WINDOW, "has_dinner"),
        _check_cluster(day, intent),
        _check_transit(day, intent),
    ])
```

- [ ] **Step 4: 跑测试确认 PASS**

Run: `cd /Users/yikuaibanz1/Desktop/sth/mtagent && PYTHONPATH=. venv/bin/pytest tests/test_route_validator.py -v`
Expected: PASS (12 passed)

- [ ] **Step 5: 提交**

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
git add agents/route_validator.py tests/test_route_validator.py
git commit -m "feat(validator): add cluster_ok + transit_ok spatial rules"
```

---

## Task 5: type_diversity + no_lunch_skipped 角色规则

> 队友规律 4 + 7: "同天必须有类型多样性"、"同类型 POI 不要在同一天出现 2 次以上"、"中午时段不安排景点 (11:30-14:30 人流最大)"。
> 实现:
> - type_diversity: `Counter(role)` 最大计数 ≤ 2 (景点/美食/购物/休闲等的桶)
> - no_lunch_skipped: 没有一个非餐饮 stop 占据整个 12:00-13:30

**Files:**
- Modify: `agents/route_validator.py`
- Modify: `tests/test_route_validator.py`

- [ ] **Step 1: 写 type_diversity + no_lunch_skipped 测试**

追加到 `tests/test_route_validator.py`：

```python
def test_type_diversity_passes_with_mixed_roles():
    from agents.route_validator import validate_day

    day = _day([
        _stop("上午景点", 9, 12, poi=_poi("a", cats=["景点"])),
        _stop("午饭", 12, 13, poi=_poi("b", cats=["美食"])),
        _stop("下午", 13, 17, poi=_poi("c", cats=["购物"])),
        _stop("晚饭", 18, 19, poi=_poi("d", cats=["美食"])),
    ])
    assert next(c for c in validate_day(day, _intent()).checks if c.name == "type_diversity").passed


def test_type_diversity_fails_when_3_same_role():
    """3 个景点 -> 队友规律: 立即疲劳."""
    from agents.route_validator import validate_day

    day = _day([
        _stop("上午景点", 9, 12, poi=_poi("a", cats=["景点"])),
        _stop("午饭", 12, 13, poi=_poi("b", cats=["美食"])),
        _stop("下午", 13, 17, poi=_poi("c", cats=["景点"])),
        _stop("晚饭", 18, 19, poi=_poi("d", cats=["景点"])),
    ])
    chk = next(c for c in validate_day(day, _intent()).checks if c.name == "type_diversity")
    assert not chk.passed
    assert "景点" in chk.detail


def test_no_lunch_skipped_passes_when_meal_in_window():
    from agents.route_validator import validate_day

    day = _day([
        _stop("上午景点", 9, 12, poi=_poi("a", cats=["景点"])),
        _stop("午饭", 12, 13, poi=_poi("b", cats=["美食"])),
        _stop("晚饭", 18, 19, poi=_poi("d", cats=["美食"])),
    ])
    assert next(c for c in validate_day(day, _intent()).checks if c.name == "no_lunch_skipped").passed


def test_no_lunch_skipped_fails_when_attraction_occupies_lunch_slot():
    from agents.route_validator import validate_day

    # 12:00-13:30 全段被景点占据, 且无餐饮在此窗口 → 跳餐
    day = _day([
        _stop("上午景点", 9, 11, poi=_poi("a", cats=["景点"])),
        _stop("午饭", 12, 14, poi=_poi("museum", cats=["景点"])),
        _stop("晚饭", 18, 19, poi=_poi("d", cats=["美食"])),
    ])
    chk = next(c for c in validate_day(day, _intent()).checks if c.name == "no_lunch_skipped")
    assert not chk.passed
```

- [ ] **Step 2: 跑测试确认 FAIL**

Run: `cd /Users/yikuaibanz1/Desktop/sth/mtagent && PYTHONPATH=. venv/bin/pytest tests/test_route_validator.py -v`
Expected: FAIL with `StopIteration` on type_diversity / no_lunch_skipped

- [ ] **Step 3: 实现两条规则**

追加到 `agents/route_validator.py`：

```python
# top imports 追加
from collections import Counter


_MAX_SAME_ROLE = 2


def _role_of(stop: Stop) -> str:
    return _infer_role_from_categories(stop.poi.categories)


def _check_type_diversity(day: DayPlan, intent: ParsedIntent) -> CheckResult:
    counts = Counter(_role_of(s) for s in day.stops)
    over = [(r, n) for r, n in counts.items() if n > _MAX_SAME_ROLE]
    passed = not over
    detail = (
        ""
        if passed
        else "role over cap: " + ", ".join(f"{r}={n}" for r, n in over)
    )
    return CheckResult(name="type_diversity", passed=passed, detail=detail)


def _check_no_lunch_skipped(day: DayPlan, intent: ParsedIntent) -> CheckResult:
    """如果 12:00-13:30 窗口被一个非餐饮 stop 完全覆盖 (arrive≤12 且 leave≥13:30)
    且窗口内没有任何餐饮 stop, 视为跳餐."""
    lo, hi = _LUNCH_WINDOW
    has_meal = any(_is_meal_stop(s) and _arrival_in(s, lo, hi) for s in day.stops)
    if has_meal:
        return CheckResult(name="no_lunch_skipped", passed=True)
    blockers = [
        s for s in day.stops
        if not _is_meal_stop(s) and s.arrival_time <= lo and s.leave_time >= hi
    ]
    passed = not blockers
    detail = (
        ""
        if passed
        else f"non-meal stop '{blockers[0].poi.name}' occupies lunch window"
    )
    return CheckResult(name="no_lunch_skipped", passed=passed, detail=detail)


# 更新 validate_day:
def validate_day(day: DayPlan, intent: ParsedIntent) -> ValidationReport:
    return ValidationReport(checks=[
        _check_stop_count(day, intent),
        _check_has_meal(day, _LUNCH_WINDOW, "has_lunch"),
        _check_has_meal(day, _DINNER_WINDOW, "has_dinner"),
        _check_cluster(day, intent),
        _check_transit(day, intent),
        _check_type_diversity(day, intent),
        _check_no_lunch_skipped(day, intent),
    ])
```

- [ ] **Step 4: 跑测试确认 PASS**

Run: `cd /Users/yikuaibanz1/Desktop/sth/mtagent && PYTHONPATH=. venv/bin/pytest tests/test_route_validator.py -v`
Expected: PASS (16 passed)

- [ ] **Step 5: 提交**

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
git add agents/route_validator.py tests/test_route_validator.py
git commit -m "feat(validator): add type_diversity + no_lunch_skipped role rules"
```

---

## Task 6: validate_route 多天包装

> RouteDraft.days 是多天列表, 每天一个 DayPlan. 给一个 `validate_route` 函数返回 `list[ValidationReport]` (每天一个), 便于 CLI/baseline 使用。

**Files:**
- Modify: `agents/route_validator.py`
- Modify: `tests/test_route_validator.py`

- [ ] **Step 1: 写 validate_route 测试**

追加到 `tests/test_route_validator.py`：

```python
from dianping.schemas import RouteDraft


def test_validate_route_returns_one_report_per_day():
    from agents.route_validator import validate_route

    good_day = _day([
        _stop("上午景点", 9, 12, poi=_poi("a", cats=["景点"])),
        _stop("午饭", 12, 13, poi=_poi("b", cats=["美食"])),
        _stop("下午", 13, 17, poi=_poi("c", cats=["购物"])),
        _stop("晚饭", 18, 19, poi=_poi("d", cats=["美食"])),
    ])
    bad_day = _day([_stop("上午景点", 9, 12, poi=_poi("a", cats=["景点"]))])

    route = RouteDraft(days=[good_day, bad_day])
    reports = validate_route(route, _intent(days=2))
    assert len(reports) == 2
    assert reports[0].score > reports[1].score
    assert reports[0].score == 1.0  # all 7 pass for good_day
```

- [ ] **Step 2: 跑测试确认 FAIL**

Run: `cd /Users/yikuaibanz1/Desktop/sth/mtagent && PYTHONPATH=. venv/bin/pytest tests/test_route_validator.py -v`
Expected: FAIL with `ImportError: cannot import name 'validate_route'`

- [ ] **Step 3: 实现 validate_route**

追加到 `agents/route_validator.py`：

```python
from dianping.schemas import RouteDraft


def validate_route(route: RouteDraft, intent: ParsedIntent) -> list[ValidationReport]:
    """逐天验证. 返回与 route.days 同序的报告列表."""
    return [validate_day(day, intent) for day in route.days]
```

- [ ] **Step 4: 跑测试确认 PASS**

Run: `cd /Users/yikuaibanz1/Desktop/sth/mtagent && PYTHONPATH=. venv/bin/pytest tests/test_route_validator.py -v`
Expected: PASS (17 passed)

- [ ] **Step 5: 提交**

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
git add agents/route_validator.py tests/test_route_validator.py
git commit -m "feat(validator): add validate_route multi-day wrapper"
```

---

## Task 7: 5 城市 × 3 variant 基线快照测试

> 跑 `plan_three_variants(stub LLM, real mock data)` 对每个城市 5 次 (5 城) × 3 (variant) = 15 个 plan。
> 把每个 plan 的 ValidationReport 序列化到 `tests/snapshots/route_quality_baseline.json`。
> 测试断言: 所有 variant 至少通过 3/7 规则 (初始低门槛, 让 bug 先暴露在快照里)。

**Files:**
- Create: `tests/test_route_quality_baseline.py`
- Create: `tests/snapshots/.gitkeep`

- [ ] **Step 1: 创建 snapshots 目录**

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
mkdir -p tests/snapshots
touch tests/snapshots/.gitkeep
```

- [ ] **Step 2: 写基线测试**

```python
# tests/test_route_quality_baseline.py
"""5 城市 × 3 variant 路线质量基线.

每次 CI 跑一遍, 把 7 条规则的通过情况打入 tests/snapshots/route_quality_baseline.json.
当前阈值很低 (>=3/7), 是为了让 bug 在快照里被看到, 而不是被测试隐藏.
修一条 rule 就把阈值升一格.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from agents.planner import Planner
from agents.planner_instant import load_city_pois_from_mock, plan_three_variants
from agents.route_validator import validate_day
from api.stub_llm import stub_planner_llm_stream
from dianping.client import DianpingClient
from dianping.schemas import ParsedIntent

# 5 城 × 一组合理的 intent
_CITIES = ["深圳", "上海", "西安", "南昌", "北京"]
_MIN_SCORE = 3 / 7  # 初始阈值: 每个 variant 至少通过 3/7 规则
_SNAPSHOT = Path("tests/snapshots/route_quality_baseline.json")


class _StubAmap:
    def __init__(self):
        self._client = self

    async def get_transit_options(self, *, origin, dest, city, traveler_type):
        from dianping.schemas import TransitInfo

        opts = {
            m: TransitInfo(mode=m, minutes=15, distance_km=2.0, source="estimated")
            for m in ("drive", "walk", "transit", "bicycle")
        }
        return opts, "walk"

    async def aclose(self):
        pass


def _intent_for(city: str) -> ParsedIntent:
    return ParsedIntent(
        city=city,
        days=1,
        traveler_type="情侣",
        time_window="一日",
        interests=["拍照"],
        estimated_hours=10,
    )


@pytest.mark.skipif(
    not all(os.path.exists(f"data/mock_dianping/{c}.json") for c in _CITIES),
    reason="5 city mock data not present",
)
def test_route_quality_baseline_all_cities():
    snapshot: dict[str, dict] = {}
    failures: list[str] = []

    for city in _CITIES:
        pois = load_city_pois_from_mock(city)
        intent = _intent_for(city)
        client = DianpingClient()
        planner = Planner(client=client, llm_call_stream=stub_planner_llm_stream)
        amap = _StubAmap()
        variants = asyncio.run(
            plan_three_variants(intent=intent, planner=planner, amap=amap, pois=pois)
        )

        snapshot[city] = {}
        for vname, vp in variants.items():
            report = validate_day(vp.day_plan, intent)
            snapshot[city][vname] = {
                "stops": len(vp.day_plan.stops),
                "score": report.score,
                "passed": report.passed_count,
                "total": report.total,
                "failed_rules": [c.name for c in report.failed],
                "details": {c.name: c.detail for c in report.failed},
            }
            if report.score < _MIN_SCORE:
                failures.append(
                    f"{city}/{vname}: score={report.score:.2f} < {_MIN_SCORE:.2f}, "
                    f"failed={[c.name for c in report.failed]}"
                )

    _SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    _SNAPSHOT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))

    assert not failures, "Route quality baseline regressions:\n" + "\n".join(failures)
```

- [ ] **Step 3: 跑测试 (预期可能 FAIL, 因为当前 planner 就有 bug)**

Run: `cd /Users/yikuaibanz1/Desktop/sth/mtagent && PYTHONPATH=. venv/bin/pytest tests/test_route_quality_baseline.py -v -s`
Expected: 测试可能 FAIL (baseline 阈值 3/7), 但会写出 `tests/snapshots/route_quality_baseline.json`。**这正是我们要的诊断输出**, 它显示每个城市/variant 具体差在哪条规则。

如果测试 FAIL: 看 snapshot JSON, 这就是后续修 planner 的 todo 列表。如果 FAIL 但 snapshot 内容显示阈值定得太严, 临时把 `_MIN_SCORE` 调到 `2/7` 让它过 (但要在 commit message 里写明 "FIXME: tighten after planner fixes")。

- [ ] **Step 4: 提交 (无论 PASS/FAIL, snapshot 都要进库)**

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
git add tests/test_route_quality_baseline.py tests/snapshots/
git commit -m "test(validator): add 5-city baseline + snapshot route_quality_baseline.json"
```

---

## Task 8: CLI - 看任意 trip JSON 的报告

> 调试用. 跑完 hackathon demo / 用户报 bug 时, `python scripts/validate_trip.py data/trips/trip_xxx.json` 就能打印一张表, 不用进 python REPL。

**Files:**
- Create: `scripts/validate_trip.py`

- [ ] **Step 1: 写 CLI 脚本**

```python
# scripts/validate_trip.py
"""Usage: python scripts/validate_trip.py data/trips/trip_xxx.json

打印每个 variant × day 的 7 规则通过表. 调试用.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from agents.route_validator import validate_day
from agents.context import TripContext
from dianping.schemas import RouteDraft


def main(path: str) -> int:
    ctx_path = Path(path)
    if not ctx_path.exists():
        print(f"FILE NOT FOUND: {path}", file=sys.stderr)
        return 2

    data = json.loads(ctx_path.read_text(encoding="utf-8"))
    ctx = TripContext.model_validate(data)
    if not ctx.intent:
        print("trip has no intent, can't validate", file=sys.stderr)
        return 2

    variants: dict[str, RouteDraft] = ctx.variants or {}
    if not variants and ctx.draft_route:
        variants = {"main": ctx.draft_route}
    if not variants:
        print("trip has no variants nor draft_route", file=sys.stderr)
        return 2

    print(f"\nTrip: {ctx.trip_id}  city={ctx.intent.city}  traveler={ctx.intent.traveler_type}  pace={ctx.intent.pace}")
    print("=" * 100)

    for vname, route in variants.items():
        for day in route.days:
            report = validate_day(day, ctx.intent)
            mark = "PASS" if report.score == 1.0 else "FAIL"
            print(
                f"\n[{mark}] variant={vname}  day={day.day_index}  "
                f"stops={len(day.stops)}  score={report.passed_count}/{report.total}"
            )
            for c in report.checks:
                glyph = "OK " if c.passed else "X  "
                print(f"  {glyph} {c.name:20s} {c.detail}")

    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python scripts/validate_trip.py <trip.json>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
```

- [ ] **Step 2: 手动跑一次最新 trip 验证 CLI 输出**

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
LATEST=$(ls -t data/trips/*.json | head -1)
PYTHONPATH=. venv/bin/python scripts/validate_trip.py "$LATEST"
```

Expected: 终端打印彩表, 例如:
```
Trip: trip_xxx  city=南昌  traveler=情侣  pace=None
====================================================================================================

[FAIL] variant=main  day=0  stops=3  score=4/7
  X   stop_count_ok       got 3 stops, expect [4, 5] for pace=适中
  OK  has_lunch
  X   has_dinner          no meal stop arrives in [18:00, 20:00]
  OK  cluster_ok
  OK  transit_ok
  OK  type_diversity
  X   no_lunch_skipped    non-meal stop 'xxx' occupies lunch window
```
(具体 PASS/FAIL 取决于真实 trip; 重要的是脚本不崩, 7 行规则全部打出来)

- [ ] **Step 3: 跑全量测试套件确认无回归**

Run: `cd /Users/yikuaibanz1/Desktop/sth/mtagent && PYTHONPATH=. venv/bin/pytest tests/ -q --ignore=tests/test_user_profile_cleaning.py --ignore=tests/test_amap_client.py --ignore=tests/test_e2e_stub.py`
Expected: PASS — 之前 baseline 356 passed, 现在应是 356 + 17 (validator unit) + 1 (baseline) = 374 passed (baseline 那一个若 FAIL 是诊断结果, 不算回归)。

- [ ] **Step 4: 提交**

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
git add scripts/validate_trip.py
git commit -m "feat(validator): add scripts/validate_trip.py CLI for ad-hoc diagnostics"
```

- [ ] **Step 5: 回头看 snapshot, 决定下一步**

打开 `tests/snapshots/route_quality_baseline.json`, 按 `failed_rules` 频次排序:
- 出现最多的那条 = 应该最先修的 planner bug
- 例如全城 5/5 都 fail `stop_count_ok` → 去 `agents/planner_instant.py` 改 fallback 路径"必须填够 N 站，不够依次放宽"
- 例如 4/5 fail `cluster_ok` → 去 candidate_pool 加距离过滤

**这一步不是代码任务, 是产出"下一份计划"的输入。**

---

## Self-Review

**1. Spec coverage** — 队友 7 条规律 → 7 条 `_check_*` 函数, 一一对应:

| 队友规律 | Task | 规则名 |
|---|---|---|
| #1 一天 3-5 站 | Task 2 | `stop_count_ok` |
| #2 交通 ≤ 30min | Task 4 | `transit_ok` |
| #2 5km 聚簇 | Task 4 | `cluster_ok` |
| #3 弹性时间 | — | 暂不验证 (没有结构化的"弹性"字段, 后续可加 `total_minutes_ok`) |
| #4 类型多样性 | Task 5 | `type_diversity` |
| #5 午晚饭锚死 | Task 3 | `has_lunch` + `has_dinner` |
| #5 中午不安排景点 | Task 5 | `no_lunch_skipped` |
| #6 连续两天不过满 | — | 跨天规则, 单天验证不覆盖, 后续 `validate_route_pacing` 可加 |
| #7 同类型 ≤ 2 | Task 5 | `type_diversity` (合并到同一规则) |

覆盖 5/7 直接规则 + 1 条衍生 (no_lunch_skipped) = 6 条硬规则, 2 条 (#3 弹性、#6 连续天) 留作扩展。这是合理的 MVP scope —— 验证器先打地基, 后续可在不破坏 API 的情况下追加 `_check_*` 函数。

**2. Placeholder scan** — 全部步骤都给了完整代码块、确切命令、明确的 PASS/FAIL 期望。没有 "TODO" / "类似 Task N" / "适当处理边界"。Task 7 唯一的"如果 FAIL 就调阈值"是有明确动作 (改 `_MIN_SCORE = 2/7` + commit message 注明 FIXME), 不是 placeholder。

**3. Type consistency** —
- `CheckResult(name, passed, detail)` — Task 1 定义, Task 2-8 全部沿用
- `ValidationReport.score / passed_count / total / failed` — Task 1 定义, Task 6 + Task 7 使用
- `_LUNCH_WINDOW`, `_DINNER_WINDOW` — Task 3 定义, Task 5 (`no_lunch_skipped`) 复用
- `_is_meal_stop` / `_arrival_in` — Task 3 定义, Task 5 复用
- `_role_of` 使用 `_infer_role_from_categories` (agents/candidate_pool.py:143, 已验证存在)
- `_haversine_km` 来自 agents/anchor.py:152, 输入是 `(lng, lat)` 元组 (已用 `grep` 确认)
- `default_pace_for_traveler` 来自 agents/tools.py:61 (已用 `grep` 确认)
- `Stop.transport_to_next_minutes` 字段存在于 schemas.py:391 (已确认)
- `stub_planner_llm_stream` + `_StubAmap` 模式抄自 `tests/test_planner_instant_v17.py:109` (已确认)
- `_intent()` fixture helper 与 `test_planner_instant_v17.py:34` 同款, 命名一致

类型/函数名一致, 无悬空引用。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-18-route-validator.md`. Two execution options:

**1. Subagent-Driven (recommended)** — 每个 Task 起一个新 subagent 干, 我在每个 Task 之间检查, 你看着我和 subagent 来回。适合你今晚累了想"看 progress bar"的状态。

**2. Inline Execution** — 我在当前 session 直接按 Task 顺序写完所有代码, 在 Task 4 (rules 写完) 和 Task 7 (baseline 跑完) 两个 checkpoint 停下让你看。适合你想一气呵成。

哪种？或者明天部署完 VPS 再回来跑也可以——这份计划自包含, 任何时候捡起来都不用回忆上下文。
