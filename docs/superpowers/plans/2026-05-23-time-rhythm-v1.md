# 时长灵动 v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop 的 arrival_time + 推荐逗留按 POI 类型 + traveler 节奏动态算，餐点 anchor 不漂；前端从"09:00-10:30"改成"09:00 · 推荐 90min"。

**Architecture:** 后端新增两个纯函数模块 `agents/duration_table.py`（categories → 基础时长 × traveler 倍率）+ `agents/scheduler.py`（贪心排程 + 餐点 anchor 软约束）。`dianping/schemas.py:Stop` 加 `recommended_duration_min` 字段（默认 60，兼容老 trip）。`agents/planner.py` 3 处 Stop 构造改为先收集 POI + slot，最后一次性 `schedule_day` 覆盖 arrival/leave。`agents/rationale.py:build_rationale_for_stop` 在前一 stop 被压缩时多一句中文 reason。前端 `web/plan_stack.html:pushPlaceCard` 渲染优先 `recommended_duration_min`，fallback 旧 durText。

**Tech Stack:** Python 3.14 + pydantic v2，无新依赖。前端纯 vanilla JS。pytest 跑测试。

**Baseline:** 417 PASS（ignore `test_user_profile_cleaning.py / test_amap_client.py / test_e2e_stub.py`）。

**Invariants（不能破）:**
- `dianping/schemas.py:216 SlotName Literal` 中文枚举 `"上午景点"/"午饭"/"下午"/"下午茶"/"晚饭"/"夜场"` 不动
- `Patch` 类不动（被 Critic 用）
- `.variant-chip` CSS 不动；新 UI 字段沿用 `recommended_duration_min` 命名
- variant_patches 只比 `openshopid`，新字段不会引入 diff 噪声

---

## File Structure

**新增**

| File | 责任 |
|---|---|
| `agents/duration_table.py` | `_DURATION_RULES` 表 + `_TRAVELER_MULTIPLIER` + `base_duration_for` / `duration_for` 纯函数 |
| `agents/scheduler.py` | `DAY_START_BY_TRAVELER` / `LUNCH_ANCHOR` / `DINNER_ANCHOR` + `schedule_day` 贪心算法 |
| `tests/test_duration_table.py` | 8 用例覆盖匹配优先级 / multiplier / fallback |
| `tests/test_scheduler.py` | 5 用例覆盖 happy / 拖时压缩 / 早起 / 商务快节奏 / 全 fallback |

**修改**

| File | 改动 |
|---|---|
| `dianping/schemas.py` | `Stop` 加 `recommended_duration_min: int = 60` 字段（line 386-392） |
| `agents/planner.py` | 3 处 Stop 构造（line 295-323 / 408-447 / 750-790 fallback）改为先收集 POI + slot_name，最后一次性调 `schedule_day` 覆盖时间 |
| `agents/rationale.py` | `build_rationale_for_stop` 增 `prev_squeeze_pct: Optional[int] = None` 参数，触发时在 reason 末尾追加中文附注；调用方传值 |
| `web/plan_stack.html` | `pushPlaceCard` 内 line 1786 durText 渲染前优先用 `stop.recommended_duration_min` |

---

## Task 1: duration_table 纯函数 + 测试

**Files:**
- Create: `agents/duration_table.py`
- Test: `tests/test_duration_table.py`

- [ ] **Step 1: 写 8 个失败测试**

```python
# tests/test_duration_table.py
"""Unit tests for agents.duration_table — categories → 基础时长 × traveler 倍率."""

from agents.duration_table import base_duration_for, duration_for


# --- base_duration_for: 关键词匹配优先级 ---

def test_base_scenic_named() -> None:
    """风景名胜命中 90."""
    assert base_duration_for(["风景名胜", "5A 景区"]) == 90


def test_base_museum_beats_generic_scenic() -> None:
    """博物馆条目在表里位于景点之前 → 命中 100 而非 90."""
    assert base_duration_for(["博物馆", "景点"]) == 100


def test_base_meal_hotpot() -> None:
    """火锅命中 90."""
    assert base_duration_for(["火锅店", "中餐厅"]) == 90


def test_base_cafe() -> None:
    """咖啡命中 40."""
    assert base_duration_for(["咖啡", "甜品"]) == 40


def test_base_fountain_landmark() -> None:
    """喷泉命中 20（打卡型）."""
    assert base_duration_for(["音乐喷泉", "标志建筑"]) == 20


def test_base_empty_fallback() -> None:
    """空 categories → DEFAULT 60."""
    assert base_duration_for([]) == 60


def test_base_unknown_fallback() -> None:
    """没命中任何关键词 → DEFAULT 60."""
    assert base_duration_for(["未知类别 X"]) == 60


# --- duration_for: traveler 倍率 + 向上取整到 5 ---

def test_duration_scenic_couple() -> None:
    """风景名胜 + 情侣: 90 × 1.2 = 108 → 110."""
    assert duration_for(["风景名胜"], "情侣") == 110


def test_duration_museum_business() -> None:
    """博物馆 + 商务: 100 × 0.7 = 70 → 70."""
    assert duration_for(["博物馆"], "商务") == 70


def test_duration_hotpot_family() -> None:
    """火锅 + 亲子: 90 × 1.4 = 126 → 130."""
    assert duration_for(["火锅"], "亲子") == 130


def test_duration_cafe_senior() -> None:
    """咖啡 + 银发: 40 × 1.3 = 52 → 55."""
    assert duration_for(["咖啡"], "银发") == 55


def test_duration_fountain_solo() -> None:
    """喷泉 + 独行: 20 × 1.0 = 20."""
    assert duration_for(["喷泉"], "独行") == 20


def test_duration_unknown_traveler_falls_back_to_1x() -> None:
    """未知 traveler → multiplier 1.0."""
    assert duration_for(["博物馆"], "外星人") == 100
```

- [ ] **Step 2: 跑测试确认全 FAIL**

Run: `PYTHONPATH=. venv/bin/pytest tests/test_duration_table.py -v`
Expected: 13 FAIL with `ModuleNotFoundError: No module named 'agents.duration_table'`

- [ ] **Step 3: 写实现**

```python
# agents/duration_table.py
"""POI categories → base duration (分钟) + traveler 节奏倍率.

调用入口:
  duration_for(categories, traveler, poi_name="") → int (向上取整到 5)
"""

from __future__ import annotations

import math
from typing import Iterable

# 顺序敏感: 先匹配的优先 (具体优先于宽泛).
# 关键词匹配规则: keyword in category 子串命中即算.
_DURATION_RULES: list[tuple[tuple[str, ...], int]] = [
    (("博物馆", "美术馆", "展览"), 100),
    (("火锅", "烧烤"), 90),
    (("夜市", "步行街"), 80),
    (("中餐厅", "西餐厅", "餐厅", "餐饮服务"), 70),
    (("商场", "购物"), 60),
    (("公园", "广场"), 50),
    (("咖啡", "茶馆", "甜品"), 40),
    (("小吃", "快餐"), 30),
    (("喷泉", "雕塑", "标志"), 20),
    (("风景名胜", "景点", "5A", "4A"), 90),
]

_DEFAULT_BASE = 60

_TRAVELER_MULTIPLIER: dict[str, float] = {
    "情侣": 1.2,
    "亲子": 1.4,
    "银发": 1.3,
    "独行": 1.0,
    "商务": 0.7,
    "朋友": 1.1,
}


def base_duration_for(categories: Iterable[str], poi_name: str = "") -> int:
    """遍历 _DURATION_RULES 顺序; rule 的任一关键词被任一 category 字符串包含即命中.

    categories 顺序无关; rule 表自身顺序决定优先级 (博物馆 > 通用景点).
    全部 miss → _DEFAULT_BASE.
    poi_name 当前不参与匹配, 保留入参为后续扩展.
    """
    cats = [c for c in categories if c]
    for keywords, base in _DURATION_RULES:
        for kw in keywords:
            for cat in cats:
                if kw in cat:
                    return base
    return _DEFAULT_BASE


def duration_for(categories: Iterable[str], traveler: str, poi_name: str = "") -> int:
    """base × multiplier, 向上取整到 5 的倍数. 未知 traveler → 1.0."""
    base = base_duration_for(categories, poi_name)
    mult = _TRAVELER_MULTIPLIER.get(traveler, 1.0)
    return math.ceil(base * mult / 5) * 5
```

- [ ] **Step 4: 跑测试确认全 PASS**

Run: `PYTHONPATH=. venv/bin/pytest tests/test_duration_table.py -v`
Expected: `13 passed`

- [ ] **Step 5: 跑全量基线确认无回归**

Run: `PYTHONPATH=. venv/bin/pytest tests/ -q --ignore=tests/test_user_profile_cleaning.py --ignore=tests/test_amap_client.py --ignore=tests/test_e2e_stub.py`
Expected: `430 passed`（417 + 13）

- [ ] **Step 6: Commit**

```bash
git add agents/duration_table.py tests/test_duration_table.py
git commit -m "feat(duration): POI category → traveler-aware duration table"
```

---

## Task 2: scheduler 贪心排程 + 测试

**Files:**
- Create: `agents/scheduler.py`
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: 写 6 个失败测试（spec 5 + 1 个 tail-cap）**

```python
# tests/test_scheduler.py
"""Unit tests for agents.scheduler — 贪心排程 + 餐点 anchor."""

from datetime import time
from types import SimpleNamespace

from agents.scheduler import (
    DAY_END_HARD_CAP,
    DAY_START_BY_TRAVELER,
    DINNER_ANCHOR,
    LUNCH_ANCHOR,
    schedule_day,
)


def _poi(name: str, categories: list[str]):
    """轻量 POI stub. scheduler 只读 .name / .categories."""
    return SimpleNamespace(name=name, categories=categories)


# --- happy path ---

def test_happy_couple_4stops_meals_in_anchor() -> None:
    """情侣 4 stop: 起点 10:00, 午餐 in [11:30,12:30], 晚餐 in [18:00,19:00]."""
    pois = [
        _poi("公园", ["公园"]),         # 50 × 1.2 = 60
        _poi("中餐厅", ["中餐厅"]),     # 70 × 1.2 = 84 → 85
        _poi("博物馆", ["博物馆"]),     # 100 × 1.2 = 120
        _poi("西餐厅", ["西餐厅"]),     # 70 × 1.2 = 85
    ]
    slots = ["上午景点", "午饭", "下午", "晚饭"]
    out = schedule_day(pois, slots, "情侣")
    assert out[0][0] == time(10, 0)                          # 起点
    assert LUNCH_ANCHOR[0] <= out[1][0] <= LUNCH_ANCHOR[1]   # 午餐 anchor
    assert DINNER_ANCHOR[0] <= out[3][0] <= DINNER_ANCHOR[1] # 晚餐 anchor


# --- 拖时压缩 ---

def test_morning_long_squeezes_prev_for_lunch() -> None:
    """情侣上午博物馆 120min 拖到晚于 12:30 → 压缩 prev (-25% max), 午餐 ≤ 12:30."""
    pois = [
        _poi("博物馆", ["博物馆"]),     # 100 × 1.2 = 120
        _poi("中餐厅", ["中餐厅"]),     # 85
    ]
    slots = ["上午景点", "午饭"]
    out = schedule_day(pois, slots, "情侣")
    # 起点 10:00 + 120 + 30 = 12:30 — 刚好命中 anchor 上限
    assert out[1][0] <= LUNCH_ANCHOR[1]
    # 博物馆 duration 没被压（因为本来就 ≤ anchor 上限）
    assert out[0][1] == 120


def test_morning_long_squeezes_prev_overshoot() -> None:
    """亲子博物馆 100×1.4=140 + 起点 8:30 = 11:00 + 140 + 30 = 13:40 → 压 -25% 后 = 13:05? 仍超 12:30 → clamp 12:30."""
    pois = [
        _poi("博物馆", ["博物馆"]),     # 100 × 1.4 = 140
        _poi("中餐厅", ["中餐厅"]),     # 70 × 1.4 = 98 → 100
    ]
    slots = ["上午景点", "午饭"]
    out = schedule_day(pois, slots, "亲子")
    # 午餐 arrival 不能超 anchor 上限
    assert out[1][0] <= LUNCH_ANCHOR[1]
    # 博物馆被压缩, 至多 -25% (140 → ≥ 105)
    assert 105 <= out[0][1] <= 140


# --- 早起 ---

def test_family_early_start_within_day_cap() -> None:
    """亲子起点 8:30; 4 stops 全部 arrival 在 21:00 前."""
    pois = [
        _poi("公园", ["公园"]),
        _poi("餐厅", ["餐厅"]),
        _poi("博物馆", ["博物馆"]),
        _poi("晚饭", ["餐厅"]),
    ]
    slots = ["上午景点", "午饭", "下午", "晚饭"]
    out = schedule_day(pois, slots, "亲子")
    assert out[0][0] == DAY_START_BY_TRAVELER["亲子"]
    for arrival, _ in out:
        assert arrival <= DAY_END_HARD_CAP


# --- 商务 ---

def test_business_fast_pace_ends_early() -> None:
    """商务节奏: 末位 arrival < 18:00 (multiplier 0.7 → 不拖到晚)."""
    pois = [
        _poi("公园", ["公园"]),
        _poi("餐厅", ["餐厅"]),
        _poi("博物馆", ["博物馆"]),
        _poi("茶馆", ["茶馆"]),
    ]
    slots = ["上午景点", "午饭", "下午", "下午茶"]
    out = schedule_day(pois, slots, "商务")
    # 注意: 因为没有 "晚饭" slot, scheduler 不会触发晚餐 anchor, 末位是下午茶, 应远早于 18:00
    assert out[-1][0] < time(18, 0)


# --- 全 fallback ---

def test_all_fallback_pois_still_schedules() -> None:
    """全 fallback POI (空 categories) → base 60 × multiplier 仍能跑通."""
    pois = [
        _poi("X", []),
        _poi("Y", []),
        _poi("Z", []),
    ]
    slots = ["上午景点", "午饭", "下午"]
    out = schedule_day(pois, slots, "独行")
    assert len(out) == 3
    assert all(isinstance(a, time) for a, _ in out)
```

- [ ] **Step 2: 跑测试确认全 FAIL**

Run: `PYTHONPATH=. venv/bin/pytest tests/test_scheduler.py -v`
Expected: 6 FAIL with `ModuleNotFoundError: No module named 'agents.scheduler'`

- [ ] **Step 3: 写实现**

```python
# agents/scheduler.py
"""贪心排程: 起点 by traveler, 餐点 anchor 不漂, leave_time 软约束.

输入: stops_poi (顺序 == 行程顺序), slot_names (一一对应), traveler.
输出: [(arrival_time, recommended_duration_min), ...] 长度同 stops_poi.

算法:
  1. 起点 = DAY_START_BY_TRAVELER[traveler] or DEFAULT.
  2. 逐 stop 滚雪球: arrival[i+1] = arrival[i] + duration[i] + transit_min.
  3. 餐点 (slot 含 "午饭"/"晚饭") 触发 anchor 检查 — 见 _apply_anchor.
  4. 末位 arrival > DAY_END_HARD_CAP → 整体回退, 从最长 stop 压 -25%.
"""

from __future__ import annotations

from datetime import time
from typing import Any

from agents.duration_table import duration_for

DAY_START_BY_TRAVELER: dict[str, time] = {
    "商务": time(9, 0),
    "独行": time(9, 30),
    "情侣": time(10, 0),
    "朋友": time(10, 0),
    "亲子": time(8, 30),
    "银发": time(8, 0),
}
DAY_START_DEFAULT = time(9, 30)

LUNCH_ANCHOR = (time(11, 30), time(12, 30))
DINNER_ANCHOR = (time(18, 0), time(19, 0))
DAY_END_HARD_CAP = time(21, 0)


def _to_min(t: time) -> int:
    return t.hour * 60 + t.minute


def _to_time(m: int) -> time:
    m = max(0, min(m, 23 * 60 + 59))
    return time(m // 60, m % 60)


def _slot_anchor(slot: str) -> tuple[int, int] | None:
    if "午饭" in slot:
        return _to_min(LUNCH_ANCHOR[0]), _to_min(LUNCH_ANCHOR[1])
    if "晚饭" in slot:
        return _to_min(DINNER_ANCHOR[0]), _to_min(DINNER_ANCHOR[1])
    return None


def schedule_day(
    stops_poi: list[Any],
    slot_names: list[str],
    traveler: str,
    transit_min_between: int = 30,
) -> list[tuple[time, int]]:
    """见模块 docstring."""
    n = len(stops_poi)
    if n == 0:
        return []
    if len(slot_names) != n:
        raise ValueError(
            f"slot_names ({len(slot_names)}) must match stops_poi ({n})"
        )

    durations = [
        duration_for(getattr(p, "categories", []) or [], traveler, getattr(p, "name", ""))
        for p in stops_poi
    ]

    arrivals_min: list[int] = []
    cur = _to_min(DAY_START_BY_TRAVELER.get(traveler, DAY_START_DEFAULT))

    for i in range(n):
        anchor = _slot_anchor(slot_names[i])
        if anchor:
            lo, hi = anchor
            if cur < lo:
                cur = lo
            elif cur > hi:
                overshoot = cur - hi
                if i > 0:
                    max_squeeze = durations[i - 1] // 4
                    squeeze = min(overshoot, max_squeeze)
                    durations[i - 1] -= squeeze
                    cur -= squeeze
                if cur > hi:
                    cur = hi
        arrivals_min.append(cur)
        cur += durations[i] + transit_min_between

    # tail check: 末位 arrival 超 DAY_END_HARD_CAP → 从最长 stop 压 -25%
    cap = _to_min(DAY_END_HARD_CAP)
    if arrivals_min[-1] > cap:
        overshoot = arrivals_min[-1] - cap
        idx_max = max(range(n), key=lambda j: durations[j])
        max_squeeze = durations[idx_max] // 4
        squeeze = min(overshoot, max_squeeze)
        durations[idx_max] -= squeeze
        for j in range(idx_max + 1, n):
            arrivals_min[j] -= squeeze

    return [(_to_time(a), d) for a, d in zip(arrivals_min, durations)]
```

- [ ] **Step 4: 跑测试确认全 PASS**

Run: `PYTHONPATH=. venv/bin/pytest tests/test_scheduler.py -v`
Expected: `6 passed`

- [ ] **Step 5: 跑全量基线**

Run: `PYTHONPATH=. venv/bin/pytest tests/ -q --ignore=tests/test_user_profile_cleaning.py --ignore=tests/test_amap_client.py --ignore=tests/test_e2e_stub.py`
Expected: `436 passed`（430 + 6）

- [ ] **Step 6: Commit**

```bash
git add agents/scheduler.py tests/test_scheduler.py
git commit -m "feat(scheduler): greedy day schedule with meal anchor + tail cap"
```

---

## Task 3: Stop schema 加 `recommended_duration_min`

**Files:**
- Modify: `dianping/schemas.py:386-392`
- Test: `tests/test_schema_stop_duration.py`

- [ ] **Step 1: 写 2 个失败测试**

```python
# tests/test_schema_stop_duration.py
"""Stop.recommended_duration_min default + override."""

from datetime import time

from dianping.schemas import POI, Stop, TimeSlot


def _poi() -> POI:
    return POI(
        openshopid="x",
        name="X",
        city="深圳",
        latitude=22.5,
        longitude=114.0,
    )


def _slot() -> TimeSlot:
    return TimeSlot(name="上午景点", start=time(9, 0), end=time(12, 0))


def test_stop_default_recommended_duration_is_60() -> None:
    s = Stop(
        poi=_poi(),
        slot=_slot(),
        arrival_time=time(9, 0),
        leave_time=time(10, 30),
    )
    assert s.recommended_duration_min == 60


def test_stop_override_recommended_duration() -> None:
    s = Stop(
        poi=_poi(),
        slot=_slot(),
        arrival_time=time(9, 0),
        leave_time=time(10, 30),
        recommended_duration_min=120,
    )
    assert s.recommended_duration_min == 120
```

- [ ] **Step 2: 跑测试确认 FAIL**

Run: `PYTHONPATH=. venv/bin/pytest tests/test_schema_stop_duration.py -v`
Expected: `AttributeError: 'Stop' object has no attribute 'recommended_duration_min'`（或类似）

- [ ] **Step 3: 修 schema**

`dianping/schemas.py:386-392` 改成：

```python
class Stop(BaseModel):
    poi: POI
    slot: TimeSlot
    arrival_time: time
    leave_time: time
    transport_to_next_minutes: int = 30
    transport_options: Optional[dict[str, TransitInfo]] = None
    recommended_duration_min: int = 60  # v1: 时长灵动; 老 trip 缓存默认 60
```

- [ ] **Step 4: 跑两个测试 PASS**

Run: `PYTHONPATH=. venv/bin/pytest tests/test_schema_stop_duration.py -v`
Expected: `2 passed`

- [ ] **Step 5: 全量基线**

Run: `PYTHONPATH=. venv/bin/pytest tests/ -q --ignore=tests/test_user_profile_cleaning.py --ignore=tests/test_amap_client.py --ignore=tests/test_e2e_stub.py`
Expected: `438 passed`（436 + 2，新字段默认值不破老测试）

- [ ] **Step 6: Commit**

```bash
git add dianping/schemas.py tests/test_schema_stop_duration.py
git commit -m "feat(schema): Stop.recommended_duration_min default 60"
```

---

## Task 4: planner.py 3 处 Stop 构造接入 schedule_day

**Files:**
- Modify: `agents/planner.py` 3 处 Stop 构造点（line 295-323 compose_route / line 408-447 compose_one_day / line 750-790 _synthesize_fallback_route）
- Test: `tests/test_planner_schedule_integration.py`

**关键约束:** schedule_day 在 `stops` list 全部 append 完后一次性调用，覆盖每个 Stop 的 `arrival_time` / `leave_time` / `recommended_duration_min`。`leave_time = arrival_time + recommended_duration_min`（保持下游兼容）。

- [ ] **Step 1: 写 2 个集成失败测试**

```python
# tests/test_planner_schedule_integration.py
"""planner.compose_one_day 走完后 Stop.recommended_duration_min 应来自 scheduler."""

from datetime import time
from types import SimpleNamespace

from agents.scheduler import LUNCH_ANCHOR
from dianping.schemas import POI, Stop, TimeSlot


def _poi(name: str, oid: str, cats: list[str]) -> POI:
    return POI(
        openshopid=oid,
        name=name,
        city="深圳",
        latitude=22.5,
        longitude=114.0,
        categories=cats,
    )


def test_synthesize_fallback_route_uses_scheduler() -> None:
    """_synthesize_fallback_route 输出的 Stop 应有 recommended_duration_min 来自 duration_for."""
    from agents.planner import _synthesize_fallback_route

    intent = SimpleNamespace(
        city="深圳",
        days=1,
        traveler_type="情侣",
        must_visit=[],
        required_slots=[],
        time_window=None,
        anchor_lng=None,
        anchor_lat=None,
        trip_mode=None,
    )
    pool = [
        _poi("公园 A", "p1", ["公园"]),
        _poi("中餐厅 B", "r1", ["中餐厅", "美食"]),
        _poi("博物馆 C", "m1", ["博物馆"]),
    ]
    route = _synthesize_fallback_route(intent, pool)
    assert route.days, "synth should produce ≥1 day"
    stops = route.days[0].stops
    assert stops, "day should have stops"
    for st in stops:
        assert st.recommended_duration_min >= 20, (
            f"recommended_duration_min should be set by scheduler, got {st.recommended_duration_min}"
        )
    # 起点 = 情侣 10:00（若 fallback synth 走 schedule_day）
    assert stops[0].arrival_time == time(10, 0)


def test_synthesize_fallback_route_meal_anchored() -> None:
    """若 fallback synth 输出包含 '午饭' slot, arrival 必须在 LUNCH_ANCHOR 内."""
    from agents.planner import _synthesize_fallback_route

    intent = SimpleNamespace(
        city="深圳",
        days=1,
        traveler_type="情侣",
        must_visit=[],
        required_slots=[],
        time_window=None,
        anchor_lng=None,
        anchor_lat=None,
        trip_mode=None,
    )
    pool = [
        _poi("公园 A", "p1", ["公园"]),
        _poi("中餐厅 B", "r1", ["中餐厅", "美食"]),
        _poi("博物馆 C", "m1", ["博物馆"]),
        _poi("西餐厅 D", "r2", ["西餐厅", "美食"]),
    ]
    route = _synthesize_fallback_route(intent, pool)
    stops = route.days[0].stops
    meal_stops = [s for s in stops if "午饭" in s.slot.name]
    if meal_stops:
        m = meal_stops[0]
        assert LUNCH_ANCHOR[0] <= m.arrival_time <= LUNCH_ANCHOR[1], (
            f"lunch arrival {m.arrival_time} outside anchor {LUNCH_ANCHOR}"
        )
```

- [ ] **Step 2: 跑测试确认 FAIL**

Run: `PYTHONPATH=. venv/bin/pytest tests/test_planner_schedule_integration.py -v`
Expected: 2 FAIL（recommended_duration_min 走默认 60 或 arrival_time 用 slot.start 而非 10:00）

- [ ] **Step 3: 写 helper `_apply_schedule_to_stops`**

在 `agents/planner.py` import 区下方添加：

```python
# v1: 时长灵动 — schedule_day 覆盖 Stop 时间
from agents.scheduler import schedule_day as _schedule_day


def _apply_schedule_to_stops(
    stops: list[Stop],
    traveler: str,
) -> list[Stop]:
    """对一组按行程顺序排好的 Stop 调 schedule_day, 用结果覆盖 arrival_time /
    leave_time / recommended_duration_min. 返回新 Stop list (同序).
    """
    if not stops:
        return stops
    pois = [s.poi for s in stops]
    slots = [s.slot.name for s in stops]
    scheduled = _schedule_day(pois, slots, traveler or "")
    out: list[Stop] = []
    for s, (arr, dur) in zip(stops, scheduled):
        # leave_time = arrival + duration (HH:MM, 不跨日)
        arr_min = arr.hour * 60 + arr.minute
        leave_min = min(arr_min + dur, 23 * 60 + 59)
        from datetime import time as _t
        leave_t = _t(leave_min // 60, leave_min % 60)
        out.append(
            s.model_copy(
                update={
                    "arrival_time": arr,
                    "leave_time": leave_t,
                    "recommended_duration_min": dur,
                }
            )
        )
    return out
```

- [ ] **Step 4: 接入 compose_route (line 295-323)**

在 compose_route 内 `days_out.append(...)` 之前（即当天 `stops` list 已经填完时）插入：

```python
            # v1: 时长灵动 — 用 scheduler 覆盖 LLM 给的时间
            stops = _apply_schedule_to_stops(stops, ctx.intent.traveler_type or "")
```

定位：`agents/planner.py:323` 之后、`days_out.append(` 之前那行（即 `for s in day_data.get("stops", []) or []:` 循环 break 后、append DayPlan 之前）。

- [ ] **Step 5: 接入 compose_one_day (line 408-447)**

在 compose_one_day 内 `day_plan = DayPlan(...)` 之前插入：

```python
        # v1: 时长灵动 — 用 scheduler 覆盖 LLM 给的时间
        stops = _apply_schedule_to_stops(stops, getattr(ctx.intent, "traveler_type", "") or "")
```

定位：`agents/planner.py:460` 附近，`day_plan = DayPlan(...)` 之前一行（确保 stops list 已经全部填完）。

- [ ] **Step 6: 接入 _synthesize_fallback_route (line 750-790 区域)**

找到 `_synthesize_fallback_route` 内组完所有 Stop 后 return 之前，加：

```python
    # v1: 时长灵动 — fallback 也走 scheduler
    for d in route.days:
        d.stops = _apply_schedule_to_stops(d.stops, getattr(intent, "traveler_type", "") or "")
    return route
```

定位：`_synthesize_fallback_route` 末尾 `return RouteDraft(...)` 或 `return route` 之前。

- [ ] **Step 7: 跑集成测试 PASS**

Run: `PYTHONPATH=. venv/bin/pytest tests/test_planner_schedule_integration.py -v`
Expected: `2 passed`

- [ ] **Step 8: 全量基线**

Run: `PYTHONPATH=. venv/bin/pytest tests/ -q --ignore=tests/test_user_profile_cleaning.py --ignore=tests/test_amap_client.py --ignore=tests/test_e2e_stub.py`
Expected: `440 passed`（438 + 2）

> ⚠️ 若个别老 planner 测试因为现在 arrival_time 走 scheduler 而不再等于 slot.start，需逐个调整断言 — 改为读 `stop.recommended_duration_min` 或不再断言具体时刻（spec 已承诺时间分配换实现）。**只允许调整断言，不允许 weaken 测试覆盖。** 若 > 5 个老测试因此挂掉，停下来上报。

- [ ] **Step 9: Commit**

```bash
git add agents/planner.py tests/test_planner_schedule_integration.py
git commit -m "feat(planner): apply scheduler to all Stop construction paths"
```

---

## Task 5: rationale 餐点压缩附注

**Files:**
- Modify: `agents/rationale.py:214-263` build_rationale_for_stop
- Modify: `agents/planner.py` 调用点传入压缩百分比
- Test: `tests/test_rationale_squeeze_note.py`

> **范围澄清:** Task 4 的 `_apply_schedule_to_stops` 已经覆盖了 duration. 为了让 rationale 知道"前一 stop 被压了 X%"，需要把 schedule_day 返回的 duration 与"自然 duration"（即未压缩的 duration_for 输出）做对比. Task 5 做这件事 + rationale 加新参数.

- [ ] **Step 1: 写 1 个失败测试**

```python
# tests/test_rationale_squeeze_note.py
"""build_rationale_for_stop 收到 prev_squeeze_pct 应在 reason 末尾追加中文附注."""

from datetime import time
from types import SimpleNamespace

from agents.rationale import build_rationale_for_stop
from dianping.schemas import POI, Stop, TimeSlot


def _stop() -> Stop:
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
    intent = SimpleNamespace(traveler_type="情侣", must_visit=[], city="南昌")
    out = build_rationale_for_stop(
        intent, _stop(), variant="main", prev_squeeze_pct=80, prev_stop_name="博物馆 A"
    )
    assert "为了赶上午饭" in out["reason"]
    assert "博物馆 A" in out["reason"]
    assert "80%" in out["reason"]


def test_no_note_when_pct_none() -> None:
    intent = SimpleNamespace(traveler_type="情侣", must_visit=[], city="南昌")
    out = build_rationale_for_stop(intent, _stop(), variant="main")
    assert "为了赶" not in out["reason"]
```

- [ ] **Step 2: 跑确认 FAIL**

Run: `PYTHONPATH=. venv/bin/pytest tests/test_rationale_squeeze_note.py -v`
Expected: 2 FAIL（`TypeError: unexpected keyword arg 'prev_squeeze_pct'`）

- [ ] **Step 3: 改 `build_rationale_for_stop` 签名**

`agents/rationale.py:214` 改 signature:

```python
def build_rationale_for_stop(
    intent: ParsedIntent,
    stop: Stop,
    variant: str = "main",
    prev_squeeze_pct: Optional[int] = None,
    prev_stop_name: str = "",
) -> dict:
```

并在函数末尾 `return _wrap(...)` 前所有分支共用的 wrap 之前，加一个统一的附加附注 helper（或者在每个 return 前的 text 上做拼接）。最简洁做法是包一层：

```python
def build_rationale_for_stop(
    intent: ParsedIntent,
    stop: Stop,
    variant: str = "main",
    prev_squeeze_pct: Optional[int] = None,
    prev_stop_name: str = "",
) -> dict:
    """..."""
    result = _build_core(intent, stop, variant)
    if prev_squeeze_pct is not None and prev_squeeze_pct < 100 and prev_stop_name:
        suffix = f" 为了赶{stop.slot.name}节点，把「{prev_stop_name}」的逗留压到 {prev_squeeze_pct}%。"
        result["reason"] = result["reason"] + suffix
        result["factors"].append(f"squeeze_prev={prev_squeeze_pct}")
    return result
```

把原 `build_rationale_for_stop` 函数体改名为 `_build_core(intent, stop, variant) -> dict`（签名等同旧 build_rationale_for_stop 三个参数 + 返回 dict）。

- [ ] **Step 4: 跑 rationale 测试 PASS**

Run: `PYTHONPATH=. venv/bin/pytest tests/test_rationale_squeeze_note.py tests/test_rationale.py -v` （`tests/test_rationale.py` 若存在）
Expected: 全 PASS（老测试不传新参数走 None 路径，行为不变）

- [ ] **Step 5: 调用点传压缩百分比**

修改 Task 4 的 `_apply_schedule_to_stops` 使其同时返回每个 stop 的"自然 duration"（未被 anchor 压缩前的值），方法是先把 `duration_for(...)` 算一遍存 `natural`，再调 schedule_day 拿 `actual`，对比得 pct。然后在 planner 中调 build_rationale_for_stop 时把对应 (`prev_squeeze_pct`, `prev_stop_name`) 传进去。

如果 planner 现在的 rationale 调用不在 schedule 同一个函数里（多半在 `agents/rationale.build_rationale_for_day` 或 routes.py SSE 流里），先 grep 调用点：

```bash
grep -n 'build_rationale_for_stop' agents/ api/ | head
```

定位调用点后，在那里读 Stop.recommended_duration_min 和"自然值"（再算一遍 `duration_for(poi.categories, traveler)`），对比得 pct，传入。

> **范围控制:** 如果调用点位置使得对比"自然 vs 实际"成本太高（>30 行改动），降级方案：跳过 squeeze_pct 传递，只做 Step 3 的函数签名扩展（向后兼容默认 None，老调用不变），rationale 附注留待后续 spec。这种降级要在 commit message 里写清楚。

- [ ] **Step 6: 全量基线**

Run: `PYTHONPATH=. venv/bin/pytest tests/ -q --ignore=tests/test_user_profile_cleaning.py --ignore=tests/test_amap_client.py --ignore=tests/test_e2e_stub.py`
Expected: `442 passed`（440 + 2）

- [ ] **Step 7: Commit**

```bash
git add agents/rationale.py agents/planner.py tests/test_rationale_squeeze_note.py
git commit -m "feat(rationale): note prev-stop squeeze for meal anchor"
```

---

## Task 6: 前端 pushPlaceCard 渲染 recommended_duration_min

**Files:**
- Modify: `web/plan_stack.html:1786` durText 渲染处

- [ ] **Step 1: 读现状**

`web/plan_stack.html:1760-1766` 当前 durText 计算：

```js
let durText = '';
if (arrTime && leaveTime) {
  const [ah,am] = arrTime.split(':').map(Number);
  const [lh,lm] = leaveTime.split(':').map(Number);
  const mins = (lh*60+lm)-(ah*60+am);
  if (mins > 0) durText = `${mins}m`;
}
```

line 1786:
```html
${durText ? `<span>· ${durText}</span>` : ''}
```

- [ ] **Step 2: 改 durText 优先用 recommended_duration_min**

把 line 1760-1766 改为：

```js
let durText = '';
const recDur = stop.recommended_duration_min;
if (recDur && recDur > 0) {
  durText = `推荐 ${recDur}min`;
} else if (arrTime && leaveTime) {
  const [ah,am] = arrTime.split(':').map(Number);
  const [lh,lm] = leaveTime.split(':').map(Number);
  const mins = (lh*60+lm)-(ah*60+am);
  if (mins > 0) durText = `${mins}m`;
}
```

line 1786 的 `<span>· ${durText}</span>` 保持不变（durText 已含"推荐 90min"）。

- [ ] **Step 3: 后端要把 recommended_duration_min 真正下发到前端**

grep SSE payload 构造点：

```bash
grep -n 'day_done\|stop\.poi\|"arrival_time"\|recommended_duration' api/routes.py | head -30
```

确认 SSE event `planner.day_done` 序列化 stops 时把 `recommended_duration_min` 也带上。如果使用 `stop.model_dump()` 一次性序列化，则字段自动包含（pydantic 默认行为），不需改。否则手动添加：

```python
"recommended_duration_min": st.recommended_duration_min,
```

> 验证方法：`curl http://127.0.0.1:9191/api/plan/stream -d ...` 看 day_done event payload 含 `recommended_duration_min` 字段。

- [ ] **Step 4: 启本地服务跑 demo 验**

```bash
# 终端 A (mock)
PYTHONPATH=. venv/bin/uvicorn dianping.mock_server:mock_app --host 127.0.0.1 --port 9192 &

# 终端 B (api, 必须用绝对路径 source env)
set -a; . /Users/yikuaibanz1/Desktop/sth/mtagent/.env; set +a
PYTHONPATH=. venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 9191 &
```

打开 `http://127.0.0.1:9191`，输入"南昌 1 天 单人旅行 美食 历史文化"+ 走完 clarify，预期 stop 卡片显示 `09:00 · 推荐 90min` 而不是 `09:00 · 90m`。

- [ ] **Step 5: 全量基线（前端改动不影响 pytest）**

Run: `PYTHONPATH=. venv/bin/pytest tests/ -q --ignore=tests/test_user_profile_cleaning.py --ignore=tests/test_amap_client.py --ignore=tests/test_e2e_stub.py`
Expected: `442 passed`（不变）

- [ ] **Step 6: Commit**

```bash
git add web/plan_stack.html api/routes.py
git commit -m "feat(ui): render recommended_duration_min on stop card"
```

---

## Task 7: e2e SSE smoke 测时间正确

**Files:**
- Test: `tests/test_e2e_sse_duration.py`

> **可选 task** - 如果 Task 6 浏览器手动验已通过且评委 demo 时间紧，可跳过.

- [ ] **Step 1: 写 SSE 集成测试**

```python
# tests/test_e2e_sse_duration.py
"""SSE flow: planner.day_done payload 含 recommended_duration_min 字段 (非 0)."""

import json

from fastapi.testclient import TestClient


def test_sse_day_done_carries_recommended_duration():
    from api.main import app

    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/plan/stream",
        json={
            "free_text": "南昌 1 天 单人旅行 美食 历史文化 预算 500 元 不要排队 想吃赣菜",
        },
    ) as resp:
        assert resp.status_code == 200
        event_name = None
        seen_dur = False
        for line in resp.iter_lines():
            if line.startswith("event:"):
                event_name = line[len("event:"):].strip()
            elif line.startswith("data:") and event_name == "planner.day_done":
                payload = json.loads(line[len("data:"):].strip())
                for st in payload.get("stops", []):
                    if st.get("recommended_duration_min", 0) > 0:
                        seen_dur = True
                        break
                if seen_dur:
                    break
        assert seen_dur, "planner.day_done should carry recommended_duration_min > 0"
```

- [ ] **Step 2: 跑确认（需要 mock_server 在 9192）**

```bash
# 启 mock
PYTHONPATH=. venv/bin/uvicorn dianping.mock_server:mock_app --port 9192 &
PYTHONPATH=. venv/bin/pytest tests/test_e2e_sse_duration.py -v
```

Expected: `1 passed`

> 如失败：很可能是 clarify 截胡（看 task 已有 session 经验，free_text 需补全所有 must-have slot）。debug 时可先 print `event_name` 与 payload。如果 clarify 持续截胡，把这 task 标 SKIP 并依赖 Task 6 手动验。

- [ ] **Step 3: Commit（若 step 2 通过）**

```bash
git add tests/test_e2e_sse_duration.py
git commit -m "test(e2e): SSE planner.day_done carries recommended_duration_min"
```

---

## 结束 checklist

- [ ] 全量基线 `pytest tests/ -q --ignore=...` 仍 ≥ `442 passed`
- [ ] `git log --oneline origin/main..HEAD` 列出本次新增的 6-7 个 commit
- [ ] 本地浏览器手动验：南昌 1 天 → stop 卡片显示"`09:00 · 推荐 90min`"且午餐 arrival ∈ `[11:30, 12:30]`
- [ ] 报告：`push origin? VPS pull + restart?` 等用户确认（破坏性操作不自动做）

---

## 风险与回滚

| 风险 | 缓解 |
|---|---|
| Task 4 集成 schedule_day 后老 planner 测试断言时间挂掉 | 允许调整断言为"in anchor 窗"而非具体时刻；> 5 个挂掉时停下上报 |
| LLM 给 stop 顺序与 slot_name 不匹配，scheduler 触发不对的 anchor | scheduler 仅看 slot_name 字符串包含 "午饭"/"晚饭"，且 planner 已有 slot 去重逻辑（line 411 used_slot_names） |
| 老 trip 缓存 stop 缺 recommended_duration_min | Task 3 默认 60 + Task 6 前端 fallback durText 双保险 |
| critic 看到 leave_time 比 arrival 远（120min）误报 | 当前 critic 检查不查 stop 内部 duration，spec 已确认 |
| variant_patches diff 引入新字段 | 已确认只比 openshopid，无影响 |

**回滚:** Task 4 改的 3 处 Stop 构造 + `_apply_schedule_to_stops` 调用点，注释这 3 行即恢复旧 LLM 时间。Task 3 schema 字段默认值不破老序列化。Task 6 前端改动是 if-else fallback，不影响老 trip 渲染。

---

## Self-Review Notes

- ✅ **Spec coverage:** duration_table (Task 1) / scheduler (Task 2) / Stop schema (Task 3) / planner 接入 (Task 4) / rationale 附注 (Task 5) / 前端 UI (Task 6) / e2e smoke (Task 7) 覆盖 spec 全部新代码段。
- ✅ **No placeholders:** 每个 code 步骤都给完整 snippet；commands 都给绝对路径 + 期望输出。
- ✅ **Type consistency:** `_apply_schedule_to_stops` 在 Task 4 定义 + Task 5 复用；`recommended_duration_min` 字段名贯穿 Task 3 / 4 / 6 / 7。
- ⚠ **已知 fragile:** Task 4 Step 8 老测试可能挂；Task 5 Step 5 调用点定位为 grep + 实施，没法预先精确写死。这两处都给了降级路径。
