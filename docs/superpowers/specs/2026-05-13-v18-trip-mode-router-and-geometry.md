# v1.8 路由 Agent + 几何形态算法 + 锚点驱动候选池

**Date**: 2026-05-13
**Status**: Spec draft (未实现, 等用户拍板接口)
**Purpose**: 解决 v1.7 P0 #1 — 用户说锚点("万象天地附近")得到 27km 外的路线; 同时把"本地探索 / 短停留 / 多日旅行"几种场景统一在一套数据流里.

---

## 1. 产品语义分类 (用户拍板)

旅行规划本质上只有两种几何形态:

| 形态 | 典型场景 | 路径特征 | 时间盒 |
|---|---|---|---|
| **圈型 (cycle)** | 本地探索一片新区域 / 朋友带逛 / 锚点附近转 | 起终点同一 zone, 顺时针游走 | 半日 ~ 一日 |
| **长线型 (path)** | 暂留打卡名迹 / 中转游 / 多城多日 | 起终点可不同, 跨 zone 串联 | 几小时 ~ 多日 |

多日规划 = 几何形态的组合 (Day1 cycle + Day2 path).

---

## 2. trip_mode 路由 (4 类)

Profiler 抽出 `trip_mode` enum:

| mode | 触发条件 | 几何 | 锚点策略 |
|---|---|---|---|
| **anchor_explore** | free_text 含"附近/转转/逛逛/这边" + 有 start_location_text | cycle | 锚点 zone 内 2-3km |
| **layover** | 含"中转/转机/路过/停留/X 小时后要走/赶火车/赶飞机" + estimated_hours ≤ 8 | path (round-trip) | 锚点 = 火车站/机场, 最后 stop 必须 ≤ 1km 回锚点 |
| **landmark_must** | 没锚点 + 半日/一日 + 城市 | cycle (zone-density 选最优 zone) | 选 city_essential 密集 zone 当 anchor |
| **multi_day** | days ≥ 2 | path (跨 zone) | v1.6 现有 _pick_anchors 逻辑 |

### 2.1 路由算法 (规则 + LLM 兜底)

```python
def route_trip_mode(intent: ParsedIntent) -> TripMode:
    text = intent.start_location_text or ""
    raw = intent.raw_user_text or ""

    # 1) 多日优先
    if (intent.days or 1) >= 2:
        return "multi_day"

    # 2) layover 关键词强匹配
    LAYOVER_KW = ("中转", "转机", "路过", "停留", "赶火车", "赶飞机",
                  "高铁", "动车", "几小时后", "X小时后")
    TRANSIT_HUB = ("火车站", "高铁站", "机场", "动车站", "客运站")
    if any(k in raw for k in LAYOVER_KW) or any(h in text for h in TRANSIT_HUB):
        return "layover"

    # 3) anchor_explore: 有具体地点锚点 + 探索关键词
    EXPLORE_KW = ("附近", "周边", "转转", "逛逛", "这边", "这里")
    if intent.start_location_text and any(k in raw for k in EXPLORE_KW):
        return "anchor_explore"
    # 锚点但没说附近 — 仍走 anchor_explore (用户说锚点本身就是探索意图)
    if intent.start_location_text:
        return "anchor_explore"

    # 4) 兜底: landmark_must
    return "landmark_must"
```

LLM 兜底: Profiler prompt 加 `trip_mode` 字段, LLM 自己推, 上面规则只作 fallback.

---

## 3. 锚点驱动的候选池 (核心)

### 3.1 流程

```
free_text
  → Profiler 抽 trip_mode + start_location_text + estimated_hours
  → agents/anchor.py:
      ├─ resolve_anchor(text, city)  # 高德 geocode → (name, lng, lat, adcode)
      ├─ amap_around(lat, lng, radius, categories)  # 高德 /place/around
      └─ merge_with_local_pool(amap_pois, local_pois)
            按 (normalize_name, < 100m) 去重, 内置优先 (有 enriched 标签)
  → candidate_pool 加 distance_penalty + radius_filter
  → planner prompt 把 anchor + radius + mode 传给 LLM
```

### 3.2 高德 API 选型

**已有 AMAP_KEY 在 .env**: `51744eaf7eabc9e02c329bdfaeff1fd6`

| 用途 | endpoint | 返回 |
|---|---|---|
| 文本 → 坐标 | `/v3/geocode/geo?address=万象天地&city=深圳` | location "lng,lat" + adcode + formatted_address |
| 周边 POI | `/v3/place/around?location=lng,lat&radius=3000&types=050000\|060000\|080000` | POI 列表 (name/location/typecode/距离) |
| POI 详情 | 已有 batch_get_poi_details, 走老路径 | — |

types 编码 (高德标准):
- `050000` 餐饮服务
- `060000` 购物服务
- `080000` 体育休闲服务
- `110000` 风景名胜
- `100000` 住宿服务 (排除)

### 3.3 agents/anchor.py 接口设计

```python
class AnchorResolution(BaseModel):
    text: str                        # 用户原话 "万象天地"
    name: str                        # 高德标准化 "深圳万象天地"
    lng: float
    lat: float
    adcode: str                      # "440300" 深圳市
    formatted_address: str
    confidence: Literal["high", "medium", "low"]  # 来自高德 level

async def resolve_anchor(text: str, city: str) -> Optional[AnchorResolution]:
    """高德 geocode 文本 → 坐标. 失败返回 None, Profiler 走 landmark_must."""

async def fetch_around(
    lng: float, lat: float, radius_m: int,
    types: list[str] = None,           # 默认餐饮+景点+购物
    limit: int = 50,
) -> list[AroundPOI]:
    """高德周边搜索. limit ≤ 50 (高德 page_size 上限)."""

class AroundPOI(BaseModel):
    name: str
    lng: float
    lat: float
    typecode: str                    # 高德 typecode
    distance_m: int                  # 距锚点直线距离
    address: str
```

### 3.4 merge 策略 (本地 + 高德)

```python
def merge_with_local_pool(
    amap_pois: list[AroundPOI],
    local_pois: list[POI],
    anchor: AnchorResolution,
    radius_m: int,
) -> list[POI]:
    """合并规则:
    1. 本地 POI 在半径内: 直接保留 (有 enriched 标签, 高优先)
    2. 高德 POI 在半径内但本地没有: 转 POI 对象 (无 enriched, 走 fallback 评分)
    3. 去重 key: (norm_name, < 100m) — 解决高德/内置同 POI 名字/坐标微差
    4. 排序: 内置 enriched.manual_priority 优先, 再按 distance asc
    """
```

去重 key 实现:
```python
def _norm_name(n: str) -> str:
    """去括号注释/分店名后缀, 简繁互转可选."""
    return re.sub(r"[(（].*?[)）]|总店|分店", "", n).strip()

def _within_100m(a, b) -> bool:
    return haversine(a, b) < 0.1  # km
```

---

## 4. 几何形态算法

### 4.1 圈型 (cycle) — anchor_explore / landmark_must

**目标**: 半径内 N 个候选 POI 选 K 个 (K = 槽位数), 串成短路径, 起终点都在锚点附近.

**算法: 贪心 Nearest Neighbor + 2-opt 优化**

```python
def solve_cycle(
    anchor: tuple[float, float],
    candidates: list[POI],
    slots: list[DaySlotSpec],        # 槽位 (上午景点/午饭/下午/晚饭)
    radius_km: float = 3.0,
) -> list[POI]:
    """
    1. 按 slot 桶分组 candidates (上午=景点, 午饭=美食, 下午=购物/休闲, 晚饭=美食)
    2. 每槽位贪心选 (score + distance penalty) 最高的 POI
    3. 用 2-opt 重排序减少回头路 (但保持时段语义不变)
    4. 终点回到 anchor 附近 (最后一站 ≤ 1km)

    复杂度: O(N²) 对 N≤50 完全 OK
    """
    picked = {}
    for slot in slots:
        bucket = filter_by_slot(candidates, slot)
        # 综合评分 = enriched score - distance_penalty
        scored = [(score(p, intent) - dist_penalty(p, anchor), p) for p in bucket]
        scored.sort(reverse=True)
        for _, p in scored:
            if p.openshopid not in picked.values():
                picked[slot.name] = p
                break
    return list(picked.values())

def dist_penalty(poi, anchor) -> float:
    """超出半径硬扣分."""
    d = haversine(poi, anchor)
    if d <= 1.5:
        return 0
    elif d <= 3.0:
        return (d - 1.5) * 10   # 1.5-3km 线性
    else:
        return 50 + (d - 3.0) * 20  # 远的硬罚
```

**2-opt 简化**: 即时路径 ≤ 5 个 POI, 用 brute-force 算 5! = 120 全排列也行, 选总 transit 最小的.

### 4.2 长线型 (path) — layover

**目标**: 给定起点(锚点 = 火车站) + 时间预算 T + POI 池 + 必须返回起点, 选 K 个 POI 总得分最大, 总耗时 ≤ T.

**算法: Orienteering Problem 简化版 (TTDP)**

```python
def solve_layover(
    anchor: tuple[float, float],     # 火车站/机场
    candidates: list[POI],
    time_budget_min: int,            # estimated_hours * 60
    avg_stay_min: int = 60,          # 每 POI 平均停留
    return_buffer_min: int = 30,     # 返回锚点预留 (safety margin)
) -> list[POI]:
    """
    1. 候选过滤: 距锚点单程 ≤ time_budget * 0.3 (避免单程吃掉预算)
    2. 计算每 POI 的 (score, time_cost = 往返 transit + stay)
    3. 贪心: 每步选 score/time_cost 比值最高且总耗时 < budget - return_buffer
    4. 最后一站必须能在 return_buffer_min 内回到锚点
    复杂度: O(N²), N ≤ 30
    """
    available_min = time_budget_min - return_buffer_min
    selected = []
    cumulative = 0
    remaining = sorted(
        candidates,
        key=lambda p: score(p, intent) / max(time_to(anchor, p) + avg_stay_min, 1),
        reverse=True,
    )
    for p in remaining:
        # 时间 = 上一站到 p + p 停留
        prev = selected[-1] if selected else anchor_poi
        leg = time_to(prev, p) + avg_stay_min
        # 检查能否回锚点
        return_time = time_to(p, anchor_poi)
        if cumulative + leg + return_time > available_min:
            continue
        selected.append(p)
        cumulative += leg
    return selected
```

**关键不变量**:
- 第一站和最后一站到锚点的距离都 ≤ time_budget * 0.3
- 总耗时 < time_budget - return_buffer

### 4.3 多日 (multi_day)

复用 v1.6 现有 `_pick_anchors + cluster_anchor_orbit + compose_one_day` 路径, 不动.

唯一改动: anchor 选择时, 如果 Profiler 给了 `start_location_text`, 第一天 anchor 用解析出的坐标 (其它天仍按 city_zone 散开).

---

## 5. Prompt 改造

### 5.1 Profiler prompt 加 trip_mode

`agents/prompts/profiler.md` 加段:

```markdown
## trip_mode 推断 (v1.8)

根据用户描述推断旅行模式:
- "anchor_explore" — 用户提到具体地点 ("万象天地附近"/"我在某某这边") + 探索意图
- "layover" — 中转停留 ("中转/路过/赶火车/X 小时后要走") + 通常 ≤ 8 小时
- "landmark_must" — 没指定锚点, 想去这个城市玩 ("西安半天拍照") — 系统选热门 zone
- "multi_day" — 用户明确说几天 (≥2 天)

输出字段:
- "trip_mode": "anchor_explore" | "layover" | "landmark_must" | "multi_day"
- "anchor_radius_km": 1.5 | 3.0 | 5.0  (anchor_explore 默认 3, layover 不用此字段)
- "return_to_anchor": true | false  (layover 必须 true)
```

### 5.2 Planner prompt 按 mode 分支

`agents/prompts/planner.md` 加 user message 变量:

```markdown
- trip_mode: {trip_mode}
- anchor: {anchor_name} ({lng},{lat})

**模式约束 (必须遵守)**:
- 如果 trip_mode == "anchor_explore":
  所有 stops 必须在 anchor 半径 {radius_km}km 内. 最后一站尽量回 anchor 附近.
- 如果 trip_mode == "layover":
  最后一站必须 ≤ 1km 到 anchor (返回火车站/机场). 总耗时不超过 {time_budget} 分钟减去 30 分钟 buffer.
- 如果 trip_mode == "landmark_must":
  优先 city_essential 桶, 集中一个 city_zone, 减少跨区奔波.
- 如果 trip_mode == "multi_day":
  按 day_index 顺序排, 每天集中一个 city_zone.

JSON schema 不变 (沿用 v1.7 stops[]), 加可选字段:
- "geometry": "cycle" | "path"
- "anchor_distance_km": 各 stop 离 anchor 的距离 (用于前端展示)
```

---

## 6. v1.7 集成 Diff 路径

### 6.1 新文件

| 文件 | 内容 |
|---|---|
| `agents/anchor.py` | resolve_anchor / fetch_around / merge_with_local_pool |
| `agents/trip_router.py` | route_trip_mode + AnchorRadius config |
| `agents/geometry.py` | solve_cycle / solve_layover (路径优化, 给 fallback 用) |
| `tests/test_anchor.py` | geocode mock + around mock + merge dedupe |
| `tests/test_trip_router.py` | 4 mode 路由规则单测 |
| `tests/test_geometry.py` | 2-opt + 贪心 NN 验证 |

### 6.2 修改文件

| 文件 | 改动 |
|---|---|
| `dianping/schemas.py` | ParsedIntent 加 `trip_mode`, `anchor_radius_km`, `return_to_anchor` |
| `agents/profiler.py` | 跑 resolve_anchor 后 (best-effort), 调 route_trip_mode |
| `agents/planner_instant.py` | plan_one_variant 接 anchor 参数; 不同 mode 调不同 candidate filter |
| `agents/candidate_pool.py` | build_candidate_pool 加 `anchor` + `radius_km` 参数, distance_penalty |
| `agents/planner.py` | _build_one_day_payload 加 trip_mode + anchor 字段, 给 LLM |
| `agents/prompts/profiler.md` | 加 trip_mode 推断段 |
| `agents/prompts/planner.md` | 加模式约束段 |
| `api/stub_llm.py` | stub_profiler_llm 加 trip_mode 关键词识别 (规则 fallback 同 trip_router.py) |
| `api/routes.py` | _stream_instant_variants 不变, 但 anchor 解析在 Profiler 阶段完成 |

### 6.3 老路径兼容 (不动)

- v1.6 多日路径 (Planner.run + compose_one_day) 不变
- ctx.variants 持久化逻辑不变
- 旧 SSE 事件不变 (profiler.understood / planner.day_done 等)
- ParsedIntent 老 3 必填字段不变
- 186+2 测试 baseline 不破

---

## 7. 工程量 + 优先级

| 阶段 | 文件 | 时间 | 风险 |
|---|---|---|---|
| **P0a** | agents/anchor.py (geocode + around) + 单测 | 1h | 低 (高德 API 已验过) |
| **P0b** | agents/trip_router.py + stub_llm 关键词 + 单测 | 30min | 低 |
| **P0c** | candidate_pool 加 anchor distance_penalty + 单测 | 30min | 低 |
| **P0d** | profiler.py 接 anchor 解析 + ParsedIntent 加字段 | 30min | 中 (要保持向后兼容) |
| **P0e** | planner_instant.py 把 anchor 传给 compose_one_day | 20min | 中 (prompt 协议要稳) |
| **P0f** | prompts/profiler.md + planner.md 改造 | 30min | 中 (LLM 真链路要验) |
| **P0g** | 浏览器 e2e 验 "万象天地附近 / 上海站 7h 中转" 两个场景 | 30min | 中 |
| **小计** | | **~4h** | |
| **P1** | layover 几何优化 (Orienteering 简化) | 1h | 中 |
| **P1** | 前端 anchor marker (锚点不同色) + 半径圈 | 1h | 低 |
| **P2** | 冷启动表单 (localStorage 偏好) | 1.5h | 低 |

### 7.1 推荐 ship 顺序 (用户拍板后)

1. **P0a-d** 一气呵成: anchor + router + candidate_pool + profiler 改造 → 测试通过
2. **P0e-g** prompt 改造 + 真 LLM 验证 → 浏览器跑两个 demo 场景
3. **P1** layover 几何精调 (赌评委有人提"赶火车场景")
4. **P2** 冷启动 (后期 polish)

---

## 8. 拍板项

需要用户确认才能动手:

| # | 决策 | 推荐 |
|---|---|---|
| Q1 | 高德 around 的 categories: 全拉 (餐饮+购物+景点+休闲) vs 按 interests 动态选 | **全拉** — 候选池靠 score 排序, 多比少安全 |
| Q2 | layover 识别: Profiler LLM 推 vs 关键词规则 vs 看 estimated_hours ≤ 8 | **三层 fallback**: LLM 优先, 规则兜底, hours 仅作 hint |
| Q3 | 本地 vs 高德 POI 去重 key | **(norm_name, 100m 内坐标)** — name 改装+坐标精度差能容忍 |
| Q4 | 半径默认: anchor_explore 多大? | **3km** — 步行+短驴车圈, 太小候选不够, 太大违背"附近" |
| Q5 | layover 返回 buffer | **30min** safety margin — 高德 transit 估算有 ±10min 抖动 |
| Q6 | 锚点解析失败 (geocode 0 命中) | **降级 landmark_must** + chat 提示"没找到「万象天地」, 给你当前最热推荐" |
| Q7 | anchor_radius_km 是否暴露到前端 | **暴露** — 前端画半径圈, 用户看到边界 |

---

## 9. 验收 (Demo 场景)

用户拍板后, ship 完 P0a-g 应能跑通:

### 场景 A: 锚点探索 (修 P0 #1)
```
输入: "深圳明天我想去万象天地附近转一转"
预期:
  - Profiler: trip_mode=anchor_explore, start_location_text="万象天地",
              anchor_radius_km=3.0
  - anchor.py: 解析到 (114.057, 22.541) 福田区
  - candidate pool: 万象天地 3km 内的餐厅/景点/咖啡
  - 路线: 4-5 站全在福田 CBD, 起终点都靠近万象天地, 总路程 ≤ 8km
```

### 场景 B: 中转游 (新场景)
```
输入: "上海中转 7 小时 想去外滩附近转转 之后要赶火车"
预期:
  - Profiler: trip_mode=layover, estimated_hours=7, anchor="上海站",
              return_to_anchor=true
  - anchor.py: 上海站 (121.456, 31.249)
  - candidate pool: 7h - 30min buffer = 6.5h, 单程 ≤ 2h, 外滩 + 周边
  - 路线: 最后一站必须 ≤ 1km 上海站, 总 transit + stay 在 6.5h 内
```

### 场景 C: 名迹必去 (兜底)
```
输入: "西安半天拍照"
预期: trip_mode=landmark_must → 走 v1.7 现有 city_essential 路径 (兼容)
```

### 场景 D: 多日 (兼容)
```
输入: "情侣 西安 3 天"
预期: trip_mode=multi_day → 走 v1.6 老路径, 不动
```

---

## 10. 已知不做 (v1.8 范围外)

- **TTDP 完整解** (动态规划 + 时间窗) — 现在贪心 + 2-opt 够 demo
- **多锚点旅行** ("先去 A 再去 B") — 用户没这种需求
- **跨城** ("深圳广州两日") — 老多日路径不支持, 不动
- **餐饮风格匹配** ("想吃湘菜") — 用 Profiler interests 关键词命中, 不另开 module
- **实时排队数据** — 大众点评 mock 也没这字段, 用 enriched.risk_tags=queue_heavy 静态标
