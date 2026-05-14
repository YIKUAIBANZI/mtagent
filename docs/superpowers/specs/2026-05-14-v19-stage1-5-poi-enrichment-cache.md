# v1.9 Stage 1.5: POI Enrichment Cache Spec

> 用户拍板想法 (2026-05-14): "根据接口搜索信息, 并发吃喝玩信息分析 agent 多线分析, 在线整理 POI → 被收集过的信息固定到本地, 下一次再被搜索到 → 更新信息. 古迹/博物馆/百年老店/公交地铁站/商圈/山水 等固定信息收集本地后台 POI."

## Problem

v1.9 Stage 1 把 `fetch_around` 接进 candidate_pool 后, **POI pool 包含问题没彻底解决**:

1. **mock_dianping 只有 2400 条 POI** (深圳/上海/西安各 800), 高德 around 拉到的新 POI 走 `_infer_role_from_categories` 兜底, **没有 EnrichedLabel** (planning_tags / risk_tags / city_zone / manual_priority 全空), score_poi 落到兜底分支 (star * 5).
2. 同一个用户 query "万象天地附近", 第二次跑还是要重新调高德 around + 同样的 POI 进 candidate_pool 还是只有 star, 长期没积累.
3. mock_dianping 那 2400 条本身覆盖不全 — 用户随便问个小城市/小景点/网红店都查不到.

## Solution: POI Enrichment Cache + 双线模型

### 核心思路

把 EnrichedLabel 从 "静态 JSON 一次性打完" 改成 **"按需 enrich + 本地累积 cache"** 的流水线:

```
高德 around / search ──→  N 个 POI
                          │
                          ▼ (for each)
                     cache lookup ──Hit──→ attach EnrichedLabel 进 pool
                          │
                          Miss
                          ▼
                  并发 batch LLM enrich (asyncio.Semaphore(5))
                          │
                          ▼
                  写回 data/poi_cache.json (norm_name + 坐标 key)
                          │
                          ▼
                  attach EnrichedLabel 进 pool
```

### 双线 (Phase B 实现)

- **A 线 固定 POI**: 名字含 `城墙 / 古城 / 塔 / 寺 / 博物馆 / 宫 / 陵 / 园 / 故居 / 老字号 / 百年` 或高德 typecode `11xxxx` (景点) / `15xxxx` (交通设施 — 地铁/公交) — 一次 enrich, 长期不变. **用 qwen-max + 长 prompt 高质量打标**.
- **B 线 动态 POI**: 餐饮 (05) / 购物 (06) / 休闲娱乐 (08) — 标签变化快 (新店开 / 老店倒). **用 qwen-plus + 短 prompt 快速打标**, 加 `last_seen` 字段, 超过 N 天复核.

Phase A (本 Stage 1.5 范围) **不区分 A/B 线**, 全用 qwen-plus 同一个 prompt; Phase B 留到 v1.9 Stage 2+.

## Cache Schema

新文件 `data/poi_cache.json`:

```json
{
  "<cache_key>": {
    "name": "深圳钟楼",
    "lng": 114.0571,
    "lat": 22.5421,
    "city": "深圳",
    "typecode": "110000",
    "categories": ["景点", "历史文化"],
    "enriched": {
      "poi_role": "city_essential",
      "manual_priority": 90,
      "city_zone": "罗湖钟楼街",
      "planning_tags": ["landmark", "history_friendly", "photo_friendly"],
      "risk_tags": ["crowded_weekend"],
      "min_stay_minutes": 60,
      "max_stay_minutes": 120,
      "traveler_types": [],
      "modifiers": {}
    },
    "source": "amap_around",
    "version": "v1.9.1",
    "created_at": "2026-05-14T15:30:00Z",
    "last_seen": "2026-05-14T15:30:00Z",
    "seen_count": 1
  }
}
```

### Cache Key 算法

```python
def cache_key(name: str, lng: float, lat: float) -> str:
    return f"{_norm_name(name)}|{round(lng, 4)}|{round(lat, 4)}"
```

- `_norm_name`: 复用 `agents/anchor.py` 中的实现 (去括号 / 总店 / 分店)
- `round(_, 4)`: ~11m 精度. 同名连锁店在不同区不会撞 key, 同店多次搜到坐标小幅漂移仍命中

## 并发模型

`agents/poi_cache.py`:

```python
async def batch_enrich(
    misses: list[POI_to_enrich],
    *,
    sem_limit: int = 5,
) -> dict[str, EnrichedLabel]:
    """对 cache miss 的 POI 并发调 qwen-plus 打标."""
    sem = asyncio.Semaphore(sem_limit)

    async def _one(poi):
        async with sem:
            return await _enrich_via_qwen(poi)

    results = await asyncio.gather(*(_one(p) for p in misses), return_exceptions=True)
    ...
```

- 50 POI / 5 并发 ≈ 10 round × (~1.5s LLM 延迟) ≈ 15s — 用户感知"略慢但能接受"
- 失败的 POI 不写 cache, 下次重试

## 集成点 (planner_instant.py)

当前 v1.9 Stage 1 改动后的代码:

```python
if intent.anchor_lng and intent.trip_mode in ("anchor_explore", "layover_eat", ...):
    around = await fetch_around(...)
    if around:
        pois = merge_with_local_pool(amap_pois=around, local_pois=pois, ...)
```

Stage 1.5 改成:

```python
if intent.anchor_lng and intent.trip_mode in (...):
    around = await fetch_around(...)
    if around:
        # NEW: cache 层
        from agents.poi_cache import lookup_and_enrich
        amap_pois_with_labels = await lookup_and_enrich(around, city=intent.city)
        # 走老 merge (但现在传 enriched 已经 attached 的 POI)
        pois = merge_with_local_pool(
            amap_pois=amap_pois_with_labels,  # 改为已 enriched 的 list[POI]
            local_pois=pois,
            ...
        )
```

需要 `merge_with_local_pool` 同时接受 `AroundPOI`(原) 或 `POI`(已 enriched). 改签名兼容两种.

## 关键不变量 (Stage 1.5 不能违反)

- ✅ Stage 1 ship 的 6 commits 不动 (helper / build_pool / fetch_around / tag_mapping / score_poi / audit)
- ✅ Stage 1 累计 249 测试 + 1 known flaky 不破
- ✅ mock_dianping 那 2400 条 POI 仍是 local_pois 基线 (作为 A 线初始资产, refix 后高质量)
- ✅ 没设 anchor 的 query (Scene C/D) 不走 cache (零回归)
- ✅ Cache miss 时 LLM 调用失败不阻塞 — 用 categories 兜底进 pool (_bucket_of 已支持)

## Acceptance

- ✅ 第一次 query "深圳万象天地附近" cache 全 miss → 并发 enrich 50 POI ≤ 20s → 写入 cache
- ✅ 第二次同 query cache 全 hit → 不调 LLM, 直接 attach enriched
- ✅ 写入后 candidate_pool 的 amap POI 进 city_essential/persona_preferred/meal/connector 比例正确
- ✅ 累计 ≥ 255 测试 (新增 ~6 个 cache 单测)

## 不在 Stage 1.5 范围 (推到 Stage 1.6 / 2)

- ❌ A/B 线区分 (qwen-max vs qwen-plus)
- ❌ 老 cache entry 复核 / 失效机制
- ❌ Cross-city cache merge / cache 备份到 git
- ❌ UI 暴露 "本次新 enrich 了 N 个 POI" (Stage 3 Adjuster 一起做)

---

## Phase C — Cache 增量更新 + RAG 化 (用户拍板远期目标, v1.9 Stage 2+)

> 用户原话: "固定 POI 不是一直是会随着使用更新的吗, 然后后续定期 RAG 存的本地作为 LLM 知识库."

### 增量更新 (Phase A 已部分实现, Phase C 完善)

A 线"固定 POI" **基础结构稳定** (name / lng / lat / typecode / categories / min_max_stay), 但下列字段**每次被搜到都会更新**:

- `last_seen` / `seen_count` / `popularity_score` (= 滑动窗口 30 天 seen_count)
- `risk_tags` (新 reviewTags 命中 "等位久 / 价格偏贵" 等 → EMA 累加)
- `planning_tags` 微调 (季节性, 例 春天樱花 → photo_friendly 强化)
- `recent_review_summary` (LLM 抽样 5 条新 review 提炼一句话, 给 chat agent 用)

B 线"动态 POI" 全字段可换 (新店开 / 老店关; 价格区间变化大). `last_seen` 超 90 天的 entry 标记为 stale, 下次搜到时强制重 enrich.

### RAG 化 (Phase C 核心)

POI cache 不只是 candidate_pool 的"快照库", 而是 **项目级 LLM 知识源**:

```
data/poi_cache.json  ──批量 embedding──→  data/vector_store/{city}.index
                                                  │
                            ┌─────────────────────┼──────────────────────┐
                            ▼                      ▼                       ▼
                    planner.compose_one_day   chat agent              critic.review_route
                    (规划时 retrieve 相似 POI)   ("这店周末排队吗"     (检查路线时
                                              → retrieve POI cache    引用 cache 知识)
                                              → 自然语言回答)
```

**实现路径**:
1. 选 embedding model: `text-embedding-v3` (qwen, 1024 维) 或 `bge-large-zh-v1.5` (本地, 1024 维)
2. 选向量库: `chromadb` (Python 进程内, 简单) 或 `faiss` (大规模快)
3. 索引粒度: 每 POI 一个 vector, payload 含 name + planning_tags + risk_tags + city_zone + recent_review_summary
4. 触发更新: cache upsert 时 enqueue embedding 任务 (异步), 或每天 cron 扫 stale entries 批量 rebuild
5. 接入点: 在 `agents/poi_cache.py` 加 `retrieve_similar(query: str, city: str, k: int) -> list[POI]`

**收益**:
- chat agent 回答"附近哪里能吃到本地特色"不需要每次重新调 LLM 推断, 直接 retrieve cache top-k
- planner 给 LLM 喂候选池时, 可以从 cache 里 retrieve 跟 user query 语义相近的 POI (不止靠 anchor 半径)
- critic 检查路线时能引用 cache 里的 `recent_review_summary` (例 "这家店最近差评开始堆积")

**不做**:
- ❌ 跨用户共享 cache (cache 是项目级, 不分用户)
- ❌ Real-time 抓大众点评 review (mock_dianping 那 800 条作为 reviewTags 来源)

### A/B 双线在 Phase C 的角色 (用户图示落地)

```
┌────────────────────────────────┐    ┌────────────────────────────────┐
│  A 线 - 基础结构稳定             │    │  B 线 - 动态短周期               │
│  古迹/博物馆/老字号/地铁/商圈/山水  │    │  餐饮/咖啡/小店/网红打卡         │
│                                │    │                                │
│  enrich: qwen-max + 长 prompt   │    │  enrich: qwen-plus + 短 prompt   │
│  更新: planning_tags 微调       │    │  更新: 90 天 stale → 强制重打     │
│  RAG: 长期高权重 (城市骨架)      │    │  RAG: 时效权重 (recent_review)   │
└────────────────────────────────┘    └────────────────────────────────┘
```

判别规则 (在 `agents/poi_cache.py:classify_line` 实现):

```python
A_LINE_KEYWORDS = ("城墙", "古城", "塔", "寺", "博物馆", "宫", "陵", "园",
                   "故居", "老字号", "百年")
A_LINE_TYPECODE_PREFIX = ("11", "15")  # 11 景点 / 15 交通设施

def classify_line(name: str, typecode: str) -> Literal["A", "B"]:
    if any(kw in name for kw in A_LINE_KEYWORDS):
        return "A"
    if typecode[:2] in A_LINE_TYPECODE_PREFIX:
        return "A"
    return "B"
```
