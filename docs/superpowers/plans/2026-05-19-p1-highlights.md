# P1 Highlights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 hackathon demo 的"AI 决策可见性"从 day 级下沉到 stop 级，把 Critic 从 stub 升成真规则检查，把已有 UserProfile 在 UI 主流程露出，让评委一眼看到"系统知道我是谁、为什么这么选、自己复检过"。

**Architecture:**
- P1.1 在 day_done 之后逐 stop yield `planner.stop_rationale`，纯函数从 `Stop` + `ParsedIntent` 推 reason（用 `enriched.must_consider` / `intent.must_visit` 子串 / `planning_tags` / variant 标签），不污染 Stop schema。
- P1.2 `agents/critic.py` 复用现有 `route_validator.validate_route` 的 6 条规则，把 failed checks 转 `Patch` 列表 + 通过 `critic.findings` SSE 事件向前端吐"我自检发现 N 处问题"。不引入 LLM，规则即可。
- P1.3 前端 `plan_stack.html` 在 hero 区加"你的画像"卡片，挂在已有 `initPrefModal()` 流程之后，复用 `GET /api/user/profile`，无后端新接口。

**Tech Stack:** Python 3.12 / FastAPI / SSE / pytest / 原生 HTML+JS（无框架）

---

## File Structure

新增：
- `tests/test_rationale_per_stop.py` — P1.1 stop 级 rationale 纯函数测试
- `tests/test_critic_real.py` — P1.2 Critic 转换 route_validator → Patch 列表测试

修改：
- `agents/rationale.py` — 新增 `build_rationale_for_stop(intent, stop) -> dict`
- `api/routes.py` — `day_done` 后逐 stop yield `planner.stop_rationale`；Critic 段加 `critic.findings`
- `agents/critic.py` — `run()` 真跑 `validate_route`，把 failed checks 翻译成 `Patch`
- `web/plan_stack.html` — 加 `case 'planner.stop_rationale'`、`case 'critic.findings'`，hero 区"你的画像"卡片

不动：
- `dianping/schemas.py`（Stop 不加 reason 字段，rationale 在事件层组装）
- `agents/route_validator.py`（Critic 只复用，不改规则）
- 后端 `/api/user/profile` GET/PUT（已够用）

---

## Task 1: P1.1 stop 级 rationale 纯函数

**Files:**
- Modify: `agents/rationale.py`（在 `build_rationale_for_day` 之后追加）
- Test: `tests/test_rationale_per_stop.py`（新文件）

- [ ] **Step 1: 写失败测试 — must_visit 子串命中走 must_visit 分支**

新文件 `tests/test_rationale_per_stop.py`：

```python
"""Stop 级 rationale 纯函数测试."""
from datetime import time

from agents.rationale import build_rationale_for_stop
from dianping.schemas import POI, EnrichedLabel, ParsedIntent, Stop, TimeSlot


def _make_stop(name: str, *, categories=None, enriched=None) -> Stop:
    poi = POI(
        openshopid=f"id-{name}",
        name=name,
        categories=categories or [],
        avgprice=80,
        star=4.5,
        longitude=115.89,
        latitude=28.68,
        enriched=enriched,
    )
    return Stop(
        poi=poi,
        slot=TimeSlot(name="上午景点", start=time(9, 0), end=time(11, 0)),
        arrival_time=time(9, 0),
        leave_time=time(11, 0),
    )


def test_must_visit_substring_hit_uses_user_keyword():
    intent = ParsedIntent(city="南昌", days=1, must_visit=["南昌博物馆"])
    stop = _make_stop("江西省博物馆")
    r = build_rationale_for_stop(intent, stop, variant="main")
    assert r["stage"] == "stop"
    assert r["poi_name"] == "江西省博物馆"
    assert "南昌博物馆" in r["text"]  # 用用户原话回引
    assert "must_visit" in r["key_factors"]
```

- [ ] **Step 2: 跑测试确认 fail**

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
PYTHONPATH=. venv/bin/pytest tests/test_rationale_per_stop.py -v
```

Expected: FAIL — `ImportError: cannot import name 'build_rationale_for_stop'`

- [ ] **Step 3: 在 `agents/rationale.py` 末尾追加最小实现**

在文件末尾追加：

```python
def build_rationale_for_stop(
    intent: ParsedIntent,
    stop,
    variant: str = "main",
) -> dict:
    """Stop 级 rationale dict。

    优先级（高 → 低）：
    1. must_visit 子串命中 → "因为你说想去 {user_keyword}"
    2. must_consider（amap inject） → "你点名的 {slot}"
    3. variant 偏置 → "low_queue 偏分店 / interest_first 偏文化"
    4. planning_tags 命中 traveler/preference → "适合 {traveler_type}+{tag}"
    5. fallback → "{slot} 就近顺路"
    """
    poi = stop.poi
    factors: list[str] = [f"variant={variant}", f"slot={stop.slot.name}"]
    text: str

    # 1. must_visit 子串
    user_keyword = _match_must_visit(poi.name, intent.must_visit or [])
    if user_keyword:
        text = f"因为你说想去「{user_keyword}」，我挑了「{poi.name}」对上。"
        factors.append("must_visit")
        return {
            "stage": "stop",
            "poi_name": poi.name,
            "slot_name": stop.slot.name,
            "variant": variant,
            "text": text,
            "key_factors": factors,
        }

    enriched = poi.enriched
    # 2. amap inject (must_consider)
    if enriched and enriched.must_consider:
        text = f"你点名要的{stop.slot.name}，我从地图实搜补了「{poi.name}」。"
        factors.append("amap_inject")
        return _wrap(stop, variant, text, factors)

    # 3. variant 偏置
    variant_text = _variant_phrase(variant, poi.name, enriched)
    if variant_text:
        text = variant_text
        factors.append(f"variant_bias={variant}")
        return _wrap(stop, variant, text, factors)

    # 4. planning_tags + traveler_type
    if enriched and enriched.planning_tags:
        tags = "/".join(enriched.planning_tags[:2])
        traveler = intent.traveler_type or ""
        if traveler:
            text = f"{stop.slot.name}选「{poi.name}」——{tags}，适合{traveler}。"
        else:
            text = f"{stop.slot.name}选「{poi.name}」，主打{tags}。"
        factors.append(f"tags={tags}")
        return _wrap(stop, variant, text, factors)

    # 5. fallback
    text = f"{stop.slot.name}就近顺路串「{poi.name}」。"
    factors.append("fallback")
    return _wrap(stop, variant, text, factors)


def _match_must_visit(poi_name: str, must_visit: list[str]) -> str:
    """返回首个子串命中的用户原话；都没命中返 ''。"""
    for kw in must_visit:
        if not kw:
            continue
        # 双向子串：用户"南昌博物馆" vs poi"江西省博物馆"
        if kw in poi_name or poi_name in kw:
            return kw
        # 去掉城市前缀再试
        core = kw
        for prefix in ("南昌", "深圳", "上海", "西安"):
            if core.startswith(prefix):
                core = core[len(prefix):]
                break
        if core and (core in poi_name or poi_name in core):
            return kw
    return ""


def _variant_phrase(variant: str, poi_name: str, enriched) -> str:
    if variant == "low_queue":
        if "分店" in poi_name or "二分店" in poi_name or "新店" in poi_name:
            return f"备选「少排队」方案，挑了人少的分店「{poi_name}」。"
        return ""
    if variant == "interest_first":
        if enriched and any(
            t in ("文化", "历史", "人文", "小众") for t in enriched.planning_tags
        ):
            return f"备选「兴趣优先」方案，文化向「{poi_name}」。"
        return ""
    return ""


def _wrap(stop, variant: str, text: str, factors: list[str]) -> dict:
    return {
        "stage": "stop",
        "poi_name": stop.poi.name,
        "slot_name": stop.slot.name,
        "variant": variant,
        "text": text,
        "key_factors": factors,
    }
```

- [ ] **Step 4: 跑测试确认 pass**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_rationale_per_stop.py -v
```

Expected: 1 PASS

- [ ] **Step 5: 加 must_consider / variant / planning_tags / fallback 测试**

在 `tests/test_rationale_per_stop.py` 追加：

```python
def test_must_consider_amap_inject_branch():
    intent = ParsedIntent(city="南昌", days=1, must_visit=[])
    enriched = EnrichedLabel(must_consider=True)
    stop = _make_stop("瓦罐汤(胜利路店)", enriched=enriched)
    r = build_rationale_for_stop(intent, stop)
    assert "地图实搜" in r["text"]
    assert "amap_inject" in r["key_factors"]


def test_low_queue_variant_prefers_branch_store():
    intent = ParsedIntent(city="南昌", days=1)
    stop = _make_stop("小罗子汤店(二分店)")
    r = build_rationale_for_stop(intent, stop, variant="low_queue")
    assert "少排队" in r["text"] and "分店" in r["text"]
    assert "variant_bias=low_queue" in r["key_factors"]


def test_interest_first_variant_prefers_culture_tag():
    intent = ParsedIntent(city="南昌", days=1)
    enriched = EnrichedLabel(planning_tags=["文化", "历史"])
    stop = _make_stop("八一起义纪念馆", enriched=enriched)
    r = build_rationale_for_stop(intent, stop, variant="interest_first")
    assert "兴趣优先" in r["text"] or "文化向" in r["text"]


def test_planning_tags_with_traveler_type():
    intent = ParsedIntent(city="南昌", days=1, traveler_type="情侣")
    enriched = EnrichedLabel(planning_tags=["拍照", "氛围"])
    stop = _make_stop("秋水广场", enriched=enriched)
    r = build_rationale_for_stop(intent, stop)
    assert "情侣" in r["text"]
    assert "拍照" in r["text"]


def test_fallback_when_no_signal():
    intent = ParsedIntent(city="南昌", days=1)
    stop = _make_stop("某无标签 POI")
    r = build_rationale_for_stop(intent, stop)
    assert "fallback" in r["key_factors"]
    assert "就近顺路" in r["text"]
```

- [ ] **Step 6: 跑全部 stop rationale 测试**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_rationale_per_stop.py -v
```

Expected: 5 PASS

- [ ] **Step 7: 跑全量测试确认无回归**

```bash
PYTHONPATH=. venv/bin/pytest tests/ -q \
  --ignore=tests/test_user_profile_cleaning.py \
  --ignore=tests/test_amap_client.py \
  --ignore=tests/test_e2e_stub.py
```

Expected: 389 passed（384 + 5 新增）

- [ ] **Step 8: commit**

```bash
git add agents/rationale.py tests/test_rationale_per_stop.py
git commit -m "feat(rationale): stop-level reason generator

Why: hackathon 评委需要看到 'AI 为什么选这家'，
现有 rationale 只到 day 级。新增纯函数推 stop reason，
优先级 must_visit > amap_inject > variant > tags > fallback。"
```

---

## Task 2: P1.1 SSE 吐 stop_rationale + 前端接收

**Files:**
- Modify: `api/routes.py:367-414`（`day_done` 之后追加 stop_rationale yield）
- Modify: `web/plan_stack.html:1085-1108`（加 `case 'planner.stop_rationale'`）

- [ ] **Step 1: routes.py 在 day_done 后逐 stop yield**

在 `api/routes.py` 当前 `build_rationale_for_day` 调用块之后（约 line 411 之后，`for d_idx, segs in segments_by_day.items()` 之前）追加：

```python
                    # P1.1: per-stop rationale, 主推荐 variant 默认 "main"
                    from agents.rationale import build_rationale_for_stop
                    for stop in day_plan.stops:
                        yield format_event(
                            "planner.stop_rationale",
                            build_rationale_for_stop(intent, stop, variant="main"),
                        )
```

注意：`intent` 在该 scope 已可见（line 159 起的 profiler.understood）。`day_plan` 是当前 for fut 循环里 `await fut` 解出的变量。`build_rationale_for_stop` 局部 import（不污染顶部，规避 autoflake 删 import 的 lesson）。

- [ ] **Step 2: 前端加 case 'planner.stop_rationale'**

在 `web/plan_stack.html` 第 1095 行 `case 'planner.rationale':` block 之后追加新 case：

```javascript
    case 'planner.stop_rationale':
      // P1.1: stop 级 "为什么选这个 POI"
      // 缓存到 pendingStopRationale[day_index][poi_name]，等地图/卡片渲染时附上
      if (!window.pendingStopRationale) window.pendingStopRationale = new Map();
      const key = `${data.poi_name}`;
      window.pendingStopRationale.set(key, data);
      // chat 流式吐一句（节省评委注意力，只吐前 2 个 stop 的）
      if (!window.stopRationaleCount) window.stopRationaleCount = 0;
      if (window.stopRationaleCount < 2) {
        pushMsg('bot', `💡 ${data.text}`);
        window.stopRationaleCount++;
      }
      break;
```

后续若有 stop 卡片渲染逻辑（grep `pushStopCard` 或类似），从 `window.pendingStopRationale.get(poi_name)` 取出展示。本 task 不要求改卡片渲染——chat 流式吐 2 句即可让评委看到。

- [ ] **Step 3: 手动验证 SSE 流**

```bash
# 终端 1
cd /Users/yikuaibanz1/Desktop/sth/mtagent
pkill -9 -f "uvicorn" 2>/dev/null; sleep 1
PYTHONPATH=. venv/bin/uvicorn dianping.mock_server:mock_app --host 127.0.0.1 --port 9192 &
sleep 1
set -a && source .env && set +a
PYTHONPATH=. venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 9191 &
sleep 2

# 终端 2 或浏览器
open http://127.0.0.1:9191/
# 输入: "明天去南昌玩一天，我知道八一广场，还有南昌博物馆，中午吃拌粉，晚上吃江西小炒"
# 预期: chat 出现 2 条 💡 开头的 stop 理由
```

Expected: 浏览器对话流里出现至少 2 句 `💡 因为你说想去「南昌博物馆」...` 之类。

- [ ] **Step 4: 跑全量测试确认无回归**

```bash
PYTHONPATH=. venv/bin/pytest tests/ -q \
  --ignore=tests/test_user_profile_cleaning.py \
  --ignore=tests/test_amap_client.py \
  --ignore=tests/test_e2e_stub.py
```

Expected: 389 passed

- [ ] **Step 5: commit**

```bash
git add api/routes.py web/plan_stack.html
git commit -m "feat(sse): stream stop-level rationale to UI

Why: 评委杀手锏——'AI 流式吐为什么选这个 POI'。
day_done 后逐 stop yield planner.stop_rationale，
前端 chat 流出前 2 句让评委直观看到决策依据。"
```

---

## Task 3: P1.2 Critic 真规则检查 + Patch 输出

**Files:**
- Modify: `agents/critic.py`（重写 `run()`）
- Test: `tests/test_critic_real.py`（新文件）

- [ ] **Step 1: 写失败测试 — Critic 把 failed checks 转 Patch**

新文件 `tests/test_critic_real.py`：

```python
"""Critic 真规则检查测试 (P1.2)."""
from datetime import time
from unittest.mock import MagicMock

import pytest

from agents.context import TripContext
from agents.critic import Critic
from dianping.schemas import (
    DayPlan, POI, ParsedIntent, RouteDraft, Stop, TimeSlot,
)


def _stop(name: str, slot_name: str, hour: int, role_cat: str = "美食") -> Stop:
    return Stop(
        poi=POI(
            openshopid=f"id-{name}",
            name=name,
            categories=[role_cat],
            avgprice=80,
            star=4.5,
            longitude=115.89,
            latitude=28.68,
        ),
        slot=TimeSlot(name=slot_name, start=time(hour, 0), end=time(hour + 2, 0)),
        arrival_time=time(hour, 0),
        leave_time=time(hour + 2, 0),
    )


def _ctx(day: DayPlan, intent: ParsedIntent) -> TripContext:
    ctx = TripContext(trip_id="t1", user_input="x")
    ctx.intent = intent
    ctx.draft_route = RouteDraft(days=[day])
    return ctx


@pytest.mark.asyncio
async def test_critic_flags_missing_lunch():
    intent = ParsedIntent(city="南昌", days=1, pace="适中")
    # 4 stops 全是非饭点 slot → has_lunch fail
    day = DayPlan(day_index=0, stops=[
        _stop("八一广场", "上午景点", 9, "景点"),
        _stop("江西省博物馆", "上午景点", 10, "景点"),
        _stop("秋水广场", "下午", 14, "景点"),
        _stop("万达广场", "晚上", 19, "购物"),
    ])
    ctx = _ctx(day, intent)
    patches = await Critic().run(ctx)
    issues = [p.issue for p in patches]
    assert any("午饭" in i or "lunch" in i for i in issues)


@pytest.mark.asyncio
async def test_critic_returns_empty_when_all_pass():
    intent = ParsedIntent(city="南昌", days=1, pace="适中")
    day = DayPlan(day_index=0, stops=[
        _stop("八一广场", "上午景点", 9, "景点"),
        _stop("瓦罐汤", "午饭", 12, "美食"),
        _stop("秋水广场", "下午", 15, "景点"),
        _stop("江西小炒", "晚饭", 19, "美食"),
    ])
    ctx = _ctx(day, intent)
    patches = await Critic().run(ctx)
    # transit / type_diversity 可能 fail（数据简单）但 lunch/dinner 都有
    # 至少不会硬挂 — 只断言无 lunch/dinner issue
    issues = [p.issue for p in patches]
    assert not any("午饭" in i for i in issues)
    assert not any("晚饭" in i for i in issues)


@pytest.mark.asyncio
async def test_critic_no_draft_route_returns_empty():
    ctx = TripContext(trip_id="t1", user_input="x")
    ctx.intent = ParsedIntent(city="南昌", days=1)
    patches = await Critic().run(ctx)
    assert patches == []
```

- [ ] **Step 2: 跑测试确认 fail**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_critic_real.py -v
```

Expected: 2 FAIL（stub 返 `[]` → 第 1 个 fail；第 3 个本来就 pass；第 2 个 stub 也 pass 因为返 `[]`），1 PASS。确认第 1 个 fail 即可。

- [ ] **Step 3: 重写 `agents/critic.py`**

把 `agents/critic.py` 整体替换为：

```python
"""Critic — 规则级 route 自检 agent (P1.2 真启用版).

复用 agents.route_validator 的 6 条规则，把 failed CheckResult 翻译成
dianping.schemas.Patch 列表。不调 LLM，纯函数 + 规则。
"""

from __future__ import annotations

from typing import Callable, Optional

from agents.context import TripContext
from agents.route_validator import validate_route
from dianping.schemas import Patch


_CHECK_TO_ISSUE = {
    "stop_count": "stop 数量不达节奏目标",
    "has_lunch": "缺午饭",
    "has_dinner": "缺晚饭",
    "transit": "通勤过长",
    "type_diversity": "同类 POI 过多",
    "no_lunch_skipped": "饭点被跳过",
}


class Critic:
    """Rule-based route critic. Outputs Patch suggestions for failed checks."""

    def __init__(self, llm_call: Optional[Callable] = None):
        # llm_call 保留参数兼容老代码，本版本不使用
        self.llm_call = llm_call

    async def run(self, ctx: TripContext) -> list[Patch]:
        draft = getattr(ctx, "draft_route", None)
        intent = getattr(ctx, "intent", None)
        if draft is None or intent is None or not draft.days:
            ctx.log_event("Critic", "skip_no_draft", {})
            return []

        reports = validate_route(draft, intent)
        patches: list[Patch] = []
        for day_idx, report in enumerate(reports):
            for check in report.failed:
                issue = _CHECK_TO_ISSUE.get(check.name, check.name)
                detail = f"{issue}: {check.detail}" if check.detail else issue
                stop_idx = self._guess_stop_idx(check.name, draft.days[day_idx])
                patches.append(
                    Patch(
                        day=day_idx,
                        stop_idx=stop_idx,
                        issue=detail,
                        suggestion_type="replace",
                        new_poi_id=None,
                    )
                )

        ctx.log_event(
            "Critic",
            "rules_done",
            {
                "days_checked": len(reports),
                "patches_total": len(patches),
                "issues": [p.issue for p in patches],
            },
        )
        return patches

    @staticmethod
    def _guess_stop_idx(check_name: str, day) -> int:
        """挑一个相关 stop_idx，找不到就 0。
        Adjuster v2 才会真用这字段，本版本只为 schema 完整。"""
        stops = day.stops
        if not stops:
            return 0
        if check_name == "has_lunch":
            # 找午饭位置（11:30-13:30），没有就第一个 slot
            for i, s in enumerate(stops):
                if 11 <= s.arrival_time.hour <= 13:
                    return i
        if check_name == "has_dinner":
            for i, s in enumerate(stops):
                if 18 <= s.arrival_time.hour <= 20:
                    return i
        return 0
```

- [ ] **Step 4: 跑测试确认 pass**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_critic_real.py -v
```

Expected: 3 PASS

- [ ] **Step 5: 跑全量测试确认无回归**

```bash
PYTHONPATH=. venv/bin/pytest tests/ -q \
  --ignore=tests/test_user_profile_cleaning.py \
  --ignore=tests/test_amap_client.py \
  --ignore=tests/test_e2e_stub.py
```

Expected: 392 passed（389 + 3 新增）。若有老 critic 相关测试挂掉先看哪条，可能要更新 stub 期望。

- [ ] **Step 6: commit**

```bash
git add agents/critic.py tests/test_critic_real.py
git commit -m "feat(critic): rule-based real run instead of v0 stub

Why: hackathon demo 需要 'AI 自检过' 的可信度。复用现有
route_validator 6 条规则，failed check → Patch，
不引入 LLM 控制 ROI。Adjuster v2 才会真消费 Patch。"
```

---

## Task 4: P1.2 SSE 吐 critic.findings + 前端展示

**Files:**
- Modify: `api/routes.py:455-466`（Critic 段加 `critic.findings`）
- Modify: `web/plan_stack.html`（加 `case 'critic.findings'`）

- [ ] **Step 1: routes.py 在 critic.done 前吐 findings**

定位 `api/routes.py` 第 455 行起的 Critic 块。把：

```python
        # ----- Critic stub -----
        try:
            yield format_event("critic.start", {})
            critic = Critic()
            patches = await critic.run(ctx)
            _stamp("critic_done")
            yield format_event("critic.done", {"patches_count": len(patches)})
```

改成：

```python
        # ----- Critic (P1.2: real rule-based check) -----
        try:
            yield format_event("critic.start", {})
            critic = Critic()
            patches = await critic.run(ctx)
            _stamp("critic_done")
            if patches:
                yield format_event(
                    "critic.findings",
                    {
                        "count": len(patches),
                        "items": [
                            {"day": p.day, "stop_idx": p.stop_idx, "issue": p.issue}
                            for p in patches[:5]  # 限前 5 条避免刷屏
                        ],
                    },
                )
            yield format_event("critic.done", {"patches_count": len(patches)})
```

注意：保持 try/except 外层不变，`critic.start` 和 `critic.done` 都保留。

- [ ] **Step 2: 前端加 case 'critic.findings'**

在 `web/plan_stack.html` 现有 SSE switch 里（紧邻 `case 'planner.stop_rationale'` 之后）追加：

```javascript
    case 'critic.findings':
      // P1.2: AI 自检发现的问题
      const head = `🔍 AI 复检了路线，发现 ${data.count} 处可优化：`;
      pushMsg('bot', head);
      data.items.forEach(it => {
        pushMsg('bot', `  · Day${it.day + 1}: ${it.issue}`);
      });
      break;
```

- [ ] **Step 3: 手动验证**

```bash
pkill -9 -f "uvicorn" 2>/dev/null; sleep 1
PYTHONPATH=. venv/bin/uvicorn dianping.mock_server:mock_app --host 127.0.0.1 --port 9192 &
sleep 1
set -a && source .env && set +a
PYTHONPATH=. venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 9191 &
sleep 2
open http://127.0.0.1:9191/
# 输入故意触发：'明天去南昌玩一天，必须去八一广场和南昌博物馆'
# 期望: 流末看到 '🔍 AI 复检了路线...' 段落
```

Expected: 浏览器对话流末出现 critic.findings 消息（若所有规则都过，本 case 不显示，是 ok 的）。

- [ ] **Step 4: 跑全量测试确认无回归**

```bash
PYTHONPATH=. venv/bin/pytest tests/ -q \
  --ignore=tests/test_user_profile_cleaning.py \
  --ignore=tests/test_amap_client.py \
  --ignore=tests/test_e2e_stub.py
```

Expected: 392 passed

- [ ] **Step 5: commit**

```bash
git add api/routes.py web/plan_stack.html
git commit -m "feat(sse): stream critic.findings to UI

Why: 让 'AI 自检' 在前端可见——只在 patches > 0 时吐，
限前 5 条避免刷屏。critic.done 保留向后兼容。"
```

---

## Task 5: P1.3 UserProfile 在 UI 主流程露出

**Files:**
- Modify: `web/plan_stack.html`（加 hero 区"你的画像"卡片 + 拉 profile 渲染）

注：这是纯前端任务，无新单测（前端逻辑靠 manual verify）。

- [ ] **Step 1: 在 `initPrefModal` 后追加 `renderProfileChip()`**

在 `web/plan_stack.html` 第 2088 行 `initPrefModal()` 函数末尾 `}` 之后追加：

```javascript
async function renderProfileChip() {
  try {
    const resp = await fetch('/api/user/profile');
    const profile = await resp.json();
    const chip = document.getElementById('profileChip');
    if (!chip) return;
    if (profile === null) {
      chip.style.display = 'none';
      return;
    }
    const mods = profile.modifiers || {};
    const onTags = Object.keys(mods).filter(k => mods[k]);
    const interests = (profile.interests_text || '').trim();
    const parts = [];
    if (onTags.length) parts.push(onTags.join(' · '));
    if (interests) parts.push(`兴趣：${interests}`);
    if (!parts.length) {
      chip.style.display = 'none';
      return;
    }
    chip.style.display = 'inline-flex';
    chip.innerHTML = `<span class="pchip-dot">👤</span><span class="pchip-text">系统记得你：${parts.join('，')}</span><button class="pchip-edit" onclick="document.getElementById('prefOverlay').classList.add('show')">改</button>`;
  } catch (_) { /* 失败不阻塞 */ }
}
```

- [ ] **Step 2: 在 DOMContentLoaded handler 加 renderProfileChip 调用**

定位现有 `window.addEventListener('DOMContentLoaded', () => { initPrefModal(); });`（约 line 2122）改成：

```javascript
window.addEventListener('DOMContentLoaded', () => {
  initPrefModal();
  renderProfileChip();
});
```

并在 `savePrefModal()` 函数末尾（保存成功后）追加 `renderProfileChip();` 让 chip 实时刷新。

- [ ] **Step 3: 在 HTML hero 区插入 chip 容器**

定位 `web/plan_stack.html` 中第一个 hero / 顶部标题区域（grep `<header` 或 `class="hero"` 或主标题 `<h1>`）。在标题正下方加：

```html
<div id="profileChip" class="profile-chip" style="display:none;"></div>
```

如找不到明确 hero 容器，就插入在 `<body>` 第一个可见块的开头。

- [ ] **Step 4: 加 CSS（在已有 `<style>` 末尾）**

定位文件中 `<style>` 块末尾，追加：

```css
.profile-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 8px 12px;
  padding: 4px 10px;
  background: #f4ede1;
  color: #6b5736;
  border-radius: 14px;
  font-size: 12px;
  line-height: 1.4;
}
.profile-chip .pchip-dot { font-size: 13px; }
.profile-chip .pchip-text { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 320px; }
.profile-chip .pchip-edit {
  background: transparent;
  border: none;
  color: #b08a4e;
  cursor: pointer;
  font-size: 12px;
  padding: 0 4px;
}
.profile-chip .pchip-edit:hover { text-decoration: underline; }
```

- [ ] **Step 5: 手动验证**

```bash
# 服务还在跑（前面 task 启动的），刷新页面
open http://127.0.0.1:9191/
# 1. 第一次访问：弹偏好 modal → 选 '怕排队' + 输入 '美食拍照' → 保存
# 2. chip 立即出现 "👤 系统记得你：怕排队，兴趣：美食拍照 [改]"
# 3. 刷新页面 chip 仍在
# 4. 点 [改] → 弹 modal → 改完 → chip 实时刷
```

Expected: chip 在 hero 区可见，文案对，"改"按钮能重开 modal。

- [ ] **Step 6: 跑全量测试确认无回归**

```bash
PYTHONPATH=. venv/bin/pytest tests/ -q \
  --ignore=tests/test_user_profile_cleaning.py \
  --ignore=tests/test_amap_client.py \
  --ignore=tests/test_e2e_stub.py
```

Expected: 392 passed（前端改动不影响后端测试）

- [ ] **Step 7: commit**

```bash
git add web/plan_stack.html
git commit -m "feat(ui): expose user profile chip in hero

Why: Stage 2 cookie profile 完成但用户感知度低。
hero 区加'系统记得你：...'chip，复用现有 GET /api/user/profile，
'改'按钮直通已有 prefModal。无后端改动。"
```

---

## Task 6: 部署到 VPS + 全链路验收

**Files:** 无新文件，仅 git push + 远程 pull

- [ ] **Step 1: push 到 origin**

```bash
git push origin main
```

Expected: 5 commits pushed (Task 1-5 各 1 commit)。

- [ ] **Step 2: 远程拉最新 + 重启 mtagent service**

```bash
ssh root@8.136.210.14 'cd /opt/mtagent && git pull && systemctl restart mtagent'
```

Expected: `Updating ... Fast-forward`；`systemctl status mtagent` 显示 active (running)。

- [ ] **Step 3: 远程冒烟测试**

```bash
ssh root@8.136.210.14 'journalctl -u mtagent -n 30 --no-pager'
curl -sI https://mt.yikuaibanz.cn/ | head -3
```

Expected: journalctl 看到启动日志无 traceback；curl 返 HTTP/2 200。

- [ ] **Step 4: 真人/手机 4G 验收 demo 输入**

打开 `https://mt.yikuaibanz.cn/`（mac 本机若被 VPN 拦走手机 4G）。输入：

```
明天去南昌玩一天，我知道八一广场，还有南昌博物馆，中午吃拌粉，晚上吃江西小炒
```

预期看到（顺序大致）：
1. 偏好 modal 弹出（首次访问）→ 选偏好保存 → hero chip "👤 系统记得你：..."
2. profiler.understood / planner.anchors 段消息
3. 💡 因为你说想去「南昌博物馆」... / 💡 ...拌粉店... 至少 2 句
4. 行程渲染 + 地图 markers
5. 🔍 AI 复检 段（如有 patches）
6. 输入"我不去博物馆了去南昌之星" → adjust 成功 → 地图更新

Expected: 全流程顺畅，三项 P1 都可见。

- [ ] **Step 5: （可选）记录验收 evidence**

把验收截图 / 录屏放在 `docs/superpowers/specs/2026-05-19-p1-demo-evidence/` 或 README，方便 hackathon 提交。本步不强制。

---

## Self-Review

- **Spec coverage：**
  - P1.1 决策理由暴露 → Task 1 + 2（rationale 函数 + SSE + 前端）✅
  - P1.2 Critic 真启用 → Task 3 + 4（规则 + Patch + SSE + 前端）✅
  - P1.3 UserProfile UI 露出 → Task 5（chip）✅
  - 部署 + 验收 → Task 6 ✅
- **Placeholder 扫描：** 每个 code block 都给了完整代码，无 TBD / TODO。Step 3 of Task 5 提到"如找不到 hero 容器就插入 body 头部"——这是 fallback 指令不是空话，前端文件结构可能有几种合理位置。
- **类型一致性：** `build_rationale_for_stop` 在 Task 1 定义、Task 2 调用，函数签名一致（`intent, stop, variant=...`）。`Patch` 用 `dianping/schemas.py:409` 的字段（day/stop_idx/issue/suggestion_type/new_poi_id）。SSE 事件名 `planner.stop_rationale` / `critic.findings` 两处一致。
- **测试覆盖：** Task 1 给 5 个 rationale 单测，Task 3 给 3 个 critic 单测。前端展示 task 用 manual verify（hackathon ROI 取舍）。
- **commit 粒度：** 5 个 commit，每个独立 ship。Task 6 部署是单独操作不算 commit。

---

## Plan complete and saved to `docs/superpowers/plans/2026-05-19-p1-highlights.md`.

Two execution options:

**1. Subagent-Driven (recommended)** — 我每个 task 派一个 fresh subagent，task 间停下来过一遍 diff。

**2. Inline Execution** — 在本会话里跑，按 step 推进，每 task 末尾停下让你 review。

哪个？
