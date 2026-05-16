# v1.9 Refine — 自由文本意图路由

**Date**: 2026-05-16
**Status**: design → implement
**Scope**: 主面板底部输入框接通后端 — 自由文本路由到 UserProfile 更新 + Adjuster 操作 (A+B+C 同句)

---

## 1. 问题

当前 `web/plan_stack.html:481` 的 `#panelInput` 是孤立 input, submit 没接后端. 用户在三方案完成后想用自然语言追加要求 ("他喜欢博物馆什么的" / "换近的吃饭" / "他喜欢博物馆, 把下午换成博物馆") 无路可走.

## 2. 设计目标

**做的:**
- A. **偏好更新**: "他喜欢博物馆" → 写 UserProfile.interests_text + 必要的 modifiers (不动当前 trip, 下次 plan 应用)
- B. **行程调整**: "把午饭换近的" / "删第三个" / "再来一版下午" / "切到少排队那版" → 解析成 AdjustRequest, 走现有 Adjuster
- C. **同句两件事**: "他喜欢博物馆, 把下午换成博物馆" → 同时触发 A 和 B
- D. **无法路由兜底**: "今天西安天气如何" → 友好回复 "这个我下版能答 😅", 不报错

**不做的:**
- 重 plan 整个 trip ("改去成都" / "改成 2 天") — 走重新表单
- add_stop 新 op ("再加一个夜景") — Refiner 路由到 `regenerate_day` 兜底, 用 user_hint 把意图带下去
- 真闲聊 / 问答 — 仅做兜底回复, 不调外部知识

## 3. 架构

```
[用户输入] panelInput enter
    ↓
POST /api/plan/{trip_id}/refine  (SSE)
    ↓
Refiner.run(user_text, trip_summary, profile) → RefineAction
    ↓
┌─────────────────────────────────┐
│ if action.profile_update:       │
│   upsert_profile(cookie, ...)   │  → SSE: refine.profile_updated
│ if action.adjust:               │
│   走现有 Adjuster._execute_op   │  → SSE: adjust.* (复用)
│ if action.chat_reply:           │
│   兜底友好回复                  │  → SSE: refine.chat_reply
└─────────────────────────────────┘
    ↓ SSE: refine.done
```

## 4. SSE 事件 (新增 `refine.*` 命名空间, `adjust.*` 复用)

| 事件 | payload | 时机 |
|---|---|---|
| `refine.thinking` | `{"reasoning": "..."}` | LLM 路由后, 第一时间吐 reasoning 给前端聊天泡泡 |
| `refine.routed` | `{"actions": ["profile", "adjust"], "summary": "更新偏好+换下午"}` | 告诉前端打算执行什么 |
| `refine.profile_updated` | `{"interests_text": "...", "modifiers": {...}}` | profile 写完 |
| `refine.chat_reply` | `{"text": "..."}` | 兜底回复 (D 类) |
| `adjust.thinking` / `adjust.stop_replaced` / `adjust.stop_removed` / `adjust.day_replaced` / `adjust.variant_switched` | (沿用) | adjust 路径复用 |
| `refine.error` | `{"reason": "..."}` | LLM 解析失败 / Adjuster raise |
| `refine.done` | `{"trip_id": "..."}` | 全部结束 |

## 5. 接口

### POST `/api/plan/{trip_id}/refine` (SSE)

Request body:
```json
{"user_text": "他喜欢博物馆什么的, 把下午换成博物馆"}
```

Response: `text/event-stream`

Cookie: 必须 `mtagent_cid` (middleware 自动签发)

## 6. Refiner

`agents/refiner.py`:

```python
class RefineAction(BaseModel):
    reasoning: str  # 一句话: 我理解的是 X, 打算 Y
    profile_update: Optional[ProfileUpdate] = None
    adjust: Optional[AdjustRequest] = None
    chat_reply: Optional[str] = None  # 无法路由时给用户的话

class ProfileUpdate(BaseModel):
    interests_text_append: Optional[str] = None  # 追加到现有 interests_text
    modifiers_set: dict[ModifierName, bool] = Field(default_factory=dict)

class Refiner:
    def __init__(self, llm_call): ...
    async def run(
        self,
        *,
        user_text: str,
        trip_summary: str,  # "西安·1天, day 0 stops: 大雁塔(上午) 长安大牌档(午饭) 长安十二时辰(下午); variants: main/low_queue/interest_first"
        current_profile: Optional[UserProfile],
    ) -> RefineAction: ...
```

LLM 单调用, JSON 输出. system prompt 在 `agents/prompts/refiner.md`.

## 7. Endpoint 实现 (api/routes.py)

复用 `/plan/{trip_id}/adjust` 的内部 op 派发逻辑 — 抽出 `_execute_adjust_op(adjuster, ctx, req) -> AsyncIterator[str]` 共享生成器, refine 和 adjust 两条路都用.

## 8. 不变量

- ❗ 老 SSE 事件名全保留 (`adjust.*` / `trip.*` / 任何已有) — `refine.*` 是新增
- ❗ `AdjustRequest` schema 不动 (Refiner 直接构造它)
- ❗ `UserProfile` schema 不动 (复用 upsert_profile API)
- ❗ Adjuster 4 method 签名不动
- ❗ Profiler 不改 — Refiner 是平级新角色, 各管一段 (Profiler 管首次 free_text, Refiner 管 post-plan 增量)
- ❗ Cookie name `mtagent_cid` 不改

## 9. 测试 (新增)

- `tests/test_refiner.py` — Refiner 单测 4 场景 (mock llm_call):
  1. 纯偏好: "他喜欢博物馆" → profile_update 非 None, adjust None
  2. 纯调整: "把午饭换近的" → adjust replace_stop, profile_update None
  3. 同句: "他喜欢博物馆, 把下午换成博物馆" → 两者都非 None
  4. 兜底: "今天天气如何" → chat_reply 非 None, 其他 None
- `tests/test_refine_route.py` — endpoint 4 集成 (cookie + SSE):
  1. profile-only: PUT 前 GET profile 是 null → refine "我重美食" → GET profile 有 modifier "重美食"=True
  2. adjust-only: 创 trip → refine "把午饭删了" → 看 SSE 含 adjust.stop_removed
  3. combined: refine "我喜欢博物馆, 换掉下午" → SSE 同时含 refine.profile_updated + adjust.stop_replaced
  4. chat-only: refine "你好" → SSE 含 refine.chat_reply

## 10. 工程量

- spec: 25min ✓
- refiner.py + prompts/refiner.md: 50min
- test_refiner.py: 30min
- /refine endpoint: 40min
- test_refine_route.py: 30min
- 前端 panelInput 绑定 + SSE 解析: 30min
- E2E 真测 3 场景: 20min
- 总 ~3h

## 11. 推迟项 (Stage 4 / 后续)

- add_stop 新 op (Adjuster 第 5 method)
- 行程级 user_hint 注入 candidate_pool 让"换近的"真按距离过滤 (现在靠 anchor_radius 默认)
- Refiner 输出多个 adjust 链 (一句话两个调整: "删第三个再换午饭")
