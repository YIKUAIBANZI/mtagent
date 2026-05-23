# 时长灵动 v1 · Design Spec

**Date:** 2026-05-23
**Status:** brainstorm 拍板，待 writing-plans
**Project:** mtagent (赛题 05)
**Author:** 用户 + Claude (brainstorming session 2)

---

## 背景

现状 planner 输出的 stops 时间是硬编码槽位：`09:00 / 12:00 / 14:00 / 18:00`，逗留也按 slot 等分。痛点：

- 滕王阁、博物馆这种慢看的地方和音乐喷泉这种打卡的混在同一 90min 框里；
- 情侣节奏 vs 商务节奏一刀切；
- "AI 不像在替我安排"，只像把 POI 串了一遍画地图。

本 spec 目标：让 stop 的 arrival_time 和"推荐逗留"按 POI 类型 + traveler 节奏动态算，餐点锚定不漂，起点按 traveler 浮动。stop 数量与变体分流（Spec 2026-05-21）不动。

---

## 整体形态决策（brainstorm 拍板）

| 决策点 | 选定 | 说明 |
|---|---|---|
| 时长来源 | 静态表 (categories) × traveler 倍率 | 纯后端、可测、不走 LLM |
| 起点 | 按 traveler 浮动 | 商务 09:00 / 情侣 10:00 / 亲子 08:30 / 银发 08:00 / 独行 09:30 / 朋友 10:00 |
| 餐点 | anchor + buffer | 午餐 12:00 ± 30min，晚餐 18:30 ± 30min |
| 冲突处理 | stop 数固定 + leave_time 软约束 | 装不下时压缩前一个 stop 至多 -25%；UI 只画 arrival + "推荐逗留 X min" |

---

## 后端

### 新模块 `agents/duration_table.py`

```python
"""POI categories → base duration 分钟 + traveler 节奏倍率."""

from __future__ import annotations
from typing import Iterable

# 顺序敏感：先匹配的优先（具体优先于宽泛）
_DURATION_RULES: list[tuple[tuple[str, ...], int]] = [
    (("博物馆", "美术馆", "展览"), 100),
    (("风景名胜", "景点", "5A", "4A"), 90),
    (("火锅", "烧烤"), 90),
    (("夜市", "步行街"), 80),
    (("中餐厅", "西餐厅", "餐厅", "餐饮服务"), 70),
    (("商场", "购物"), 60),
    (("公园", "广场"), 50),
    (("咖啡", "茶馆", "甜品"), 40),
    (("小吃", "快餐"), 30),
    (("喷泉", "雕塑", "标志"), 20),
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
    """遍历 _DURATION_RULES 的顺序, 任一关键词被 categories 集合中任一字符串包含即命中,
    返回该 rule 的 base. _DURATION_RULES 自身顺序决定优先级 (博物馆 > 通用景点).
    全部 miss → _DEFAULT_BASE. categories 顺序无关."""

def duration_for(categories: Iterable[str], traveler: str, poi_name: str = "") -> int:
    """base × multiplier, 向上取整到 5 的倍数."""
```

### 新模块 `agents/scheduler.py`

```python
"""贪心排程: 起点 by traveler, 餐点 anchor 不漂, leave_time 软约束."""

from datetime import time

DAY_START_BY_TRAVELER: dict[str, time] = {
    "商务": time(9, 0),
    "独行": time(9, 30),
    "情侣": time(10, 0),
    "朋友": time(10, 0),
    "亲子": time(8, 30),
    "银发": time(8, 0),
}
DAY_START_DEFAULT = time(9, 30)

LUNCH_ANCHOR = (time(11, 30), time(12, 30))   # 午餐 arrive 必须 in 此窗
DINNER_ANCHOR = (time(18, 0), time(19, 0))    # 晚餐 arrive 必须 in 此窗
DAY_END_HARD_CAP = time(21, 0)


def schedule_day(
    stops_poi: list["POI"],
    slot_names: list[str],           # 与 stops_poi 一一对应，如 ["上午景点","午饭","下午","晚饭"]
    traveler: str,
    transit_min_between: int = 30,
) -> list[tuple[time, int]]:
    """返回 [(arrival_time, recommended_duration_min), ...]，长度同 stops_poi.

    算法:
    1. 起点 = DAY_START_BY_TRAVELER[traveler] or DEFAULT.
    2. 逐 stop 滚雪球: arrival[i+1] = arrival[i] + duration[i] + transit_min.
    3. 餐点 (slot 含 "午饭"/"晚饭") 触发 anchor 检查:
       - 若 arrival 在 anchor 窗内 → 保持.
       - 若 arrival 在窗后 (拖太晚) → 把它强制 = anchor 中心, 同时把前一个 stop 的
         duration 按比例压缩, 最多 -25%; 若 -25% 仍装不下, 接受 arrival = anchor 窗
         上限 (即午餐 12:30, 晚餐 19:00).
       - 若 arrival 在窗前 (太早) → 把它延后到 anchor 下限 (午餐 11:30, 晚餐 18:00).
    4. 末位 arrival > DAY_END_HARD_CAP → 整体回退, 把超出的分钟从最长 stop 压掉
       (单 stop -25% 极限). 该极限仍不够则保持原状, 由 critic 提示 stop_count_ok 警告.
    """
```

### Schema 改动 `dianping/schemas.py:Stop`

```python
class Stop(BaseModel):
    poi: POI
    slot: TimeSlot
    arrival_time: time
    leave_time: time                          # 兼容字段, 不再前端显示
    transport_to_next_minutes: int = 30
    transport_options: Optional[dict[str, TransitInfo]] = None
    recommended_duration_min: int = 60        # 新, 前端显示用
```

### Planner 接入

`agents/planner.py` 和 `agents/planner_instant.py` 在选完 POI、确定 `slot_name` 后，调 `schedule_day(stops_poi, slot_names, traveler)`，覆盖原 slot-based 时间分配；同时把 `leave_time` 设为 `arrival_time + recommended_duration_min`（保持下游兼容）。

`agents/rationale.build_rationale_for_stop` 接收新字段，若餐点触发了压缩，多一句中文 reason `为了赶上午饭节点，把 ${prev_stop_name} 的逗留压到 ${pct}%`。

---

## 前端 `web/plan_stack.html`

### `pushPlaceCard` 渲染

旧：
```js
${arrTime ? `<span>${escapeHtml(arrTime)}</span>` : ''}
${durText ? `<span>· ${durText}</span>` : ''}
```

新：
```js
${arrTime ? `<span>${escapeHtml(arrTime)}</span>` : ''}
${stop.recommended_duration_min ? `<span>· 推荐 ${stop.recommended_duration_min}min</span>` : (durText ? `<span>· ${durText}</span>` : '')}
```

`recommended_duration_min` 为 null/0 时 fallback 走旧的 `durText`（`arrival_time → leave_time` 差）。

### chip + variant compare UI 不动

variant_patches diff 仅看 `openshopid`，新字段不影响。

---

## 测试

### `tests/test_duration_table.py`

| 用例 | 断言 |
|---|---|
| 风景名胜 + 情侣 | 90 × 1.2 = 108 → 110 |
| 博物馆 + 商务 | 100 × 0.7 = 70 → 70 |
| 火锅 + 亲子 | 90 × 1.4 = 126 → 130 |
| 咖啡 + 银发 | 40 × 1.3 = 52 → 55 |
| 喷泉 + 独行 | 20 × 1.0 = 20 |
| 空 categories | fallback 60 × multiplier |
| 多关键词 categories（["景点", "公园"]）| 取首匹配 |
| 未知 traveler | multiplier = 1.0 fallback |

### `tests/test_scheduler.py`

| 用例 | 断言 |
|---|---|
| Happy 4 stop 情侣 | 起点 10:00, 午餐 in 11:30-12:30, 晚餐 in 18:00-19:00 |
| 上午景点拖时（博物馆 100×1.2=120min） | 午餐 arrival 仍 ≤ 12:30; 前一 stop duration 被压 ≥ -10% |
| 亲子早起（8:30） | 起点 = 8:30; 4 stops 全部 arrival 落在 21:00 前 |
| 商务节奏短 | 末位 arrival < 18:00 (快节奏不拖到晚) |
| 全 fallback POI（无 categories 命中） | base 60 × multiplier, schedule 仍能跑通 |

---

## 不在本 spec 范围

- LLM 估时长（spec 已否决）
- stop 数量自适应（保持现 4-5 stops 固定）
- 天气/客流动态调整
- recommended_duration_min ↔ leave_time 双向一致性维护（leave_time 只是后端 spacing 工具）
- 多日 trip 的 day_end_hard_cap 跨日逻辑（v1 单日 MVP）

---

## 风险与回滚

| 风险 | 缓解 |
|---|---|
| 餐点压缩前一个 stop 显得 AI 改行程不告知 | stop_rationale 多一句"为午餐节点压 ${prev} 到 ${pct}%" |
| 老 trip 缓存 stop 缺 recommended_duration_min | 前端 fallback 旧 durText；后端 schema default = 60 |
| schedule_day 算到极限仍不 fit | critic 报警 stop_count_ok = False，不阻塞流式 |
| traveler enum 未匹配 | duration multiplier = 1.0, day_start = DEFAULT |
| variant_routes diff 比较新字段不一致 | variant_patches 只比 openshopid，无影响（已验证）|

回滚：planner 调 schedule_day 是单点替换，回滚一行注释即恢复旧硬编码。
