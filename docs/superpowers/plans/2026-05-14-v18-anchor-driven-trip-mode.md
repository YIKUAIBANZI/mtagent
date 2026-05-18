# v1.8 锚点驱动 + Trip Mode Router 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修 v1.7 P0 #1 — 用户说"万象天地附近"得到 27km 外的路线。在 5 类 trip_mode 路由 + 高德 geocode/around 解析锚点 + candidate_pool 距离惩罚的基础上，让规划真的以锚点为圆心。

**Architecture:** Profiler 跑完拿 free_text → trip_router 推 trip_mode (anchor_explore / layover_eat / layover_explore / landmark_must / multi_day) → anchor.py 用高德 geocode 解析 start_location_text → 半径内拉高德 around POI + merge 本地 enriched POI → candidate_pool 加 distance_penalty + radius_filter → planner_instant 把 anchor 传给 compose_one_day → planner.md prompt 按 mode 加约束。前端 plan_stack.html anchor_explore 时画半径圈 + anchor ★。

**Tech Stack:** Python 3.11 + pydantic + httpx + 高德 v3 API (geocode/place around) + FastAPI SSE + 既有 qwen-plus / stub_llm。

**Spec source:** `docs/superpowers/specs/2026-05-13-v18-trip-mode-router-and-geometry.md`

**Baseline:** main HEAD `01cbf3a` + Track A 修复 (188 passed + 1 known flaky)。

**关键不变量（不能违反）:**
- 186 baseline 测试不破，新加测试只增不减
- ParsedIntent 老 3 必填字段 (city/days/traveler_type) 不动
- v1.6 多日 SSE 路径不动 (Planner.run / compose_one_day / day_done 旧 payload)
- ctx.variants 持久化逻辑不变
- 旧 SSE 事件名全保留
- score_poi 不依赖 reviewCount/avgprice
- "终南山古楼观钟楼" (B0FFI9FCX9) demote 不能回弹
- polylineQueue 220ms worker / planner.done 不重画 polyline

---

## File Structure

**新建文件 (4 个):**

| 文件 | 责任 | 行数估计 |
|---|---|---|
| `agents/anchor.py` | 高德 geocode + around + LLM fallback 解析 + merge 本地 POI | ~200 |
| `agents/trip_router.py` | 5 mode 规则路由 + hub_type 推断 + radius/safety_margin 计算 | ~120 |
| `tests/test_anchor.py` | anchor.py 单测 (geocode mock + around mock + merge dedupe) | ~150 |
| `tests/test_trip_router.py` | 5 mode 路由 + 节假日 + hub_type 规则单测 | ~180 |

**修改文件 (9 个):**

| 文件 | 改动 |
|---|---|
| `dianping/schemas.py` | ParsedIntent 加 `trip_mode`, `anchor_radius_km`, `hub_type`, `safety_margin_min`, `anchor_lng`, `anchor_lat`, `anchor_resolved_name` |
| `agents/profiler.py` | 跑完 LLM 后 best-effort 调 anchor.resolve_anchor + trip_router.route_trip_mode |
| `agents/candidate_pool.py` | build_candidate_pool 加 anchor + radius_km 参数, score_poi 加 distance_penalty |
| `agents/planner_instant.py` | plan_one_variant 接 anchor 真实坐标, 不再用 flat_pois[0] 当锚点 |
| `agents/planner.py` | _build_one_day_payload 加 trip_mode + anchor 字段, compose_one_day 受 anchor 影响 |
| `agents/prompts/profiler.md` | 加 trip_mode 推断段 + hub_type + start_location_text 抽取规则 |
| `agents/prompts/planner.md` | 加模式约束段 (anchor_explore 半径 / layover 返回 / landmark_must zone) |
| `api/stub_llm.py` | stub_profiler_llm 加 trip_mode 关键词识别 + anchor 抽取 |
| `web/plan_stack.html` | anchor_explore 时画半透明半径圈 + anchor ★ marker |

---

## 任务拆分总览

| # | 任务 | 估时 | 依赖 |
|---|---|---|---|
| 1 | ParsedIntent 加 v1.8 字段 + schema 单测 | 15min | - |
| 2 | agents/trip_router.py + 单测 | 45min | 1 |
| 3 | agents/anchor.py (geocode + around + merge) + 单测 | 90min | 1 |
| 4 | candidate_pool 加 distance_penalty + 单测 | 30min | 1 |
| 5 | profiler.py 接 anchor + trip_router + 单测 | 30min | 2,3 |
| 6 | stub_llm 加 trip_mode + anchor 关键词 + 单测 | 20min | 1,2 |
| 7 | planner_instant.py 接真实 anchor + 单测 | 30min | 3,4 |
| 8 | prompts/profiler.md + planner.md 改造 | 30min | 7 |
| 9 | plan_stack.html 画半径圈 + anchor ★ | 30min | 5 |
| 10 | 浏览器 e2e 验三场景 + 提交 | 30min | 9 |

**总计 ~5.5h**

---

## Task 1: ParsedIntent 扩展 v1.8 字段

**Files:**
- Modify: `dianping/schemas.py:288-311` (ParsedIntent class)
- Test: `tests/test_v18_schema.py` (NEW)

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_v18_schema.py`:

```python
"""v1.8 ParsedIntent 新字段单测."""

from dianping.schemas import ParsedIntent


def test_parsed_intent_has_v18_trip_mode_default_none():
    intent = ParsedIntent(city="深圳", days=1, traveler_type="情侣")
    assert intent.trip_mode is None
    assert intent.anchor_radius_km is None
    assert intent.hub_type is None
    assert intent.safety_margin_min is None
    assert intent.anchor_lng is None
    assert intent.anchor_lat is None
    assert intent.anchor_resolved_name is None


def test_parsed_intent_accepts_v18_anchor_explore():
    intent = ParsedIntent(
        city="深圳",
        days=1,
        traveler_type="情侣",
        trip_mode="anchor_explore",
        anchor_radius_km=3.0,
        anchor_lng=114.057,
        anchor_lat=22.541,
        anchor_resolved_name="深圳万象天地",
    )
    assert intent.trip_mode == "anchor_explore"
    assert intent.anchor_radius_km == 3.0


def test_parsed_intent_accepts_v18_layover_eat():
    intent = ParsedIntent(
        city="上海",
        days=1,
        traveler_type="独行",
        trip_mode="layover_eat",
        hub_type="train",
        safety_margin_min=30,
        anchor_lng=121.456,
        anchor_lat=31.249,
        anchor_resolved_name="上海站",
    )
    assert intent.trip_mode == "layover_eat"
    assert intent.hub_type == "train"
    assert intent.safety_margin_min == 30


def test_parsed_intent_backward_compat_no_v18_fields():
    """老 v1.7 路径不带 v1.8 字段, 仍能构造."""
    intent = ParsedIntent(city="西安", days=2, traveler_type="情侣")
    dumped = intent.model_dump()
    assert "trip_mode" in dumped
    assert dumped["trip_mode"] is None
```

- [ ] **Step 2: Run test, 验证 FAIL**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_v18_schema.py -v
```
Expected: 4 个 FAIL，错误信息含 "trip_mode" 字段不存在。

- [ ] **Step 3: 改 schemas.py**

在 `dianping/schemas.py:288` 加 type alias (在 ParsedIntent 之前):

```python
TripMode = Literal[
    "anchor_explore",
    "layover_eat",
    "layover_explore",
    "landmark_must",
    "multi_day",
]
HubType = Literal["train", "highspeed", "airport", "bus"]
```

在 `dianping/schemas.py:311` (ParsedIntent 最后) `weather_temp_c` 字段之后追加：

```python
    # v1.8 trip_mode 路由 + 锚点驱动 (全部 optional, 老 v1.7 路径不依赖)
    trip_mode: Optional[TripMode] = None
    anchor_radius_km: Optional[float] = None  # 默认按 mode 推 (anchor_explore=3.0)
    hub_type: Optional[HubType] = None  # layover 专用 (火车/高铁/机场/客运)
    safety_margin_min: Optional[int] = None  # layover 返程预留分钟
    anchor_lng: Optional[float] = None  # 高德 geocode 解析后的坐标
    anchor_lat: Optional[float] = None
    anchor_resolved_name: Optional[str] = None  # 高德标准化地名
```

- [ ] **Step 4: Run test, 验证 PASS**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_v18_schema.py -v
```
Expected: 4 PASS

- [ ] **Step 5: 全测试回归**

```bash
PYTHONPATH=. venv/bin/pytest tests/ -q --ignore=tests/test_user_profile_cleaning.py
```
Expected: 188 + 4 = 192 passed, 1 known flaky

- [ ] **Step 6: Commit**

```bash
git add dianping/schemas.py tests/test_v18_schema.py
git commit -m "feat(v1.8): ParsedIntent + TripMode/HubType 类型 + 锚点字段"
```

---

## Task 2: trip_router.py 5 mode 路由

**Files:**
- Create: `agents/trip_router.py`
- Test: `tests/test_trip_router.py`

- [ ] **Step 1: 写失败的测试 (规则路由)**

创建 `tests/test_trip_router.py`:

```python
"""v1.8 trip_router 5 mode 路由规则单测."""

from datetime import date

from agents.trip_router import (
    HUB_SAFETY_MARGIN,
    infer_hub_type,
    is_chinese_holiday,
    route_trip_mode,
)
from dianping.schemas import ParsedIntent


def _intent(**kwargs) -> ParsedIntent:
    defaults = dict(city="深圳", days=1, traveler_type="情侣")
    defaults.update(kwargs)
    return ParsedIntent(**defaults)


def test_route_multi_day_when_days_geq_2():
    assert route_trip_mode(_intent(days=2), "深圳3天家庭游") == "multi_day"
    assert route_trip_mode(_intent(days=5), "随便玩玩") == "multi_day"


def test_route_layover_eat_when_transit_keyword_and_food_intent():
    text = "上海中转 7 小时 想吃吃吃 之后赶火车"
    intent = _intent(city="上海", start_location_text="上海站", estimated_hours=7)
    assert route_trip_mode(intent, text) == "layover_eat"


def test_route_layover_explore_when_transit_keyword_and_visit_intent():
    text = "上海中转 7 小时 想去外滩附近转转 然后赶火车"
    intent = _intent(city="上海", start_location_text="上海站", estimated_hours=7)
    assert route_trip_mode(intent, text) == "layover_explore"


def test_route_anchor_explore_when_start_location_with_nearby_word():
    text = "深圳明天我想去万象天地附近转一转"
    intent = _intent(start_location_text="万象天地")
    assert route_trip_mode(intent, text) == "anchor_explore"


def test_route_anchor_explore_when_only_start_location_no_nearby():
    """用户说锚点本身就是探索意图, 不需要"附近""转转"关键词."""
    intent = _intent(start_location_text="万象天地")
    assert route_trip_mode(intent, "深圳万象天地") == "anchor_explore"


def test_route_landmark_must_when_no_anchor_no_layover():
    intent = _intent(city="西安", time_window="半日_下午")
    assert route_trip_mode(intent, "西安半天拍照") == "landmark_must"


def test_infer_hub_type_train():
    assert infer_hub_type("上海站") == "train"
    assert infer_hub_type("深圳北站") == "highspeed"
    assert infer_hub_type("西安咸阳国际机场") == "airport"
    assert infer_hub_type("深圳福田汽车站") == "bus"
    assert infer_hub_type("万象天地") is None


def test_hub_safety_margin_values():
    """火车 30min, 飞机 2h, 客运 20min, 高铁 30min."""
    assert HUB_SAFETY_MARGIN["train"] == 30
    assert HUB_SAFETY_MARGIN["airport"] == 120
    assert HUB_SAFETY_MARGIN["bus"] == 20
    assert HUB_SAFETY_MARGIN["highspeed"] == 30


def test_is_chinese_holiday_2026():
    """2026 春节 2/17 (周二)."""
    assert is_chinese_holiday(date(2026, 2, 17)) is True
    # 平常工作日
    assert is_chinese_holiday(date(2026, 5, 14)) is False
```

- [ ] **Step 2: Run test, 验证 FAIL**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_trip_router.py -v
```
Expected: ImportError "agents.trip_router".

- [ ] **Step 3: 创建 agents/trip_router.py**

```python
"""v1.8 Trip Mode Router — 5 类规则路由 + hub_type / safety_margin 推断.

按 spec docs/superpowers/specs/2026-05-13-v18-trip-mode-router-and-geometry.md §2.

规则 fallback, LLM 优先 (Profiler 已抽 trip_mode 字段则跳过此 router).
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from dianping.schemas import HubType, ParsedIntent, TripMode

# ---- 关键词字典 ----

LAYOVER_KEYWORDS = (
    "中转", "转机", "路过", "停留",
    "赶火车", "赶飞机", "赶车", "赶高铁",
    "高铁", "动车", "几小时后", "小时后要走",
)
TRANSIT_HUB_KEYWORDS = ("火车站", "高铁站", "机场", "动车站", "客运站")
EXPLORE_KEYWORDS = ("附近", "周边", "转转", "逛逛", "这边", "这里", "一带")
EAT_KEYWORDS = ("吃", "美食", "餐厅", "饭", "面", "粉", "小吃", "夜宵", "下午茶")
VISIT_KEYWORDS = ("看", "玩", "逛", "转", "拍照", "景点", "打卡", "游览")

# hub_type 推断
HUB_TYPE_RULES: list[tuple[tuple[str, ...], HubType]] = [
    (("高铁站", "动车站", "北站", "东站", "南站", "西站"), "highspeed"),
    (("机场", "国际机场"), "airport"),
    (("汽车站", "客运站", "长途"), "bus"),
    (("火车站", "站"), "train"),
]

# safety_margin (minutes) — Q5 拍板
HUB_SAFETY_MARGIN: dict[HubType, int] = {
    "train": 30,
    "highspeed": 30,
    "airport": 120,
    "bus": 20,
}

# 节假日 buffer (节假日 + holiday_buffer 分钟)
HOLIDAY_BUFFER_MIN = 45

# 2026 中国法定假日 (硬编码, 一年表足够)
HOLIDAYS_2026: set[date] = {
    # 元旦
    date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3),
    # 春节 (2/17-2/23)
    date(2026, 2, 17), date(2026, 2, 18), date(2026, 2, 19),
    date(2026, 2, 20), date(2026, 2, 21), date(2026, 2, 22), date(2026, 2, 23),
    # 清明 (4/4-4/6)
    date(2026, 4, 4), date(2026, 4, 5), date(2026, 4, 6),
    # 劳动 (5/1-5/5)
    date(2026, 5, 1), date(2026, 5, 2), date(2026, 5, 3),
    date(2026, 5, 4), date(2026, 5, 5),
    # 端午 (6/19-6/21)
    date(2026, 6, 19), date(2026, 6, 20), date(2026, 6, 21),
    # 中秋 + 国庆 (10/1-10/8)
    date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3),
    date(2026, 10, 4), date(2026, 10, 5), date(2026, 10, 6),
    date(2026, 10, 7), date(2026, 10, 8),
}

# anchor_radius_km 默认值 (Q4 拍板, 冷启动后续覆盖)
DEFAULT_ANCHOR_RADIUS_KM = 4.0  # walk=2 / bike=4 / transit=6 中位


def is_chinese_holiday(d: date) -> bool:
    return d in HOLIDAYS_2026


def infer_hub_type(text: Optional[str]) -> Optional[HubType]:
    """从 start_location_text 推 hub_type. 没命中返 None."""
    if not text:
        return None
    for keywords, hub in HUB_TYPE_RULES:
        if any(k in text for k in keywords):
            return hub
    return None


def _has_any(text: str, words: tuple[str, ...]) -> bool:
    return any(w in text for w in words)


def route_trip_mode(intent: ParsedIntent, raw_text: str) -> TripMode:
    """5 类规则路由. Spec §2.1.

    优先级: multi_day → layover → anchor_explore → landmark_must (兜底).
    """
    # 1) 多日优先
    if (intent.days or 1) >= 2:
        return "multi_day"

    # 2) layover — keyword OR hub_type 命中
    is_layover = (
        _has_any(raw_text, LAYOVER_KEYWORDS)
        or infer_hub_type(intent.start_location_text) is not None
        or _has_any(intent.start_location_text or "", TRANSIT_HUB_KEYWORDS)
    )
    if is_layover:
        # 区分 layover_eat / layover_explore
        has_eat = _has_any(raw_text, EAT_KEYWORDS)
        has_visit = _has_any(raw_text, VISIT_KEYWORDS)
        if has_eat and not has_visit:
            return "layover_eat"
        if has_visit and not has_eat:
            return "layover_explore"
        # 都有 / 都没: 默认 explore (更通用)
        return "layover_explore"

    # 3) anchor_explore: 有具体地点锚点
    if intent.start_location_text:
        return "anchor_explore"

    # 4) 兜底
    return "landmark_must"


def compute_safety_margin(
    hub_type: Optional[HubType], at_date: Optional[date] = None
) -> int:
    """基础 safety_margin + 节假日 buffer."""
    if hub_type is None:
        return 30  # 默认
    base = HUB_SAFETY_MARGIN.get(hub_type, 30)
    if at_date and is_chinese_holiday(at_date):
        base += HOLIDAY_BUFFER_MIN
    return base
```

- [ ] **Step 4: Run test, 验证 PASS**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_trip_router.py -v
```
Expected: 9 PASS

- [ ] **Step 5: Commit**

```bash
git add agents/trip_router.py tests/test_trip_router.py
git commit -m "feat(v1.8): trip_router 5 mode 规则路由 + hub_type + safety_margin"
```

---

## Task 3: anchor.py 高德 geocode + around + merge

**Files:**
- Create: `agents/anchor.py`
- Test: `tests/test_anchor.py`

- [ ] **Step 1: 写失败的测试 (Pydantic model + dedupe 逻辑)**

创建 `tests/test_anchor.py`:

```python
"""v1.8 anchor.py: 高德 geocode + around + merge 本地 POI."""

from unittest.mock import AsyncMock, patch

import pytest

from agents.anchor import (
    AnchorResolution,
    AroundPOI,
    _norm_name,
    _within_100m,
    fetch_around,
    merge_with_local_pool,
    resolve_anchor,
)
from dianping.schemas import POI, EnrichedLabel


def _make_poi(name, openshopid, lat, lng, categories=None, has_enriched=True):
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
    if has_enriched:
        p.enriched = EnrichedLabel(
            poi_role="city_essential", manual_priority=90, city_zone="福田"
        )
    return p


def test_norm_name_strips_branch_and_parens():
    assert _norm_name("万象天地(福田店)") == "万象天地"
    assert _norm_name("老孙家总店") == "老孙家"
    assert _norm_name("茶颜悦色 长沙分店") == "茶颜悦色 长沙"
    assert _norm_name("万象天地") == "万象天地"


def test_within_100m_true_when_close():
    assert _within_100m((114.057, 22.541), (114.0571, 22.5411)) is True


def test_within_100m_false_when_far():
    assert _within_100m((114.057, 22.541), (114.07, 22.55)) is False


@pytest.mark.asyncio
async def test_resolve_anchor_returns_resolution_on_success():
    """高德 geocode 命中: 返回标准化地名 + 坐标."""
    mock_response = {
        "status": "1",
        "geocodes": [
            {
                "formatted_address": "广东省深圳市福田区万象天地",
                "location": "114.057000,22.541000",
                "adcode": "440304",
                "level": "兴趣点",
            }
        ],
    }

    with patch("agents.anchor._amap_get", new=AsyncMock(return_value=mock_response)):
        result = await resolve_anchor("万象天地", city="深圳")

    assert result is not None
    assert result.lng == 114.057
    assert result.lat == 22.541
    assert result.adcode == "440304"
    assert "万象天地" in result.name
    assert result.confidence == "high"


@pytest.mark.asyncio
async def test_resolve_anchor_returns_none_when_geocode_empty():
    mock_response = {"status": "1", "geocodes": []}
    with patch("agents.anchor._amap_get", new=AsyncMock(return_value=mock_response)):
        result = await resolve_anchor("不存在地名XYZ", city="深圳")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_around_returns_around_pois():
    mock_response = {
        "status": "1",
        "pois": [
            {
                "name": "老孙家泡馍",
                "location": "114.058,22.542",
                "typecode": "050000",
                "distance": "120",
                "address": "深圳市福田区某街",
            },
            {
                "name": "深圳书城",
                "location": "114.060,22.540",
                "typecode": "080000",
                "distance": "300",
                "address": "深圳市福田区福华一路",
            },
        ],
    }
    with patch("agents.anchor._amap_get", new=AsyncMock(return_value=mock_response)):
        pois = await fetch_around(
            lng=114.057, lat=22.541, radius_m=3000, limit=50
        )

    assert len(pois) == 2
    assert pois[0].name == "老孙家泡馍"
    assert pois[0].distance_m == 120
    assert pois[0].lng == 114.058


def test_merge_dedupes_by_name_and_coord():
    """高德 POI 跟本地同名+100m 内坐标 → 视为同一, 保本地 (有 enriched)."""
    anchor = AnchorResolution(
        text="万象天地", name="深圳万象天地",
        lng=114.057, lat=22.541, adcode="440304",
        formatted_address="...", confidence="high",
    )
    local = [_make_poi("老孙家泡馍", "id_1", 22.5420, 114.0581)]
    amap = [
        AroundPOI(
            name="老孙家泡馍", lng=114.058, lat=22.542, typecode="050000",
            distance_m=120, address="..."
        ),
        AroundPOI(
            name="深圳书城", lng=114.060, lat=22.540, typecode="080000",
            distance_m=300, address="..."
        ),
    ]
    merged = merge_with_local_pool(amap, local, anchor, radius_m=3000)
    # 本地"老孙家泡馍"保留 (带 enriched), 高德同名跳过, 高德"深圳书城"新加
    names = [p.name for p in merged]
    assert "老孙家泡馍" in names
    assert "深圳书城" in names
    assert len(merged) == 2  # 不重复
    # 本地 POI 仍带 enriched
    laoshun = next(p for p in merged if p.name == "老孙家泡馍")
    assert laoshun.enriched is not None


def test_merge_filters_out_of_radius():
    anchor = AnchorResolution(
        text="x", name="x", lng=114.057, lat=22.541, adcode="440304",
        formatted_address="...", confidence="high",
    )
    # 远的本地 POI (深圳东 ~ 30km) — 应过滤掉
    local = [_make_poi("远 POI", "id_far", 22.55, 114.30)]
    merged = merge_with_local_pool([], local, anchor, radius_m=3000)
    assert merged == []
```

- [ ] **Step 2: Run test, 验证 FAIL**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_anchor.py -v
```
Expected: ImportError "agents.anchor".

- [ ] **Step 3: 创建 agents/anchor.py**

```python
"""v1.8 锚点解析 — 高德 geocode + place around + merge 本地 POI.

Spec §3. AMAP_KEY 已在 .env (沿用 weather.py 的 key).
"""

from __future__ import annotations

import math
import os
import re
from typing import Literal, Optional

import httpx
from pydantic import BaseModel

from dianping.schemas import POI

_AMAP_BASE = "https://restapi.amap.com"
_TIMEOUT = 5.0

# 高德 typecode (Spec §3.2)
DEFAULT_AROUND_TYPES = "050000|060000|080000|110000"


class AnchorResolution(BaseModel):
    text: str
    name: str
    lng: float
    lat: float
    adcode: str
    formatted_address: str
    confidence: Literal["high", "medium", "low"]


class AroundPOI(BaseModel):
    name: str
    lng: float
    lat: float
    typecode: str
    distance_m: int
    address: str


async def _amap_get(path: str, params: dict) -> dict:
    """高德 GET 调用. 内置 timeout, 抛 httpx.HTTPError 由 caller 处理."""
    key = os.environ.get("AMAP_KEY", "")
    params = {**params, "key": key}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(f"{_AMAP_BASE}{path}", params=params)
        resp.raise_for_status()
        return resp.json()


async def resolve_anchor(text: str, city: str) -> Optional[AnchorResolution]:
    """高德 geocode 文本 → 坐标. Spec §3.3.

    失败 (status != 1 / geocodes 空) 返 None, caller 走 LLM fallback 或 landmark_must.
    """
    try:
        data = await _amap_get(
            "/v3/geocode/geo", {"address": text, "city": city}
        )
    except Exception:
        return None
    if data.get("status") != "1":
        return None
    geocodes = data.get("geocodes") or []
    if not geocodes:
        return None
    g = geocodes[0]
    location = g.get("location", "")
    try:
        lng_str, lat_str = location.split(",")
        lng, lat = float(lng_str), float(lat_str)
    except (ValueError, AttributeError):
        return None
    level = g.get("level", "")
    confidence: Literal["high", "medium", "low"]
    if level in ("兴趣点", "门牌号", "兴趣点群"):
        confidence = "high"
    elif level in ("道路", "地铁站", "公交站台"):
        confidence = "medium"
    else:
        confidence = "low"
    return AnchorResolution(
        text=text,
        name=g.get("formatted_address", text),
        lng=lng,
        lat=lat,
        adcode=g.get("adcode", ""),
        formatted_address=g.get("formatted_address", ""),
        confidence=confidence,
    )


async def fetch_around(
    lng: float,
    lat: float,
    radius_m: int,
    types: str = DEFAULT_AROUND_TYPES,
    limit: int = 50,
) -> list[AroundPOI]:
    """高德周边搜索. Spec §3.2.

    limit ≤ 50 (高德 page_size 上限).
    """
    try:
        data = await _amap_get(
            "/v3/place/around",
            {
                "location": f"{lng:.6f},{lat:.6f}",
                "radius": min(radius_m, 50000),  # 高德上限 50km
                "types": types,
                "offset": min(limit, 50),
                "page": 1,
                "extensions": "base",
            },
        )
    except Exception:
        return []
    if data.get("status") != "1":
        return []
    out: list[AroundPOI] = []
    for raw in data.get("pois", []):
        loc = raw.get("location", "")
        try:
            lng_s, lat_s = loc.split(",")
            p_lng, p_lat = float(lng_s), float(lat_s)
        except (ValueError, AttributeError):
            continue
        out.append(
            AroundPOI(
                name=raw.get("name", ""),
                lng=p_lng,
                lat=p_lat,
                typecode=raw.get("typecode", ""),
                distance_m=int(raw.get("distance") or 0),
                address=raw.get("address", "") if isinstance(raw.get("address"), str) else "",
            )
        )
    return out


_PAREN_PAT = re.compile(r"[(（].*?[)）]|总店|分店")


def _norm_name(name: str) -> str:
    """归一化店名 — 去括号注释 + 总店/分店 后缀."""
    return _PAREN_PAT.sub("", name).strip()


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """great-circle distance in km. Input: (lng, lat) tuples."""
    lng1, lat1 = math.radians(a[0]), math.radians(a[1])
    lng2, lat2 = math.radians(b[0]), math.radians(b[1])
    dl = lng2 - lng1
    dp = lat2 - lat1
    h = (
        math.sin(dp / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dl / 2) ** 2
    )
    return 6371 * 2 * math.asin(math.sqrt(h))


def _within_100m(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return _haversine_km(a, b) < 0.1


def merge_with_local_pool(
    amap_pois: list[AroundPOI],
    local_pois: list[POI],
    anchor: AnchorResolution,
    radius_m: int,
) -> list[POI]:
    """合并本地 + 高德 POI. Spec §3.4.

    规则:
    1. 本地 POI 在半径内: 保留 (有 enriched 标签, 优先)
    2. 高德 POI 在半径内 + 本地没有: 转 POI 对象 (无 enriched, 兜底)
    3. 去重 key: (norm_name, < 100m 坐标)
    4. 排序: 内置 enriched.manual_priority desc → 距 anchor 距离 asc
    """
    anchor_pt = (anchor.lng, anchor.lat)
    radius_km = radius_m / 1000.0

    kept_local: list[POI] = []
    local_keys: set[tuple[str, int, int]] = set()
    for p in local_pois:
        d = _haversine_km(anchor_pt, (p.longitude, p.latitude))
        if d > radius_km:
            continue
        # 100m 网格当 key (lat/lng 各保留 3 位 = ~111m)
        key = (_norm_name(p.name), round(p.latitude, 3), round(p.longitude, 3))
        if key in local_keys:
            continue
        local_keys.add(key)
        kept_local.append(p)

    # 高德 POI: 去重 vs 本地 (name + 100m coord)
    kept_amap: list[POI] = []
    for ap in amap_pois:
        d = _haversine_km(anchor_pt, (ap.lng, ap.lat))
        if d > radius_km:
            continue
        norm = _norm_name(ap.name)
        # 检查是否与某个本地 POI 同名 + 100m 内
        dup = False
        for lp in kept_local:
            if _norm_name(lp.name) == norm and _within_100m(
                (ap.lng, ap.lat), (lp.longitude, lp.latitude)
            ):
                dup = True
                break
        if dup:
            continue
        # 转 POI 对象 (无 enriched, openshopid 用 typecode + 坐标 hash)
        synthetic_id = f"amap_{ap.typecode}_{round(ap.lng, 4)}_{round(ap.lat, 4)}"
        categories = _typecode_to_categories(ap.typecode)
        kept_amap.append(
            POI(
                openshopid=synthetic_id,
                name=ap.name,
                city=local_pois[0].city if local_pois else "",
                latitude=ap.lat,
                longitude=ap.lng,
                categories=categories,
                address=ap.address,
                avgprice=0,
                star=0,
                business_hour="",
            )
        )

    # 排序: 本地优先 (有 enriched 高 manual_priority) → 高德兜底
    kept_local.sort(
        key=lambda p: (
            -(p.enriched.manual_priority if p.enriched else 0),
            _haversine_km(anchor_pt, (p.longitude, p.latitude)),
        )
    )
    kept_amap.sort(key=lambda p: _haversine_km(anchor_pt, (p.longitude, p.latitude)))
    return kept_local + kept_amap


def _typecode_to_categories(typecode: str) -> list[str]:
    """高德 typecode → 我们的 categories. 5 位粗分."""
    if not typecode:
        return ["其它"]
    prefix = typecode[:2]
    return {
        "05": ["美食"],
        "06": ["购物"],
        "07": ["生活服务"],
        "08": ["休闲娱乐"],
        "11": ["景点"],
    }.get(prefix, ["其它"])
```

- [ ] **Step 4: Run test, 验证 PASS**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_anchor.py -v
```
Expected: 8 PASS

- [ ] **Step 5: 回归测试**

```bash
PYTHONPATH=. venv/bin/pytest tests/ -q --ignore=tests/test_user_profile_cleaning.py
```
Expected: 192 + 8 + 9 = 209 passed (从 task 1+2 起累计), 1 known flaky

- [ ] **Step 6: Commit**

```bash
git add agents/anchor.py tests/test_anchor.py
git commit -m "feat(v1.8): anchor.py 高德 geocode + around + merge 本地 POI"
```

---

## Task 4: candidate_pool 加 anchor distance_penalty

**Files:**
- Modify: `agents/candidate_pool.py:74-158` (score_poi function), `:168-212` (build_candidate_pool)
- Test: `tests/test_candidate_pool_v18_anchor.py`

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_candidate_pool_v18_anchor.py`:

```python
"""v1.8: candidate_pool 加 anchor distance_penalty 单测."""

from agents.candidate_pool import build_candidate_pool, score_poi
from dianping.schemas import POI, EnrichedLabel, ParsedIntent


def _make_poi(name, openshopid, lat, lng, role="city_essential", priority=80):
    p = POI(
        openshopid=openshopid, name=name, city="深圳",
        latitude=lat, longitude=lng,
        categories=["景点"], avgprice=100, star=4.5, business_hour="09:00-21:00",
    )
    p.enriched = EnrichedLabel(poi_role=role, manual_priority=priority, city_zone="福田")
    return p


def _intent(**kw):
    d = dict(city="深圳", days=1, traveler_type="情侣")
    d.update(kw)
    return ParsedIntent(**d)


def test_score_poi_anchor_within_1_5km_no_penalty():
    """1.5km 内距离不扣分."""
    poi = _make_poi("近 POI", "id1", 22.541, 114.057)
    intent = _intent(
        anchor_lat=22.540, anchor_lng=114.056, anchor_radius_km=3.0
    )
    no_anchor = score_poi(poi, _intent(), variant="main")
    with_anchor = score_poi(poi, intent, variant="main")
    # 100m 内, 无惩罚
    assert with_anchor == no_anchor


def test_score_poi_anchor_beyond_radius_heavy_penalty():
    """超出半径 (3km) 后硬扣分 ≥ 50."""
    poi = _make_poi("远 POI", "id2", 22.6, 114.2)  # ~ 17km
    intent = _intent(
        anchor_lat=22.541, anchor_lng=114.057, anchor_radius_km=3.0
    )
    s = score_poi(poi, intent, variant="main")
    s_no_anchor = score_poi(poi, _intent(), variant="main")
    assert s_no_anchor - s >= 50.0


def test_build_candidate_pool_filters_out_of_radius_when_anchor_set():
    """有 anchor 时, 远 POI 直接被过滤出候选池."""
    pois = [
        _make_poi("近 1", "n1", 22.541, 114.057),
        _make_poi("近 2", "n2", 22.542, 114.058),
        _make_poi("远 1", "f1", 22.60, 114.30),  # 30km 外
    ]
    intent = _intent(
        anchor_lat=22.541, anchor_lng=114.057, anchor_radius_km=3.0
    )
    pool = build_candidate_pool(pois=pois, intent=intent, variant="main")
    all_names = [p.name for bucket in (pool.city_essential, pool.persona_preferred,
                                       pool.meal, pool.connector) for p in bucket]
    assert "远 1" not in all_names
    assert "近 1" in all_names


def test_build_candidate_pool_no_anchor_keeps_old_behavior():
    """没 anchor 时, 城市范围内全保留 (老 v1.7 行为)."""
    pois = [
        _make_poi("近", "n1", 22.541, 114.057),
        _make_poi("远", "f1", 22.6, 114.3),
    ]
    intent = _intent()  # 无 anchor
    pool = build_candidate_pool(pois=pois, intent=intent, variant="main")
    all_names = [p.name for bucket in (pool.city_essential, pool.persona_preferred,
                                       pool.meal, pool.connector) for p in bucket]
    assert "近" in all_names
    assert "远" in all_names
```

- [ ] **Step 2: Run test, 验证 FAIL**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_candidate_pool_v18_anchor.py -v
```
Expected: 4 FAIL (anchor 字段在 score_poi 不生效)

- [ ] **Step 3: 改 candidate_pool.py**

`agents/candidate_pool.py:74` `score_poi` 函数末尾 `return score` 之前加：

```python
    # v1.8 anchor distance_penalty (Spec §4.1)
    if intent.anchor_lng is not None and intent.anchor_lat is not None:
        from agents.anchor import _haversine_km

        d_km = _haversine_km(
            (intent.anchor_lng, intent.anchor_lat),
            (poi.longitude, poi.latitude),
        )
        radius = intent.anchor_radius_km or 3.0
        if d_km <= radius / 2:  # 半径一半内不扣
            pass
        elif d_km <= radius:
            score -= (d_km - radius / 2) * 10  # 线性扣
        else:
            score -= 50 + (d_km - radius) * 20  # 超出硬扣

    return score
```

`agents/candidate_pool.py:193-198` 在 `for poi in pois:` 循环里, `if poi.city != intent.city:` 之后加 radius hard filter:

```python
    for poi in pois:
        if poi.city != intent.city:
            continue
        # v1.8: 有 anchor 时硬过滤掉超出 radius 2x 的 POI (太远连进池都不该)
        if intent.anchor_lng is not None and intent.anchor_lat is not None:
            from agents.anchor import _haversine_km

            d = _haversine_km(
                (intent.anchor_lng, intent.anchor_lat),
                (poi.longitude, poi.latitude),
            )
            if d > (intent.anchor_radius_km or 3.0) * 2:
                continue
        bucket = _bucket_of(poi)
```

- [ ] **Step 4: Run test, 验证 PASS**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_candidate_pool_v18_anchor.py -v
PYTHONPATH=. venv/bin/pytest tests/test_candidate_pool_v17.py -v
```
Expected: 全 PASS, 老 v1.7 测试不破

- [ ] **Step 5: Commit**

```bash
git add agents/candidate_pool.py tests/test_candidate_pool_v18_anchor.py
git commit -m "feat(v1.8): candidate_pool 加 anchor distance_penalty + radius filter"
```

---

## Task 5: Profiler 接 anchor.resolve_anchor + trip_router

**Files:**
- Modify: `agents/profiler.py:89-186` (Profiler.run method)
- Test: `tests/test_profiler_v18.py`

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_profiler_v18.py`:

```python
"""v1.8 Profiler 集成 anchor + trip_router 单测."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from agents.context import TripContext
from agents.profiler import Profiler
from dianping.schemas import UserInput


@pytest.mark.asyncio
async def test_profiler_resolves_anchor_and_sets_trip_mode_explore():
    """用户说"万象天地附近" → trip_mode=anchor_explore + anchor 坐标已填."""
    fake_llm = AsyncMock(return_value=json.dumps({
        "city": "深圳",
        "days": 1,
        "traveler_type": "情侣",
        "time_window": "一日",
        "start_location_text": "万象天地",
    }))

    from agents.anchor import AnchorResolution
    fake_anchor = AnchorResolution(
        text="万象天地", name="深圳万象天地",
        lng=114.057, lat=22.541, adcode="440304",
        formatted_address="深圳市福田区万象天地", confidence="high",
    )
    with patch("agents.profiler._resolve_anchor", new=AsyncMock(return_value=fake_anchor)):
        profiler = Profiler(llm_call=fake_llm)
        ctx = TripContext.create(
            user_input=UserInput(free_text="深圳明天我想去万象天地附近转一转")
        )
        out = await profiler.run(ctx)

    assert out.understood.trip_mode == "anchor_explore"
    assert out.understood.anchor_lng == 114.057
    assert out.understood.anchor_lat == 22.541
    assert out.understood.anchor_resolved_name == "深圳市福田区万象天地"
    assert out.understood.anchor_radius_km == 4.0  # DEFAULT_ANCHOR_RADIUS_KM


@pytest.mark.asyncio
async def test_profiler_layover_sets_hub_type_and_safety_margin():
    """中转场景: hub_type=train + safety_margin=30."""
    fake_llm = AsyncMock(return_value=json.dumps({
        "city": "上海",
        "days": 1,
        "traveler_type": "独行",
        "time_window": "一日",
        "start_location_text": "上海站",
        "estimated_hours": 7,
    }))

    from agents.anchor import AnchorResolution
    fake_anchor = AnchorResolution(
        text="上海站", name="上海站",
        lng=121.456, lat=31.249, adcode="310101",
        formatted_address="上海站", confidence="high",
    )
    with patch("agents.profiler._resolve_anchor", new=AsyncMock(return_value=fake_anchor)):
        profiler = Profiler(llm_call=fake_llm)
        ctx = TripContext.create(
            user_input=UserInput(free_text="上海中转 7 小时 想吃吃吃 然后赶火车")
        )
        out = await profiler.run(ctx)

    assert out.understood.trip_mode == "layover_eat"
    assert out.understood.hub_type == "train"
    assert out.understood.safety_margin_min == 30


@pytest.mark.asyncio
async def test_profiler_anchor_failure_falls_back_to_landmark_must():
    """geocode 失败: trip_mode=landmark_must, anchor 坐标=None."""
    fake_llm = AsyncMock(return_value=json.dumps({
        "city": "西安", "days": 1, "traveler_type": "情侣",
        "time_window": "半日_下午",
        "start_location_text": "不存在的地名XYZ",
    }))
    with patch("agents.profiler._resolve_anchor", new=AsyncMock(return_value=None)):
        profiler = Profiler(llm_call=fake_llm)
        ctx = TripContext.create(
            user_input=UserInput(free_text="西安半天 想去不存在的地名XYZ 拍照")
        )
        out = await profiler.run(ctx)

    # geocode 失败 + 没 layover 关键词 → 退化 landmark_must (透明告知前端走)
    assert out.understood.trip_mode == "landmark_must"
    assert out.understood.anchor_lng is None


@pytest.mark.asyncio
async def test_profiler_no_anchor_text_routes_landmark_must():
    """用户没说任何锚点 → landmark_must."""
    fake_llm = AsyncMock(return_value=json.dumps({
        "city": "西安", "days": 1, "traveler_type": "情侣", "time_window": "半日_下午",
    }))
    profiler = Profiler(llm_call=fake_llm)
    ctx = TripContext.create(user_input=UserInput(free_text="西安半天拍照"))
    out = await profiler.run(ctx)
    assert out.understood.trip_mode == "landmark_must"
    assert out.understood.anchor_lng is None


@pytest.mark.asyncio
async def test_profiler_multi_day_routes_multi_day():
    fake_llm = AsyncMock(return_value=json.dumps({
        "city": "西安", "days": 3, "traveler_type": "情侣",
    }))
    profiler = Profiler(llm_call=fake_llm)
    ctx = TripContext.create(user_input=UserInput(free_text="情侣 西安 3 天"))
    out = await profiler.run(ctx)
    assert out.understood.trip_mode == "multi_day"
```

- [ ] **Step 2: Run test, 验证 FAIL**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_profiler_v18.py -v
```
Expected: 5 FAIL (profiler 不动 trip_mode + anchor)

- [ ] **Step 3: 改 profiler.py**

在 `agents/profiler.py:186` (ctx.intent = understood 之前) 加 anchor + trip_router 集成。

找到 `ctx.intent = understood` 这一行，在它之前插入：

```python
        # v1.8 trip_mode 路由 + anchor 解析
        from agents.anchor import resolve_anchor as _resolve_anchor
        from agents.trip_router import (
            DEFAULT_ANCHOR_RADIUS_KM,
            compute_safety_margin,
            infer_hub_type,
            route_trip_mode,
        )

        # 1) Resolve anchor (best-effort, 失败不阻塞)
        if understood.start_location_text and understood.city:
            try:
                anchor = await _resolve_anchor(
                    understood.start_location_text, understood.city
                )
            except Exception as aerr:
                anchor = None
                ctx.log_event("Profiler", "anchor_failed", {"error": str(aerr)})
            if anchor is not None:
                understood.anchor_lng = anchor.lng
                understood.anchor_lat = anchor.lat
                understood.anchor_resolved_name = anchor.name

        # 2) Route trip_mode (规则路由, LLM 已抽 trip_mode 则尊重)
        if not understood.trip_mode:
            understood.trip_mode = route_trip_mode(
                understood, ctx.user_input.free_text
            )

        # 3) Layover: 推 hub_type + safety_margin
        if understood.trip_mode in ("layover_eat", "layover_explore"):
            if not understood.hub_type:
                understood.hub_type = infer_hub_type(
                    understood.start_location_text
                )
            if understood.safety_margin_min is None:
                # at_date 留 None (Profiler 阶段不知道用户哪天用), 节假日 buffer 后续可加
                understood.safety_margin_min = compute_safety_margin(
                    understood.hub_type
                )

        # 4) Anchor_explore: 默认半径 (冷启动后续覆盖)
        if (
            understood.trip_mode == "anchor_explore"
            and understood.anchor_radius_km is None
        ):
            understood.anchor_radius_km = DEFAULT_ANCHOR_RADIUS_KM

        # 5) 锚点解析失败 + 用户提了锚点 + 非多日 → 降级 landmark_must
        if (
            understood.start_location_text
            and understood.anchor_lng is None
            and understood.trip_mode in ("anchor_explore", "layover_eat", "layover_explore")
        ):
            understood.trip_mode = "landmark_must"
```

- [ ] **Step 4: Run test, 验证 PASS**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_profiler_v18.py -v
```
Expected: 5 PASS

- [ ] **Step 5: 回归测试**

```bash
PYTHONPATH=. venv/bin/pytest tests/ -q --ignore=tests/test_user_profile_cleaning.py
```
Expected: 累计 testbase + 5 新 PASS, 1 known flaky

- [ ] **Step 6: Commit**

```bash
git add agents/profiler.py tests/test_profiler_v18.py
git commit -m "feat(v1.8): profiler 集成 anchor 解析 + trip_router + hub_type"
```

---

## Task 6: stub_llm 加 trip_mode 关键词 + anchor 抽取

**Files:**
- Modify: `api/stub_llm.py:59-150` (stub_profiler_llm function)
- Test: `tests/test_stub_llm_v18.py`

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_stub_llm_v18.py`:

```python
"""v1.8 stub_profiler_llm 加 trip_mode / hub_type / start_location 关键词识别."""

import json

import pytest

from api.stub_llm import stub_profiler_llm


@pytest.mark.asyncio
async def test_stub_extracts_wanxiang_tiandi_as_anchor():
    out = json.loads(await stub_profiler_llm(
        "", "深圳明天我想去万象天地附近转一转"
    ))
    assert out["city"] == "深圳"
    assert out["start_location_text"] == "万象天地"


@pytest.mark.asyncio
async def test_stub_extracts_shanghai_station_as_anchor():
    out = json.loads(await stub_profiler_llm(
        "", "上海中转 7 小时 想吃吃吃 然后赶火车 在上海站"
    ))
    assert out["start_location_text"] == "上海站"


@pytest.mark.asyncio
async def test_stub_extracts_estimated_hours_from_x_hours():
    out = json.loads(await stub_profiler_llm("", "上海中转 7 小时 想转转"))
    assert out["estimated_hours"] == 7
```

- [ ] **Step 2: Run test, 验证 FAIL**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_stub_llm_v18.py -v
```
Expected: 3 FAIL (stub 老正则只识别"我现在在 X 附近")

- [ ] **Step 3: 改 stub_llm.py**

`api/stub_llm.py:53-55` 替换 `_START_LOC_PAT`:

```python
_START_LOC_PAT = re.compile(
    r"我?现在在([^,，。.！!？?\s]+?)(附近|这|这里|这边)?(?=[,，。.！!？?\s]|$)"
)
# v1.8 通用锚点抽取: 万象天地附近 / 在 X 站 / X 机场 / 想去 X 附近
_ANCHOR_PATS = [
    re.compile(r"想?去?(?:在)?([^\s,，。.！!？?]+?)(?:附近|周边|这边|这里|一带)"),
    re.compile(r"(?:在|从)([^\s,，。.！!？?]+(?:站|机场|客运站))"),
]
_HOURS_PAT = re.compile(r"(\d+)\s*(?:个)?小时")
```

`api/stub_llm.py:124` 替换 `loc_match = _START_LOC_PAT.search(user)` 块:

```python
    # v1.8 锚点抽取: 三正则按优先级试, 命中即停
    start_location_text = None
    loc_match = _START_LOC_PAT.search(user)
    if loc_match:
        start_location_text = loc_match.group(1)
    else:
        for pat in _ANCHOR_PATS:
            m = pat.search(user)
            if m:
                cand = m.group(1).strip()
                # 过滤短噪音 (≤ 1 字 / 含数字)
                if len(cand) >= 2 and not any(c.isdigit() for c in cand):
                    start_location_text = cand
                    break
```

`api/stub_llm.py:131` 在 `estimated_hours = None` 那行附近, 加 hours 抽取:

```python
    # v1.8: "X 小时" 显式抽 (覆盖原 time_window 估算)
    hours_match = _HOURS_PAT.search(user)
    if hours_match:
        estimated_hours = int(hours_match.group(1))
```

- [ ] **Step 4: Run test, 验证 PASS**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_stub_llm_v18.py -v
```
Expected: 3 PASS

- [ ] **Step 5: 回归测试 (stub 老路径不破)**

```bash
PYTHONPATH=. venv/bin/pytest tests/ -q --ignore=tests/test_user_profile_cleaning.py
```
Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
git add api/stub_llm.py tests/test_stub_llm_v18.py
git commit -m "feat(v1.8): stub_llm 加锚点抽取 + 小时数 + 通用 anchor 正则"
```

---

## Task 7: planner_instant 接真实 anchor

**Files:**
- Modify: `agents/planner_instant.py:186-245` (plan_one_variant function)
- Test: `tests/test_planner_instant_v18.py`

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_planner_instant_v18.py`:

```python
"""v1.8: planner_instant 用真实 anchor 坐标 (而非第一个 POI)."""

from datetime import time

import pytest

from agents.planner_instant import plan_one_variant
from dianping.schemas import POI, EnrichedLabel, ParsedIntent


def _make_poi(name, openshopid, lat, lng):
    p = POI(
        openshopid=openshopid, name=name, city="深圳",
        latitude=lat, longitude=lng,
        categories=["景点"], avgprice=100, star=4.5, business_hour="09:00-21:00",
    )
    p.enriched = EnrichedLabel(
        poi_role="city_essential", manual_priority=90, city_zone="福田"
    )
    return p


@pytest.mark.asyncio
async def test_plan_one_variant_uses_intent_anchor_lng_lat_when_set(monkeypatch):
    """anchor_lng/lat 在 intent 已设 → compose_one_day 收到 真实 anchor, 不是 POI[0]."""
    intent = ParsedIntent(
        city="深圳", days=1, traveler_type="情侣",
        time_window="一日",
        trip_mode="anchor_explore",
        anchor_lng=114.057, anchor_lat=22.541,
        anchor_resolved_name="深圳万象天地",
        anchor_radius_km=3.0,
    )
    pois = [_make_poi("近 POI", "n1", 22.542, 114.058)]

    captured_anchor = {}

    class _FakePlanner:
        async def compose_one_day(self, *, day_idx, intent, template, anchor,
                                   day_cluster_pois, amap, on_partial=None):
            captured_anchor["a"] = anchor
            from dianping.schemas import DayPlan
            return day_idx, DayPlan(day_index=0, anchor_district=anchor[0], stops=[]), []

    class _FakeAmap:
        pass

    # 监 _synthesize_fallback_route 不被调
    async def _no_transit(*a, **kw):
        return 0, []

    monkeypatch.setattr("api.routes._compute_day_transits", _no_transit)
    # 跳过 PlannerLLMError 路径 — compose_one_day 直接返回空 stops 但有 anchor
    # 把 plan_one_variant 内的 PlannerLLMError 设为 Exception 子类不会捕获的状态
    # → 让 captured_anchor 有值即可断言

    try:
        await plan_one_variant(
            intent=intent, variant="main", planner=_FakePlanner(),
            amap=_FakeAmap(), pois=pois,
        )
    except Exception:
        pass

    assert captured_anchor["a"][0] == "深圳万象天地"
    assert captured_anchor["a"][1] == 22.541  # lat
    assert captured_anchor["a"][2] == 114.057  # lng


@pytest.mark.asyncio
async def test_plan_one_variant_falls_back_to_first_poi_when_no_anchor(monkeypatch):
    """没设 anchor_lng/lat → 仍用 POI[0] (v1.7 行为兼容)."""
    intent = ParsedIntent(
        city="深圳", days=1, traveler_type="情侣", time_window="一日",
    )
    pois = [_make_poi("第一 POI", "n1", 22.5, 114.0)]

    captured_anchor = {}

    class _FakePlanner:
        async def compose_one_day(self, *, day_idx, intent, template, anchor,
                                   day_cluster_pois, amap, on_partial=None):
            captured_anchor["a"] = anchor
            from dianping.schemas import DayPlan
            return day_idx, DayPlan(day_index=0, anchor_district=anchor[0], stops=[]), []

    class _FakeAmap:
        pass

    async def _no_transit(*a, **kw):
        return 0, []
    monkeypatch.setattr("api.routes._compute_day_transits", _no_transit)

    try:
        await plan_one_variant(
            intent=intent, variant="main", planner=_FakePlanner(),
            amap=_FakeAmap(), pois=pois,
        )
    except Exception:
        pass

    assert captured_anchor["a"][1] == 22.5
    assert captured_anchor["a"][2] == 114.0
```

- [ ] **Step 2: Run test, 验证 FAIL**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_planner_instant_v18.py -v
```
Expected: 第一个 FAIL (老逻辑用 POI[0])

- [ ] **Step 3: 改 planner_instant.py**

替换 `agents/planner_instant.py:204-210` 的 anchor 构造:

```python
    # v1.8: 优先用 intent.anchor_lng/lat (来自高德 geocode); 兜底 POI[0]
    if intent.anchor_lng is not None and intent.anchor_lat is not None:
        anchor_name = intent.anchor_resolved_name or intent.start_location_text or "锚点"
        anchor_lat = intent.anchor_lat
        anchor_lng = intent.anchor_lng
    else:
        anchor_name = intent.start_location_text or (
            flat_pois[0].name if flat_pois else "市中心"
        )
        anchor_lat = flat_pois[0].latitude if flat_pois else 0.0
        anchor_lng = flat_pois[0].longitude if flat_pois else 0.0
    anchor = (anchor_name, anchor_lat, anchor_lng)
```

- [ ] **Step 4: Run test, 验证 PASS**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_planner_instant_v18.py -v
```
Expected: 2 PASS

- [ ] **Step 5: 回归测试**

```bash
PYTHONPATH=. venv/bin/pytest tests/ -q --ignore=tests/test_user_profile_cleaning.py
```
Expected: 全 PASS (老 v1.7 instant 测试也 PASS)

- [ ] **Step 6: Commit**

```bash
git add agents/planner_instant.py tests/test_planner_instant_v18.py
git commit -m "feat(v1.8): planner_instant 优先用真实 anchor 坐标"
```

---

## Task 8: prompts/profiler.md + planner.md 改造

**Files:**
- Modify: `agents/prompts/profiler.md`
- Modify: `agents/prompts/planner.md`

注意: prompt 文件没法单测, 只能改完后真 LLM 跑过. 本任务跑完后立刻进 Task 10 验证.

- [ ] **Step 1: 改 profiler.md**

在 `agents/prompts/profiler.md` 文件末尾追加段:

```markdown

## v1.8 trip_mode 推断

根据用户描述, 在结构化输出 JSON 加 `trip_mode` 字段, 取值之一:

- `"anchor_explore"`: 用户提到具体地点 ("万象天地附近"/"我在某某这边") + 想转转
- `"layover_eat"`: 中转停留, 主要想吃吃吃 (含"中转/路过/赶火车/赶飞机" + "吃/美食/餐厅"等)
- `"layover_explore"`: 中转停留, 主要想看看 (含上述 hub 关键词 + "看/玩/逛/景点")
- `"landmark_must"`: 没指定具体锚点, 来这城市玩 ("西安半天拍照")
- `"multi_day"`: 多天行程 (days ≥ 2 时强制此值)

同时输出:
- `"hub_type"`: layover 时给出 "train" | "highspeed" | "airport" | "bus"
- `"anchor_radius_km"`: anchor_explore 时, 用户提到"散步/走着去" → 2, "骑车" → 4, "坐车/远点也行" → 6. 默认 4.

JSON 输出示例:
```json
{
  "city": "深圳", "days": 1, "traveler_type": "情侣", "time_window": "一日",
  "start_location_text": "万象天地",
  "trip_mode": "anchor_explore",
  "anchor_radius_km": 4,
  "interests": ["拍照", "美食"]
}
```
```

- [ ] **Step 2: 改 planner.md**

在 `agents/prompts/planner.md` 末尾追加段:

```markdown

## v1.8 trip_mode 模式约束

输入 user payload 含 `trip_mode` 字段时, 必须遵守以下约束:

### anchor_explore
- 所有 stops 必须在 anchor 半径 `anchor_radius_km` 内 (payload 给出)
- 最后一站尽量回 anchor 附近 (1km 内)
- 跨 zone 应当避免

### layover_eat
- 行程以美食为主 (至少 60% stops 是 categories 含"美食")
- 最后一站必须 ≤ 1km 回 anchor (火车站/机场)
- 总耗时不超过 `(estimated_hours * 60 - safety_margin_min)` 分钟

### layover_explore
- 行程以景点/观光为主
- 最后一站必须 ≤ 1km 回 anchor
- 总耗时不超过 `(estimated_hours * 60 - safety_margin_min)` 分钟

### landmark_must
- 优先 city_essential POI (manual_priority ≥ 80 通常是)
- 集中一个 city_zone, 减少跨区奔波

### multi_day
- 按 day_index 顺序排, 每天集中一个 city_zone
- 走 v1.6 老多日逻辑
```

- [ ] **Step 3: Commit**

```bash
git add agents/prompts/profiler.md agents/prompts/planner.md
git commit -m "feat(v1.8): profiler/planner prompts 加 trip_mode 推断和模式约束"
```

---

## Task 9: plan_stack.html 画半径圈 + anchor ★

**Files:**
- Modify: `web/plan_stack.html` (找 `case 'planner.day_done':` 或 anchor 渲染处, 加 anchor circle + marker)

- [ ] **Step 1: 找到合适的渲染锚点**

```bash
grep -n "AMap.Circle\|AMap.Marker\|fitMapToAllMarkers\|trip.complete\|planner.done" web/plan_stack.html
```

- [ ] **Step 2: 加 anchor circle + ★ marker 渲染逻辑**

在 `case 'trip.complete':` 之后 (~line 680) 加:

```javascript
    // v1.8: anchor_explore 模式画半径圈 + ★ marker
    if (trip && trip.intent && trip.intent.trip_mode === 'anchor_explore'
        && trip.intent.anchor_lng && trip.intent.anchor_lat) {
      drawAnchorCircle(
        trip.intent.anchor_lng,
        trip.intent.anchor_lat,
        (trip.intent.anchor_radius_km || 4) * 1000,
        trip.intent.anchor_resolved_name || trip.intent.start_location_text
      );
    }
```

在文件末尾 `</script>` 之前加函数:

```javascript
let anchorCircle = null;
let anchorMarker = null;

function drawAnchorCircle(lng, lat, radius_m, name) {
  if (!map) return;
  // 清除老的
  if (anchorCircle) map.remove(anchorCircle);
  if (anchorMarker) map.remove(anchorMarker);

  anchorCircle = new AMap.Circle({
    center: [lng, lat],
    radius: radius_m,
    strokeColor: '#ff3e00',
    strokeOpacity: 0.6,
    strokeWeight: 2,
    strokeStyle: 'dashed',
    fillColor: '#ff3e00',
    fillOpacity: 0.08,
    zIndex: 50,
  });
  anchorMarker = new AMap.Marker({
    position: [lng, lat],
    icon: new AMap.Icon({
      size: new AMap.Size(36, 36),
      imageSize: new AMap.Size(36, 36),
      image: 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 36"><circle cx="18" cy="18" r="14" fill="%23ff3e00" stroke="white" stroke-width="3"/><text x="18" y="24" text-anchor="middle" font-size="18" fill="white">★</text></svg>',
    }),
    offset: new AMap.Pixel(-18, -18),
    zIndex: 120,
    title: name || '锚点',
  });
  map.add(anchorCircle);
  map.add(anchorMarker);
}
```

- [ ] **Step 3: 浏览器手动验** (Task 10 一并验, 这一步不需要单独验)

- [ ] **Step 4: Commit**

```bash
git add web/plan_stack.html
git commit -m "feat(v1.8): plan_stack.html anchor_explore 模式画半径圈和 ★"
```

---

## Task 10: 浏览器 e2e 三场景验证

**Files:**
- 无文件改动, 只验证

- [ ] **Step 1: 启服务**

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
pkill -9 -f uvicorn 2>/dev/null; sleep 1
PYTHONPATH=. venv/bin/uvicorn dianping.mock_server:mock_app --host 127.0.0.1 --port 9192 &
set -a && source .env && set +a && unset MTAGENT_AMAP_DISABLED && \
  PYTHONPATH=. venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 9191 &
sleep 3
```

- [ ] **Step 2: 场景 A — anchor_explore (修 P0 #1)**

浏览器打开 `http://127.0.0.1:9191/`, 输入: `深圳明天我想去万象天地附近转一转`

预期:
- chat: "听清啦 📍 深圳 · 📅 1 天 · 👥 情侣"
- chat: "为你准备 3 个方案 ✨ 主推荐先出, 备选稍后"
- 地图: 福田区, anchor ★ + 半透明橙色 4km 半径圈
- stops: 全部在万象天地 3-4km 内, 不再出现东湖公园/南头古城等远 POI
- chat: "🧘 少排队 / 💖 兴趣优先" 备选 chip
- chat 末尾: "行程画好啦"

```bash
# 后端验证 (并行)
curl -s -X POST http://127.0.0.1:9191/api/plan/stream \
  -H 'Content-Type: application/json' \
  -d '{"free_text":"深圳明天我想去万象天地附近转一转"}' \
  > /tmp/scene_a.txt
grep -E 'trip_mode|anchor_lng|profiler.understood' /tmp/scene_a.txt | head -5
```

Expected: `trip_mode: anchor_explore` + `anchor_lng: 114.0x` + 所有 stops 距 anchor < 4km

- [ ] **Step 3: 场景 B — layover_eat**

输入: `上海中转 7 小时 想吃吃吃 之后赶火车`

预期:
- trip_mode=layover_eat
- hub_type=train
- safety_margin_min=30
- 60% stops 含美食 categories
- 最后一站靠近上海站

- [ ] **Step 4: 场景 C — landmark_must (兼容)**

输入: `西安半天拍照`

预期: 走老 v1.7 路径 (没 anchor), trip_mode=landmark_must, 测试 baseline 行为不破.

- [ ] **Step 5: 场景 D — multi_day (兼容)**

输入: `情侣 西安 3 天`

预期: 走 v1.6 多日老路径, trip_mode=multi_day, 不动 anchor.

- [ ] **Step 6: 全测试回归**

```bash
PYTHONPATH=. venv/bin/pytest tests/ -q --ignore=tests/test_user_profile_cleaning.py
```
Expected: 188 (baseline) + 4 (Task 1) + 9 (Task 2) + 8 (Task 3) + 4 (Task 4) + 5 (Task 5) + 3 (Task 6) + 2 (Task 7) = 223 passed, 1 known flaky

- [ ] **Step 7: 最终 commit**

```bash
git log --oneline -10
git status
# 若有 prompt 改后没补的测试调整, 在这一步补
```

---

## 验收 (Acceptance)

✅ **修 P0 #1**: 用户说"万象天地附近" → 所有 stops 在万象天地 4km 内
✅ **5 mode 路由**: anchor_explore / layover_eat / layover_explore / landmark_must / multi_day 都覆盖
✅ **layover 安全**: 火车 30min / 飞机 2h buffer, 最后一站 ≤ 1km 回锚点
✅ **不破基线**: 188 测试 + 1 flaky → 223+ 测试 + 1 flaky
✅ **不破老路径**: v1.6 多日 / v1.7 instant 单测全 PASS
✅ **前端**: anchor_explore 半径圈 + ★ marker 渲染

## 不在本计划范围

- ❌ 几何形态算法 (solve_cycle / solve_layover 几何优化) — P1, 当前靠 candidate_pool distance_penalty 已能让 LLM 选近的
- ❌ 冷启动表单 (localStorage 偏好) — P2
- ❌ 前端 3-tab UI 完整版 — 老 TODO 不动
- ❌ Planner LLM Prompt 改造 (4 桶结构喂 LLM) — 老 TODO, 跟本任务并行不冲突, 不在本 PR
