# mtagent v0 后端骨架设计

> **日期:** 2026-05-08
> **范围:** v0 后端骨架（数据契约层 A + Agent 编排层 B）
> **关联文档:** `meituan_hackathon_plan.md` / `MOCK_DATA_REQUIREMENTS.md` / `mt接口文档.md`
> **作者:** Banz × Claude
> **状态:** Spec 待 Banz review

---

## 1. Background

美团 2026 AI Hackathon 赛题 05 「现在就出发 · AI 本地路线智能规划」，截止 **2026-06-07**。

主办方明确**赛道五不提供真实数据**，"可查阅 AI 后进行模拟"——本项目的数据基础完全靠 LLM 模拟生成（已由独立 data_generator 完成 2400 条 POI），但**接口契约 100% 对齐大众点评开放平台 schema**。

**赛题硬约束：**
- 路线生成 < 10 秒
- 至少覆盖餐饮 + 娱乐/文化两类
- 路线规模 ≥ 3 个 POI

**赛题三评分维度：** 完整性（路线可用性 + 多约束满足）/ 创新性（体验创新 + 技术创新）/ 应用效果。

**参考工程:** `~/Desktop/sth/travel-agent/`（FastAPI + qwen-plus + 高德 + xhs，6000+ 行）。本工程 mtagent 采用"复制并大砍"策略——保留 cluster_pois / ranker / mapper / api 骨架，砍 xhs 爬虫 / cleaner / 老 check_poi_status / 4 套前端中的 3 套。

**数据资产现状:**
- `data/mock_dianping/` 已含 2400 条 POI（深圳 / 上海 / 西安各 800）+ index.json + metadata.json，schema 已 1:1 对齐点评字段表
- `data_generator/` 已含完整生成器代码（生成 / 验证 / 索引 / 重平衡），可后续增量补数据

---

## 2. Goals (v0 交付能力)

| # | 能力 | 验收点 |
|---|---|---|
| 1 | **数据契约层** | Pydantic schema 100% 解析 `data/mock_dianping/*.json` 全 2400 条 |
| 2 | **Mock Server** | FastAPI sub-app 实现 4 个真实点评接口路径，签名验证打通 |
| 3 | **HTTP Client** | production-ready 客户端，**改 BASE_URL 一行切真接口** |
| 4 | **Profiler** | LLM 解析自由文本 → ParsedIntent，缺关键字段返回 `missing_fields` |
| 5 | **Planner** | 确定性工具编排 + 单次 LLM 流式编排，**含规划智能** |
| 6 | **Critic / Adjuster** | 文件 + 类 + system prompt 草稿建好，`run()` 是合法 stub |
| 7 | **TripContext** | 贯穿 4 Agent 的共享状态对象，JSON 持久化 |

---

## 3. Non-Goals (后续 spec 单独覆盖)

- ❌ C 子系统（FastAPI 路由 + SSE 事件协议）→ v1 spec
- ❌ D 子系统（用户偏好持久化 + 反馈闭环）→ v3 spec
- ❌ 前端 plan_stack.html 改造 → v1 spec
- ❌ 多方案对比 N=2（暴走 vs 佛系）→ v3 spec
- ❌ Critic 真实 ReAct 工具调用 → v2 spec
- ❌ Adjuster 真实单天重排 → v3 spec
- ❌ 真实点评 appkey 联调 → 不做（赛题方明确无数据）
- ❌ 理解卡片流式 reveal / 预选标签 / 节奏滑块 → v1 与队友定 UI 后加

---

## 4. 架构总览

### 4.1 三层端口适配器（Hexagonal）

```
Agents Layer        — Profiler / Planner / Critic / Adjuster
       ↓ (only via Tools)
Tools Layer         — search / batchgetpoi / cluster / route / day_template / business_hour_check
       ↓ (only via Client)
Client Layer        — DianpingClient (HTTP) + AmapRouteClient (路径) + LLM Client
       ↓ (HTTP)
Mock Server         — dianping/mock_server.py (FastAPI sub-app, port 9192)
```

**纪律:** 层只能向下依赖。Agent 不直接 import Client；Tool 不直接 import Agent。

### 4.2 模块清单

```
mtagent/
├── dianping/                    # A: 数据契约层
│   ├── __init__.py
│   ├── schemas.py
│   ├── auth.py
│   ├── client.py
│   └── mock_server.py
├── agents/                      # B: Agent 编排层
│   ├── __init__.py
│   ├── context.py
│   ├── tools.py
│   ├── profiler.py
│   ├── planner.py
│   ├── critic.py
│   ├── adjuster.py
│   └── prompts/
│       ├── profiler.md
│       ├── planner.md
│       ├── critic.md
│       └── adjuster.md
├── data/
│   └── mock_dianping/           # 已存在，2400 POI
├── data_generator/              # 已存在，可增量补数据
├── tests/
│   ├── test_signature.py
│   ├── test_schemas.py
│   ├── test_mock_server.py
│   ├── test_planner_constraints.py
│   └── test_e2e_stub.py
├── archive/                     # travel-agent 老代码归档
├── docs/superpowers/specs/      # 本 spec 所在
├── config.py
├── main.py
└── CLAUDE.md
```

---

## 5. 数据契约层（A）

### 5.1 `dianping/schemas.py`

按三份点评接口文档（POI 详情 / UGC / POI 搜索）1:1 翻译为 Pydantic v2 模型。

**核心类型:**
- `POI` — 完整 POI 详情，**所有富字段 Optional**（cover 字段权限不确定 + mock 与真接口的兼容性）
- `UGC` — 评论项 `{nick, userface, ispithy, score, star, content, photos, addtime}`
- `ReviewTag` — `{tag: str, hit: int}`
- `Dish` — `{dishName, picUrl, price, recommendCount}`
- `MallInfo` — `{popularShops, dzPopularShops, discount, ...}`
- `DealInfo` — `{dealName, originPrice, discountPrice, type, ...}`
- `SearchRecord` — 搜索接口返回项（默认只有 `openshopid` + `name`，distance/category 标 Optional）

**业务对象（不在点评 schema 内，业务自定义）:**
- `ParsedIntent` — Profiler 输出（city / days / traveler_type / budget_level / preferences / must_visit / avoid / start_date）
- `ProfilerOutput` — `{understood: ParsedIntent, ready_to_plan: bool, missing_fields: list[str]}`
- `RouteDraft` — Planner 输出（`days: list[DayPlan]`）
- `DayPlan` — `{date, anchor_district, stops: list[Stop]}`
- `Stop` — 单个行程节点 `{poi: POI, slot: TimeSlot, arrival_time, leave_time, transport_to_next}`
- `TimeSlot` — `{name: enum["上午景点", "午饭", "下午", "下午茶", "晚饭", "夜场"], start, end}`
- `Patch` — Critic 输出修改建议 `{day, stop_idx, issue, suggestion}`
- `Feedback` — Adjuster 接收的用户反馈 `{action, target_stop, reason}`

### 5.2 `dianping/auth.py`

实现签名算法（与三份接口文档对齐）:

```python
def sign(params: dict, appsecrect: str) -> str:
    """
    参数名小写 → ASCII 排序 → 拼接 (key1value1key2value2...) 
    → 前后包 secret → utf-8 编码 → MD5 → hex 小写
    
    除去：appsecrect 参数本身、值为空的参数、content 字段（UGC 上传专用，本工程不用）
    """
```

**单测必跑（`tests/test_signature.py`）:**
- 文档例子：`{a:1, b:2, ab:3}` + secret=`xyz` → 排序拼接 `xyza1ab3b2xyz` → MD5 hex 小写

### 5.3 `dianping/client.py`

```python
class DianpingClient:
    def __init__(self, base_url: str, appkey: str, secret: str, session: str):
        self.base_url = base_url  # http://localhost:9192 默认；改一行切真接口
        ...
    
    async def opencity(self) -> list[str]: ...
    async def search(
        self, *, keyword: str | None = None, city: str | None = None,
        latitude: float | None = None, longitude: float | None = None,
        radius: int = 1000, categories: str | None = None,
        page: int = 1, limit: int = 25, mall: int | None = None,
    ) -> list[SearchRecord]: ...
    async def get_single_poi(self, openshopid: str) -> POI: ...
    async def batch_get_poi(self, ids: list[str]) -> dict[str, POI]: ...
```

- httpx 异步客户端
- 自动加签 + 公共参数（appkey / session / timestamp / sign）
- BASE_URL 默认 `http://localhost:9192`，**env `MTAGENT_DIANPING_BASE_URL` 改一行切真接口**
- 失败抛 `DianpingAPIError`（带 status / message）

### 5.4 `dianping/mock_server.py`

FastAPI sub-app，启动时从 `data/mock_dianping/{深圳,上海,西安}.json` 一次性加载到内存（约 11 MB，无压力）。

**实现路径（与真接口完全一致）:**

| 路径 | 实现策略 |
|---|---|
| `POST /router/city/opencity` | 返回 `["深圳", "上海", "西安"]` |
| `POST /router/poisearch/search` | 利用 `data/mock_dianping/index.json` 的 by_keyword / by_category / by_district 索引筛选；半径过滤用 `latitude/longitude` + Haversine 距离 |
| `POST /router/poi/batchgetpoi` | 按 `multiopenshopid` 拿详情字典 |
| `POST /router/poi/getsinglepoi` | 单个 `openshopid` 详情 |

**强制启用签名验证** ——开发期 appkey/secret 用占位 `"demo-appkey"` / `"demo-secret"`，client 发请求前算签名，mock_server 验证通过才返回。这样 client **100% 走真接口流程**，切真接口零改动。

启动方式：**独立进程在 9192**（不与主 app 9191 同进程）。这样 demo 时打开两个终端窗口，左边是 mock server 日志（看到接口被调用），右边是主 app 日志（看到 Agent 编排流程）——评委一眼能看出"client 调外部 API"的真实感。

```python
# 启动 mock server
uvicorn dianping.mock_server:mock_app --host 127.0.0.1 --port 9192

# 启动主 app（另一终端）
uvicorn main:app --host 127.0.0.1 --port 9191
```

切真接口时只需修改 `.env` 里 `MTAGENT_DIANPING_BASE_URL=https://poiopen.dianping.com`，主 app 不重启。

---

## 6. Agent 编排层（B）

### 6.1 `agents/context.py`

```python
class TripContext(BaseModel):
    trip_id: str
    user_input: UserInput
    profile: UserProfile | None = None         # v3 反馈闭环用
    intent: ParsedIntent | None = None         # Profiler 输出
    candidate_pois: list[POI] = []             # Planner 召回池
    draft_route: RouteDraft | None = None      # Planner 输出
    critic_patches: list[Patch] = []           # v2 才填
    user_feedback: list[Feedback] = []         # v3 才填
    trace: list[Event] = []                    # 全程事件流（debug + 重放）
    
    def save(self) -> None:
        """写到 data/trips/{trip_id}.json"""
    
    @classmethod
    def load(cls, trip_id: str) -> "TripContext": ...
```

**JSON 持久化策略:** 每次 Agent 调用前后写盘一次。文件小（< 100 KB），IO 开销可忽略。好处:
- Debug 时可直接重放
- demo 翻车可瞬间复原
- 后期 eval 集就是这堆 JSON

### 6.2 `agents/tools.py`

工具层（Pure functions，不持有状态）：

```python
# Client 包装
async def search_pois(client, **params) -> list[SearchRecord]: ...
async def batch_get_poi_details(client, ids: list[str]) -> dict[str, POI]: ...

# 复用 travel-agent
def cluster_anchor_orbit(pois: list[POI], k: int, max_radius_km: float = 5.0) -> list[Cluster]: ...
def rank_by_traveler_type(pois: list[POI], traveler_type: str) -> list[POI]: ...

# 高德路径（v0 stub 固定 30 min，v1 接真路径）
async def get_route(start: Coord, stops: list[Coord]) -> Route: ...

# 规划智能（v0 必落代码）
def generate_day_template(days: int, traveler_type: str, pace: str = "moderate") -> list[DayTemplate]: ...
def check_business_hours(poi: POI, visit_time: datetime) -> bool: ...
def filter_by_intent_constraints(pois: list[POI], intent: ParsedIntent) -> list[POI]: ...
```

**`generate_day_template` 输出形态:**

```python
class DaySlot(BaseModel):
    name: Literal["上午景点", "午饭", "下午", "下午茶", "晚饭", "夜场"]
    start_time: time   # 09:00
    end_time: time     # 12:00
    category_pool: list[str]   # ["休闲娱乐", "购物"]
    is_meal: bool       
    optional: bool      # True 时可选（下午茶 / 夜场）
    min_stay_minutes: int
    max_stay_minutes: int

class DayTemplate(BaseModel):
    day_index: int    # 0-based
    slots: list[DaySlot]
```

**模板预设（v0 三套节奏，对应 traveler_type）:**
- **暴走** — 6 时段 / ~7 POI: 上午景点 + 午饭 + 下午商场 + 下午茶 + 晚饭 + 夜场
- **适中** — 4-5 时段 / ~5 POI: 上午景点 + 午饭 + 下午商场 + 晚饭 + （可选夜场）
- **佛系** — 4 时段 / ~4 POI: 上午景点 + 午饭 + 下午景点 + 晚饭

`traveler_type` 默认映射: 情侣→适中、家庭亲子→佛系、银发→佛系、独行→适中、商务→暴走、朋友团→暴走（用户显式 override 可改）

### 6.3 `agents/profiler.py` （最简版 v0）

**职责:** 解析用户自由文本 → 结构化意图。

**流程:**
1. 接收 `user_input.free_text`
2. 调 LLM（qwen-plus）解析为 `ParsedIntent`（city / days / traveler_type / budget_level / preferences / must_visit / avoid / start_date）
3. 检查必填三项（city / days / traveler_type）是否齐全
4. 输出 `ProfilerOutput`:
   - 齐全 → `ready_to_plan: True`
   - 缺 → `missing_fields: [...]`，前端按钮收集

**v0 不做（v1 加）:** 理解卡片流式叙述、预选标签、节奏滑块、对话式追问。

### 6.4 `agents/planner.py`

**确定性工具编排 + 单次 LLM:**

```python
async def run(self, ctx: TripContext) -> RouteDraft:
    intent = ctx.intent
    
    # 1. 日模板生成
    pace = intent.preferences.get("pace", default_pace_for_traveler(intent.traveler_type))
    templates = generate_day_template(intent.days, intent.traveler_type, pace)
    
    # 2. anchor 选取（每天选一个核心商圈）
    anchors = pick_anchors(intent.city, intent.days, intent.preferences, intent.must_visit)
    
    # 3. 候选召回（并发，按类目 × anchor）
    candidates_by_anchor = await asyncio.gather(*[
        search_pois(self.client, latitude=a.lat, longitude=a.lng,
                    categories=cat, radius=5000, limit=25)
        for a in anchors
        for cat in unique_categories(templates)
    ])
    
    # 4. 详情批量
    all_ids = [r.openshopid for batch in candidates_by_anchor for r in batch]
    poi_details = await batch_get_poi_details(self.client, dedup(all_ids))
    
    # 5. 聚类（每天 cluster 半径 ≤ 5km，强制不跨区）
    clusters = cluster_anchor_orbit(poi_details.values(), k=intent.days, max_radius_km=5.0)
    
    # 6. 营业时间过滤（按 day_template 时段 + intent.start_date）
    filtered = filter_by_business_hours(clusters, templates, intent.start_date)
    
    # 7. 业务约束过滤（预算 / 必去 / 避开）
    filtered = filter_by_intent_constraints(filtered, intent)
    
    # 8. 按 traveler_type 排序
    ranked = rank_by_traveler_type(filtered, intent.traveler_type)
    
    # 9. 单次 LLM 流式编排（候选 + 模板 + 约束塞 prompt）
    route = await llm_compose_route(
        intent, templates, ranked, prompt=PROMPTS.PLANNER, stream=True,
    )
    
    # 10. 校验 RouteSchema + 业务规则
    return RouteDraft.model_validate(route)
```

**LLM 调用约束:**
- 模型: qwen-plus
- max_tokens: 4000
- 流式输出: 是（v0 内部流但不暴露给前端，C 子系统才接 SSE）
- 输出格式: 严格 JSON（用 `response_format={"type": "json_object"}`）

### 6.5 `agents/critic.py` （v0 stub）

```python
class Critic:
    async def run(self, ctx: TripContext) -> list[Patch]:
        return []  # v2 实现 ReAct 异步检查
```

但已建好类骨架 + `prompts/critic.md` 草稿，v2 spec 直接填内脏，**不返工骨架**。

### 6.6 `agents/adjuster.py` （v0 stub）

```python
class Adjuster:
    async def run(self, ctx: TripContext, action: AdjustAction) -> RouteDraft:
        raise NotImplementedError("v3 实现")
```

---

## 7. 关键数据流（端到端 stub）

```
1. 客户端发起规划：
   POST /plan/start
   body: {free_text: "情侣 3 天深圳预算 3000 爱拍照"}
   → 创建 TripContext(trip_id, user_input)
   → ctx.save()

2. Profiler.run(ctx):
   → ctx.intent = ParsedIntent(city="深圳", days=3, traveler_type="情侣",
                               budget_level="moderate", preferences=["拍照", "打卡"])
   → ctx.save()
   → ProfilerOutput(ready_to_plan=True)

3. Planner.run(ctx):
   → 1: templates = [DayTemplate × 3]（适中节奏）
   → 2: anchors = [万象天地, 海岸城, 华侨城]
   → 3-4: 召回 + 详情，~120 个候选 POI
   → 5: cluster k=3，每天聚簇半径 ≤ 5km
   → 6-7: business_hour + 预算 + must_visit/avoid 过滤
   → 8: ranker 按"情侣"排序（出片优先）
   → 9: LLM 单次编排 → 3 天每天 5 个 POI 的合规 RouteDraft
   → ctx.draft_route = RouteDraft(...)
   → ctx.save()

4. Critic.run(ctx) → []  # v0 stub
5. Adjuster 不调用
6. 返回 ctx.draft_route 给客户端
```

---

## 8. 规划智能约束（v0 必落代码）

### 8.1 一日时段模板硬约束
- 餐饮**锚死** 12:00-13:30 / 18:00-20:00
- 上午景点 09:00-12:00、下午景点/商场 13:30-17:00、下午茶 15:30-16:30（可选）、夜场 20:00-22:00（可选）
- LLM 只在每个时段填具体 POI，**不让 LLM 自由编时段**

### 8.2 跨区聚类硬约束
- 一天所有 POI 必须在 cluster 半径 ≤ 5 km
- 复用 `tools/cluster_pois.py`（K-means + 节假日规避）
- 例外: `intent.preferences` 含 "多区打卡" 时半径放宽到 10km

### 8.3 营业时间硬约束
- `business_hour` 必须包含 `visit_time`
- `intent.start_date` 推算每日星期 → 周一闭馆 POI 在周一被过滤
- 餐饮 POI 必须在午饭 12:00 / 晚饭 18:00 时段营业

### 8.4 时间合理性约束
- POI 间默认 **30 min buffer**
- 停留时间下限: 餐饮 60 / 景点 60 / 商场 120 / 茶 30 / 夜场 60（写在 `min_stay_minutes` 字段）
- 一天总活动时间封顶 **9-10h**，超了砍 POI

### 8.5 业务约束
- 人均预算: `intent.budget_level` 与 `poi.avgprice` 匹配（性价比 ≤ 100、适中 100-300、精致 300+）
- `must_visit`: 必须出现在路线
- `avoid`: 不能出现在路线
- `user_marked.disliked / been_there`: v3 反馈闭环时过滤

---

## 9. 测试策略

### 9.1 单元测试

| 文件 | 覆盖范围 |
|---|---|
| `test_signature.py` | 文档 `xyza1ab3b2xyz` 例子做 MD5 断言 |
| `test_schemas.py` | mock 数据 100% parse + invalid 数据抛 `ValidationError` |
| `test_mock_server.py` | 4 接口路径返回正确结构 + 签名验证拒绝错签 |
| `test_planner_constraints.py` | cluster 半径 ≤ 5km / business_hour 不冲突 / 餐饮时段约束 / 周一闭馆过滤 / 预算匹配 |

### 9.2 集成测试

| 文件 | 覆盖范围 |
|---|---|
| `test_e2e_stub.py` | 完整端到端: `情侣 3 天深圳` → Profiler → Planner → 校验 RouteDraft 满足全部约束 |

---

## 10. 验收标准（v0 完成的硬指标）

- [ ] Pydantic schema 100% 解析 `data/mock_dianping/*.json` 全 2400 条
- [ ] Mock server 用 `uvicorn` 起在 9192，4 接口路径全响应、签名验证通过
- [ ] HTTP Client 调 mock server 能拿结构化数据，**改 BASE_URL env 一行切真接口**（演示通过）
- [ ] Profiler 解析 "情侣 3 天深圳预算 3000 爱拍照" 输出正确 `ParsedIntent`
- [ ] Planner 端到端跑通: 输入意图 → 输出 3 天每天 4-7 个 POI 的合规 `RouteDraft`
- [ ] Planner 输出满足 §8 全部规划智能约束
- [ ] Critic / Adjuster 文件 + 类 + prompt 草稿建好，`run()` 是合法 stub
- [ ] TripContext JSON 持久化跑通（写入 / 读出闭环）
- [ ] 全部单元测试通过
- [ ] 端到端 stub 测试通过

---

## 11. 工程量估计

| 阶段 | 预估 |
|---|---|
| Section 1: 复制 travel-agent 砍出 mtagent 骨架 | 30-45 min |
| Section 2: 数据契约层 4 文件 (schemas/auth/client/mock_server) | 2-2.5 h |
| Section 3: Agent 编排层 6 文件 + tools + prompts | 3-3.5 h |
| 测试 + 联调 | 1-1.5 h |
| **总计** | **~7-8 h** |

可在一个工作日 + 一个晚上之内完成。

---

## 12. 已对齐决策（参考）

| 决策项 | 选定方案 |
|---|---|
| 数据源 | 纯血点评 POI/UGC + 高德路径 |
| Mock server 形态 | HTTP 模式（强叙事，BASE_URL 一行切换） |
| Planner 编排 | 确定性工具流 + 单次 LLM 流式 |
| Critic 编排 | ReAct（v2 实现） |
| Agent 通信 | 函数调用 + TripContext 共享状态 |
| 状态存储 | v0 JSON，提交版升 SQLite |
| LLM | qwen-plus（4 次/规划预算上限） |
| 工程策略 | 复制 travel-agent → mtagent，旧代码 archive/ |
| Profiler v0 | 单 textarea + missing_fields，UI 后续与队友定 |
| 规划智能放 v0 | 工程量翻倍但 v1/v2 不返工 schema |
| 多方案对比 | v3 加，v0 day_template 模板 enum 已支持 |

---

## 13. Out of Scope 提醒

本 spec 不覆盖以下（后续单独 spec）:

- **C 子系统:** FastAPI 路由设计 / SSE 事件协议 / 错误处理 / CORS
- **D 子系统:** Cookie identity / user_profile JSON schema / Adjuster 写回逻辑 / 反馈闭环 UI 接入
- **前端:** plan_stack.html 改造 / 流式 reveal UI / 预选标签 / 多方案 tab / 实时调整按钮
- **多方案 N=2:** 暴走版 vs 佛系版并行生成
- **Critic 真实逻辑:** ReAct 多轮 tool use / patches 推送
- **Adjuster 真实逻辑:** 单天重排 / 就近替换 / profile 写回
- **Eval 集:** 5-10 case 黄金路线对比

---

## 14. 风险与未决问题

1. **mtagent git 状态:** mtagent 在 `~/Desktop/sth/` 外层 git repo 内（非独立 repo），外层 repo 有 submodule 异常。本 spec 不阻塞主线，但 git workflow 需 Banz 后续整理（建议 `cd mtagent && git init` 独立化，或解决 sth/ submodule 问题）。

2. **数据生成富字段差异:** 抽样发现部分 POI 的 `reviewTags` 全部正面（无负面 tag），违反 `MOCK_DATA_REQUIREMENTS.md` 第 3.3 节 "每个 POI 必有 1-3 个负面 tag"。Planner 可正常跑（不阻塞 v0），但 v2 Critic 真做时若发现负面信号不足要回炉补数据。

3. **travel-agent 复用代码迁移:** `cluster_pois.py` / `ranker.py` / `mapper.py` 假设的输入结构和点评 schema 不完全一致（前者基于高德 POI），迁移时需小幅适配字段名（`type` → `categories`，`rating` → `star`）。

---

> **最后一句话:**
> v0 是脊柱，不是完整产品。脊柱立稳——Schema 对齐 / 仿真层完整 / Planner 智能落代码——v1（前端 + SSE）/ v2（Critic）/ v3（Adjuster + 反馈闭环 + 多方案）才能在不返工骨架的前提下叠上去。
