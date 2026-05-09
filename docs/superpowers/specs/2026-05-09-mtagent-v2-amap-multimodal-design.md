# mtagent v2 高德 API 多模态路径集成设计

> **日期:** 2026-05-09
> **范围:** v2（F 子系统 — 高德 API 接入 + 4 模式（驾车/步行/公交+地铁/骑行）路径时间 + 前端 chip 切换）
> **依赖:** v1.5 rationale stream 已 ship + 真 qwen3.6-plus 配置 ship
> **关联文档:**
> - `2026-05-09-mtagent-v1.5-rationale-stream-design.md`
> - `2026-05-09-mtagent-v1.6-streaming-per-day-design.md`（独立分支，可与 v2 并行落地）
> **截止节点:** 2026-05-15 前完成（赛题 2026-06-07）
> **分支:** `feat/v2-amap-multimodal`

---

## 1. Background

v1.5 跑通了 rationale，但每个 stop 的 `transport_to_next_minutes` 默认硬编码 30 分钟——既不真实也不会触发评委 wow 时刻。美团赛题就是「本地路线智能规划」，**没有 transit 数据 = 缺最关键的一只鞋**。

**v2 的两个杀手锏：**
1. **真 transit 时间** —— 调高德 API 算每段实际通勤时间（地铁/公交/驾车/步行/骑行）。rationale 升级："Day 1 全程地铁 1.5h，比打车省 80%" 这种带数字的硬证据
2. **多模态切换** —— 前端每段显示 chip selector「🚇 12min ¥4 · 🚗 8min ¥15 · 🚶 28min · 🚲 18min ¥3」，用户点切换最优。这是用户日常用高德 App 的真实使用习惯——把它原生植入 demo

这两个加上 v1.5 rationale 形成 demo 时的「双杀手锏」。

---

## 2. Goals (v2 交付能力)

| # | 能力 | 验收点 |
|---|---|---|
| 1 | **amap 4 模式 client** | `agents/amap.py` 提供 `get_transit(origin, dest, modes=["drive","walk","transit","bicycle"])` 异步并发 4 个 endpoint，返回统一 schema |
| 2 | **每个 stop pair 的多模态时间填回 Stop** | Stop 新增 `transport_options: dict[str, TransitInfo]` 字段，per-mode 含 minutes / distance_km / price_yuan / detail |
| 3 | **每天 stops 的 transit 计算异步化** | 每个 day_done 后并发 4 模式 × N-1 段 = 4(N-1) 次 amap 调用（asyncio.gather）；不阻塞主流，单独 yield `transit.updated` 事件 |
| 4 | **失败兜底 haversine** | amap 任一模式失败/超时 → 用 haversine 距离 × 1.4 + 经验速度系数估算（drive 30km/h、walk 5km/h、transit 20km/h、bicycle 15km/h）。`source: "estimated"` 透明标注 |
| 5 | **环境开关** | `MTAGENT_AMAP_DISABLED=1` 完全跳过 amap 调用走 fallback；测试默认 `disabled` |
| 6 | **前端 chip selector** | 每个 stop pair 之间显示 4 个 chip（图标+时间+价格），traveler_type 推荐预选；点击切换 mode 立即更新当日总通勤分钟 + rationale |
| 7 | **rationale 升级带 transit 硬证据** | `build_rationale_for_day` 接收可选 `transit_summary` → 文案含具体数字"全程 92 分钟通勤，地铁占 70%，比打车省 ¥80" |
| 8 | **测试** | unit：amap client 4 模式 + haversine fallback + 限流；SSE：transit.updated 事件位置 + 字段；rationale：含 transit 文案 |

---

## 3. Non-Goals

- ❌ **真打 amap 写入测试** —— MockTransport 模拟，避免烧配额
- ❌ **路径 polyline 绘制** —— 时间轴只显示数字，不画地图（高德嵌入式 Map 是 v3 范围）
- ❌ **打车实时定价** —— 用驾车距离 × 计价规则简化估算（深圳起步 11¥+2.4¥/km），不调真打车 API
- ❌ **公交+地铁多方案对比**（同一 mode 内地铁主 vs 公交主） —— 取 amap 返回首方案
- ❌ **路线点击展开分段详情** —— 第一版只显示总时间/价格 chip，"展开看详情" 留 v2.1
- ❌ **跟 v1.6 per-day streaming 合并** —— v2 在 main 上独立干；v1.6 落地后两者都改 `routes.py`，merge 时手动 resolve
- ❌ **离线缓存 transit 数据** —— 每次请求都调 amap（同一 trip 内可加 LRU，但 v2 范围外）

---

## 4. 架构

### 4.1 模块新增

```
mtagent/
├── agents/
│   └── amap.py                         # NEW: 4 模式 client + haversine fallback
└── tests/
    ├── test_amap_client.py             # NEW: 4 模式 client 单测 + MockTransport
    ├── test_amap_fallback.py           # NEW: haversine 估算测试
    └── test_sse_transit.py             # NEW: SSE transit.updated 事件测试
```

### 4.2 模块改动

```
mtagent/
├── dianping/schemas.py                 # MODIFIED: Stop 加 transport_options 字段（Optional default None，向后兼容）
├── api/routes.py                       # MODIFIED: 每个 day_done 后 yield transit.updated 事件
├── agents/rationale.py                 # MODIFIED: build_rationale_for_day 接收可选 transit_summary
├── tests/test_rationale.py             # MODIFIED: +3 case rationale 含 transit 文案
└── web/plan_stack.html                 # MODIFIED: chip selector + 状态切换 + rationale 联动
```

### 4.3 不动

- `agents/planner.py` —— Planner 不感知 transit，由 routes.py 在 day_done 后异步调用
- `agents/profiler.py` / `agents/critic.py` / `agents/mapper.py`
- `dianping/` 数据契约层（除 schemas.Stop 加可选字段）
- v1.5 SSE 协议老事件全部保留兼容

---

## 5. 数据契约

### 5.1 Stop schema 增量

```python
class TransitInfo(BaseModel):
    """单 mode 通勤信息."""
    mode: Literal["drive", "walk", "transit", "bicycle"]
    minutes: int
    distance_km: float
    price_yuan: Optional[float] = None  # walk/bicycle 没价格
    source: Literal["amap", "estimated"]  # 真 amap 还是 haversine 估算

class Stop(BaseModel):
    poi: POI
    slot: TimeSlot
    arrival_time: time
    leave_time: time
    transport_to_next_minutes: int = 30  # 保留作 fallback 默认值
    transport_options: Optional[dict[str, TransitInfo]] = None  # NEW: {"drive": ..., "walk": ...}
```

向后兼容：旧 trip JSON 反序列化时 `transport_options=None` 默认。

### 5.2 SSE 事件 schema

新事件 `transit.updated`：

```jsonc
{
  "event": "transit.updated",
  "data": {
    "day_index": 0,
    "segments": [
      {
        "from_index": 0,           // stop in day.stops
        "to_index": 1,
        "options": {
          "drive":    {"minutes": 8,  "distance_km": 4.2, "price_yuan": 15, "source": "amap"},
          "walk":     {"minutes": 28, "distance_km": 2.1, "price_yuan": null, "source": "amap"},
          "transit":  {"minutes": 12, "distance_km": 4.0, "price_yuan": 4,  "source": "amap"},
          "bicycle":  {"minutes": 18, "distance_km": 4.0, "price_yuan": 3,  "source": "amap"}
        },
        "recommended": "transit"   // 后端按 traveler_type 推荐
      },
      ...
    ]
  }
}
```

每天 (N-1) 段 stop pair。事件在对应 day_done 之后任意时间到。前端 upsert 渲染。

### 5.3 事件序列变化（v1.5 → v2）

3 天行程 v1.5 = 20 事件，v2 = 23 事件（+3 个 transit.updated 每天 1 个）。

---

## 6. amap client 设计

### 6.1 接口

```python
# agents/amap.py

class AmapClient:
    def __init__(self, key: str, base_url: str = "https://restapi.amap.com", timeout: float = 5.0):
        self.key = key
        self.base_url = base_url
        self._client = httpx.AsyncClient(timeout=timeout, limits=httpx.Limits(max_connections=8))
        self.disabled = bool(os.environ.get("MTAGENT_AMAP_DISABLED"))

    async def get_transit_options(
        self,
        origin: tuple[float, float],   # (lng, lat) 高德格式
        dest: tuple[float, float],
        traveler_type: Optional[str] = None,
    ) -> dict[str, TransitInfo]:
        """4 mode 并发调用，任一失败 fallback 到 haversine."""
        if self.disabled:
            return self._haversine_all_modes(origin, dest)
        coros = [
            self._driving(origin, dest),
            self._walking(origin, dest),
            self._transit(origin, dest),
            self._bicycling(origin, dest),
        ]
        results = await asyncio.gather(*coros, return_exceptions=True)
        out = {}
        for mode, r in zip(["drive", "walk", "transit", "bicycle"], results):
            if isinstance(r, Exception):
                out[mode] = self._haversine_one(mode, origin, dest)
            else:
                out[mode] = r
        return out
```

### 6.2 4 个 endpoint

| Mode | endpoint | params | 解析字段 |
|---|---|---|---|
| `drive` | `/v3/direction/driving` | `origin=lng,lat&destination=lng,lat&strategy=0` | `route.paths[0].duration` 秒 → 分；`distance` 米 |
| `walk` | `/v3/direction/walking` | 同上 | 同上（无价格） |
| `transit` | `/v3/direction/transit/integrated` | 同上 + `city=...` | `route.transits[0].duration` 秒；`cost` 元 |
| `bicycle` | `/v4/direction/bicycling` | 同上（v4 endpoint） | `data.paths[0].duration` 秒 |

注意 v4 endpoint 与 v3 路径不一致；driving response 嵌套 `route.paths`，bicycling 嵌套 `data.paths`。client 内部处理差异。

### 6.3 价格估算

| Mode | 公式 |
|---|---|
| `drive` | 起步 11¥（深圳/上海/西安通用近似）+ 2.4¥ × max(0, km - 3)；高德返回 `taxi_cost` 时优先用 |
| `transit` | 高德返回 `cost` 元 |
| `walk` | null |
| `bicycle` | 共享单车按 1.5¥/30min + 0.5¥/10min 简化 |

### 6.4 haversine fallback

```python
def _haversine_one(mode: str, o, d) -> TransitInfo:
    km = haversine(o, d) * 1.4  # ×1.4 经验弯路系数
    speeds = {"drive": 30, "walk": 5, "transit": 20, "bicycle": 15}  # km/h
    minutes = int(km / speeds[mode] * 60)
    price = self._estimate_price(mode, km)
    return TransitInfo(mode=mode, minutes=minutes, distance_km=km, price_yuan=price, source="estimated")
```

### 6.5 推荐 mode 策略（per traveler_type）

| traveler_type | 推荐 mode | 理由 |
|---|---|---|
| 银发 | drive 或 transit | 不爬楼，舒服 |
| 家庭亲子 | drive | 带娃方便 |
| 情侣 | transit 或 walk | 经济+氛围 |
| 独行 | walk 或 bicycle | 灵活 |
| 商务 | drive | 效率 |
| 朋友团 | transit | 一群人地铁好 |

`recommended` 字段写在 SSE 事件里，前端默认预选。

---

## 7. 前端 chip selector 设计

### 7.1 视觉

每个 stop card 之间插一行 chip（4 个）：

```
[🚗 8min ¥15] [🚇 12min ¥4 ✓]  [🚶 28min] [🚲 18min ¥3]
```

- 4 个 chip 横向 flex
- 推荐 mode 默认选中态（amber 背景 + ✓）
- 字号小（text-xs / text-sm 灰）
- 估算来源 `source=estimated` 时 chip 边框虚线 + 标 ⚠

### 7.2 状态管理

```javascript
// per trip 全局状态
const transitSelections = new Map();  // key: `${dayIdx}_${segIdx}`, value: mode
const transitData = new Map();        // key: `${dayIdx}_${segIdx}`, value: {options, recommended}

// 收到 transit.updated 时
function handleTransitUpdated(data) {
  data.segments.forEach(seg => {
    const key = `${data.day_index}_${seg.from_index}`;
    transitData.set(key, seg);
    if (!transitSelections.has(key)) {
      transitSelections.set(key, seg.recommended);
    }
    renderTransitChips(data.day_index, seg);
  });
  recomputeDayCommuteTotal(data.day_index);
}

// chip 点击切换 mode
function selectMode(key, mode) {
  transitSelections.set(key, mode);
  renderTransitChips(...);  // 重画选中态
  recomputeDayCommuteTotal(parseInt(key.split('_')[0]));
}
```

### 7.3 rationale 联动

切 mode 后调 `recomputeDayCommuteTotal(dayIdx)`：
- 求和该天所有段的选中 mode 时间/价格
- 调 `upsertDayRationale(dayIdx, newText)` 在原 v1.5 文案后追加："（当前选地铁，全程 92 分钟，¥12）"

或者后端在 transit.updated 事件中直接给 4 套 rationale 候选，前端按选择切换显示。**第一版前端自己拼**，避免后端复杂化。

---

## 8. 后端 routes.py 集成点

```python
# api/routes.py 改动（在每个 day_done + day rationale 后）

for d in days_out:
    yield format_event("planner.day_done", ...)
    yield format_event("planner.rationale", build_rationale_for_day(...))

    # NEW: amap 异步触发，发完所有 day 之后并发处理
# 在 critic.start 之前 yield 全部 transit.updated（单后台 task gather）

amap = AmapClient(key=os.environ["AMAP_KEY"])
transit_tasks = [
    compute_day_transits(d, anchors, intent.traveler_type, amap)
    for d in days_out
]
for coro in asyncio.as_completed(transit_tasks):
    day_index, segments = await coro
    yield format_event("transit.updated", {
        "day_index": day_index,
        "segments": segments,
    })
```

注意：transit 事件晚于所有 day rationale 事件到（顺序 = profiler → planner → all day_done → all rationale → all transit.updated → critic → trip.complete）。前端 v1.5 已渲染好 day card 才更新 chip，无乱序问题。

---

## 9. 测试覆盖

### 9.1 unit `tests/test_amap_client.py` (8+ case)

- driving 解析正确
- walking 解析正确
- transit 解析正确（cost 字段）
- bicycle v4 endpoint 解析正确
- 4 模式并发同时返回
- 任一模式 timeout → 该 mode fallback 到 haversine
- amap 全部失败 → 4 mode 全 estimated
- traveler_type 决定 recommended

### 9.2 unit `tests/test_amap_fallback.py` (4 case)

- haversine 经验速度系数对各 mode 输出合理
- env `MTAGENT_AMAP_DISABLED=1` 跳过真请求
- price 估算公式（drive / transit / bicycle）

### 9.3 SSE 协议 `tests/test_sse_transit.py` (3 case)

- 3 天行程发出 3 个 transit.updated 事件（每天一个）
- 每个 segments 数 = stops - 1
- 字段 schema：mode keys、recommended、source

### 9.4 rationale `tests/test_rationale.py` (新增 +3 case)

- transit_summary={"total_min": 92, "main_mode": "transit"} → 文案含 "92 分钟" 和 "地铁"
- transit_summary=None → 跟 v1.5 一致（向后兼容）
- 估算来源 source="estimated" → 文案带「估算」标识

### 9.5 既有测试不破

77 → 77 + 8 + 4 + 3 + 3 = **95 全过**为完工标志。

### 9.6 浏览器人眼验收

输入：`"带长辈小孩五人西安三天预算 6000"`
- 每天 day card 内每对 stop 之间出现 4 chip
- 默认推荐 mode（家庭亲子→drive）选中
- 点其他 chip 切换，rationale 文案立刻更新带数字
- 估算 chip 显示 ⚠

---

## 10. 工作量预估

| 任务 | 时间 |
|---|---|
| Task 1: amap.py client + 4 mode parser + 单测 | 90 min |
| Task 2: haversine fallback + 单测 + env 开关 | 45 min |
| Task 3: schemas.Stop 加 transport_options + 反序列化向后兼容测试 | 30 min |
| Task 4: routes.py 接 amap + as_completed yield transit.updated + SSE 测试 | 60 min |
| Task 5: rationale.py transit_summary 参数 + 单测 | 45 min |
| Task 6: 前端 chip selector UI + 状态 Map + 切换 | 120 min |
| Task 7: 前端 rationale 联动 + 估算样式 | 30 min |
| Task 8: 真 uvicorn 端到端 + 浏览器验收 | 30 min |
| Task 9: commit + push | 10 min |
| **合计** | **~7-8 小时（1 工作日）** |

---

## 11. 风险与回退

| 风险 | 应对 |
|---|---|
| amap API 配额耗尽 | env `MTAGENT_AMAP_DISABLED=1` 全用 haversine，能跑 demo |
| 公交方案返回结构最复杂 | 取 `transits[0]` 首方案；多方案 v2.1 处理 |
| 前端 chip 点击重画卡顿 | DOM 更新限于单 segment，不重画整个 day card |
| traveler_type → mode 推荐错（如银发不该 drive？） | 推荐策略写在 `_RECOMMENDED_MODE` dict，可调 |
| Stop schema 加字段破坏既有 trip JSON | Optional default None，反序列化 OK；旧 trip 没 transit chip 显示 |
| 公交 API 需要 city 参数，跨城无效 | 每天 anchor 同城，传 intent.city 即可 |
| 配额估算不准（实际打车价格偏差） | source="estimated" 透明标注 |

---

## 12. 与其他子项目的接口

- **v1.5 rationale**：`build_rationale_for_day` 接收可选 `transit_summary` 参数。无 transit 数据时退化到 v1.5 行为。
- **v1.5.1 文案升级（待写 plan）**：transit 数据是 rationale 升级的核心硬证据，**v2 落地后 v1.5.1 直接读 transit_summary**
- **v1.6 流式 per-day**：v1.6 改的是 Planner 内 LLM call 的流式逻辑，与 v2 transit 计算解耦。两个分支各自落地，merge 时手动 resolve `routes.py` 中 `for d in days_out` 段（v1.6 改这段，v2 也加 yield）
- **v3 Adjuster**：用户切 mode 后某段太久 → Adjuster 触发就近替换。v3 范围
- **v3 嵌入式高德地图**：把 polyline 真画出来。已有 AMAP_WEB_JS_KEY，v2 已奠基

---

**End of v2 spec.**
