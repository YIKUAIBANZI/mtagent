# Cluster-Aware Fallback Picking Fix Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `_synthesize_fallback_route` 在挑下一个 stop 时考虑"距离已挑 stops 的中心点"，避免把跨城 POI 塞进同一条路线。修完后 baseline snapshot 的 15 个 `cluster_ok` 全部 PASS（当前全 FAIL）。

**Architecture:** 外科手术式修改一个函数。在 `agents/planner.py:_synthesize_fallback_route` 的内层挑选循环加 **centroid-aware distance gate + 3 级 graceful degradation**（5km → 8km → 无限制），保证不引入新的"空 slot"。复用 `agents/anchor._haversine_km`。新增 1 个单元测试 + 重跑 baseline snapshot。

**Tech Stack:** Python 3.11, pytest, 复用已有 `_haversine_km`。无新依赖。

---

## Diagnosis Recap（来自 Explore agent 的根因报告）

`tests/test_route_quality_baseline.py:_intent_for` 不设 `anchor_lng/lat` → `candidate_pool.py:263-276` 空间预过滤被跳过 → 全城 POI 进入桶 → `_reorder_for_variant` (planner_instant.py:360-364) `low_queue` 分支把 star≥4.8 沉底，地理上分散的低星 POI 浮顶 → `_synthesize_fallback_route` (planner.py:727-733) 贪心挑第一个 category 匹配，**零空间检查** → 上海/low_queue 拉到 22.77km。

修法选了 (C) — 在挑选循环里加距离 gate，理由：
- 一个改动覆盖所有 3 个 variant
- 不动 `_reorder_for_variant`（避免影响 main 路径的星级排序意图）
- 不引入新概念（不发明 anchor），用已挑 stops 的运行中心点
- 配 3 级 graceful degradation，杜绝"修一个 bug 引入下一个"

不修法 (A)（在 `build_candidate_pool` 设合成 anchor）的原因：会改变所有调用路径包括 LLM 路径，scope 太大。
不修法 (B)（只动 `_reorder_for_variant`）的原因：深圳/main 7.46km、北京/main 7.46km 不是 low_queue 才炸，main 也炸。

---

## File Structure

| File | Responsibility |
|---|---|
| **Modify** `agents/planner.py` | `_synthesize_fallback_route` 内层挑选循环加 centroid guard。新增小 helper `_pick_near_centroid(slot, cluster, used, stops_so_far)`。 |
| **Modify** `tests/test_planner_fallback_must_visit.py` 或 新增 `tests/test_fallback_cluster_guard.py` | 1 个单元测试：合成 cluster = [近 POI in lunch slot, 远 POI in lunch slot]，断言 fallback 挑近的。判断：复用现有 must_visit 测试的 fixture 模式，但单独建文件更清晰（不污染 must_visit 主题）→ 新建文件。 |
| **Modify** `tests/snapshots/route_quality_baseline.json` | 重跑 baseline 后的新快照。15 个 `cluster_ok` 全 PASS，分数 7/7。 |

---

## Task 1: 实现 centroid guard + 单元测试

**Files:**
- Create: `tests/test_fallback_cluster_guard.py`
- Modify: `agents/planner.py` (`_synthesize_fallback_route`, ~line 720-735)

- [ ] **Step 1: 写失败的单元测试**

Create `tests/test_fallback_cluster_guard.py` with EXACTLY:

```python
"""Cluster-aware fallback picking — prevent fallback from selecting POIs
that would blow up the day's spatial spread."""
from __future__ import annotations

from datetime import time

import pytest

from agents.planner import _synthesize_fallback_route
from agents.tools import DaySlotSpec, DayTemplate
from dianping.schemas import POI


def _poi(sid: str, lat: float, lng: float, cats: list[str]) -> POI:
    return POI(
        openshopid=sid,
        name=sid,
        city="测试市",
        latitude=lat,
        longitude=lng,
        categories=cats,
    )


def _tmpl() -> DayTemplate:
    return DayTemplate(slots=[
        DaySlotSpec(name="上午景点", start=time(9, 0), end=time(12, 0),
                    category_pool=["景点"], is_meal=False,
                    min_stay_minutes=60, max_stay_minutes=180),
        DaySlotSpec(name="午饭", start=time(12, 0), end=time(13, 30),
                    category_pool=["美食"], is_meal=True,
                    min_stay_minutes=60, max_stay_minutes=90),
        DaySlotSpec(name="下午", start=time(13, 30), end=time(17, 0),
                    category_pool=["景点"], is_meal=False,
                    min_stay_minutes=60, max_stay_minutes=180),
    ])


def test_fallback_prefers_near_poi_when_far_one_listed_first():
    """合成场景: 第一个景点在 (22.54, 114.05). 午饭候选列表里, 远的 (22.65, 114.05, ~12km)
    排在近的 (22.545, 114.052, ~0.7km) 前面. 修复后 fallback 必须选近的."""
    anchor_poi = _poi("a", 22.5400, 114.0500, ["景点"])
    far_meal = _poi("far_meal", 22.6500, 114.0500, ["美食"])  # ~12km from anchor
    near_meal = _poi("near_meal", 22.5450, 114.0520, ["美食"])  # ~0.7km
    aft = _poi("c", 22.5410, 114.0510, ["景点"])

    # cluster order: anchor first (so it gets picked for 上午景点),
    # then far_meal BEFORE near_meal (this is the bug scenario)
    cluster = [anchor_poi, far_meal, near_meal, aft]

    days = _synthesize_fallback_route(
        templates=[_tmpl()],
        anchors=[("测试区", 0.0)],
        day_clusters=[cluster],
        intent=None,
    )
    assert len(days) == 1
    stop_names = [s.poi.name for s in days[0].stops]
    # 上午景点应该是 anchor (cluster[0])
    assert stop_names[0] == "a"
    # 午饭应该是 near_meal (距离 anchor < 5km), 而不是 far_meal (>5km)
    assert "near_meal" in stop_names, f"got {stop_names}; far_meal was picked"
    assert "far_meal" not in stop_names


def test_fallback_relaxes_to_any_when_no_near_candidate_exists():
    """合成场景: 只有远的 meal 候选. fallback 必须降级接受远的, 不能留空 slot."""
    anchor_poi = _poi("a", 22.5400, 114.0500, ["景点"])
    far_meal = _poi("far_meal", 22.6500, 114.0500, ["美食"])  # 12km, only meal option
    aft = _poi("c", 22.5410, 114.0510, ["景点"])

    cluster = [anchor_poi, far_meal, aft]

    days = _synthesize_fallback_route(
        templates=[_tmpl()],
        anchors=[("测试区", 0.0)],
        day_clusters=[cluster],
        intent=None,
    )
    stop_names = [s.poi.name for s in days[0].stops]
    # 必须仍然有 far_meal — 不能为了 cluster 让 slot 空
    assert "far_meal" in stop_names
    # 应该有 3 个 stop (不能因为距离 gate 而少给 stop)
    assert len(days[0].stops) == 3
```

- [ ] **Step 2: 跑测试确认 FAIL**

Run: `cd /Users/yikuaibanz1/Desktop/sth/mtagent && PYTHONPATH=. venv/bin/pytest tests/test_fallback_cluster_guard.py -v`
Expected: `test_fallback_prefers_near_poi_when_far_one_listed_first` FAIL — 因为当前 `_synthesize_fallback_route` 贪心挑第一个 category 匹配（=far_meal）。`test_fallback_relaxes_to_any_when_no_near_candidate_exists` 当前会 PASS（因为根本没 gate）但修复后也必须 PASS（gate 降级后接受远的）。

- [ ] **Step 3: 实现 centroid guard**

修改 `agents/planner.py`。

**a) 顶部 import 段（找到 `from agents.anchor import ...` 或最近的 anchor import；没有就追加）：**

```python
from agents.anchor import _haversine_km
```

如果文件还没 import `agents.anchor`，加在其他 agents.* import 之后。

**b) 在 `_synthesize_fallback_route` 函数定义之前（约 planner.py:647 前），新增小 helper：**

```python
# Cluster-aware fallback picking: 3 级距离 gate (5km → 8km → any)
# 保证不引入"空 slot"——降级到 any 永远能找到候选 (只要 category 匹配)
_FALLBACK_CLUSTER_TIERS_KM: tuple[float, ...] = (5.0, 8.0, float("inf"))


def _pick_near_centroid(
    slot,
    cluster: list[POI],
    used: set[str],
    stops_so_far: list[Stop],
) -> Optional[POI]:
    """Pick the first category-matching POI within distance tiers from the
    running centroid of stops_so_far. If stops_so_far is empty (this is the
    first stop), distance is not enforced.
    """
    if not stops_so_far:
        for p in cluster:
            if p.openshopid in used:
                continue
            if any(c in slot.category_pool for c in p.categories):
                return p
        return None

    cx = sum(s.poi.longitude for s in stops_so_far) / len(stops_so_far)
    cy = sum(s.poi.latitude for s in stops_so_far) / len(stops_so_far)
    for limit_km in _FALLBACK_CLUSTER_TIERS_KM:
        for p in cluster:
            if p.openshopid in used:
                continue
            if not any(c in slot.category_pool for c in p.categories):
                continue
            d = _haversine_km((cx, cy), (p.longitude, p.latitude))
            if d <= limit_km:
                return p
    return None
```

**c) 修改 `_synthesize_fallback_route` 内层挑选循环。** 找到这块：

```python
        # --- fill all slots (use pre-assignment or category-pool match) ---
        stops: list[Stop] = []
        for slot in tmpl.slots:
            if slot.optional:
                continue
            picked: Optional[POI] = slot_assignments.get(slot.name)
            if picked is None:
                for p in cluster:
                    if p.openshopid in used:
                        continue
                    if any(c in slot.category_pool for c in p.categories):
                        picked = p
                        break
            if picked is None:
                continue
            used.add(picked.openshopid)
            stops.append(
                Stop(
                    poi=picked,
                    ...
                )
            )
```

替换为：

```python
        # --- fill all slots (use pre-assignment or cluster-aware match) ---
        stops: list[Stop] = []
        for slot in tmpl.slots:
            if slot.optional:
                continue
            picked: Optional[POI] = slot_assignments.get(slot.name)
            if picked is None:
                picked = _pick_near_centroid(slot, cluster, used, stops)
            if picked is None:
                continue
            used.add(picked.openshopid)
            stops.append(
                Stop(
                    poi=picked,
                    slot=TimeSlot(name=slot.name, start=slot.start, end=slot.end),
                    arrival_time=slot.start,
                    leave_time=slot.end,
                    transport_to_next_minutes=30,
                )
            )
```

注意：must_visit pre-assignment 路径（`slot_assignments.get(slot.name)`）不变——用户明确指定的 POI 优先，不受距离 gate 限制。

- [ ] **Step 4: 跑单元测试确认 PASS**

Run: `cd /Users/yikuaibanz1/Desktop/sth/mtagent && PYTHONPATH=. venv/bin/pytest tests/test_fallback_cluster_guard.py -v`
Expected: 2 passed

- [ ] **Step 5: 跑全量测试确认无回归**

Run: `cd /Users/yikuaibanz1/Desktop/sth/mtagent && PYTHONPATH=. venv/bin/pytest tests/ -q --ignore=tests/test_user_profile_cleaning.py --ignore=tests/test_amap_client.py --ignore=tests/test_e2e_stub.py`
Expected: 376 passed (374 baseline + 2 new) — **除了** `tests/test_route_quality_baseline.py::test_route_quality_baseline_all_cities` 可能 FAIL，因为 snapshot 现在不再匹配预期。如果 FAIL，那是 Task 2 要处理的内容，不算 regression。

如果有其他测试 FAIL（不是 baseline），停下报 BLOCKED，描述 FAIL 的测试 + 错误。

- [ ] **Step 6: 提交**

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
git add agents/planner.py tests/test_fallback_cluster_guard.py
git commit -m "fix(planner): cluster-aware fallback picking with 3-tier distance gate"
```

**CRITICAL: `git add` ONLY 这 2 个文件。工作树还有 20+ 个无关 dirty 文件，绝不能 `git add .`。**

## Self-Review

- 单元测试覆盖 happy path（gate 起效）+ degradation（无近候选时不留空 slot）
- centroid 用经度/纬度算术平均（对小范围 OK，跨经线问题不在本场景）
- `_pick_near_centroid` 是无副作用纯函数，只读 cluster 和 stops_so_far
- must_visit 路径完全不动 — 用户指定的 POI 不被距离 gate 否决
- 3 级阈值用 `(5.0, 8.0, float("inf"))` 保证总能挑出（如果 category 匹配的话）

## Report Format

- **Status:** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- 单元测试输出（2 passed）
- 全量测试输出 — 报告 baseline test 是否 FAIL（预期 FAIL，Task 2 处理）
- `git show --stat HEAD` 输出
- 如果 baseline 之外有其他 FAIL，STOP 并报告

---

## Task 2: 重跑 baseline + 更新 snapshot

**Files:**
- Modify: `tests/snapshots/route_quality_baseline.json`

- [ ] **Step 1: 跑 baseline 看新结果**

Run: `cd /Users/yikuaibanz1/Desktop/sth/mtagent && PYTHONPATH=. venv/bin/pytest tests/test_route_quality_baseline.py -v -s 2>&1 | tail -30`

测试本身会自动重写 snapshot（看 baseline 测试 line 92-93 的 `_SNAPSHOT.write_text(...)`）。预期：测试 PASS（5 城 × 3 variant 全员 7/7），snapshot 文件自动覆盖。

如果测试 FAIL（不是预期）— 看 failure 消息：仍有 cluster_ok 超 5km 的城市/variant，说明 Task 1 的 centroid gate 没完全起效（可能 must_visit pre-assignment 把远 POI 锁住了，或 first stop 自身就在偏远区域）。报 DONE_WITH_CONCERNS，附 snapshot 内容，等待诊断。

- [ ] **Step 2: 检查 snapshot diff**

Run: `cd /Users/yikuaibanz1/Desktop/sth/mtagent && git diff tests/snapshots/route_quality_baseline.json | head -80`

预期变化：
- 所有 15 个 plan 的 `cluster_ok` 从 FAIL → PASS
- `score` 从 0.857 (6/7) → 1.0 (7/7)
- `failed_rules` 从 `["cluster_ok"]` → `[]`
- `details` 从有 cluster_ok detail → `{}`
- `stops` 应保持 4（如果掉到 3 表示降级 gate 反而让 slot 空了，需要回滚或诊断）

如果 `stops` 数量在某些 city/variant 下从 4 掉到 3，**这是 regression**，报 BLOCKED 并附 city 列表。

- [ ] **Step 3: 提交 snapshot 更新**

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
git add tests/snapshots/route_quality_baseline.json
git commit -m "test(validator): refresh snapshot — cluster_ok now PASS 15/15 after fallback fix"
```

- [ ] **Step 4: 跑诊断 CLI 看一个真实 trip 看效果**

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
LATEST=$(ls -t data/trips/*.json | head -1)
PYTHONPATH=. venv/bin/python scripts/validate_trip.py "$LATEST"
```

观察：cluster_ok 那行从 X 变 OK 了吗？（真实 trip 可能走 LLM 路径而非 fallback，所以可能没变化，但不算失败——这个 task 修的就是 fallback path）

## Report Format

- **Status:** DONE | DONE_WITH_CONCERNS | BLOCKED
- 新 snapshot 的 PASS/FAIL 统计：15/15 PASS? 哪些仍 FAIL？
- snapshot diff 的关键变化（贴 git diff 摘要）
- 任何 stops 数量回退的 regression
- CLI 输出片段（如果有变化）

---

## Self-Review (controller-level after both tasks)

**1. Spec coverage:**
- ✓ `_synthesize_fallback_route` 内层挑选循环加 centroid 距离 gate
- ✓ 3 级 graceful degradation 防止引入空 slot
- ✓ must_visit pre-assignment 路径不变（用户意图优先）
- ✓ 单元测试覆盖 happy + degradation 两路径
- ✓ baseline snapshot 自动重写并提交
- 部分覆盖：真实 LLM 路径的 stops 数量 bug（南昌 main 3 stops）— **不在本 plan scope**，是单独的后续 task，需要另开 plan 修 `plan_one_variant` 的"LLM 不够补齐"逻辑

**2. Placeholder scan:** 无 TODO / 无 "类似 Task N" / 所有代码块完整可粘贴 / 所有 bash 命令包含 expected output 描述。

**3. Type consistency:**
- `_pick_near_centroid` 签名：`(slot, cluster: list[POI], used: set[str], stops_so_far: list[Stop]) -> Optional[POI]` — 与 `_synthesize_fallback_route` 内已有变量名 `cluster`/`used`/`stops` 一致
- `Optional[POI]` 在 planner.py 顶部已 import（typing.Optional）— 复查 import 时确认
- `_haversine_km((lng, lat), (lng, lat))` 顺序与 anchor.py:152 docstring 一致
- `_FALLBACK_CLUSTER_TIERS_KM` 元组 — `float("inf")` 永远 ≥ 任何 km，保证最后一档兜底

---

## Execution Handoff

After Task 1 + Task 2 both green:

**Recommended next plan (out of scope here):** 修 `plan_one_variant` 的 LLM 路径：当 LLM 返回 stops 数 < goal_stops_by_pace(intent) 时，对剩余 slot 触发 fallback 补齐。这能解决你当面看到的"南昌 main 3 stops" bug。Diagnostic snapshot 已经能监控这个。
