# mtagent v1 SSE 流式 + 前端集成设计

> **日期:** 2026-05-08
> **范围:** v1（C 子系统 — FastAPI 路由 + SSE 流式协议 + 前端 plan_stack 接 SSE）
> **依赖:** v0 后端骨架已完成（schemas / auth / client / mock_server / agents / tools 全部跑通，46 单测全绿）
> **关联文档:** `2026-05-08-mtagent-v0-backend-design.md` / `2026-05-08-mtagent-v0-backend.md`
> **截止节点:** 2026-05-15 前完成（赛题截止 2026-06-07，预留 v2/v3 时间）

---

## 1. Background

v0 后端骨架已交付：用户输入自由文本 → Profiler 解析意图 → Planner 确定性工具编排 + 单次 LLM 流式编排 → 出符合规划智能约束（日模板 / 跨区聚类 / 营业时间 / 预算）的 RouteDraft。**但 v0 没有 HTTP 路由，整条流水线只能从 pytest 跑通。**

v1 的使命：**把 v0 这条 pipeline 暴露成浏览器可访问的端到端流式体验**——评委打开浏览器输入"情侣 3 天深圳" → 看到关键词从输入框飞出 → 候选 POI 卡片渐进式入场 → LLM 流式编排路线 → 时间轴一段段画出来。**完整命中赛题"流式 reveal + < 10s 响应"两条加分项**。

v0 已经做了所有"难的"：数据契约、Agent 编排、规划智能。v1 是把它们组装成 demo——**主要是协议设计 + 前端工程**，没有新算法决策。

---

## 2. Goals (v1 交付能力)

| # | 能力 | 验收点 |
|---|---|---|
| 1 | **FastAPI 主 app** | uvicorn 起在 9191，挂 CORS，可访问 `/api/health` |
| 2 | **SSE 流式端点** | `POST /api/plan/stream` 接收 free_text，按事件协议（§5）流出 ~10 个事件，主路径 < 10s |
| 3 | **Profiler 缺字段处理** | Profiler 识别到 missing_fields 时流出 `profiler.clarifying` 事件，前端可重新提交补全 |
| 4 | **错误流** | 任意 Agent 抛错时流出 `error` 事件，前端可显示，连接优雅关闭 |
| 5 | **CORS** | 允许本地 file://、127.0.0.1:9191、127.0.0.1:8000 等开发来源 |
| 6 | **静态文件服务** | 主 app mount `web/` 目录，访问 `/` 返回 plan_stack.html |
| 7 | **前端 plan_stack.html 改造** | 输入框 → SSE 接收 → 三段流式 reveal（理解卡片 / 候选 POI / 时间轴）→ 完整路线 |
| 8 | **集成测试** | TestClient 跑通 SSE，断言事件序列符合 §5 协议 |

---

## 3. Non-Goals (v2/v3 单独 spec)

- ❌ Adjuster 真实实现（替换 POI / 单天重排 / profile 写回）→ v3
- ❌ 多方案 N=2 对比（暴走 vs 佛系并行生成）→ v3
- ❌ Critic 真实 ReAct（异步检查 + 推送优化建议）→ v2
- ❌ 用户 profile 持久化（cookie identity + JSON）→ v3
- ❌ 反馈闭环（用户拒了什么写回 profile）→ v3
- ❌ 真实 Dianping appkey 切换（赛题方明确无数据）

---

## 4. 架构

### 4.1 模块新增

```
mtagent/
├── api/                              # NEW: HTTP 层（C 子系统）
│   ├── __init__.py
│   ├── main.py                       # FastAPI app + CORS + lifespan + 静态挂载
│   ├── routes.py                     # /api/* 路由
│   ├── sse.py                        # SSE 事件序列化辅助
│   └── deps.py                       # 共享依赖（DianpingClient 单例）
├── web/
│   └── plan_stack.html               # 改造：输入区 + reveal 区 + SSE 客户端
└── tests/
    ├── test_api_health.py
    ├── test_sse_protocol.py
    └── test_e2e_browser.py           # （可选 P2）Playwright 端到端
```

### 4.2 进程模型

**两个独立 uvicorn 进程：**

```
Terminal 1: uvicorn dianping.mock_server:mock_app --port 9192
Terminal 2: uvicorn api.main:app --port 9191
```

**主 app（9191）调用 mock_server（9192）走 HTTP**——这是 v0 已经验证的"client 调外部 API"形态，demo 时打开两个终端窗口让评委一眼看出"系统在调外部数据源"。

切真接口时只改 `.env` 里 `MTAGENT_DIANPING_BASE_URL=https://poiopen.dianping.com`，主 app **零代码改动**。

### 4.3 单例 client（避免每次请求新建 httpx）

`api/deps.py` 用 lifespan 创建一个共享 `DianpingClient`，路由层 inject 进 Planner / Profiler。请求结束 client 不关，进程结束才 close。

---

## 5. SSE 事件协议（v1 协议契约）

### 5.1 主端点

```
POST /api/plan/stream
Content-Type: application/json
Accept: text/event-stream

Body: { "free_text": "情侣 3 天深圳预算 3000 爱拍照", "extra": { ... } }
```

`extra` 用于 Profiler 缺字段后的补全（前端按钮收集后再次提交时塞这里），可选字段：`city`, `days`, `traveler_type`, `budget_level`, `pace`。

**响应：** `text/event-stream`，事件序列见 §5.2。

### 5.2 事件枚举（按发生顺序）

| 事件名 | 触发时机 | 数据 schema |
|---|---|---|
| `trip.started` | trip_id 创建后 | `{"trip_id": "trip_xxx"}` |
| `profiler.start` | Profiler.run 开始 | `{"phase": "正在理解需求..."}` |
| `profiler.understood` | LLM 解析 ParsedIntent 完成 | 完整 ParsedIntent JSON |
| `profiler.ready` | 必填字段齐全，进 Planner | `{}` |
| `profiler.clarifying` | 缺关键字段（任一分支：与 ready 互斥） | `{"missing_fields": ["days", "traveler_type"]}` — 此后流式 close，前端补全后重新提交 |
| `planner.start` | Planner.run 开始 | `{"phase": "正在挑选 POI..."}` |
| `planner.anchors` | anchor 选取完成 | `{"anchors": [{"name": "福田CBD", "lat": 22.5, "lng": 114.0}, ...]}` |
| `planner.candidates_loaded` | search + batch 拿完详情 | `{"count": 87, "preview": [{"openshopid":"...", "name":"..."}]}` |
| `planner.clusters_ready` | 聚类完成 | `{"per_day_count": [12, 15, 10]}` |
| `planner.compose_start` | LLM 编排开始 | `{"phase": "正在编排路线..."}` |
| `planner.token` | LLM 流式 token | `{"chunk": "..."}` |
| `planner.day_done` | 单日完成（增量推送） | `{"day_index": 0, "stops": [...]}` |
| `planner.done` | 完整 RouteDraft 出炉 | 完整 RouteDraft JSON + summary |
| `critic.start` | Critic stub 开始（v1 只是 placeholder） | `{}` |
| `critic.done` | Critic stub 完成 | `{"patches_count": 0}` |
| `trip.complete` | 全流程结束，连接关闭 | `{"trip_id": "...", "duration_ms": 8200}` |
| `error` | 任意阶段抛错 | `{"phase": "planner", "message": "...", "stack_trace": "..."}` （之后连接关闭） |

### 5.3 SSE 行格式

```
event: profiler.understood
data: {"city":"深圳","days":3,"traveler_type":"情侣",...}

event: planner.token
data: {"chunk":"今天上午"}

```

每条事件以**双换行**结尾。`data:` 必须是单行 JSON（不换行），UTF-8。

### 5.4 时序与时延预算

```
t=0     trip.started
t=200ms profiler.start → profiler.understood → profiler.ready (本地 LLM mock 时几乎瞬时)
t=500ms planner.start → planner.anchors
t=2s    planner.candidates_loaded（5 anchor × 5 类目并发，~1.5s）
t=2.5s  planner.clusters_ready
t=3s    planner.compose_start → planner.token...（LLM 4-5s 流式）
t=8s    planner.day_done × 3
t=8.2s  planner.done
t=8.3s  critic.start → critic.done (v1 stub)
t=8.4s  trip.complete

总耗时：< 10s ✓ 满足赛题硬约束
```

### 5.5 Profiler 缺字段的客户端流程

```
client → POST /api/plan/stream { "free_text": "深圳" }
server → SSE: trip.started → profiler.start → profiler.understood
              → profiler.clarifying { "missing_fields": ["days", "traveler_type"] }
server   close stream

client   弹按钮收集（"几天？" "和谁？"）
client → POST /api/plan/stream { "free_text": "深圳", "extra": { "days": 3, "traveler_type": "情侣" } }
server → SSE: 完整流（profiler.ready 直通 planner）
```

---

## 6. 前端 plan_stack.html 改造

### 6.1 现状

`web/plan_stack.html` 来自 travel-agent，结构是 Jinja2 + Alpine.js + 高德 JS SDK。v0 已经复制到 mtagent/web/ 但**未改造**。

### 6.2 v1 改造目标

**用纯 vanilla JS（去 Alpine 依赖，简化部署）+ Tailwind CDN**。结构：

```
+--------------------------------------------------+
|  [Logo] · 想去哪里？                              |
|                                                  |
|  ┌─────────────────────────────────────────┐    |
|  │ 告诉我你想要的旅行...                    │    |
|  │                                          │    |
|  └─────────────────────────────────────────┘    |
|  [生成路线]                                      |
|                                                  |
|  --- 流式 reveal 区（生成时显示）---             |
|                                                  |
|  ◐ 正在理解需求...                               |
|     ✓ 城市：深圳   ✓ 天数：3 天                  |
|     ✓ 同行：情侣   ✓ 偏好：拍照/打卡             |
|                                                  |
|  ◐ 正在挑选 POI...                              |
|     [候选卡片 #1] [候选卡片 #2] ... → 滑入      |
|                                                  |
|  ◐ 正在编排路线...                              |
|     <streamed token text>                        |
|                                                  |
|  --- 路线时间轴（完成后显示）---                 |
|                                                  |
|  Day 1 · 福田CBD                                 |
|  ├─ 09:00 上午景点  [POI 卡片]                  |
|  ├─ 12:00 午饭     [POI 卡片]                  |
|  ├─ 13:30 下午     [POI 卡片]                  |
|  └─ 18:00 晚饭     [POI 卡片]                  |
|                                                  |
|  Day 2 · ... (类似)                              |
|  Day 3 · ... (类似)                              |
+--------------------------------------------------+
```

### 6.3 SSE 客户端策略

**用 `fetch()` + `ReadableStream` 解析 SSE**（不用 EventSource API，因为 EventSource 不支持 POST）：

```javascript
async function streamPlan(freeText, extra) {
  const resp = await fetch("/api/plan/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ free_text: freeText, extra }),
  });
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE 事件以双换行 \n\n 分隔
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const rawEvent = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      handleEvent(parseSSE(rawEvent));
    }
  }
}
```

`handleEvent({event, data})` 按事件名 dispatch 到对应 UI 渲染函数。

### 6.4 三段流式 reveal 渲染

| 阶段 | 触发事件 | UI 动作 |
|---|---|---|
| **理解卡片** | `profiler.understood` | 关键词 chip 从输入框逐个飞出 + 卡片淡入 |
| **候选 POI** | `planner.candidates_loaded` | 6-10 张候选卡片从右滑入（CSS transform + transition） |
| **时间轴** | `planner.day_done` × N + `planner.token` | 每收到 day_done 添加一天的时间轴段；token 流追加到 narrative 摘要区 |

### 6.5 错误 / Clarifying / Complete 处理

- `profiler.clarifying` → 弹出按钮组 modal，用户选完后调用 `streamPlan(freeText, extra)` 重新跑
- `error` → toast 红色提示 "出错：{message}"，保留已显示内容
- `trip.complete` → reveal 区折叠，时间轴展开为主视图

---

## 7. 错误处理 / 边界

### 7.1 LLM API key 缺失

`agents/profiler.py` / `agents/planner.py` 默认调 qwen-plus，需要 `DASHSCOPE_API_KEY`。v1 增加：

- 启动时（lifespan）检查 `DASHSCOPE_API_KEY`，缺失则**降级到内置 stub LLM**（返回 hardcoded ParsedIntent + 调 fallback synthesis 出路线）
- `error` 事件携带 `degraded: true` 标记，前端 toast 提示"运行在降级模式"

### 7.2 mock_server 没起

主 app 调 `client.search()` 失败 → `httpx.ConnectError` → `error` 事件，前端 toast "数据源不可用，请确认 mock_server 是否在 9192"。

### 7.3 SSE 客户端断连

v1 不实现重连。前端用户重新点"生成路线"创建新 trip。

### 7.4 trip_id 不存在的 GET

v1 提供 `GET /api/plan/{trip_id}`（从 `data/trips/{trip_id}.json` 读 TripContext），404 错误正常返回。

---

## 8. 测试策略

### 8.1 协议测试

`tests/test_sse_protocol.py`：
- TestClient + TestClient.stream() 接收 SSE 流
- 断言事件序列包含 `trip.started`, `profiler.start`, `profiler.understood`, `planner.start`, `planner.done`, `trip.complete`
- 断言事件 schema 符合 §5.2

### 8.2 健康检查

`tests/test_api_health.py`：`GET /api/health` → 200 `{"ok": true}`

### 8.3 缺字段流程

`tests/test_sse_clarifying.py`：用户输入 "深圳"（无 days/traveler_type）→ 流出 `profiler.clarifying` 后流关闭 → 前端补全后再 POST → 完整流。

### 8.4 错误流程

`tests/test_sse_error.py`：mock LLM 抛 ValueError → SSE 出 `error` 事件后关闭。

### 8.5 浏览器端到端（P2，可选）

`tests/test_e2e_browser.py` 用 playwright-cli：跑 mock_server + main app → 浏览器访问 `/` → 输入文本 → 验证时间轴渲染。**v1 阶段如果时间紧可跳过**，手动浏览器验收。

---

## 9. 验收标准（v1 完成的硬指标）

- [ ] `uvicorn api.main:app --port 9191` 起来，`GET /api/health` 返回 200
- [ ] `POST /api/plan/stream` body `{"free_text":"情侣 3 天深圳"}` 返回 SSE 流
- [ ] SSE 流包含完整事件序列（≥ 10 个事件，按 §5.2 顺序）
- [ ] 事件 schema 全部符合 §5.2
- [ ] 主路径 `trip.started` → `trip.complete` 总耗时 < 10s（fake LLM 时 < 3s，真 qwen 时 < 10s）
- [ ] Profiler 缺字段路径正确（`profiler.clarifying` 后流关闭，再次提交完成）
- [ ] 错误路径正确（任意 Agent 抛错 → `error` 事件 → 流关闭）
- [ ] CORS 允许本地 file:// 来源
- [ ] 静态文件 `GET /` 返回 plan_stack.html
- [ ] 前端 plan_stack.html 改造完成：输入框 + SSE 接收 + 三段 reveal + 时间轴
- [ ] 浏览器手动跑完整 demo（输入文本 → 看到流式 reveal → 路线渲染）
- [ ] 全部 v0 + v1 单元/集成测试通过（v0 46 个 + v1 ~5 个）

---

## 10. 工程量估计

| 阶段 | 预估 |
|---|---|
| Task 1: api/ 包骨架（main / CORS / 静态挂载 / health） | 30 min |
| Task 2: SSE 工具（sse.py 事件序列化） | 30 min |
| Task 3: `/api/plan/stream` 路由 + Agent 编排 | 1.5-2 h |
| Task 4: Profiler clarifying + error 路径 | 30-45 min |
| Task 5: 单例 client + lifespan | 20 min |
| Task 6: 协议测试 + 健康测试 + 缺字段测试 + 错误测试 | 1 h |
| Task 7: 前端 plan_stack 改造（HTML/CSS/JS） | 1.5-2 h |
| Task 8: 浏览器端到端验收 | 30 min |
| **总计** | **6-7 h** |

---

## 11. 已对齐决策（v0 阶段已定，v1 沿用）

| 决策项 | 选定方案 |
|---|---|
| 数据源 | 纯血点评 POI/UGC + 高德路径 |
| Mock server 形态 | 独立进程 9192，HTTP 模式 |
| Planner 编排 | 确定性 + 单次 LLM 流式 |
| Critic 形态 | v1 stub，v2 ReAct 真做 |
| Adjuster 形态 | v1 不实现，v3 真做 |
| 多方案 | v1 不做，v3 加 |
| LLM | qwen-plus 主，缺 key 时降级 stub |
| 状态存储 | JSON 文件（data/trips/） |
| 客户端→Mock 通信 | HTTP（demo 时强叙事） |

---

## 12. Out of Scope 提醒

本 spec **不涉及**：

- **D 子系统**（用户 profile + 反馈闭环 + 多方案）→ v3 spec
- **Critic 真实 ReAct**（异步多轮工具调用 + 优化建议推送）→ v2 spec
- **Adjuster 真实**（就近替换 + 单天重排 + profile 写回）→ v3 spec
- **WebSocket / Redis pub-sub**（v1 单 SSE 长连接够用）
- **认证 / 会话 / cookie identity**（v3 反馈闭环时引入）
- **Eval 集 + 自动评分**
- **生产部署 / Dockerfile / CI**（hackathon 不需要）

---

## 13. 风险与未决问题

1. **DASHSCOPE_API_KEY 没配置时跑测试 / demo**：v1 在 `agents/profiler.py` / `agents/planner.py` 已经支持注入 mock llm_call。v1 加一个**全局 stub LLM**（fallback），让无 key 也能跑通完整流程（demo 路线是 stub 合成的，不调真 LLM）。

2. **前端 SSE 兼容性**：现代浏览器（Chrome/Safari/Firefox）都支持 fetch + ReadableStream。Banz 自用 demo 不考虑老浏览器。

3. **CORS 来源穷举**：开发期允许 `*`（v1 hackathon 阶段安全要求低），生产前收紧。

4. **`planner.token` 流粒度**：qwen-plus 的 streaming chunk 大小不可控。前端按 token 追加渲染，不做合并。

---

## 14. 接管 v1 实施的 Agent 必读

**第一件事：** 跑一次 `cd ~/Desktop/sth/mtagent && source venv/bin/activate && PYTHONPATH=. pytest tests/ -v` 确认 v0 46 个测试全过。如果有挂掉，先修 v0 不要碰 v1。

**第二件事：** 阅读：
- `docs/superpowers/specs/2026-05-08-mtagent-v0-backend-design.md`（v0 设计）
- `docs/superpowers/plans/2026-05-08-mtagent-v0-backend.md`（v0 实施细节）
- `agents/planner.py` 和 `agents/profiler.py`（看现有 Agent 怎么用 llm_call 注入）
- `dianping/mock_server.py`（看 lifespan 如何加载数据）

**第三件事：** 按 `docs/superpowers/plans/2026-05-08-mtagent-v1-streaming.md` 跑 task。

**不要做的：**
- 不要改 v0 已有的 Agent / Tool / Schema 实现（除非 spec 第 7.1 节提到的 stub LLM 降级）
- 不要重写 mock_server（v0 已经稳定）
- 不要塞 Adjuster / Critic 真做的代码（那是 v2/v3）

---

> **最后一句话:**
>
> v1 不是"加新功能"，是"把 v0 已有能力暴露成 demo 可见的体验"。事件协议是契约，前端按协议渲染——**协议对了，前端自然好做**。把 §5 SSE 事件协议作为单一权威来源，所有讨论和编码都对着这张表。
