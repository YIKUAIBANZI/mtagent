# v1.9 Stage 1.5: POI Enrichment Cache Spec

> 用户拍板想法 (2026-05-14):
> 1. "根据接口搜索信息, 并发吃喝玩信息分析 agent 多线分析, 在线整理 POI → 被收集过的信息固定到本地."
> 2. "主要两条线就是: 直接搜 POI / 搜本地内置 POI 数据."
> 3. "直接搜到的 POI 数据用得多可以内置到本地 POI 然后定期一起 RAG 固化."

## 双线含义 (用户澄清, 按数据来源分, 非按 POI 性质分)

```
┌─────────────────────┐         ┌─────────────────────┐
│  线 ① 实时搜索       │         │  线 ② 本地内置库      │
│  (live fetch)        │         │  (local POI store)   │
│  ─────────────────   │         │  ─────────────────   │
│  agents.anchor.       │         │  data/mock_dianping/ │
│  fetch_around 高德    │         │  *.json (2400 POI)   │
│  每次 query 即拉       │         │  + enriched_labels   │
│  快 + 全 + LLM 贵     │         │  + (晋升来的 POI)     │
└──────────┬──────────┘         └──────────▲──────────┘
           │                                │
           ▼                                │
     poi_cache.json                          │  ← Promotion (Phase B)
     ─────────────────                       │  seen_count ≥ 5
     seen_count++                            │  → 复制本地表
     last_seen 刷                            │
                                             │
                                             │
   三池合并 → embedding → 向量库 → RAG (Phase C)
```

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

### 分 Phase 落地

- **Phase A** (本 Stage 1.5 已 ship): cache 骨架, 实时搜索 → enrich → 写 cache. 不做晋升 / 不做 RAG.
- **Phase B** (后续): **Promotion 晋升机制** — cache 中 `seen_count ≥ 5` 的 entry 复制进本地 POI 库, 之后规划时走本地零成本路径.
- **Phase C** (远期): cache + 本地 + 晋升后的合并库 → embedding → chromadb 向量库 → planner/chat/critic 共用的 RAG 知识源.

注: 早期 spec 提过 "A 线固定 POI / B 线动态 POI" 的按性质分线 — **此版本以用户 2026-05-14 澄清为准, 双线指数据来源而非 POI 性质**. `agents/poi_cache.py:classify_line` 函数 (识别 城墙/塔/博物馆/typecode 11/15) 仍保留, 但只作为 Promotion 优先级提示 (A 类景点优先晋升), 不再作为分流 model 强度的依据.

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

## 不在 Stage 1.5 范围 (推到 Phase B / C)

- ❌ Promotion 晋升机制 (Phase B)
- ❌ 三池合并 → embedding → 向量库 RAG (Phase C)
- ❌ 老 cache entry 复核 / 失效机制 (Phase C 配套)
- ❌ UI 暴露 "本次新 enrich 了 N 个 POI" (Stage 3 Adjuster 一起做)

---

## Phase B — Promotion 晋升机制 (用户拍板, 2026-05-14)

> 用户原话: "直接搜到的 POI 数据用得多可以内置到本地 POI 然后定期一起 RAG 固化."

### 触发条件

cache entry 满足 **seen_count ≥ 5** 即晋升 (用户拍板的阈值, 简单可调).

### 实施: `scripts/promote_cache.py` (独立脚本, 手动 / cron 跑)

```python
"""Promote cache entries with seen_count >= 5 into local POI store.

把 data/poi_cache.json 中常被搜到的 entry 复制进:
- data/mock_dianping/{city}.json (POI 主表追加)
- data/poi_enriched_labels.json (EnrichedLabel 追加)

复制后 cache entry 加 `promoted: true` 标记, lookup 时优先走本地路径.
本地有副本的 cache entry 不再被晋升 (跳过).
"""

def promote_cache(
    *,
    min_seen_count: int = 5,
    cities: list[str] = ["深圳", "上海", "西安"],
    dry_run: bool = False,
) -> dict:
    """返回 {city: {promoted_count, skipped_already_local, ...}}.

    步骤:
    1. load data/poi_cache.json
    2. 对每个 entry, 检查 seen_count >= min_seen_count AND not promoted
    3. classify_line() 优先 A 类景点 (城墙/塔/博物馆/typecode 11/15)
    4. 转 POI dict + EnrichedLabel dict
    5. 追加到 mock_dianping/{city}.json (去重: openshopid 不重复)
    6. 追加到 poi_enriched_labels.json[city][openshopid]
    7. cache entry 标记 promoted=true
    """
```

### 触发方式

```bash
# 手动跑 (推荐 hackathon demo 前预热)
PYTHONPATH=. venv/bin/python scripts/promote_cache.py --dry-run
PYTHONPATH=. venv/bin/python scripts/promote_cache.py

# 或加 cron (远期):
# 0 3 * * * cd /path/to/mtagent && venv/bin/python scripts/promote_cache.py
```

### Acceptance (Phase B)

- ✅ cache 中 seen_count ≥ 5 的 entry 被复制进本地表
- ✅ 同 openshopid 重复时跳过 (幂等)
- ✅ 下次 `lookup_and_enrich` 走本地路径不再调 LLM
- ✅ 单测覆盖: 阈值过滤 / 幂等 / cache 标记 promoted

---

## Phase C — RAG 化 (用户拍板, 远期目标 v2.0+)

> 用户原话: "然后定期一起 RAG 固化."

### 数据流

```
线 ① cache  ────┐
线 ② 本地 POI ──┼──→ 合并去重 ──→ 批量 embedding ──→ chromadb 向量库
晋升来的 POI ──┘                  (qwen text-embedding-v3, 1024 维)
                                          │
                                          ▼
                          ┌───────────────┼───────────────┐
                          ▼               ▼               ▼
                  planner.compose_   chat agent      critic.review_route
                    one_day            ("这店周末排队")  (引用 recent_review)
                  (语义相近 POI top-k)
```

### 技术栈 (用户拍板)

- **Embedding**: `text-embedding-v3` (qwen via DashScope, 1024 维) — 复用 DASHSCOPE_API_KEY
- **向量库**: `chromadb` — Python 进程内, 零部署, 数据存 `data/vector_store/{city}.chromadb/`
- **更新策略**: cache `upsert` / 本地 POI 追加时 enqueue embedding 任务 (异步, 不阻塞规划); 或日级 cron `scripts/rebuild_index.py` 批量重建.

### 统一接入接口

```python
# agents/poi_cache.py 新增
async def retrieve_similar(
    query: str,
    city: str,
    k: int = 10,
    *,
    sources: list[Literal["cache", "local", "promoted"]] = ["cache", "local", "promoted"],
) -> list[POI]:
    """语义相近 POI top-k. 各 agent (planner/chat/critic) 共用."""
```

### 接入点

- **planner.compose_one_day**: 给 LLM 喂候选池前, 先 `retrieve_similar(user.free_text, city, k=20)` 拿语义相关 POI 补进 candidate_pool (不止靠 anchor 半径)
- **chat agent** (v2 Stage 3+ 落地时): 用户问"这店周末排队吗" → retrieve → 拿 risk_tags + recent_review_summary → 自然语言答
- **critic.review_route** (v2+): 检查路线时引用 cache 里的 `recent_review_summary` (例 "这家店最近差评堆积")

### Phase C 不做

- ❌ 跨用户共享 (cache 是项目级)
- ❌ Real-time 抓大众点评 review (用 mock_dianping 那 800 条做 reviewTags 来源)
- ❌ 多模态 embedding (图像/位置 graph) — v3+

### Phase A/B 留下的钩子已具备

| Phase C 需要 | Phase A/B 是否已有 |
|---|---|
| cache entry 含基础字段 | ✅ name/lng/lat/typecode/enriched 都有 |
| cache entry 含热度信号 | ✅ seen_count / last_seen / created_at |
| 本地 POI 库可追加 | ✅ mock_dianping/*.json 格式标准 |
| 本地 enriched 可追加 | ✅ poi_enriched_labels.json 按 city.openshopid 索引 |
| classify_line (A 类优先) | ✅ Phase A 已实现 (复用作 Promotion 优先级) |
| 跨 agent 共用接口 | ❌ retrieve_similar 待 Phase C 实现 |
