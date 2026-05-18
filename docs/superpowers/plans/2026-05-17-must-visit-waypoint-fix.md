# Must-Visit Waypoint Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a user specifies multiple must-visit destinations (e.g., "我要去故宫还有长城"), all of them reliably appear in the generated itinerary — even when the LLM fallback is triggered.

**Architecture:** Two-layer fix. Layer 1: fix `_synthesize_fallback_route` to honor `must_visit` by pre-assigning those POIs to matching slots before filling the rest. Layer 2: inject explicit slot-to-POI mapping into the LLM prompt so the LLM doesn't need to "decide" which slot gets which must-visit POI — it just fills in the blanks.

**Tech Stack:** Python 3.11, Pydantic v2, Qwen LLM via OpenAI-compatible API, pytest for tests.

---

## Context (read before touching code)

### Why fallback happens

`plan_one_variant` (`agents/planner_instant.py`) calls `planner.compose_one_day(...)`. If that throws `PlannerLLMError`, the code calls `_synthesize_fallback_route` (`agents/planner.py:558`). This fallback iterates over slots and picks the FIRST POI whose `categories` intersects the slot's `category_pool`. It never checks `intent.must_visit`. Result: even though both 故宫 and 长城 are in `city_essential` with score=999, the fallback ignores them and picks arbitrary POIs.

### Why the LLM sometimes fails

The LLM receives `must_visit=["故宫","长城"]` and a 4-slot "一日" template (上午景点, 午饭, 下午, 晚饭). Two scenic POIs compete for two scenic slots. The LLM must also obey all other constraints (time windows, categories, diversity). It sometimes returns `"stops":[]` or raises a JSON parse error → `PlannerLLMError`.

### Key files

| File | Relevant lines | Role |
|---|---|---|
| `agents/planner.py` | 558–603 | `_synthesize_fallback_route` — ignore must_visit bug |
| `agents/planner.py` | 389–482 | `_build_one_day_payload` — LLM prompt builder |
| `agents/planner_instant.py` | 32–39 | Slot template definitions |
| `agents/candidate_pool.py` | 230–247 | must_visit already pushed to city_essential[0] w/ score=999 |
| `tests/test_planner_fallback_must_visit.py` | NEW | Tests for Fix A |
| `tests/test_planner_must_visit_slot_hint.py` | NEW | Tests for Fix B |

---

## Task 1: Fix `_synthesize_fallback_route` to honor must_visit (Fix A)

**Files:**
- Modify: `agents/planner.py:558-603`
- Create: `tests/test_planner_fallback_must_visit.py`

### What to change

Find the `_synthesize_fallback_route` function at line 558 of `agents/planner.py`. Its loop structure is:

```python
for d, (tmpl, anchor, cluster) in enumerate(zip(templates, anchors, day_clusters)):
    stops = []
    used: set[str] = set()
    for slot in tmpl.slots:
        if slot.optional:
            continue
        picked: Optional[POI] = None
        for p in cluster:
            if p.openshopid in used:
                continue
            if any(c in slot.category_pool for c in p.categories):
                picked = p
                break
        if picked:
            ...
```

The fix: before the slot loop, pre-assign must_visit POIs to the best-matching slot.

- [ ] **Step 1: Write the failing test**

Create `tests/test_planner_fallback_must_visit.py`:

```python
"""Test that _synthesize_fallback_route honors intent.must_visit."""
import pytest
from dianping.schemas import ParsedIntent, POI, EnrichedLabel
from agents.tools import DaySlotSpec, DayTemplate
from datetime import time


def _make_poi(openshopid, name, categories):
    return POI(
        openshopid=openshopid,
        name=name,
        city="北京",
        latitude=39.92,
        longitude=116.40,
        categories=categories,
        star=4.5,
        avgprice=80,
        business_hour="09:00-18:00",
    )


def _make_scenic_poi(oid, name):
    p = _make_poi(oid, name, ["旅游景点", "风景名胜"])
    p.enriched = EnrichedLabel(
        poi_role="city_essential",
        universal_level="high",
        manual_priority=999,
        min_stay_minutes=90,
        max_stay_minutes=180,
    )
    return p


def _make_restaurant_poi(oid, name):
    return _make_poi(oid, name, ["美食", "中餐厅"])


@pytest.fixture
def template():
    return DayTemplate(
        day_index=0,
        slots=[
            DaySlotSpec(name="上午景点", start=time(9,0), end=time(12,0),
                        category_pool=["休闲娱乐","旅游景点"], is_meal=False,
                        min_stay_minutes=60, max_stay_minutes=180),
            DaySlotSpec(name="午饭", start=time(12,0), end=time(13,30),
                        category_pool=["美食"], is_meal=True,
                        min_stay_minutes=60, max_stay_minutes=90),
            DaySlotSpec(name="下午", start=time(13,30), end=time(17,0),
                        category_pool=["休闲娱乐","旅游景点"], is_meal=False,
                        min_stay_minutes=90, max_stay_minutes=180),
            DaySlotSpec(name="晚饭", start=time(18,0), end=time(20,0),
                        category_pool=["美食"], is_meal=True,
                        min_stay_minutes=60, max_stay_minutes=120),
        ],
    )


def test_fallback_includes_all_must_visit(template):
    """_synthesize_fallback_route must assign must_visit POIs to matching slots."""
    from agents.planner import _synthesize_fallback_route

    gugong = _make_scenic_poi("poi_gugong", "故宫博物院")
    changcheng = _make_scenic_poi("poi_changcheng", "长城")
    restaurant = _make_restaurant_poi("poi_rest", "随机餐厅")
    other_scenic = _make_scenic_poi("poi_other", "颐和园")

    intent = ParsedIntent(
        city="北京",
        days=1,
        traveler_type="独行",
        must_visit=["故宫", "长城"],
        time_window="一日",
    )
    cluster = [gugong, changcheng, restaurant, other_scenic]

    days = _synthesize_fallback_route(
        templates=[template],
        anchors=[("故宫", 39.92, 116.40)],
        day_clusters=[cluster],
        intent=intent,
    )

    assert len(days) == 1
    stop_names = [s.poi.name for s in days[0].stops]
    assert "故宫博物院" in stop_names, f"故宫 missing from {stop_names}"
    assert "长城" in stop_names, f"长城 missing from {stop_names}"


def test_fallback_must_visit_with_no_match_in_cluster(template):
    """If a must_visit POI is not in cluster, fallback should not crash."""
    from agents.planner import _synthesize_fallback_route

    restaurant = _make_restaurant_poi("poi_rest", "随机餐厅")

    intent = ParsedIntent(
        city="北京",
        days=1,
        traveler_type="独行",
        must_visit=["故宫"],  # 故宫 NOT in cluster
        time_window="一日",
    )
    cluster = [restaurant]

    # Should not raise — just proceed with whatever is in cluster
    days = _synthesize_fallback_route(
        templates=[template],
        anchors=[("市中心", 39.92, 116.40)],
        day_clusters=[cluster],
        intent=intent,
    )
    assert len(days) == 1  # no crash
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
PYTHONPATH=. venv/bin/pytest tests/test_planner_fallback_must_visit.py -v
```

Expected: FAIL — `assert "长城" in stop_names`

- [ ] **Step 3: Modify `_synthesize_fallback_route` to pre-assign must_visit POIs**

In `agents/planner.py`, find `def _synthesize_fallback_route` (around line 558). Replace the inner slot-filling loop with this pattern:

```python
def _synthesize_fallback_route(
    templates: list[DayTemplate],
    anchors: list[tuple[str, float, float]],
    day_clusters: list[list[POI]],
    intent: ParsedIntent,
) -> list[DayPlan]:
    """Fallback route builder.

    v1.9.4: honors intent.must_visit by pre-assigning must_visit POIs
    to their best-matching slot before filling remaining slots normally.
    """
    must_visit_names: list[str] = list(getattr(intent, "must_visit", None) or [])
    days: list[DayPlan] = []

    for d, (tmpl, anchor, cluster) in enumerate(
        zip(templates, anchors, day_clusters)
    ):
        stops = []
        used: set[str] = set()

        # ── Phase 1: pre-assign must_visit POIs to best-matching slot ──
        # Build a slot index we can mutate
        available_slots = list(tmpl.slots)
        slot_assignments: dict[str, POI] = {}  # slot_name → POI

        for must_name in must_visit_names:
            # Find the must_visit POI in cluster (substring match)
            must_poi = next(
                (
                    p
                    for p in cluster
                    if must_name in p.name
                    or p.name in must_name
                    or any(must_name in c for c in (p.categories or []))
                ),
                None,
            )
            if must_poi is None or must_poi.openshopid in used:
                continue
            # Find the best-matching unoccupied slot
            # Prefer non-meal slots for scenic POIs, meal slots for food POIs
            is_food = any(
                kw in " ".join(must_poi.categories or [])
                for kw in ["美食", "餐", "food"]
            )
            best_slot = next(
                (
                    s
                    for s in available_slots
                    if s.name not in slot_assignments
                    and not s.optional
                    and s.is_meal == is_food
                ),
                None,
            ) or next(
                (
                    s
                    for s in available_slots
                    if s.name not in slot_assignments and not s.optional
                ),
                None,
            )
            if best_slot:
                slot_assignments[best_slot.name] = must_poi
                used.add(must_poi.openshopid)

        # ── Phase 2: fill remaining slots with best-match POI ──
        for slot in available_slots:
            if slot.optional:
                continue
            if slot.name in slot_assignments:
                picked = slot_assignments[slot.name]
            else:
                picked = None
                for p in cluster:
                    if p.openshopid in used:
                        continue
                    if any(c in slot.category_pool for c in p.categories):
                        picked = p
                        break
            if picked is None:
                continue
            used.add(picked.openshopid)
            from datetime import datetime

            arr = datetime.combine(datetime.today(), slot.start)
            lv = datetime.combine(
                datetime.today(),
                slot.end,
            )
            from agents.tools import DayStop

            stops.append(
                DayStop(
                    poi=picked,
                    slot=slot,
                    arrival_time=arr,
                    leave_time=lv,
                )
            )

        days.append(
            DayPlan(
                day_index=d,
                anchor_district=anchor[0],
                stops=stops,
            )
        )
    return days
```

> **Note**: The existing `_synthesize_fallback_route` uses `DayStop` and `DayPlan`. Read the existing implementation carefully to ensure the import structure and field names match (check `agents/tools.py` and `dianping/schemas.py`).

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_planner_fallback_must_visit.py -v
```

Expected: 2 PASS

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
PYTHONPATH=. venv/bin/pytest tests/ -q --ignore=tests/test_user_profile_cleaning.py 2>&1 | tail -6
```

Expected: 346+ passed, 0 new failures (2 known flaky: test_amap_client + test_e2e_stub).

- [ ] **Step 6: Commit**

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
git add agents/planner.py tests/test_planner_fallback_must_visit.py
git commit -m "fix(v1.9.4): fallback route builder honors intent.must_visit"
```

---

## Task 2: Inject slot-to-POI hint into LLM prompt for must_visit (Fix B)

**Files:**
- Modify: `agents/planner.py:389-482` (`_build_one_day_payload`)
- Create: `tests/test_planner_must_visit_slot_hint.py`

### What to change

`_build_one_day_payload` builds the user message string sent to the LLM. Add a section that maps each must_visit POI to its recommended slot AND provides the `poi_openshopid` so the LLM doesn't have to "choose" — it just confirms.

The mapping logic: for each must_visit name, find the matching POI in `day_cluster_pois` (same substring match), then pick the best-matching slot from the template.

- [ ] **Step 1: Write the failing test**

Create `tests/test_planner_must_visit_slot_hint.py`:

```python
"""Test that _build_one_day_payload injects slot hints for must_visit POIs."""
import json
import pytest
from datetime import time
from dianping.schemas import ParsedIntent, POI, EnrichedLabel
from agents.tools import DaySlotSpec, DayTemplate


def _slot_template():
    return DayTemplate(
        day_index=0,
        slots=[
            DaySlotSpec(name="上午景点", start=time(9,0), end=time(12,0),
                        category_pool=["休闲娱乐","旅游景点"], is_meal=False,
                        min_stay_minutes=60, max_stay_minutes=180),
            DaySlotSpec(name="午饭", start=time(12,0), end=time(13,30),
                        category_pool=["美食"], is_meal=True,
                        min_stay_minutes=60, max_stay_minutes=90),
            DaySlotSpec(name="下午", start=time(13,30), end=time(17,0),
                        category_pool=["休闲娱乐","旅游景点"], is_meal=False,
                        min_stay_minutes=90, max_stay_minutes=180),
            DaySlotSpec(name="晚饭", start=time(18,0), end=time(20,0),
                        category_pool=["美食"], is_meal=True,
                        min_stay_minutes=60, max_stay_minutes=120),
        ],
    )


def _make_scenic_poi(oid, name):
    p = POI(openshopid=oid, name=name, city="北京",
            latitude=39.92, longitude=116.40,
            categories=["旅游景点"], star=4.8, avgprice=0,
            business_hour="09:00-18:00")
    p.enriched = EnrichedLabel(poi_role="city_essential", universal_level="high",
                               manual_priority=999, min_stay_minutes=90, max_stay_minutes=180)
    return p


def test_payload_contains_slot_hint_for_must_visit():
    """When must_visit has 2 items, payload _instruction contains slot pre-assignment."""
    from agents.planner import Planner

    planner = Planner(client=None, llm_call=None, llm_call_stream=None)
    intent = ParsedIntent(
        city="北京", days=1, traveler_type="独行",
        must_visit=["故宫", "长城"], time_window="一日",
    )
    gugong = _make_scenic_poi("oid_gugong", "故宫博物院")
    changcheng = _make_scenic_poi("oid_changcheng", "长城")
    other = _make_scenic_poi("oid_other", "颐和园")

    payload_str = planner._build_one_day_payload(
        day_idx=0,
        intent=intent,
        template=_slot_template(),
        anchor=("故宫", 39.92, 116.40),
        day_cluster_pois=[gugong, changcheng, other],
    )
    payload = json.loads(payload_str)
    instruction = payload["_instruction"]

    # Should contain explicit slot assignment for both must_visit POIs
    assert "故宫" in instruction, f"故宫 hint missing from instruction: {instruction[:300]}"
    assert "长城" in instruction or "oid_changcheng" in instruction, \
        f"长城 hint missing from instruction: {instruction[:300]}"
    assert "上午景点" in instruction or "下午" in instruction, \
        "Slot names should appear in must_visit hint"


def test_payload_no_hint_when_must_visit_empty():
    """When must_visit is empty, no slot hint section is added."""
    from agents.planner import Planner

    planner = Planner(client=None, llm_call=None, llm_call_stream=None)
    intent = ParsedIntent(
        city="北京", days=1, traveler_type="独行",
        must_visit=[], time_window="一日",
    )
    scenic = _make_scenic_poi("oid_a", "颐和园")

    payload_str = planner._build_one_day_payload(
        day_idx=0, intent=intent,
        template=_slot_template(),
        anchor=("市中心", 39.92, 116.40),
        day_cluster_pois=[scenic],
    )
    payload = json.loads(payload_str)
    # No "硬约束" must_visit hint injected
    assert "必须使用以下" not in payload["_instruction"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_planner_must_visit_slot_hint.py -v
```

Expected: FAIL — `assert "故宫" in instruction`

- [ ] **Step 3: Add slot-hint builder helper and inject into `_build_one_day_payload`**

In `agents/planner.py`, add this helper BEFORE `_build_one_day_payload`:

```python
def _build_must_visit_slot_hints(
    must_visit: list[str],
    day_cluster_pois: list,
    template,
) -> str:
    """Returns a compact LLM hint string pre-assigning must_visit POIs to slots.

    Example output:
      "故宫→上午景点(poi_openshopid=oid_gugong); 长城→下午(poi_openshopid=oid_changcheng)"

    If a must_visit name has no matching POI in cluster, it's omitted (no hallucination).
    """
    if not must_visit:
        return ""

    hints = []
    used_slots: set[str] = set()
    used_oids: set[str] = set()

    # Separate scenic slots (is_meal=False) from meal slots
    scenic_slots = [s for s in template.slots if not s.is_meal and not s.optional]
    meal_slots = [s for s in template.slots if s.is_meal and not s.optional]

    for must_name in must_visit:
        # Find matching POI (substring match)
        poi = next(
            (
                p
                for p in day_cluster_pois
                if p.openshopid not in used_oids
                and (must_name in p.name or p.name in must_name)
            ),
            None,
        )
        if poi is None:
            continue

        # Determine if food or scenic
        is_food = any(
            kw in " ".join(poi.categories or [])
            for kw in ["美食", "餐", "food"]
        )
        slot_pool = meal_slots if is_food else scenic_slots

        # Pick first available slot
        slot = next(
            (s for s in slot_pool if s.name not in used_slots),
            None,
        )
        if slot is None:
            continue

        used_slots.add(slot.name)
        used_oids.add(poi.openshopid)
        hints.append(
            f"{must_name}→{slot.name}(poi_openshopid={poi.openshopid}, name={poi.name})"
        )

    if not hints:
        return ""

    return (
        "【硬约束·必须遵守】以下 must_visit 地点已预分配到指定 slot，"
        "必须使用这些 poi_openshopid，不得替换或省略：\n"
        + "; ".join(hints)
        + "。其余 slot 从 candidates 自由选。"
    )
```

Then in `_build_one_day_payload`, insert the hint BEFORE the existing must_visit hardconstraint in `_instruction`. Find this line in the existing instruction string:

```python
+ (
    f"【硬约束】intent.must_visit={intent.must_visit}，"
    ...
)
```

Replace it with:

```python
+ _build_must_visit_slot_hints(
    must_visit=list(intent.must_visit or []),
    day_cluster_pois=day_cluster_pois,
    template=template,
)
```

(Remove the old `【硬约束】intent.must_visit=...` block — the new helper produces a better, more specific hint.)

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_planner_must_visit_slot_hint.py -v
```

Expected: 2 PASS

- [ ] **Step 5: Run full test suite**

```bash
PYTHONPATH=. venv/bin/pytest tests/ -q --ignore=tests/test_user_profile_cleaning.py 2>&1 | tail -6
```

Expected: 346+ passed, 0 new failures.

- [ ] **Step 6: Commit**

```bash
git add agents/planner.py tests/test_planner_must_visit_slot_hint.py
git commit -m "feat(v1.9.4): inject slot-to-POI mapping hint for must_visit into LLM prompt"
```

---

## Task 3: E2E verification

**Files:**
- No new files. Verify against running server.

- [ ] **Step 1: Restart services**

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
pkill -9 -f "uvicorn" 2>/dev/null; sleep 1
PYTHONPATH=. venv/bin/uvicorn dianping.mock_server:mock_app --host 127.0.0.1 --port 9192 &
sleep 1
set -a && source .env && set +a && unset MTAGENT_AMAP_DISABLED
PYTHONPATH=. venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 9191 &
sleep 2 && echo "ready"
```

- [ ] **Step 2: Test must_visit with 2 distant waypoints**

```bash
curl -s --max-time 50 -X POST http://127.0.0.1:9191/api/plan/stream \
  -H "Content-Type: application/json" \
  -d '{"free_text":"明天我要去北京转转 我要去故宫还有长城然后我要吃那个北京烤鸭"}' \
  --no-buffer 2>&1 | grep "stop_names\|has_fallback\|trip.complete"
```

Expected:
- All 3 variants have `has_fallback: false` (LLM succeeded)
- `stop_names` for each variant contains both "故宫" and "长城" (or their POI names)
- `trip.complete` appears

- [ ] **Step 3: Test must_visit with single waypoint (regression check)**

```bash
curl -s --max-time 40 -X POST http://127.0.0.1:9191/api/plan/stream \
  -H "Content-Type: application/json" \
  -d '{"free_text":"明天去上海外滩走走"}' \
  --no-buffer 2>&1 | grep "stop_names\|has_fallback\|trip.complete"
```

Expected: `trip.complete` appears, 外滩 or related POI in stop_names, no crash.

- [ ] **Step 4: Final baseline check**

```bash
PYTHONPATH=. venv/bin/pytest tests/ -q --ignore=tests/test_user_profile_cleaning.py 2>&1 | tail -4
```

Expected: 346+ passed, 2 known flaky.

- [ ] **Step 5: Save session**

```
/save-session
```

---

## Invariants (do NOT break these)

- `adjust.*` SSE event names stay unchanged
- `refine.*` SSE event names stay unchanged
- `_stream_adjust_events` helper signature unchanged
- `Refiner` failure always returns `RefineAction(chat_reply=...)`, never raises
- test baseline: 346 passed + 2 known flaky (`test_amap_client` + `test_e2e_stub`)
