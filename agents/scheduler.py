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
        raise ValueError(f"slot_names ({len(slot_names)}) must match stops_poi ({n})")

    durations = [
        duration_for(
            getattr(p, "categories", []) or [], traveler, getattr(p, "name", "")
        )
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
