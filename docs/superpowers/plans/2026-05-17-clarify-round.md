# Clarify Round (v1.10) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在路线生成前加入 1-2 轮 chip 式对话问答，后台并行预取 POI，把等待感转化为对话感。

**Architecture:** Profiler 完成后并行启动 QuestionGenerator（快模型）和 Amap 预取；有问题则 emit `clarify.question` 并挂起，等用户通过 `POST /answer` 回答；答完后合并 answers 进 intent 再触发 variant 生成。无问题时退化为老路径。

**Tech Stack:** Python/FastAPI SSE, Pydantic v2, OpenAI-compatible API（DeepSeek/Kimi/Qwen 均可）, Vanilla JS chip UI

---

## File Map

| 文件 | 操作 | 职责 |
|---|---|---|
| `dianping/schemas.py` | 修改 | 新增 `ClarifyQuestion` + `ClarifyAnswer` |
| `agents/context.py` | 修改 | TripContext 新增 3 个字段 |
| `agents/questioner.py` | 新建 | QuestionGenerator — 快模型生成 0-2 个问题 |
| `api/stub_llm.py` | 修改 | 新增 `resolve_questioner_llm()` |
| `api/routes.py` | 修改 | plan_stream 并行启动 + 挂起；新增 answer 端点；提取 `_run_variants` |
| `web/plan_stack.html` | 修改 | clarify.question 事件 → chip bubble + 回调 |
| `tests/test_questioner.py` | 新建 | QuestionGenerator 单元测试 |
| `tests/test_clarify_round.py` | 新建 | answer 端点集成测试 |

---

## Task 1: 新增 Schema

**Files:**
- Modify: `dianping/schemas.py`
- Test: `tests/test_clarify_round.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/test_clarify_round.py`：

```python
"""Tests for ClarifyQuestion / ClarifyAnswer schemas."""
import pytest
from dianping.schemas import ClarifyAnswer, ClarifyQuestion


def test_clarify_question_schema():
    q = ClarifyQuestion(idx=0, text="中午想吃什么？", options=["北京烤鸭", "胡同小吃", "随便清淡"])
    assert q.idx == 0
    assert len(q.options) == 3


def test_clarify_answer_skip():
    a = ClarifyAnswer(idx=0, choice=None, skipped=True)
    assert a.skipped is True
    assert a.choice is None


def test_clarify_answer_choice():
    a = ClarifyAnswer(idx=0, choice="北京烤鸭")
    assert a.skipped is False
    assert a.choice == "北京烤鸭"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
PYTHONPATH=. venv/bin/pytest tests/test_clarify_round.py -v
```

预期：`ImportError: cannot import name 'ClarifyAnswer'`

- [ ] **Step 3: 在 `dianping/schemas.py` 末尾加两个 class**

在文件末尾（`UserProfile` 等 class 之后）添加：

```python
class ClarifyQuestion(BaseModel):
    """一个澄清问题，由 QuestionGenerator 生成。"""
    idx: int
    text: str
    options: list[str]  # 3 个预设选项；前端自动追加"自定义"和"跳过"


class ClarifyAnswer(BaseModel):
    """用户对一个澄清问题的回答。"""
    idx: int
    choice: Optional[str] = None   # 选项文字 or 用户自定义输入
    skipped: bool = False
```

- [ ] **Step 4: 跑测试确认通过**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_clarify_round.py -v
```

预期：3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add dianping/schemas.py tests/test_clarify_round.py
git commit -m "feat(v1.10): add ClarifyQuestion + ClarifyAnswer schemas"
```

---

## Task 2: TripContext 新增字段

**Files:**
- Modify: `agents/context.py`
- Test: `tests/test_clarify_round.py`（追加）

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_clarify_round.py`）

```python
def test_trip_context_clarify_fields():
    from agents.context import TripContext
    from dianping.schemas import ClarifyAnswer, ClarifyQuestion, UserInput

    ctx = TripContext.create(user_input=UserInput(free_text="去北京玩"))
    assert ctx.clarify_questions == []
    assert ctx.clarify_answers == []
    assert ctx.pre_fetched_pois == []

    ctx.clarify_questions = [ClarifyQuestion(idx=0, text="吃什么？", options=["A", "B", "C"])]
    ctx.clarify_answers = [ClarifyAnswer(idx=0, choice="A")]
    assert len(ctx.clarify_questions) == 1
    assert ctx.clarify_answers[0].choice == "A"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_clarify_round.py::test_trip_context_clarify_fields -v
```

预期：`AttributeError: 'TripContext' object has no attribute 'clarify_questions'`

- [ ] **Step 3: 修改 `agents/context.py`**

在 `from dianping.schemas import (` 块中追加两个 import：

```python
from dianping.schemas import (
    ClarifyAnswer,
    ClarifyQuestion,
    Event,
    Feedback,
    ParsedIntent,
    Patch,
    POI,
    RouteDraft,
    UserInput,
    UserProfile,
)
```

在 `TripContext` class 内，`variants` 字段之后追加：

```python
    # v1.10 澄清对话轮
    clarify_questions: list[ClarifyQuestion] = Field(default_factory=list)
    clarify_answers: list[ClarifyAnswer] = Field(default_factory=list)
    pre_fetched_pois: list[POI] = Field(default_factory=list)
```

- [ ] **Step 4: 跑测试确认通过**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_clarify_round.py -v
```

预期：4 tests PASS

- [ ] **Step 5: 跑全量测试确认不破坏现有**

```bash
PYTHONPATH=. venv/bin/pytest tests/ -q --ignore=tests/test_user_profile_cleaning.py --ignore=tests/test_amap_client.py --ignore=tests/test_e2e_stub.py
```

预期：348 passed

- [ ] **Step 6: Commit**

```bash
git add agents/context.py tests/test_clarify_round.py
git commit -m "feat(v1.10): add clarify_questions/answers/pre_fetched_pois to TripContext"
```

---

## Task 3: 新建 `agents/questioner.py`

**Files:**
- Create: `agents/questioner.py`
- Test: `tests/test_questioner.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/test_questioner.py`：

```python
"""Tests for QuestionGenerator."""
import json
import pytest
from unittest.mock import AsyncMock
from dianping.schemas import ClarifyQuestion, ParsedIntent


@pytest.mark.asyncio
async def test_questioner_returns_two_questions_for_sparse_intent():
    """稀疏意图（无餐饮偏好、含排队地标）→ 返回 2 个问题。"""
    from agents.questioner import QuestionGenerator

    fake_response = json.dumps({
        "questions": [
            {"idx": 0, "text": "中午想吃什么？", "options": ["北京烤鸭", "胡同小吃", "随便清淡"]},
            {"idx": 1, "text": "故宫需要预约，您约好了吗？", "options": ["约好了", "还没约", "帮我考虑进去"]},
        ]
    })
    fake_llm = AsyncMock(return_value=fake_response)

    intent = ParsedIntent(city="北京", days=1, traveler_type="情侣", must_visit=["故宫", "天坛"])
    qg = QuestionGenerator(llm_call=fake_llm)
    questions = await qg.generate(intent=intent, user_input="明天去北京玩故宫天坛")

    assert len(questions) == 2
    assert all(isinstance(q, ClarifyQuestion) for q in questions)
    assert questions[0].idx == 0
    assert len(questions[0].options) == 3


@pytest.mark.asyncio
async def test_questioner_returns_empty_for_rich_intent():
    """意图已很丰富（有餐饮偏好 + 无排队地标）→ 返回 0 个问题。"""
    from agents.questioner import QuestionGenerator

    fake_response = json.dumps({"questions": []})
    fake_llm = AsyncMock(return_value=fake_response)

    intent = ParsedIntent(
        city="上海", days=1, traveler_type="朋友团",
        preferences=["美食", "拍照"], must_visit=[]
    )
    qg = QuestionGenerator(llm_call=fake_llm)
    questions = await qg.generate(intent=intent, user_input="上海外滩吃吃喝喝拍拍照")

    assert questions == []


@pytest.mark.asyncio
async def test_questioner_falls_back_on_llm_error():
    """LLM 抛异常 → 返回空列表，不崩溃。"""
    from agents.questioner import QuestionGenerator

    failing_llm = AsyncMock(side_effect=Exception("timeout"))
    intent = ParsedIntent(city="北京", days=1, traveler_type="情侣")
    qg = QuestionGenerator(llm_call=failing_llm)
    questions = await qg.generate(intent=intent, user_input="去北京")

    assert questions == []
```

- [ ] **Step 2: 跑测试确认失败**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_questioner.py -v
```

预期：`ModuleNotFoundError: No module named 'agents.questioner'`

- [ ] **Step 3: 创建 `agents/questioner.py`**

```python
"""QuestionGenerator — 规划前澄清问题生成器 (v1.10).

用快速 LLM (DeepSeek Flash / Kimi / Qwen) 根据 ParsedIntent 生成 0-2 个澄清问题。
LLM 失败时静默返回空列表，路由退化为老路径。
"""
from __future__ import annotations

import json
import os
from typing import Awaitable, Callable, Optional

from dianping.schemas import ClarifyQuestion, ParsedIntent

_SYSTEM_PROMPT = """\
你是一个旅行规划助手，需要在为用户生成路线前，提出 0-2 个最有价值的补充问题。

规则：
1. 只问对路线影响大的信息缺口，不问已知信息
2. 意图已很丰富（有餐饮偏好 + 无排队地标）时输出 0 个问题
3. 每个问题必须提供恰好 3 个高质量、本地化的预设选项
4. 问题优先级：
   a. must_visit 含排队重地标（故宫/颐和园/兵马俑等）→ 询问预约状态
   b. 无餐饮偏好 + 全天行程 → 询问午餐/晚餐口味
   c. time_window 不明确 → 询问行程松紧
   d. traveler_type 含孩子 → 询问孩子年龄/体力
5. 最多 2 个问题，每个问题 options 数组恰好 3 个元素

输出严格 JSON，格式：
{"questions": [{"idx": 0, "text": "...", "options": ["...", "...", "..."]}, ...]}
"""

_HIGH_QUEUE_LANDMARKS = {"故宫", "天安门", "颐和园", "天坛", "兵马俑", "大雁塔", "西湖", "外滩"}


def _build_user_payload(intent: ParsedIntent, user_input: str) -> str:
    known = {
        "city": intent.city,
        "days": intent.days,
        "traveler_type": intent.traveler_type,
        "must_visit": list(intent.must_visit or []),
        "preferences": list(intent.preferences or []),
        "time_window": intent.time_window,
        "budget_level": intent.budget_level,
    }
    has_queue_landmark = any(lm in (intent.must_visit or []) for lm in _HIGH_QUEUE_LANDMARKS)
    has_food_pref = any("美食" in p or "餐" in p for p in (intent.preferences or []))

    hints = []
    if has_queue_landmark:
        hints.append("must_visit 含排队重地标，考虑询问预约状态")
    if not has_food_pref and (intent.time_window or "").startswith("一日"):
        hints.append("无餐饮偏好且全天行程，考虑询问午餐口味")

    return json.dumps(
        {
            "user_original_input": user_input,
            "parsed_intent": known,
            "generation_hints": hints,
        },
        ensure_ascii=False,
    )


class QuestionGenerator:
    def __init__(self, llm_call: Optional[Callable[[str, str], Awaitable[str]]] = None):
        self.llm_call = llm_call or _default_llm_call

    async def generate(self, *, intent: ParsedIntent, user_input: str) -> list[ClarifyQuestion]:
        """返回 0-2 个 ClarifyQuestion。LLM 失败时返回空列表。"""
        payload = _build_user_payload(intent, user_input)
        try:
            raw = await self.llm_call(_SYSTEM_PROMPT, payload)
            data = json.loads(raw)
            questions = []
            for item in data.get("questions", [])[:2]:
                questions.append(
                    ClarifyQuestion(
                        idx=item["idx"],
                        text=item["text"],
                        options=item["options"][:3],
                    )
                )
            return questions
        except Exception:
            return []


async def _default_llm_call(system: str, user: str) -> str:
    """OpenAI-compatible call. 优先用 QUESTIONER_* env，回退到 Qwen。"""
    from openai import AsyncOpenAI

    api_key = os.environ.get("QUESTIONER_API_KEY") or os.environ.get("DASHSCOPE_API_KEY", "")
    base_url = os.environ.get(
        "QUESTIONER_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    model = os.environ.get("QUESTIONER_MODEL", "qwen-plus")

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    return resp.choices[0].message.content or '{"questions": []}'
```

- [ ] **Step 4: 跑测试确认通过**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_questioner.py -v
```

预期：3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/questioner.py tests/test_questioner.py
git commit -m "feat(v1.10): add QuestionGenerator with fallback-safe LLM call"
```

---

## Task 4: `api/stub_llm.py` 新增 `resolve_questioner_llm`

**Files:**
- Modify: `api/stub_llm.py`

- [ ] **Step 1: 在 `api/stub_llm.py` 末尾追加**

```python
def resolve_questioner_llm() -> Callable[[str, str], Awaitable[str]]:
    """QuestionGenerator LLM resolver.

    优先用 QUESTIONER_API_KEY（DeepSeek/Kimi），回退到 Qwen，无 key 时返回 stub（空问题）。
    """
    if os.environ.get("QUESTIONER_API_KEY") or os.environ.get("DASHSCOPE_API_KEY"):
        from agents.questioner import _default_llm_call

        return _default_llm_call

    async def _stub(system: str, user: str) -> str:
        return '{"questions": []}'

    return _stub
```

- [ ] **Step 2: 跑全量测试确认无破坏**

```bash
PYTHONPATH=. venv/bin/pytest tests/ -q --ignore=tests/test_user_profile_cleaning.py --ignore=tests/test_amap_client.py --ignore=tests/test_e2e_stub.py
```

预期：350 passed（含新增的 questioner + clarify_round 测试）

- [ ] **Step 3: Commit**

```bash
git add api/stub_llm.py
git commit -m "feat(v1.10): add resolve_questioner_llm to stub_llm"
```

---

## Task 5: 提取 `_run_variants` + 修改 `plan_stream` + 新增 `answer` 端点

**Files:**
- Modify: `api/routes.py`
- Test: `tests/test_clarify_round.py`（追加）

这是最关键的任务，分几个子步骤：

### 5a: 提取 `_run_variants` helper

`plan_stream` 里 variant 生成逻辑（约从 `pre_pois = await _prefetch_amap_pois(...)` 到 SSE 流结束）目前是内嵌的 generator 代码。把它提取成一个 async generator helper，让 `plan_stream` 和 `answer` 端点都能复用。

- [ ] **Step 1: 在 `api/routes.py` 里找 variant 生成段起始行**

```bash
grep -n "_prefetch_amap_pois\|variant.main_started\|pre_pois = await" api/routes.py | head -10
```

记住行号，用于下一步定位。

- [ ] **Step 2: 在 `_prefetch_amap_pois` 函数定义之前，新增 `_run_variants` helper**

在 `api/routes.py` 中 `async def _prefetch_amap_pois` 上方插入：

```python
async def _run_variants(ctx: TripContext, intent, pois: list, amap, planner) -> AsyncIterator[str]:
    """Variant 生成 SSE 流（被 plan_stream 和 answer 端点共用）。

    intent 已包含 clarify_answers 合并结果。
    ctx.pre_fetched_pois 不为空时跳过重复 Amap 抓取。
    """
    import asyncio as _asyncio
    from agents.planner_instant import plan_one_variant, plan_three_variants

    # 若已有预取结果，直接用
    pre_pois = ctx.pre_fetched_pois if ctx.pre_fetched_pois else await _prefetch_amap_pois(intent, pois)

    _VARIANTS = ["main", "low_queue", "interest_first"]
    partial_bufs: dict[str, list] = {v: [] for v in _VARIANTS}

    def _make_partial_cb(v: str):
        async def _cb(day_idx: int, names: list[str]) -> None:
            partial_bufs[v].append((day_idx, names))
        return _cb

    _gwps = getattr(intent, "geocoded_waypoints", [])
    if len(_gwps) >= 2:
        from agents.anchor import _haversine_km as _hv_pre
        _max_wp_dist = max(
            _hv_pre((_gwps[0].lng, _gwps[0].lat), (wp.lng, wp.lat)) for wp in _gwps[1:]
        )
        if _max_wp_dist > (intent.anchor_radius_km or 3.0):
            intent = intent.model_copy(update={"anchor_radius_km": _max_wp_dist + 5.0})

    # (以下粘贴现有 plan_stream 内的 variant 生成代码，原封不动)
    # ... [见 Step 3 说明]
```

> **Step 3 说明：** 把现有 `plan_stream` 内从 `yield format_event("variant.main_started", ...)` 到函数末尾的所有代码，剪切粘贴到 `_run_variants` 内，把其中的 `pre_pois = await _prefetch_amap_pois(intent, pois)` 一行删掉（已在函数头处理）。然后在 `plan_stream` 对应位置改为：

```python
        async for chunk in _run_variants(ctx, intent, pois, amap, planner):
            yield chunk
```

- [ ] **Step 4: 确认 `plan_stream` 现有行为不变**

```bash
pkill -9 -f "uvicorn" 2>/dev/null; sleep 1
PYTHONPATH=. venv/bin/uvicorn dianping.mock_server:mock_app --host 127.0.0.1 --port 9192 &
sleep 1
set -a && source .env && set +a
PYTHONPATH=. venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 9191 &
sleep 2
curl -s -N -X POST http://127.0.0.1:9191/api/plan/stream \
  -H "Content-Type: application/json" \
  -d '{"free_text":"去深圳玩一天"}' | head -20
```

预期：看到 `event: trip.started` 后正常规划流。

### 5b: 修改 `plan_stream`，加入澄清对话轮

- [ ] **Step 5: 在 `plan_stream` 的 `profiler.ready` 之后、variant 生成之前，插入并行启动逻辑**

找到 `yield format_event("profiler.ready", {})` 这行（约在 112 行），在其**之后**插入：

```python
            # ── v1.10 Clarify Round ──────────────────────────────────────────
            from agents.questioner import QuestionGenerator
            from api.stub_llm import resolve_questioner_llm

            qg = QuestionGenerator(llm_call=resolve_questioner_llm())

            # 并行：生成问题 + 预取 POI（intent 已在 profiler 完成后存到 ctx）
            q_task = asyncio.create_task(
                qg.generate(intent=ctx.intent, user_input=body.free_text)
            )
            prefetch_task = asyncio.create_task(
                _prefetch_amap_pois(ctx.intent, [])
            )

            questions = await q_task
            ctx.clarify_questions = questions

            # 预取结果存 ctx（answer 端点启动 variant 时复用）
            pre_pois_result = await prefetch_task
            if pre_pois_result:
                ctx.pre_fetched_pois = pre_pois_result
            ctx.save()

            if questions:
                # 有问题：emit 第一条，挂起等用户回答
                yield format_event(
                    "clarify.question",
                    {"idx": 0, "text": questions[0].text, "options": questions[0].options},
                )
                yield format_event(
                    "trip.complete",
                    {
                        "trip_id": ctx.trip_id,
                        "duration_ms": int((time.time() - start_time) * 1000),
                        "status": "awaiting_clarification",
                    },
                )
                return  # 等待 POST /answer
            # ── 无问题：直接进 variant 生成 ──────────────────────────────────
```

### 5c: 新增 `POST /api/plan/{trip_id}/answer` 端点

- [ ] **Step 6: 在 `api/routes.py` 末尾（或 GET /plan/{trip_id} 附近）新增**

```python
class ClarifyAnswerRequest(BaseModel):
    idx: int
    choice: Optional[str] = None
    skipped: bool = False


@router.post("/plan/{trip_id}/answer")
async def submit_clarify_answer(
    trip_id: str,
    body: ClarifyAnswerRequest,
    request: Request,
    client: DianpingClient = Depends(deps.get_client),
):
    """接收一条澄清回答。还有问题则返回下一条；全答完则触发 variant 生成。"""
    from agents.amap import AmapClient as _AmapClient
    from agents.planner import Planner as _Planner
    from dianping.schemas import ClarifyAnswer

    try:
        ctx = TripContext.load(trip_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="trip not found")

    # 记录答案
    ctx.clarify_answers.append(
        ClarifyAnswer(idx=body.idx, choice=body.choice, skipped=body.skipped)
    )

    answered = len(ctx.clarify_answers)
    total = len(ctx.clarify_questions)

    async def event_stream() -> AsyncIterator[str]:
        # 还有问题
        if answered < total:
            next_q = ctx.clarify_questions[answered]
            ctx.save()
            yield format_event(
                "clarify.question",
                {"idx": next_q.idx, "text": next_q.text, "options": next_q.options},
            )
            return

        # 全部答完：合并 answers 进 intent，启动 variant 生成
        yield format_event("clarify.done", {})

        intent = ctx.intent
        if ctx.clarify_answers:
            # 把答案拼成补充 context 字符串，存到 intent.extra_context（见下文）
            notes = []
            for ans in ctx.clarify_answers:
                if not ans.skipped and ans.choice:
                    q_text = ctx.clarify_questions[ans.idx].text if ans.idx < len(ctx.clarify_questions) else ""
                    notes.append(f"{q_text}→{ans.choice}")
            if notes:
                extra = "【用户补充偏好】" + "；".join(notes)
                intent = intent.model_copy(
                    update={"extra_clarify_context": extra}
                )

        # 重新加载 pois（instant 路径用 mock data）
        from dianping.schemas import RouteDraft
        amap = _AmapClient(key=os.environ.get("AMAP_KEY", ""))
        planner = _Planner(
            client=None,
            llm_call=resolve_planner_llm(),
            llm_call_stream=resolve_planner_llm_stream(),
        )

        # pois: 若有 pre_fetched_pois 直接用（_run_variants 内会检查 ctx.pre_fetched_pois）
        ctx.save()

        try:
            async for chunk in _run_variants(ctx, intent, [], amap, planner):
                yield chunk
        except Exception as exc:
            yield format_event("error", {"phase": "variants", "message": str(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

- [ ] **Step 7: 在 `dianping/schemas.py` 的 `ParsedIntent` 中新增 `extra_clarify_context` 字段**

找到 `class ParsedIntent(BaseModel):` 定义，在现有字段末尾追加：

```python
    extra_clarify_context: Optional[str] = None  # v1.10: 澄清对话补充偏好
```

- [ ] **Step 8: 在 `agents/planner.py` 的 `_build_one_day_payload` 中注入 extra_clarify_context**

找到 `_instruction` 字符串的末尾（`"返回必须是合法 JSON，stops 数组不能为空。"` 之后），追加：

```python
                    + (
                        intent.extra_clarify_context + " " if intent.extra_clarify_context else ""
                    )
```

- [ ] **Step 9: 写集成测试**（追加到 `tests/test_clarify_round.py`）

```python
@pytest.mark.asyncio
async def test_answer_endpoint_emits_next_question(tmp_path, monkeypatch):
    """POST /answer 还有问题 → emit clarify.question，不触发 variant 生成。"""
    import os
    monkeypatch.setenv("MTAGENT_TRIPS_DIR", str(tmp_path))

    from agents.context import TripContext
    from dianping.schemas import ClarifyQuestion, ParsedIntent, UserInput

    ctx = TripContext.create(user_input=UserInput(free_text="去北京"))
    ctx.intent = ParsedIntent(city="北京", days=1, traveler_type="情侣")
    ctx.clarify_questions = [
        ClarifyQuestion(idx=0, text="吃什么？", options=["A", "B", "C"]),
        ClarifyQuestion(idx=1, text="约好了吗？", options=["X", "Y", "Z"]),
    ]
    ctx.save()

    from fastapi.testclient import TestClient
    from api.main import app

    with TestClient(app) as tc:
        resp = tc.post(
            f"/api/plan/{ctx.trip_id}/answer",
            json={"idx": 0, "choice": "A"},
        )
    assert resp.status_code == 200
    text = resp.text
    assert "clarify.question" in text
    assert "约好了吗" in text
```

- [ ] **Step 10: 跑测试**

```bash
PYTHONPATH=. venv/bin/pytest tests/test_clarify_round.py -v
```

预期：所有 clarify_round 测试 PASS

- [ ] **Step 11: Commit**

```bash
git add api/routes.py dianping/schemas.py agents/planner.py tests/test_clarify_round.py
git commit -m "feat(v1.10): plan_stream clarify round + answer endpoint + intent injection"
```

---

## Task 6: 前端 Chip Bubble UI

**Files:**
- Modify: `web/plan_stack.html`

- [ ] **Step 1: 在 SSE 事件处理 switch-case 里新增 `clarify.question` 和 `clarify.done`**

找到现有 `case 'profiler.clarifying':` 这段（约 838 行），在其前面插入：

```javascript
    case 'clarify.question':
      removeTyping();
      renderClarifyQuestion(data, currentTripId);
      break;

    case 'clarify.done':
      removeTyping();
      pushMsg('bot', '好，正在为你规划… ✨');
      pushTyping();
      break;
```

- [ ] **Step 2: 在文件末尾的 `<script>` 块内追加 `renderClarifyQuestion` 函数**

```javascript
// ── v1.10 Clarify Round ──────────────────────────────────────────────────────
function renderClarifyQuestion(data, tripId) {
  const { idx, text, options } = data;
  const wrap = document.createElement('div');
  wrap.className = 'chat-msg bot clarify-question-wrap';

  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';
  bubble.textContent = text;
  wrap.appendChild(bubble);

  const chips = document.createElement('div');
  chips.className = 'clarify-chips';

  const allOptions = [...options, '自定义…'];
  allOptions.forEach((opt, i) => {
    const btn = document.createElement('button');
    btn.className = 'clarify-chip';
    btn.textContent = (i < options.length ? String.fromCharCode(65 + i) + ' ' : 'D ') + opt;
    btn.addEventListener('click', () => {
      if (opt === '自定义…') {
        _showCustomInput(wrap, idx, tripId);
      } else {
        _submitAnswer(idx, opt, false, tripId, wrap);
      }
    });
    chips.appendChild(btn);
  });

  // Skip 按钮
  const skipBtn = document.createElement('button');
  skipBtn.className = 'clarify-chip clarify-skip';
  skipBtn.textContent = '跳过 →';
  skipBtn.addEventListener('click', () => _submitAnswer(idx, null, true, tripId, wrap));
  chips.appendChild(skipBtn);

  wrap.appendChild(chips);
  chatPanel.appendChild(wrap);
  chatPanel.scrollTop = chatPanel.scrollHeight;

  // 30s 超时自动跳过
  const timeout = setTimeout(() => _submitAnswer(idx, null, true, tripId, wrap), 30000);
  wrap._clarifyTimeout = timeout;
}

function _showCustomInput(wrap, idx, tripId) {
  const existing = wrap.querySelector('.clarify-custom-input');
  if (existing) return;
  const row = document.createElement('div');
  row.className = 'clarify-custom-input';
  const inp = document.createElement('input');
  inp.type = 'text';
  inp.placeholder = '输入你的想法…';
  inp.className = 'clarify-custom-text';
  const confirmBtn = document.createElement('button');
  confirmBtn.textContent = '确认';
  confirmBtn.className = 'clarify-chip';
  confirmBtn.addEventListener('click', () => {
    if (inp.value.trim()) _submitAnswer(idx, inp.value.trim(), false, tripId, wrap);
  });
  row.appendChild(inp);
  row.appendChild(confirmBtn);
  wrap.appendChild(row);
  inp.focus();
}

async function _submitAnswer(idx, choice, skipped, tripId, wrap) {
  if (wrap._clarifyTimeout) clearTimeout(wrap._clarifyTimeout);
  // 禁用 chip 防止重复提交
  wrap.querySelectorAll('.clarify-chip').forEach(b => b.disabled = true);

  // 显示用户的选择
  if (!skipped && choice) pushMsg('user', choice);

  const resp = await fetch(`/api/plan/${tripId}/answer`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ idx, choice: skipped ? null : choice, skipped }),
  });
  if (!resp.ok || !resp.body) return;

  // 读 SSE 流（下一条问题 or clarify.done + planning 事件）
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const blocks = buf.split('\n\n');
    buf = blocks.pop() || '';
    for (const blk of blocks) {
      let ev = '', dat = null;
      for (const line of blk.split('\n')) {
        if (line.startsWith('event:')) ev = line.slice(6).trim();
        if (line.startsWith('data:')) {
          try { dat = JSON.parse(line.slice(5).trim()); } catch (_) {}
        }
      }
      if (!ev) continue;
      // 复用现有 planning 事件处理
      handleSSEEvent(ev, dat);
    }
  }
}
```

- [ ] **Step 3: 提取现有 switch-case 内容为 `handleSSEEvent(ev, dat)` 函数**

目前 SSE 事件处理分散在几个地方。找到处理 `plan_stream` SSE 的主 while 循环（约 800-950 行），把其中的 `switch(ev) { ... }` 提取成：

```javascript
function handleSSEEvent(ev, dat) {
  switch (ev) {
    // ... 现有所有 case 原封不动粘贴过来 ...
  }
}
```

原来的调用改为 `handleSSEEvent(ev, dat)`。这样 `_submitAnswer` 中的 answer SSE 流也能复用同一套事件处理器。

- [ ] **Step 4: 加 CSS（在 `<style>` 块末尾追加）**

```css
/* v1.10 Clarify Round chips */
.clarify-question-wrap { margin-bottom: 8px; }
.clarify-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.clarify-chip {
  padding: 6px 14px;
  border-radius: 20px;
  border: 1.5px solid #e8632a;
  background: #fff;
  color: #e8632a;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.clarify-chip:hover:not(:disabled) { background: #e8632a; color: #fff; }
.clarify-chip:disabled { opacity: 0.5; cursor: default; }
.clarify-skip { border-color: #aaa; color: #888; }
.clarify-skip:hover:not(:disabled) { background: #aaa; color: #fff; }
.clarify-custom-input { display: flex; gap: 6px; margin-top: 6px; }
.clarify-custom-text {
  flex: 1; padding: 6px 10px; border-radius: 16px;
  border: 1.5px solid #ddd; font-size: 13px;
}
```

- [ ] **Step 5: 手动测试**

```bash
pkill -9 -f "uvicorn" 2>/dev/null; sleep 1
PYTHONPATH=. venv/bin/uvicorn dianping.mock_server:mock_app --host 127.0.0.1 --port 9192 &
sleep 1
set -a && source .env && set +a
PYTHONPATH=. venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 9191 &
sleep 2 && open http://127.0.0.1:9191/
```

发送「明天去北京玩，去故宫还有天坛」，验证：
- [ ] 出现问题气泡 + A/B/C chip + 跳过按钮
- [ ] 点 A → 显示用户选择气泡 → 出现第二个问题
- [ ] 点跳过 → 直接进 variant 生成
- [ ] 地图正常渲染 3 个 variant

- [ ] **Step 6: 跑全量测试**

```bash
PYTHONPATH=. venv/bin/pytest tests/ -q --ignore=tests/test_user_profile_cleaning.py --ignore=tests/test_amap_client.py --ignore=tests/test_e2e_stub.py
```

预期：≥350 passed

- [ ] **Step 7: Commit**

```bash
git add web/plan_stack.html
git commit -m "feat(v1.10): clarify round chip UI with auto-skip timeout"
```

---

## 自检 Checklist

**Spec coverage:**
- [x] 每次触发 → plan_stream 每次启动 QuestionGenerator
- [x] 0-2 个问题 → QuestionGenerator.generate 返回 0-2 条
- [x] 顺序逐条 → answer 端点每次只 emit 一条 clarify.question
- [x] chip + 自定义 + 跳过 → renderClarifyQuestion 实现
- [x] 后台并行预取 → asyncio.create_task(q_task) + asyncio.create_task(prefetch_task)
- [x] 答案合并进 intent → extra_clarify_context 注入 planner payload
- [x] QuestionGenerator 失败退化 → try/except 返回 []
- [x] 30s 超时跳过 → setTimeout 30000ms

**Placeholder 扫描:** 无 TBD / TODO

**类型一致性:**
- `ClarifyQuestion` 在 schemas、context、questioner、routes 均一致
- `ClarifyAnswer` 在 schemas、context、routes 均一致
- `extra_clarify_context: Optional[str]` 在 ParsedIntent + planner payload 均引用
