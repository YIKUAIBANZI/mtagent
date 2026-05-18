# v1.9 Stage 1: 数据 + 推荐 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 解决 v1.8 e2e 暴露的"锚点半径内 POI 池稀疏"问题, 让 Scene A 万象天地 / Scene B 上海中转 的 stops 数从 1-2 个涨到 4 个, 同时清理 EnrichedLabel 脏点, 抽出 tag_mapping 数据化.

**Architecture:** 三步走 — (1) 集成 `anchor.fetch_around` 进 candidate_pool, 让无 enriched 的高德 POI 也能进 4 桶 (按 categories 推 poi_role); (2) 写 audit 脚本扫描脏点 (城墙=美食 等), LLM 重打标红 POI; (3) 把硬编码的 INTEREST_TO_TAG 抽到 `data/tag_mapping.json`, 加 review_tag → planning_tag 反向归纳.

**Tech Stack:** Python 3.11 + pydantic + httpx + 高德 v3 around (已验) + qwen-plus (脏点重打) + 既有 4 桶候选池.

**Spec source:** `docs/superpowers/specs/2026-05-14-v19-data-recommend-profile-adjust.md` §Stage 1

**Baseline:** main HEAD `7cb5acc` (v1.8 + Track A 修复). 测试 223 passed + 1 known flaky.

**关键不变量 (不能违反):**
- 223 baseline 测试不破
- ParsedIntent 老 3 必填字段不动
- v1.6 多日 / v1.7 instant / v1.8 anchor 三条路径不破
- score_poi 不依赖 reviewCount/avgprice (amap 数据局限)
- "终南山古楼观钟楼" demote 不能回弹

---

## File Structure

**新建文件 (7 个):**

| 文件 | 责任 |
|---|---|
| `agents/tag_mapping.py` | TagMapping pydantic + load + expand_user_signals |
| `data/tag_mapping.json` | user_interest_to_planning_tags + user_constraints_to_risk_tags + review_tag 映射 |
| `scripts/audit_enriched.py` | 扫描 mock_dianping POI, 输出标红清单 |
| `scripts/refix_enriched.py` | LLM 重打标红 POI, patch enriched_labels.json |
| `tests/test_tag_mapping.py` | tag_mapping 加载 + 映射验证 |
| `tests/test_planner_instant_v19_amap_pool.py` | fetch_around 集成验证 |
| `tests/test_enriched_audit.py` | audit 规则单测 |

**修改文件 (3 个):**

| 文件 | 改动 |
|---|---|
| `agents/candidate_pool.py` | (a) score_poi 改用 tag_mapping; (b) _bucket_of 加 _infer_role_from_categories fallback; (c) build_candidate_pool 接受 amap_pois 参数 |
| `agents/planner_instant.py` | plan_one_variant 在 build_candidate_pool 之前 await fetch_around 拉锚点周边 |
| `data/poi_enriched_labels.json` | (refix 脚本运行后) patch 脏点 |

---

## 任务拆分总览

| # | 任务 | 估时 | 依赖 |
|---|---|---|---|
| 1 | `_infer_role_from_categories` helper + 单测 | 20min | - |
| 2 | `build_candidate_pool` 接受 amap_pois 参数 + 无 enriched POI fallback 评分 + 单测 | 40min | 1 |
| 3 | `planner_instant.plan_one_variant` 集成 fetch_around + 单测 | 40min | 2 |
| 4 | `data/tag_mapping.json` 文件落地 + Loader (`agents/tag_mapping.py`) + 单测 | 30min | - |
| 5 | `candidate_pool.score_poi` 用 tag_mapping (重构, 不破老测试) + 单测 | 30min | 4 |
| 6 | `scripts/audit_enriched.py` 规则扫描 + 单测 | 45min | - |
| 7 | `scripts/refix_enriched.py` LLM 重打 (含 dry-run 模式) | 1h | 6 |
| 8 | 跑一次完整 refix, 提交 patch (data/*.json) | 30min | 7 |
| 9 | 浏览器 e2e 再验 Scene A/B/C/D + 收尾 | 30min | 3,8 |

**总计 ~5.5h**

---

## Task 1: `_infer_role_from_categories` Helper

**Files:**
- Modify: `agents/candidate_pool.py` (加新 helper, ~10 行)
- Test: `tests/test_infer_role.py` (NEW)

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_infer_role.py`:

```python
"""v1.9 _infer_role_from_categories: 给无 enriched POI 兜底 poi_role."""

from agents.candidate_pool import _infer_role_from_categories


def test_meal_for_food_categories():
    assert _infer_role_from_categories(["美食"]) == "meal"
    assert _infer_role_from_categories(["美食", "本帮菜"]) == "meal"


def test_city_essential_for_landmark():
    assert _infer_role_from_categories(["景点"]) == "city_essential"
    assert _infer_role_from_categories(["历史文化", "景点"]) == "city_essential"


def test_connector_for_shopping_and_leisure():
    assert _infer_role_from_categories(["购物"]) == "connector"
    assert _infer_role_from_categories(["休闲娱乐"]) == "connector"


def test_fallback_when_empty_or_unknown():
    assert _infer_role_from_categories([]) == "fallback"
    assert _infer_role_from_categories(["不存在分类"]) == "fallback"
    assert _infer_role_from_categories(None) == "fallback"  # type: ignore
```

- [ ] **Step 2: Run test, 验证 FAIL**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_infer_role.py -v
```
Expected: ImportError 或 4 FAIL `_infer_role_from_categories` 不存在

- [ ] **Step 3: 实现 `_infer_role_from_categories`**

在 `agents/candidate_pool.py` 末尾加 (跟 `_bucket_of` 同级):

```python
def _infer_role_from_categories(categories: Optional[list[str]]) -> str:
    """v1.9: 给无 enriched 的 POI 按 categories 兜底 poi_role.

    用于高德 fetch_around 返回的 POI (没经过 mock_dianping enriched 流程).
    """
    if not categories:
        return "fallback"
    cats = " ".join(categories)
    if "美食" in cats:
        return "meal"
    if "景点" in cats or "历史文化" in cats:
        return "city_essential"
    if "购物" in cats or "休闲娱乐" in cats:
        return "connector"
    return "fallback"
```

- [ ] **Step 4: Run test, 验证 PASS**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_infer_role.py -v
```
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add agents/candidate_pool.py tests/test_infer_role.py
git commit -m "feat(v1.9): _infer_role_from_categories 给无 enriched POI 兜底"
```

---

## Task 2: `build_candidate_pool` 接受 amap_pois

**Files:**
- Modify: `agents/candidate_pool.py:_bucket_of` + `build_candidate_pool`
- Test: `tests/test_build_pool_v19_amap.py` (NEW)

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_build_pool_v19_amap.py`:

```python
"""v1.9: build_candidate_pool 接受 amap POI (无 enriched) 加入桶."""

from agents.candidate_pool import build_candidate_pool
from dianping.schemas import POI, EnrichedLabel, ParsedIntent


def _local_poi(name, openshopid, lat, lng, role="city_essential", priority=80):
    p = POI(
        openshopid=openshopid,
        name=name,
        city="深圳",
        latitude=lat,
        longitude=lng,
        categories=["景点"],
        avgprice=100,
        star=4.5,
        business_hour="09:00-21:00",
    )
    p.enriched = EnrichedLabel(
        poi_role=role, manual_priority=priority, city_zone="福田"
    )
    return p


def _amap_poi(name, openshopid, lat, lng, categories):
    """高德来的 POI: 无 enriched."""
    return POI(
        openshopid=openshopid,
        name=name,
        city="深圳",
        latitude=lat,
        longitude=lng,
        categories=categories,
        avgprice=0,
        star=0,
        business_hour="",
    )


def _intent(**kw):
    d = dict(
        city="深圳",
        days=1,
        traveler_type="情侣",
        anchor_lat=22.541,
        anchor_lng=114.057,
        anchor_radius_km=3.0,
    )
    d.update(kw)
    return ParsedIntent(**d)


def test_amap_poi_with_food_categories_enters_meal_bucket():
    pois = [
        _local_poi("钟楼景区", "id_l", 22.541, 114.057),
        _amap_poi("老孙家泡馍(高德)", "amap_food_1", 22.542, 114.058, ["美食"]),
    ]
    pool = build_candidate_pool(pois=pois, intent=_intent(), variant="main")
    meal_names = [p.name for p in pool.meal]
    assert "老孙家泡馍(高德)" in meal_names


def test_amap_poi_with_landmark_enters_city_essential_bucket():
    pois = [
        _amap_poi("深圳书城(高德)", "amap_landmark_1", 22.541, 114.057, ["景点"]),
    ]
    pool = build_candidate_pool(pois=pois, intent=_intent(), variant="main")
    ce_names = [p.name for p in pool.city_essential]
    assert "深圳书城(高德)" in ce_names


def test_local_poi_priority_over_amap_in_same_bucket():
    """本地 POI 有 enriched (高 manual_priority), 应排 amap POI 之前."""
    pois = [
        _amap_poi("amap-A", "amap_1", 22.541, 114.057, ["景点"]),
        _local_poi("local-A", "id_l", 22.542, 114.058, "city_essential", 95),
    ]
    pool = build_candidate_pool(pois=pois, intent=_intent(), variant="main")
    assert pool.city_essential[0].name == "local-A"


def test_amap_poi_with_unknown_categories_excluded_from_main_buckets():
    """fallback 角色不进任何桶 (v1.7 不变量保持)."""
    pois = [
        _amap_poi("未知分类", "amap_x", 22.541, 114.057, ["其它"]),
    ]
    pool = build_candidate_pool(pois=pois, intent=_intent(), variant="main")
    all_names = [
        p.name
        for bucket in (
            pool.city_essential,
            pool.persona_preferred,
            pool.meal,
            pool.connector,
        )
        for p in bucket
    ]
    assert "未知分类" not in all_names
```

- [ ] **Step 2: Run test, 验证 FAIL**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_build_pool_v19_amap.py -v
```
Expected: 4 FAIL (无 enriched POI 当前直接 skip)

- [ ] **Step 3: 改 `_bucket_of` 函数**

找 `agents/candidate_pool.py` 中 `_bucket_of` 函数, 替换:

```python
def _bucket_of(poi: POI) -> Optional[str]:
    """Return poi_role bucket name, or None if no enriched + categories 也推不出.

    v1.9: 无 enriched 时按 categories 兜底 (高德 around POI 用).
    """
    if poi.enriched is not None:
        return poi.enriched.poi_role
    # v1.9 fallback: 按 categories 推 poi_role
    role = _infer_role_from_categories(poi.categories)
    return role if role != "fallback" else None
```

- [ ] **Step 4: Run test, 验证 PASS**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_build_pool_v19_amap.py -v
```
Expected: 4 PASS

- [ ] **Step 5: 老 v1.7 / v1.8 候选池测试不破**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_candidate_pool_v17.py tests/test_candidate_pool_v18_anchor.py -v
```
Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
git add agents/candidate_pool.py tests/test_build_pool_v19_amap.py
git commit -m "feat(v1.9): build_candidate_pool 兼容无 enriched 的高德 POI"
```

---

## Task 3: `planner_instant.plan_one_variant` 集成 `fetch_around`

**Files:**
- Modify: `agents/planner_instant.py:plan_one_variant`
- Test: `tests/test_planner_instant_v19_amap_pool.py` (NEW)

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_planner_instant_v19_amap_pool.py`:

```python
"""v1.9: planner_instant 在锚点模式下拉高德 around POI 合进 pool."""

from unittest.mock import AsyncMock, patch

import pytest

from agents.planner_instant import plan_one_variant
from dianping.schemas import POI, EnrichedLabel, ParsedIntent


def _make_poi(name, openshopid, lat, lng, categories=None):
    p = POI(
        openshopid=openshopid,
        name=name,
        city="深圳",
        latitude=lat,
        longitude=lng,
        categories=categories or ["景点"],
        avgprice=100,
        star=4.5,
        business_hour="09:00-21:00",
    )
    p.enriched = EnrichedLabel(
        poi_role="city_essential", manual_priority=80, city_zone="福田"
    )
    return p


@pytest.mark.asyncio
async def test_plan_one_variant_calls_fetch_around_when_anchor_set(monkeypatch):
    """anchor_lng/lat 已设 + trip_mode=anchor_explore → 应调用 fetch_around."""
    intent = ParsedIntent(
        city="深圳",
        days=1,
        traveler_type="情侣",
        time_window="一日",
        trip_mode="anchor_explore",
        anchor_lng=114.057,
        anchor_lat=22.541,
        anchor_radius_km=3.0,
    )
    local_pois = [_make_poi("local-A", "id_l", 22.541, 114.058)]

    from agents.anchor import AroundPOI

    fake_around = [
        AroundPOI(
            name="高德新 POI",
            lng=114.060,
            lat=22.540,
            typecode="050000",
            distance_m=300,
            address="...",
        )
    ]
    fetch_mock = AsyncMock(return_value=fake_around)

    captured = {"called": False, "pool_size": 0}

    class _FakePlanner:
        async def compose_one_day(
            self,
            *,
            day_idx,
            intent,
            template,
            anchor,
            day_cluster_pois,
            amap,
            on_partial=None,
        ):
            captured["pool_size"] = len(day_cluster_pois)
            from dianping.schemas import DayPlan

            return (
                day_idx,
                DayPlan(day_index=0, anchor_district=anchor[0], stops=[]),
                [],
            )

    async def _no_transit(*a, **kw):
        return 0, []

    monkeypatch.setattr("api.routes._compute_day_transits", _no_transit)
    monkeypatch.setattr("agents.anchor.fetch_around", fetch_mock)

    class _FakeAmap:
        pass

    try:
        await plan_one_variant(
            intent=intent,
            variant="main",
            planner=_FakePlanner(),
            amap=_FakeAmap(),
            pois=local_pois,
        )
    except Exception:
        pass

    fetch_mock.assert_awaited_once()
    # 合并后 pool ≥ 本地 1 + 高德 1
    assert captured["pool_size"] >= 1  # 至少本地保留, 高德可能因 _bucket_of 决策进/不进


@pytest.mark.asyncio
async def test_plan_one_variant_skips_fetch_around_when_no_anchor(monkeypatch):
    """没设 anchor → 不调用 fetch_around (兼容 v1.7 老路径)."""
    intent = ParsedIntent(
        city="深圳",
        days=1,
        traveler_type="情侣",
        time_window="一日",
        # 无 anchor_lng/lat
    )
    local_pois = [_make_poi("local-A", "id_l", 22.541, 114.058)]
    fetch_mock = AsyncMock(return_value=[])

    class _FakePlanner:
        async def compose_one_day(self, **kw):
            from dianping.schemas import DayPlan

            return 0, DayPlan(day_index=0, anchor_district="", stops=[]), []

    async def _no_transit(*a, **kw):
        return 0, []

    monkeypatch.setattr("api.routes._compute_day_transits", _no_transit)
    monkeypatch.setattr("agents.anchor.fetch_around", fetch_mock)

    class _FakeAmap:
        pass

    try:
        await plan_one_variant(
            intent=intent,
            variant="main",
            planner=_FakePlanner(),
            amap=_FakeAmap(),
            pois=local_pois,
        )
    except Exception:
        pass

    fetch_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_plan_one_variant_layover_eat_uses_food_types(monkeypatch):
    """layover_eat 模式 fetch_around 应带 types 含 050000 (餐饮)."""
    intent = ParsedIntent(
        city="上海",
        days=1,
        traveler_type="独行",
        time_window="一日",
        trip_mode="layover_eat",
        anchor_lng=121.456,
        anchor_lat=31.249,
        anchor_radius_km=3.0,
    )
    captured_types = {"types": None}

    async def _fake_fetch(lng, lat, radius_m, types="050000|060000|080000|110000", limit=50):
        captured_types["types"] = types
        return []

    monkeypatch.setattr("agents.anchor.fetch_around", _fake_fetch)

    class _FakePlanner:
        async def compose_one_day(self, **kw):
            from dianping.schemas import DayPlan

            return 0, DayPlan(day_index=0, anchor_district="", stops=[]), []

    async def _no_transit(*a, **kw):
        return 0, []

    monkeypatch.setattr("api.routes._compute_day_transits", _no_transit)

    class _FakeAmap:
        pass

    try:
        await plan_one_variant(
            intent=intent,
            variant="main",
            planner=_FakePlanner(),
            amap=_FakeAmap(),
            pois=[],
        )
    except Exception:
        pass

    assert captured_types["types"] is not None
    assert "050000" in captured_types["types"]
```

- [ ] **Step 2: Run test, 验证 FAIL**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_planner_instant_v19_amap_pool.py -v
```
Expected: 3 FAIL (fetch_around 没被调用 / 类型没传)

- [ ] **Step 3: 改 `plan_one_variant`**

在 `agents/planner_instant.py:plan_one_variant` 函数体最开头 (template 之前) 加:

```python
    # v1.9: anchor 模式下拉高德周边 POI 合进本地池 (扩 pool)
    if (
        intent.anchor_lng is not None
        and intent.anchor_lat is not None
        and intent.trip_mode in ("anchor_explore", "layover_eat", "layover_explore")
    ):
        from agents.anchor import (
            AnchorResolution,
            fetch_around,
            merge_with_local_pool,
        )

        # types: layover_eat 偏餐饮, 其它用全 4 类
        types = (
            "050000"
            if intent.trip_mode == "layover_eat"
            else "050000|060000|080000|110000"
        )
        radius_m = int((intent.anchor_radius_km or 3.0) * 1000)
        try:
            around = await fetch_around(
                lng=intent.anchor_lng,
                lat=intent.anchor_lat,
                radius_m=radius_m,
                types=types,
                limit=50,
            )
        except Exception:
            around = []
        if around:
            anchor_obj = AnchorResolution(
                text=intent.start_location_text or "",
                name=intent.anchor_resolved_name or "",
                lng=intent.anchor_lng,
                lat=intent.anchor_lat,
                adcode="",
                formatted_address="",
                confidence="medium",
            )
            pois = merge_with_local_pool(
                amap_pois=around,
                local_pois=pois,
                anchor=anchor_obj,
                radius_m=radius_m,
            )
```

注意: 这段必须在 `template = make_instant_template(...)` 之前, 因为 pois 变量后续被 flatten_candidate_pool 用.

- [ ] **Step 4: Run test, 验证 PASS**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_planner_instant_v19_amap_pool.py -v
```
Expected: 3 PASS

- [ ] **Step 5: 老路径回归**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_planner_instant_v17.py tests/test_planner_instant_v18.py tests/test_sse_instant_v17.py -v
```
Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
git add agents/planner_instant.py tests/test_planner_instant_v19_amap_pool.py
git commit -m "feat(v1.9): planner_instant 集成 fetch_around 扩 pool"
```

---

## Task 4: `data/tag_mapping.json` + `agents/tag_mapping.py`

**Files:**
- Create: `data/tag_mapping.json`
- Create: `agents/tag_mapping.py`
- Test: `tests/test_tag_mapping.py` (NEW)

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_tag_mapping.py`:

```python
"""v1.9 tag_mapping: 用户兴趣/约束 → planning_tags / risk_tags 映射."""

from agents.tag_mapping import TagMapping, expand_user_signals, load_tag_mapping
from dianping.schemas import ParsedIntent


def _intent(**kw):
    d = dict(city="深圳", days=1, traveler_type="情侣")
    d.update(kw)
    return ParsedIntent(**d)


def test_load_tag_mapping_returns_pydantic_model():
    m = load_tag_mapping()
    assert isinstance(m, TagMapping)
    assert "拍照" in m.user_interest_to_planning_tags
    assert "photo_friendly" in m.user_interest_to_planning_tags["拍照"]


def test_expand_user_signals_with_photo_interest():
    intent = _intent(interests=["拍照"])
    pos, neg = expand_user_signals(intent)
    assert "photo_friendly" in pos
    assert neg == set()


def test_expand_user_signals_with_avoid_queue_constraint():
    intent = _intent(constraints={"avoid_queue": True})
    pos, neg = expand_user_signals(intent)
    assert "queue_heavy" in neg


def test_expand_user_signals_combines_legacy_preferences():
    """v1.6 老字段 preferences 也要映射."""
    intent = _intent(preferences=["美食"])
    pos, neg = expand_user_signals(intent)
    assert "food_quality" in pos or "local_food" in pos


def test_expand_user_signals_returns_empty_when_no_signals():
    intent = _intent()
    pos, neg = expand_user_signals(intent)
    assert pos == set()
    assert neg == set()
```

- [ ] **Step 2: Run test, 验证 FAIL**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_tag_mapping.py -v
```
Expected: ImportError "agents.tag_mapping"

- [ ] **Step 3: 创建 `data/tag_mapping.json`**

```bash
cat > data/tag_mapping.json << 'JSONEOF'
{
  "user_interest_to_planning_tags": {
    "拍照": ["photo_friendly", "citywalk_friendly"],
    "出片": ["photo_friendly"],
    "美食": ["food_quality", "local_food"],
    "吃": ["food_quality", "local_food"],
    "咖啡": ["coffee_friendly", "rest_friendly"],
    "下午茶": ["coffee_friendly"],
    "文化": ["culture_friendly", "museum_friendly", "history_friendly"],
    "历史": ["culture_friendly", "history_friendly"],
    "展览": ["museum_friendly", "culture_friendly"],
    "购物": ["shopping_friendly"],
    "夜景": ["night_friendly"],
    "夜生活": ["night_friendly"],
    "亲子": ["family_friendly"],
    "约会": ["couple_friendly"],
    "citywalk": ["citywalk_friendly"],
    "休闲": ["rest_friendly"],
    "自然": ["rest_friendly"],
    "打卡": ["photo_friendly", "first_visit_friendly"]
  },
  "user_constraints_to_risk_tags": {
    "avoid_queue": ["queue_heavy", "crowded_weekend"],
    "avoid_walking": ["walk_heavy"],
    "avoid_cross_district": ["far_from_anchor"],
    "need_meal": []
  },
  "review_tag_to_planning_tags": {
    "环境优雅": ["rest_friendly", "couple_friendly"],
    "适合约会": ["couple_friendly"],
    "出片漂亮": ["photo_friendly"],
    "本地特色": ["local_food"],
    "服务周到": ["rest_friendly"],
    "性价比高": ["low_budget_friendly"],
    "亲子友好": ["family_friendly"],
    "交通方便": ["transit_friendly"]
  },
  "review_tag_to_risk_tags": {
    "等位久": ["queue_heavy"],
    "价格偏贵": ["pricey"],
    "位置难找": ["hard_to_find"],
    "停车难": ["hard_to_find"],
    "上菜慢": ["queue_heavy"]
  }
}
JSONEOF
```

- [ ] **Step 4: 创建 `agents/tag_mapping.py`**

```python
"""v1.9 Tag Mapping — 用户自然语言 ↔ planning_tags / risk_tags 数据化.

Spec §1.3 docs/superpowers/specs/2026-05-14-v19-data-recommend-profile-adjust.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from dianping.schemas import ParsedIntent

_TAG_MAPPING_PATH = Path("data/tag_mapping.json")


class TagMapping(BaseModel):
    user_interest_to_planning_tags: dict[str, list[str]] = Field(default_factory=dict)
    user_constraints_to_risk_tags: dict[str, list[str]] = Field(default_factory=dict)
    review_tag_to_planning_tags: dict[str, list[str]] = Field(default_factory=dict)
    review_tag_to_risk_tags: dict[str, list[str]] = Field(default_factory=dict)


_CACHED: Optional[TagMapping] = None


def load_tag_mapping(path: Optional[Path] = None) -> TagMapping:
    """读取 data/tag_mapping.json. 进程内缓存."""
    global _CACHED
    if _CACHED is not None and path is None:
        return _CACHED
    p = path or _TAG_MAPPING_PATH
    if not p.exists():
        return TagMapping()
    data = json.loads(p.read_text(encoding="utf-8"))
    m = TagMapping(**data)
    if path is None:
        _CACHED = m
    return m


def expand_user_signals(intent: ParsedIntent) -> tuple[set[str], set[str]]:
    """合并 intent.interests + intent.preferences + intent.constraints → (positive, negative).

    positive: planning_tags 集 (POI 命中应加分)
    negative: risk_tags 集 (POI 命中应扣分)
    """
    m = load_tag_mapping()
    positive: set[str] = set()
    negative: set[str] = set()
    for src in list(intent.interests or []) + list(intent.preferences or []):
        tags = m.user_interest_to_planning_tags.get(src, [])
        positive.update(tags)
    for cname, on in (intent.constraints or {}).items():
        if not on:
            continue
        tags = m.user_constraints_to_risk_tags.get(cname, [])
        negative.update(tags)
    return positive, negative
```

- [ ] **Step 5: Run test, 验证 PASS**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_tag_mapping.py -v
```
Expected: 5 PASS

- [ ] **Step 6: Commit**

```bash
git add data/tag_mapping.json agents/tag_mapping.py tests/test_tag_mapping.py
git commit -m "feat(v1.9): tag_mapping.json + Loader + expand_user_signals"
```

---

## Task 5: `score_poi` 用 `tag_mapping`

**Files:**
- Modify: `agents/candidate_pool.py:score_poi`
- Test: `tests/test_score_poi_v19_tag_mapping.py` (NEW)

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_score_poi_v19_tag_mapping.py`:

```python
"""v1.9: score_poi 应通过 tag_mapping 计算 interest match, 不再硬编码."""

from agents.candidate_pool import score_poi
from dianping.schemas import POI, EnrichedLabel, ParsedIntent


def _make_poi(name, openshopid, planning_tags=None):
    p = POI(
        openshopid=openshopid,
        name=name,
        city="深圳",
        latitude=22.541,
        longitude=114.057,
        categories=["景点"],
        avgprice=100,
        star=4.5,
        business_hour="09:00-21:00",
    )
    p.enriched = EnrichedLabel(
        poi_role="city_essential",
        manual_priority=80,
        city_zone="福田",
        planning_tags=planning_tags or [],
    )
    return p


def _intent(**kw):
    d = dict(city="深圳", days=1, traveler_type="情侣")
    d.update(kw)
    return ParsedIntent(**d)


def test_score_with_photo_interest_boosts_photo_friendly_poi():
    poi = _make_poi("photo POI", "id1", planning_tags=["photo_friendly"])
    no_interest = score_poi(poi, _intent(), variant="main")
    with_interest = score_poi(
        poi, _intent(interests=["拍照"]), variant="main"
    )
    assert with_interest > no_interest


def test_score_with_avoid_queue_penalizes_queue_heavy():
    poi = POI(
        openshopid="id2",
        name="排队 POI",
        city="深圳",
        latitude=22.541,
        longitude=114.057,
        categories=["美食"],
        avgprice=100,
        star=4.5,
        business_hour="09:00-21:00",
    )
    poi.enriched = EnrichedLabel(
        poi_role="meal",
        manual_priority=80,
        city_zone="福田",
        risk_tags=["queue_heavy"],
    )
    no_constraint = score_poi(poi, _intent(), variant="main")
    with_constraint = score_poi(
        poi, _intent(constraints={"avoid_queue": True}), variant="main"
    )
    assert with_constraint < no_constraint


def test_legacy_preferences_still_work():
    """v1.6 preferences=["美食"] 老语义保持."""
    poi = _make_poi("食店", "id3", planning_tags=["food_quality"])
    boosted = score_poi(
        poi, _intent(preferences=["美食"]), variant="main"
    )
    base = score_poi(poi, _intent(), variant="main")
    assert boosted > base
```

- [ ] **Step 2: Run test, 验证 FAIL or PASS**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_score_poi_v19_tag_mapping.py -v
```

老 score_poi 也用 `_interest_tags` (INTEREST_TO_TAG 硬编码), 可能 partial pass. 关键是后面要让 tag_mapping 替代它.

- [ ] **Step 3: 改 `score_poi` 用 tag_mapping**

在 `agents/candidate_pool.py:score_poi` 找到这段:

```python
    # interest match
    want_tags = _interest_tags(intent)
    for t in enriched.planning_tags:
        if t in want_tags:
            score += 10.0
```

替换成:

```python
    # v1.9: interest + constraint via tag_mapping
    from agents.tag_mapping import expand_user_signals

    positive, negative = expand_user_signals(intent)
    for t in enriched.planning_tags:
        if t in positive:
            score += 10.0
    for t in enriched.risk_tags:
        if t in negative:
            score -= 25.0
```

并删除老 `_interest_tags` helper + 老 `INTEREST_TO_TAG` 字典.

找 `agents/candidate_pool.py` 顶部 (`INTEREST_TO_TAG = {`) 和 `def _interest_tags`, 删除这两个块.

注意: 老 risk_penalty 段 (avoid_queue / avoid_walking 那段) 也要清理, 因为 tag_mapping 已覆盖. 找:

```python
    # risk penalty
    avoid_queue = intent.constraints.get("avoid_queue", False)
    avoid_walking = intent.constraints.get("avoid_walking", False)
    ...
    # variant-specific penalty (B4 起作用)
    if variant == "low_queue":
        ...
    else:
        # main / interest_first 用用户 constraint 加正常惩罚
        if avoid_queue and queue_heavy:
            score -= 30.0
        if avoid_walking and walk_heavy:
            score -= 20.0
```

简化成 (保留 variant=low_queue 的全局 queue/walk 惩罚, 删 main 路径里靠 constraint 单独扣的, 因为 negative set 已含):

```python
    # variant-specific penalty
    if variant == "low_queue":
        if "queue_heavy" in enriched.risk_tags:
            score -= 50.0
        if "walk_heavy" in enriched.risk_tags:
            score -= 30.0
        if "crowded_weekend" in enriched.risk_tags:
            score -= 20.0
    # main / interest_first 的 constraint 惩罚已被 negative set 覆盖
```

- [ ] **Step 4: Run new tests + 老测试**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_score_poi_v19_tag_mapping.py tests/test_candidate_pool_v17.py tests/test_candidate_pool_v18_anchor.py -v
```
Expected: 全 PASS. 老 test_avoid_queue_constraint_penalizes_under_main_variant 仍 PASS (tag_mapping 走 -25 路径).

- [ ] **Step 5: 全测试回归**

```bash
PYTHONPATH=. venv/bin/pytest tests/ -q --ignore=tests/test_user_profile_cleaning.py
```
Expected: 全 PASS + 1 known flaky

- [ ] **Step 6: Commit**

```bash
git add agents/candidate_pool.py tests/test_score_poi_v19_tag_mapping.py
git commit -m "feat(v1.9): score_poi 用 tag_mapping 替代硬编码 INTEREST_TO_TAG"
```

---

## Task 6: `scripts/audit_enriched.py`

**Files:**
- Create: `scripts/audit_enriched.py`
- Test: `tests/test_enriched_audit.py` (NEW)

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_enriched_audit.py`:

```python
"""v1.9 enriched 脏点扫描规则单测."""

import pytest

from scripts.audit_enriched import audit_poi, AuditFlag


def _poi_dict(**kw):
    """简化 dict, 不走 full POI schema (audit 只看必要字段)."""
    d = dict(
        openshopid="x",
        name="测试 POI",
        categories=["景点"],
        enriched={
            "poi_role": "city_essential",
            "manual_priority": 80,
            "city_zone": "福田",
            "planning_tags": ["photo_friendly", "landmark"],
            "risk_tags": [],
        },
    )
    d.update(kw)
    return d


def test_audit_flags_landmark_with_food_category():
    """城墙/古城/塔/寺 含 美食 categories → 脏点."""
    p = _poi_dict(name="西安城墙", categories=["美食"])
    flags = audit_poi(p)
    assert AuditFlag.LANDMARK_WITH_FOOD in flags


def test_audit_flags_hotel_in_route():
    """酒店/宾馆 不应进路线."""
    p = _poi_dict(name="如家酒店深圳店", categories=["住宿"])
    flags = audit_poi(p)
    assert AuditFlag.HOTEL_AS_POI in flags


def test_audit_flags_meal_role_without_food_category():
    """poi_role=meal 但 categories 不含美食."""
    p = _poi_dict(
        name="某公园",
        categories=["休闲娱乐"],
        enriched={
            "poi_role": "meal",
            "manual_priority": 80,
            "city_zone": "",
            "planning_tags": [],
            "risk_tags": [],
        },
    )
    flags = audit_poi(p)
    assert AuditFlag.MEAL_ROLE_NO_FOOD_CATEGORY in flags


def test_audit_flags_city_essential_low_priority():
    """city_essential 角色但 manual_priority < 70."""
    p = _poi_dict(
        enriched={
            "poi_role": "city_essential",
            "manual_priority": 50,
            "city_zone": "福田",
            "planning_tags": ["landmark"],
            "risk_tags": [],
        }
    )
    flags = audit_poi(p)
    assert AuditFlag.CITY_ESSENTIAL_LOW_PRIORITY in flags


def test_audit_flags_missing_city_zone():
    p = _poi_dict(
        enriched={
            "poi_role": "meal",
            "manual_priority": 80,
            "city_zone": "",
            "planning_tags": ["food_quality"],
            "risk_tags": [],
        },
        categories=["美食"],
    )
    flags = audit_poi(p)
    assert AuditFlag.MISSING_CITY_ZONE in flags


def test_audit_flags_too_few_planning_tags():
    p = _poi_dict(
        enriched={
            "poi_role": "meal",
            "manual_priority": 80,
            "city_zone": "福田",
            "planning_tags": ["food_quality"],  # 1 个, 阈值 ≥ 2
            "risk_tags": [],
        },
        categories=["美食"],
    )
    flags = audit_poi(p)
    assert AuditFlag.TOO_FEW_PLANNING_TAGS in flags


def test_audit_clean_poi_no_flags():
    p = _poi_dict(
        name="老孙家泡馍",
        categories=["美食"],
        enriched={
            "poi_role": "meal",
            "manual_priority": 80,
            "city_zone": "钟楼-鼓楼",
            "planning_tags": ["food_quality", "local_food", "lunch_friendly"],
            "risk_tags": [],
        },
    )
    flags = audit_poi(p)
    assert flags == []
```

- [ ] **Step 2: Run test, 验证 FAIL**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_enriched_audit.py -v
```
Expected: ImportError

- [ ] **Step 3: 创建 `scripts/__init__.py` (if not exists) + `scripts/audit_enriched.py`**

```bash
touch scripts/__init__.py
```

创建 `scripts/audit_enriched.py`:

```python
"""v1.9 EnrichedLabel 脏点扫描.

跑全量 mock_dianping POI, 根据规则标红, 输出 data/generated/enriched_audit_report.json.
配合 scripts/refix_enriched.py 用 LLM 重打.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Optional


class AuditFlag(str, Enum):
    LANDMARK_WITH_FOOD = "landmark_with_food"
    HOTEL_AS_POI = "hotel_as_poi"
    MEAL_ROLE_NO_FOOD_CATEGORY = "meal_role_no_food_category"
    CITY_ESSENTIAL_LOW_PRIORITY = "city_essential_low_priority"
    MISSING_CITY_ZONE = "missing_city_zone"
    TOO_FEW_PLANNING_TAGS = "too_few_planning_tags"


_LANDMARK_KEYWORDS = ("城墙", "古城", "塔", "寺", "博物馆", "宫", "陵", "园")
_HOTEL_KEYWORDS = ("酒店", "宾馆", "公寓", "客栈")


def _has_any(s: str, words: tuple[str, ...]) -> bool:
    return any(w in s for w in words)


def audit_poi(poi: dict) -> list[AuditFlag]:
    """Audit 一个 POI dict, 返回标红 flags 列表."""
    flags: list[AuditFlag] = []
    name = poi.get("name", "")
    categories = poi.get("categories") or []
    cats_str = " ".join(categories)
    enriched = poi.get("enriched") or {}

    # Rule 1: 地标 含 美食
    if _has_any(name, _LANDMARK_KEYWORDS) and "美食" in cats_str:
        flags.append(AuditFlag.LANDMARK_WITH_FOOD)

    # Rule 2: 酒店 当 POI
    if _has_any(name, _HOTEL_KEYWORDS):
        flags.append(AuditFlag.HOTEL_AS_POI)

    # Rule 3: meal 角色但 categories 不含美食
    if (
        enriched.get("poi_role") == "meal"
        and "美食" not in cats_str
    ):
        flags.append(AuditFlag.MEAL_ROLE_NO_FOOD_CATEGORY)

    # Rule 4: city_essential 但 manual_priority < 70
    if (
        enriched.get("poi_role") == "city_essential"
        and (enriched.get("manual_priority") or 0) < 70
    ):
        flags.append(AuditFlag.CITY_ESSENTIAL_LOW_PRIORITY)

    # Rule 5: city_zone 缺失
    if not (enriched.get("city_zone") or ""):
        flags.append(AuditFlag.MISSING_CITY_ZONE)

    # Rule 6: planning_tags 不够
    if len(enriched.get("planning_tags") or []) < 2:
        flags.append(AuditFlag.TOO_FEW_PLANNING_TAGS)

    return flags


def audit_city(city: str) -> dict:
    """Audit 一城所有 POI. 返回 {flagged_count, total, report}."""
    poi_path = Path(f"data/mock_dianping/{city}.json")
    enriched_path = Path("data/poi_enriched_labels.json")
    if not poi_path.exists():
        return {"error": f"missing {poi_path}", "city": city}

    pois = json.loads(poi_path.read_text(encoding="utf-8"))
    enriched_all = (
        json.loads(enriched_path.read_text(encoding="utf-8"))
        if enriched_path.exists()
        else {}
    )
    enriched_map = enriched_all.get(city, {})

    report = []
    for p in pois:
        en = enriched_map.get(p.get("openshopid"))
        flagged = audit_poi({**p, "enriched": en})
        if flagged:
            report.append(
                {
                    "openshopid": p.get("openshopid"),
                    "name": p.get("name"),
                    "categories": p.get("categories"),
                    "flags": [f.value for f in flagged],
                }
            )
    return {
        "city": city,
        "total": len(pois),
        "flagged_count": len(report),
        "flagged_rate": round(len(report) / max(len(pois), 1), 3),
        "report": report,
    }


def main() -> None:
    output = Path("data/generated/enriched_audit_report.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    all_results = {}
    for city in ("深圳", "上海", "西安"):
        r = audit_city(city)
        all_results[city] = r
        if "error" not in r:
            print(
                f"{city}: {r['flagged_count']}/{r['total']} 标红 "
                f"({r['flagged_rate'] * 100:.1f}%)"
            )
        else:
            print(f"{city}: {r['error']}")
    output.write_text(
        json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nReport written to {output}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test, 验证 PASS**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_enriched_audit.py -v
```
Expected: 7 PASS

- [ ] **Step 5: 跑一次实际 audit (会读 mock 数据, 不写代码)**

```bash
PYTHONPATH=. venv/bin/python scripts/audit_enriched.py
```

记录输出每城的 flagged_rate (作为 Task 8 的对照基准).

- [ ] **Step 6: Commit**

```bash
git add scripts/__init__.py scripts/audit_enriched.py tests/test_enriched_audit.py
git commit -m "feat(v1.9): scripts/audit_enriched.py 脏点规则扫描"
```

---

## Task 7: `scripts/refix_enriched.py`

**Files:**
- Create: `scripts/refix_enriched.py`

注意: 这个脚本直接调真 LLM (qwen-plus), 单测覆盖 prompt 拼装即可, refix 实际效果靠 Task 8 跑完后人工抽检.

- [ ] **Step 1: 写 prompt 拼装单测**

加到 `tests/test_enriched_audit.py` 末尾:

```python


def test_build_refix_prompt_includes_name_categories_reviewtags():
    from scripts.refix_enriched import build_refix_prompt

    poi = {
        "openshopid": "id1",
        "name": "西安城墙",
        "categories": ["美食"],  # 脏: 应该是 景点
        "city": "西安",
        "star": 4.7,
        "reviewTags": [
            {"tag": "历史悠久", "hit": 234},
            {"tag": "夜景好", "hit": 189},
        ],
    }
    flags = ["landmark_with_food"]
    prompt = build_refix_prompt(poi, flags)
    assert "西安城墙" in prompt
    assert "美食" in prompt  # 原 categories 应被引用
    assert "历史悠久" in prompt  # reviewTags
    assert "landmark_with_food" in prompt  # flag 说明
```

- [ ] **Step 2: Run test, 验证 FAIL**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_enriched_audit.py::test_build_refix_prompt_includes_name_categories_reviewtags -v
```
Expected: FAIL (no module scripts.refix_enriched)

- [ ] **Step 3: 创建 `scripts/refix_enriched.py`**

```python
"""v1.9 LLM 重打脏点 POI 的 EnrichedLabel.

读 data/generated/enriched_audit_report.json, 对每个标红 POI 调 qwen-plus,
patch 到 data/poi_enriched_labels.json + data/poi_agent_labels.json.

支持 --dry-run 只打印不写文件.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

PLANNING_TAGS_VOCAB = [
    "food_quality", "local_food", "snack_friendly", "coffee_friendly",
    "photo_friendly", "culture_friendly", "museum_friendly", "history_friendly",
    "shopping_friendly", "night_friendly", "family_friendly", "couple_friendly",
    "elderly_friendly", "solo_friendly", "business_friendly", "rest_friendly",
    "citywalk_friendly", "rainy_day_friendly", "transit_friendly",
    "low_budget_friendly", "premium_friendly", "landmark", "first_visit_friendly",
    "atmosphere", "lunch_friendly", "dinner_friendly", "rain_friendly",
]
RISK_TAGS_VOCAB = [
    "queue_heavy", "crowded_weekend", "walk_heavy", "far_from_anchor",
    "hard_to_find", "pricey", "reservation_needed", "unstable_opening",
    "weather_sensitive", "not_family_friendly", "not_elderly_friendly",
]
POI_ROLES = ["city_essential", "persona_preferred", "meal", "connector", "fallback"]


def build_refix_prompt(poi: dict, flags: list[str]) -> str:
    """拼装 LLM 重打 prompt."""
    review_tags_str = "\n".join(
        f"  - {rt['tag']} hit={rt['hit']}"
        for rt in (poi.get("reviewTags") or [])[:5]
    )
    return f"""你是本地路线规划专家. 给定 POI 信息, 当前 EnrichedLabel 被标红, 请重新生成正确的 label.

## POI 信息
- 名字: {poi.get('name')}
- 城市: {poi.get('city')}
- 当前 categories: {poi.get('categories')}
- star: {poi.get('star')}
- top reviewTags:
{review_tags_str or '  (无)'}

## 标红原因
{', '.join(flags)}

## 任务
1. 根据 name + reviewTags 判断真实的 categories (categories 错时给修正)
2. 选合适的 poi_role: {', '.join(POI_ROLES)}
3. 从词表选 planning_tags (≥ 2 个):
   {', '.join(PLANNING_TAGS_VOCAB)}
4. 从词表选 risk_tags (可空):
   {', '.join(RISK_TAGS_VOCAB)}
5. 推断 city_zone (区域名, 例 "万象天地 / 科技园" / "钟楼-鼓楼-城墙")
6. manual_priority 0-100, city_essential 通常 80+

## 输出严格 JSON
{{
  "fix_categories": ["景点", "历史文化"],
  "poi_role": "city_essential",
  "planning_tags": ["landmark", "culture_friendly", "photo_friendly"],
  "risk_tags": ["crowded_weekend"],
  "city_zone": "钟楼-鼓楼-城墙",
  "manual_priority": 95,
  "min_stay_minutes": 60,
  "max_stay_minutes": 180
}}

要求:
- 标签必须从词表选, 不能自造
- categories/name 矛盾时 (例如城墙=美食), 以 name + reviewTags 为准
"""


async def refix_poi(poi: dict, flags: list[str]) -> dict:
    """调 qwen-plus 重打 enriched label. 返回新 enriched dict (含 fix_categories)."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
        base_url=os.environ.get(
            "QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
    )
    prompt = build_refix_prompt(poi, flags)
    resp = await client.chat.completions.create(
        model=os.environ.get("QWEN_MODEL", "qwen-plus"),
        messages=[
            {"role": "system", "content": "你是路线规划数据校对专家. 严格按 JSON schema 输出."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
        extra_body={"enable_thinking": False},
    )
    return json.loads(resp.choices[0].message.content or "{}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只打印不写文件")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 个 (调试)")
    args = parser.parse_args()

    audit_path = Path("data/generated/enriched_audit_report.json")
    if not audit_path.exists():
        print("先跑 scripts/audit_enriched.py")
        return
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    enriched_path = Path("data/poi_enriched_labels.json")
    enriched_all = (
        json.loads(enriched_path.read_text(encoding="utf-8"))
        if enriched_path.exists()
        else {}
    )

    fix_count = 0
    for city, result in audit.items():
        if "error" in result:
            continue
        for entry in result.get("report", []):
            if args.limit and fix_count >= args.limit:
                break
            oid = entry["openshopid"]
            poi_path = Path(f"data/mock_dianping/{city}.json")
            pois = json.loads(poi_path.read_text(encoding="utf-8"))
            poi = next((p for p in pois if p["openshopid"] == oid), None)
            if not poi:
                continue
            poi["city"] = city
            try:
                new_enriched = await refix_poi(poi, entry["flags"])
            except Exception as exc:
                print(f"FAIL {city} {oid}: {exc}")
                continue

            if args.dry_run:
                print(f"DRY {city} {oid} {poi['name']}: {new_enriched}")
                fix_count += 1
                continue

            # patch enriched_all
            city_map = enriched_all.setdefault(city, {})
            existing = city_map.get(oid, {})
            existing.update(
                {
                    "poi_role": new_enriched.get("poi_role", existing.get("poi_role", "fallback")),
                    "planning_tags": new_enriched.get("planning_tags", []),
                    "risk_tags": new_enriched.get("risk_tags", []),
                    "city_zone": new_enriched.get("city_zone", ""),
                    "manual_priority": new_enriched.get("manual_priority", 0),
                    "min_stay_minutes": new_enriched.get("min_stay_minutes", 60),
                    "max_stay_minutes": new_enriched.get("max_stay_minutes", 120),
                }
            )
            city_map[oid] = existing
            fix_count += 1
            print(f"FIXED {city} {oid} {poi['name']}")

    if not args.dry_run:
        enriched_path.write_text(
            json.dumps(enriched_all, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nWrote {fix_count} fixes to {enriched_path}")
    else:
        print(f"\nDRY: would write {fix_count} fixes")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run test, 验证 PASS**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_enriched_audit.py -v
```
Expected: 全 PASS (含新加的 build_refix_prompt 测试)

- [ ] **Step 5: Commit**

```bash
git add scripts/refix_enriched.py tests/test_enriched_audit.py
git commit -m "feat(v1.9): scripts/refix_enriched.py LLM 重打脏点 POI"
```

---

## Task 8: 跑 refix + 验证标红率下降

**Files:**
- 修改 `data/poi_enriched_labels.json` (refix 脚本输出)

- [ ] **Step 1: 跑 audit 记录基线**

```bash
PYTHONPATH=. venv/bin/python scripts/audit_enriched.py 2>&1 | tee /tmp/audit_before.txt
```
Expected: 每城 flagged_rate 输出, 记录基线 (例如 15%).

- [ ] **Step 2: Dry-run refix 看会改什么 (限 5 个)**

```bash
set -a && source .env && set +a
PYTHONPATH=. venv/bin/python scripts/refix_enriched.py --dry-run --limit 5
```
Expected: 输出 5 个 dry 结果, 不写文件.

- [ ] **Step 3: 真跑全量 refix**

```bash
set -a && source .env && set +a
PYTHONPATH=. venv/bin/python scripts/refix_enriched.py 2>&1 | tee /tmp/refix_log.txt
```

Expected: FIXED 行数 ≈ 基线 flagged_count. 失败 < 5%.

- [ ] **Step 4: 再跑 audit 看下降**

```bash
PYTHONPATH=. venv/bin/python scripts/audit_enriched.py 2>&1 | tee /tmp/audit_after.txt
```
Expected: 每城 flagged_rate < 3%.

- [ ] **Step 5: 全测试回归**

```bash
PYTHONPATH=. venv/bin/pytest tests/ -q --ignore=tests/test_user_profile_cleaning.py
```
Expected: 全 PASS + 1 known flaky.

- [ ] **Step 6: Commit patch**

```bash
git add data/poi_enriched_labels.json data/generated/enriched_audit_report.json
git commit -m "data(v1.9): refix enriched 脏点 (audit 标红率从 X% 降到 Y%)"
```

(commit message 里把实际数字填上)

---

## Task 9: 浏览器 e2e 三场景 + 提交

**Files:**
- 无文件改动, 只验证

- [ ] **Step 1: 启服务**

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
pkill -9 -f uvicorn 2>/dev/null
sleep 1
PYTHONPATH=. venv/bin/uvicorn dianping.mock_server:mock_app --host 127.0.0.1 --port 9192 &
set -a && source .env && set +a && unset MTAGENT_AMAP_DISABLED
PYTHONPATH=. venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 9191 &
sleep 4
```

- [ ] **Step 2: Scene A — 万象天地附近**

```bash
curl -sN -X POST http://127.0.0.1:9191/api/plan/stream \
  -H 'Content-Type: application/json' \
  -d '{"free_text":"深圳明天我想去万象天地附近转一转"}' \
  --max-time 60 > /tmp/scene_a_v19.txt
awk '/^event: planner.day_done$/{getline; print}' /tmp/scene_a_v19.txt | head -1 | python3 -c "
import sys, json, re
m = re.search(r'data:\s*({.*})', sys.stdin.read())
if m:
    d = json.loads(m.group(1))
    print(f'variant={d.get(\"variant\")} stops={len(d.get(\"stops\",[]))}')
    for s in d.get('stops', [])[:6]:
        cat = ','.join(s.get('categories',[]))
        print(f'  {s[\"slot_name\"]:8s} {s[\"poi_name\"]:25s} cat={cat}')
"
```
Expected: main variant stops ≥ 4. 至少 1 个美食 categories.

- [ ] **Step 3: Scene B — 上海中转**

```bash
curl -sN -X POST http://127.0.0.1:9191/api/plan/stream \
  -H 'Content-Type: application/json' \
  -d '{"free_text":"上海中转 7 小时 想吃吃吃 之后赶火车 在上海站"}' \
  --max-time 60 > /tmp/scene_b_v19.txt
awk '/^event: planner.day_done$/{getline; print}' /tmp/scene_b_v19.txt | head -1 | python3 -c "
import sys, json, re
m = re.search(r'data:\s*({.*})', sys.stdin.read())
if m:
    d = json.loads(m.group(1))
    print(f'variant={d.get(\"variant\")} stops={len(d.get(\"stops\",[]))}')
    for s in d.get('stops', [])[:6]:
        cat = ','.join(s.get('categories',[]))
        meal = '🍴' if '美食' in cat else '  '
        print(f'  {meal} {s[\"slot_name\"]:8s} {s[\"poi_name\"]:25s} cat={cat}')
"
```
Expected: main variant stops ≥ 4. 至少 60% 是美食.

- [ ] **Step 4: Scene C / D — 兼容性**

```bash
curl -sN -X POST http://127.0.0.1:9191/api/plan/stream \
  -H 'Content-Type: application/json' \
  -d '{"free_text":"西安半天拍照"}' \
  --max-time 60 > /tmp/scene_c_v19.txt
grep "trip_mode" /tmp/scene_c_v19.txt | head -1

curl -sN -X POST http://127.0.0.1:9191/api/plan/stream \
  -H 'Content-Type: application/json' \
  -d '{"free_text":"情侣 西安 3 天"}' \
  --max-time 90 > /tmp/scene_d_v19.txt
grep "trip_mode" /tmp/scene_d_v19.txt | head -1
```
Expected: Scene C `trip_mode: landmark_must`, Scene D `trip_mode: multi_day`.

- [ ] **Step 5: 浏览器手动验**

打开 `http://127.0.0.1:9191/`, 输入 "深圳万象天地附近转转":
- 应看到锚点 ★ + 半径圈 (v1.8 功能)
- stops 数量 4 (相比 v1.8 的 2)
- chat 无"自相矛盾"消息

- [ ] **Step 6: 关掉服务 + 最终全测试**

```bash
pkill -9 -f uvicorn
PYTHONPATH=. venv/bin/pytest tests/ -q --ignore=tests/test_user_profile_cleaning.py
```
Expected: 223 baseline + 新加测试 (累计 ~245 passed) + 1 known flaky.

- [ ] **Step 7: 收尾确认**

```bash
git log --oneline 7cb5acc..HEAD
git status
```
Expected: ~8 个新 commit, 无未提交修改 (除 mock_dianping 数据底座用户负责).

---

## 验收 (Acceptance)

✅ **Scene A**: 万象天地附近 stops 从 2 → 4, 含美食 POI (高德 around 拉进来)
✅ **Scene B**: 上海中转 stops 从 1 → 4, ≥ 60% 美食 (layover_eat types 餐饮优先)
✅ **Scene C/D**: 老路径不破 (landmark_must / multi_day)
✅ **EnrichedLabel 脏点**: 标红率从 ~15% → < 3%
✅ **tag_mapping 数据化**: INTEREST_TO_TAG 从代码消失, 改 JSON 立刻生效
✅ **测试**: 223 baseline → 累计 ≥ 245 passed, 1 known flaky

## 不在本计划范围 (v2.0 / Stage 2-4)

- ❌ UserProfile / 冷启动 (Stage 2)
- ❌ Adjuster v1 换地点换计划 (Stage 3)
- ❌ 反馈闭环 (Stage 4)
- ❌ location_pools.json (推到 v2.0)
- ❌ city_profiles.json (P3)
- ❌ route_slot_rules.json 抽出 (P3)
