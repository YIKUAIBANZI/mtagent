# Clarify Round Design — v1.10

**Date:** 2026-05-17  
**Topic:** 规划前智能澄清对话轮（Clarify Round）

---

## 目标

在路线生成前加入 1-2 轮自然语言问答，收集餐饮偏好、预约状态、行程松紧等个性化信息，同时让后台并行完成 POI 抓取，把"等待感"转化为"对话感"。

---

## 触发条件

**每次用户发起规划请求都触发**，不区分意图完整程度。QuestionGenerator 根据 ParsedIntent 决定问 1 个还是 2 个问题（可以是 0 个，如意图已极其明确）。

---

## 整体流程

```
用户发消息
    ↓
POST /api/plan/stream
    ↓
[顺序] Profiler 解析意图 → ParsedIntent 存入 ctx
    ↓
[并行启动两个 Task]
  Task A: QuestionGenerator (DeepSeek Flash / Kimi k2)
          → 读 ParsedIntent + 原始 user_input
          → 输出 list[ClarifyQuestion]（0-2 条）
  Task B: Amap geocode + POI 预取
          → geocode must_visit + anchor
          → fetch_around
          → 结果存 ctx.pre_fetched_pois
    ↓
[Task A 完成，约 1s] emit clarify.question[0] → 前端展示 Q1
    ↓
用户回答（chip 点击 / 自定义输入 / Skip）
POST /api/plan/{trip_id}/answer
    ↓
如有 Q2: emit clarify.question[1] → 用户回答
    ↓
所有问题结束: emit clarify.done → variant 生成开始
（此时 Task B 已完成，ctx.pre_fetched_pois 就绪，跳过重复抓取）
```

---

## UI 交互样式

```
🤖  去故宫和天坛，好安排！先问你一个问题 🙌

🤖  中午想吃什么？
    [A 北京烤鸭]  [B 胡同小吃]  [C 随便，清淡就好]  [D 自定义…]  [跳过 →]

👤  （点 A）

🤖  故宫和天坛需要提前预约，您约好了吗？
    [A 都约好了]  [B 只约了故宫]  [C 还没约，帮我考虑进去]  [D 自定义…]  [跳过 →]

👤  （点 C）

🤖  好，正在为你规划… ✨
    （→ 无缝进入现有 planning SSE 事件流）
```

问题顺序：一次展示一条，前一条回答后再出下一条。

---

## 新增 Schema（`dianping/schemas.py`）

```python
class ClarifyQuestion(BaseModel):
    idx: int
    text: str
    options: list[str]   # 3 个预设选项（前端自动追加"自定义"和"跳过"）

class ClarifyAnswer(BaseModel):
    idx: int
    choice: str | None   # 选项文字 or 用户自定义输入
    skipped: bool = False
```

---

## TripContext 新增字段

```python
clarify_questions: list[ClarifyQuestion] = []
clarify_answers: list[ClarifyAnswer] = []
pre_fetched_pois: list[POI] = []   # 并行预取，variant 生成时复用
```

---

## 新增组件：`agents/questioner.py`

**职责：** 根据 ParsedIntent + 原始用户文本，生成 0-2 个澄清问题。

**输入：**
- `intent: ParsedIntent`
- `user_input: str`

**输出：** `list[ClarifyQuestion]`

**模型：** DeepSeek V3 Flash 或 Kimi k2（快速、低成本，~1s）

**Prompt 设计原则：**
- 告知模型已知字段（city、must_visit、traveler_type 等）
- 要求只问用户输入中明确缺失且对路线影响大的信息
- 问题数量：intent 已很丰富时输出 1 条或空列表；信息稀少时输出 2 条
- 每条问题必须带 3 个高质量预设选项（本地化、具体）

**问题优先级规则（prompt 中注明）：**
1. must_visit 含排队重地标（故宫/颐和园等）→ 预约状态
2. 无餐饮偏好 + 全天行程 → 午餐/晚餐口味
3. time_window 不明确 → 行程松紧
4. traveler_type 有孩子 → 孩子年龄/体力

---

## API 变更

### 现有端点修改：`POST /api/plan/stream`

Profiler 完成后不直接进 variant 生成，而是：
1. 并行启动 QuestionGenerator + Amap 预取
2. 若 questions 非空，emit `clarify.question` 事件后挂起（ctx 持久化）
3. 若 questions 为空，直接进入 variant 生成（退化为老路径）

### 新增端点：`POST /api/plan/{trip_id}/answer`

```
Body: ClarifyAnswer
Response: SSE stream
  → 还有问题: emit clarify.question（下一条）
  → 全部答完: emit clarify.done，随即进入 variant 生成 SSE
```

---

## SSE 新增事件

| 事件名 | Payload | 含义 |
|--------|---------|------|
| `clarify.question` | `{idx, text, options}` | 前端展示一条问题 + chips |
| `clarify.done` | `{}` | 所有问题结束，生成开始 |

现有 planning 事件（`planner.anchors`、`day_partial` 等）不变，接在 `clarify.done` 之后正常流出。

---

## 前端变更（`web/plan_stack.html`）

1. 新增 SSE 事件处理：`clarify.question` → `renderClarifyQuestion(data)`
2. `renderClarifyQuestion` 渲染：
   - 问题气泡（bot 消息样式）
   - A/B/C chip 按钮
   - "D 自定义" → 展开 input 框
   - "跳过 →" 按钮
3. 点击任意选项 → `POST /api/plan/{trip_id}/answer` → 监听 SSE 继续
4. `clarify.done` 事件 → 展示"正在规划…"，切换到现有 planning 渲染逻辑

---

## 错误处理

- QuestionGenerator 超时（>3s）或失败 → 跳过澄清，直接进 variant 生成
- 用户 30s 未回答 → 前端超时自动 POST skip answer，生成继续
- Amap 预取失败 → ctx.pre_fetched_pois 为空，variant 生成内部重试（现有行为）

---

## 不做的事

- 不做超过 2 轮问答（防止问卷感）
- 不做问题间的条件依赖（Q2 不依赖 Q1 的答案，避免复杂状态机）
- 不修改现有 Profiler LLM（Qwen）
- 不做用户答案的持久化学习（留给 UserProfile 机制）
