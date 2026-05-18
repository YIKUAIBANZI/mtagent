# mtagent 数据模拟落地方案

**Date**: 2026-05-14
**Source**: 用户提供的 `mtagent_data_improvement_plan.md` (GPT 方案) + v1.8 e2e 验证暴露的实际痛点
**Goal**: 给出 6 类数据资产的**模拟生成方法 + 质量校验流程**, 让 Hackathon demo 池子从"稀疏"变"够吃 + 真实".

---

## 1. 方案 vs mtagent 现状对照

GPT 方案提出 6 个数据资产, 跟当前 mtagent 的差距:

| 数据资产 | 现状 | 差距 | 阻塞 v1.8 验证 |
|---|---|---|---|
| **POI 基础数据** | ✅ 934 POI/3 城, 大众点评字段完整 | 数据量充足, 但分布不均 (锚点 4km 半径内稀疏) | 🔴 是 — 这是 e2e Scene A/B 主因 |
| **EnrichedLabel** | ✅ 实现, 字段齐, 934 全 attach | covergae OK 但质量抽检不足 (西安城墙 categories=美食 这种脏点) | 🟡 部分 — 桶错乱影响推荐 |
| **location_pools.json** | ❌ 没有 (EnrichedLabel.city_zone 字段勉强算半实现) | 完全缺 — 没"已知好玩区域"概念 | 🟡 间接 — landmark_must 没东西可选 |
| **tag_mapping.json** | ❌ 硬编码在 `candidate_pool.py:31` (INTEREST_TO_TAG) | 散在代码里, 不可维护 | 🟢 不阻塞但应该 |
| **route_slot_rules.json** | ⚠️ 半实现 (`planner_instant.py:41` _SLOT_DEFS) | 在代码里, 没数据化, 半日_上午/夜间 不完整 | 🟢 不阻塞 |
| **city_profiles.json** | ❌ 没有 | 完全缺 | 🟢 加分项 |
| **user_profile_schema.json** | ⚠️ 半实现 (ParsedIntent + cookie 兜底, 没长期画像) | 没历史/收藏/反馈 | 🟢 P2 反馈闭环 |

---

## 2. 跟 v1.8 痛点的优先级 (按"立刻能提升 demo 质量"排)

GPT 方案给的优先级 (location_pools > enriched > tag_mapping) 是面向**长期数据质量**. 我们的 Hackathon demo 时间盒 (≤ 6/7) 应该按**立刻见效**重排:

| 优先级 | 任务 | 立刻见效在 | 工程量 |
|---|---|---|---|
| **P0** | A. **集成 anchor.fetch_around 进 candidate_pool** | Scene A/B "stops 数太少" 立刻消失 | 1.5h |
| **P0** | B. **EnrichedLabel 脏点扫描 + 修** (西安城墙等) | meal/景点桶不再错乱 | 1h |
| **P1** | C. **location_pools.json 生成** (每城 10-15 个 zone) | landmark_must 场景从城市级泛推变 zone 级精推 | 3-4h |
| **P1** | D. **tag_mapping.json 抽出** | 可维护性 + Profiler/Planner prompt 一致 | 30min |
| **P2** | E. **city_profiles.json 生成** (weather_rules 已有, 补 avoid_rules + default_zones) | 雨天/节假日策略更细 | 1h |
| **P2** | F. **route_slot_rules.json 抽出** | 槽位规则可调, 不用改代码 | 1h |
| **P3** | G. **user_profile 反馈闭环** | 长期个性化, demo 内体现不出来 | 半天 |

---

## 3. 模拟数据的方法 — 每个文件分别说

模拟数据有 3 种生成方式, 不同文件按特性选:

| 方式 | 适用 | 校验难度 |
|---|---|---|
| **手工种子 + LLM 扩写** | 区域/城市这种小规模高质量数据 | 低 (人工抽检 100%) |
| **LLM 全量生成 + 规则校验** | 大量 POI label 这种 | 中 (规则过滤 + 抽样 20%) |
| **真实数据 + 规则补全** | 已有 POI 加 enriched | 高 (跟原数据一致性校验) |

### 3.1 location_pools.json (P1, 推荐手工 + LLM 协作)

**做法**:

**Step 1 — 手工列种子**: 我每城用高德地图 + 本地知识列 15 个 zone (10 分钟可完成), 字段只填:
```
zone_id, name, center (从高德 geocode 拿坐标), district, radius_km, type
```

**Step 2 — LLM 扩写 5 个评分字段 + tags**:

提示词模板:
```
你是深圳本地资深玩家. 给定 zone "万象天地 / 科技园" (中心 22.541, 113.953, 半径 2.5km),
按以下 schema 返回 JSON, 必须基于事实 (不要虚构 POI/路名):

{
  "tags": ["美食", "购物", ...],            # 选 3-6 个标签
  "good_time_windows": ["半日_下午", ...],  # 哪些 time_window 适合
  "suitable_traveler_types": [...],         # 4 类 traveler 哪些适合
  "transport_score": 0.9,                   # 0-1, 地铁/公交便利度
  "food_score": 0.9,
  "shopping_score": 0.85,
  "night_score": 0.75,
  "photo_score": 0.8,
  "crowd_risk": 0.6,                        # 0-1, 高峰拥挤度
  "avg_budget_level": "适中",                # 性价比/适中/精致
  "recommended_duration_hours": [3, 5],
  "description": "30 字内描述区域特色"
}

要求:
- description 必须含具体地名/品类 (不能"环境优雅服务好")
- 分数差异要明显 (不要每个都 0.7-0.8)
- 不知道就给中间值 0.5, 别瞎编
```

**Step 3 — 校验**:
- 用 anchor.resolve_anchor 验 center 坐标 (高德能不能定位到)
- 检查 zone 跟 mock_dianping POI 重叠 (每个 zone 至少 ≥ 5 个 POI 在 radius_km 内)
- 抽检 5 个 zone 让人工看 description 是否"有具体细节"

**模拟工程量**: 3 城 × 15 zone × ~2 min/zone (LLM + 校验) = ~1.5h, 加 2h 跑数据 = **3.5h**

**质量门**: 每 zone description 至少含 1 个具体地名 + radius_km 内 POI ≥ 5

### 3.2 EnrichedLabel 脏点修复 + 补全 (P0)

GPT 方案的"P0 200 个核心 POI 有 enriched label" — 我们已经 934 全覆盖, 但质量不一. 实际做法:

**Step 1 — 自动扫描**:

写个 `scripts/enriched_quality_audit.py` 跑全量 POI, 标红:

```python
RULES = [
    ("城墙/古城/塔/寺" in name) and ("美食" in categories),    # 类型矛盾
    poi_role == "meal" and not any("美食" in c for c in categories),  # 角色错位
    poi_role == "city_essential" and manual_priority < 70,    # 高位 POI 低优先级
    city_zone == "",                                          # zone 缺失
    len(planning_tags) < 2,                                   # 标签太薄
]
```

**Step 2 — LLM 重打**: 标红的 POI 用提示词重新生成 enriched label:

```
你是路线规划专家. 给定 POI 信息:
  name: 西安城墙
  city: 西安
  categories: ["美食"]                   # ⚠️ 这条似乎错
  star: 4.7, reviewCount: 12345
  reviewTags: ["历史悠久 hit 234", "夜景好 hit 189", ...]
  address: 西安市碑林区南大街

按 EnrichedLabel schema 返回 JSON:
{
  "poi_role": "city_essential",          # 5 选 1, 必须对得起 categories
  "planning_tags": [...],                # 从给定词表选 (附词表)
  "risk_tags": [...],
  "city_zone": "钟楼-鼓楼-城墙",
  "suggested_slots": ["morning", "afternoon", "evening"],
  "min_stay_minutes": 60, "max_stay_minutes": 180,
  "traveler_types": [...],
  "manual_priority": 95,                  # 0-100, city_essential 通常 80+
  "fix_categories": ["景点", "历史文化"]   # 如果原 categories 错, 给修正建议
}

要求:
- categories 矛盾时, 以 name 和 reviewTags 为准 (城墙是景点不是美食)
- planning_tags 必须从 [photo_friendly, culture_friendly, ...] 词表选, 不能自造
- description 必须引用 reviewTags 里 hit 最高的项
```

**Step 3 — 人工抽检**:
- 跑完所有标红 POI 重打
- 抽样 20% 让我看, 通过率 ≥ 95% 算合格
- 不合格 5% 二次人工修

**模拟工程量**: 假设 934 POI 中 ~150 标红, LLM 重打 ~1h + 抽检 ~30min = **1.5h**

**质量门**: 跑完后再次 audit 标红率 < 3%

### 3.3 tag_mapping.json (P1, 直接抽出)

不需要"模拟", 把代码里 `candidate_pool.py:31 INTEREST_TO_TAG` 抽到 JSON:

```json
{
  "user_interest_to_planning_tags": { ...已有的 INTEREST_TO_TAG ... },
  "user_constraints_to_risk_tags": { "avoid_queue": ["queue_heavy", "crowded_weekend"], ... },
  "review_tag_to_planning_tags": {
    "环境优雅": ["rest_friendly", "couple_friendly"],
    "适合约会": ["couple_friendly"],
    ... 从 mock_dianping 实际出现的 reviewTags 反向归纳, 不要凭空写
  }
}
```

**Step 1 — 收集**: 跑脚本扫 mock_dianping 所有 reviewTags, 按 hit 总和排序, 取 top 50

**Step 2 — LLM 映射**: 给 LLM 50 个 reviewTag + 当前 planning_tags 词表, 让它一一对应:

```
给定 reviewTag "等位久" (mock_dianping 真实出现, 总 hit=2341),
从 planning_tags 词表 [...全表...] 中选 1-2 个最对应的; 如果是 risk 信号, 也可以从 risk_tags 词表选.
不要选模糊词. 没有匹配就返 [].

输出 JSON: { "等位久": ["queue_heavy"], ... }
```

**Step 3 — 人工 review**: 50 个全过一遍, ~15 min

**模拟工程量**: 30min

### 3.4 POI 池扩充 (高德 around 集成 = P0 A, 不是模拟)

这不是"模拟数据", 而是**真接高德 POI**. 见 §4 落地方案 A.

但有个**模拟 fallback**: 高德 around 拉不到 (网络/限流) 时, 我们也可以预生成"虚拟 POI 池":

```python
# scripts/generate_fallback_around.py
for zone in location_pools:
    # 给每个 zone 生成 30 个 POI:
    # - 6 家餐厅 (用 LLM 编名字, 真街道地址用高德 around 拿一次缓存)
    # - 6 家咖啡/下午茶
    # - 4 家购物
    # - 4 家景点
    # - 10 家 connector
```

但这不推荐 — 直接接高德 API 真数据更好.

### 3.5 city_profiles.json (P2)

每城一份, 字段在 GPT §10. 模拟方法跟 location_pools 类似:

**Step 1 — 我手工列**: 3 城 weather_rules / avoid_rules / default_zones (基本是 location_pools 的汇总), 30 min

**Step 2 — LLM 补 city_tags + recommended_trip_styles**:

```
城市: 西安. 已知 default_zones: [...].
请给出:
- city_tags: 6 个最能代表这城旅游特色的关键词 (例: 历史/面食/古迹)
- recommended_trip_styles: 这城最适合什么样的人群组合
- avoid_rules: 3 条这城路线规划 anti-pattern (例: 半日游不建议跨钟楼-华清池)
```

**模拟工程量**: 3 城 × 15min = **45min**

### 3.6 route_slot_rules.json (P2)

把 `planner_instant.py:41 _SLOT_DEFS` 抽到 JSON, 加 max_total_transit_ratio 等 v1.8 没有的字段.

不需要 LLM, **纯重构** + 加几条规则. 30min.

### 3.7 user_profile 长期画像 (P3, demo 不展示)

Hackathon 一次性 demo 体现不出长期画像价值. 留 P3, 只先把 schema 定义好留扩展点.

---

## 4. 落地执行顺序 (建议)

按 P0/P1 排, 假设 hackathon 还剩 24-30h 净开发时间:

```
Day 1 (6h):
  [P0-A] 集成 anchor.fetch_around 进 candidate_pool (1.5h)
         → 立刻让 Scene A/B 池子从 1-2 stops 涨到 4 stops
  [P0-B] EnrichedLabel 脏点扫描 + 修 (1.5h)
         → 跑 audit 脚本, LLM 重打, 抽检
  [P1-C] location_pools.json 生成 (3h)
         → 3 城 × 15 zone × LLM + 校验

Day 2 (4h):
  [P1-D] tag_mapping.json 抽出 (30min)
  [P2-E] city_profiles.json (1h)
  [P2-F] route_slot_rules.json 抽出 (1h)
  [验证] 浏览器再过 v1.8 三场景, 看 stops 数 + 真实性 (1.5h)

Day 3+ : Hackathon polish (前端 + 冷启动 + demo 视频)
```

---

## 5. 模拟数据的质量保证策略

### 5.1 三层校验

```
LLM 生成 → 规则过滤 → 抽检 → 上线
```

**规则过滤** (自动跑):
- POI: name 跟 categories 不矛盾 (城墙/塔/寺 != 美食)
- Zone: center 能被高德 geocode 反查
- EnrichedLabel: planning_tags 全在词表内
- city_zone: 跟 location_pools 里的 zone_id 一致

**抽检** (人工):
- 每批 LLM 输出抽 20%
- 抽检率 ≥ 95% 通过才上线
- 不通过的 5% 退回 LLM 重打或人工改

**上线** (commit + 跑测试):
- 每次数据更新跑 `tests/test_real_data_smoke.py` (跑现有 v1.7 smoke + 加 v1.8 anchor smoke)
- 全测试 baseline 不能破

### 5.2 LLM 模拟的反 hallucination 措施

GPT 方案没强调, 但实战经验:

| 风险 | 措施 |
|---|---|
| LLM 编造不存在的 POI 名字 | 提示词强约束 "必须基于真实地名, 不知道就返 null" |
| LLM 给所有 POI 同一组高分 | 用 few-shot 给反差示例 (好分/坏分各 1 个) |
| LLM 输出格式漂移 (JSON 多/少字段) | response_format=json + pydantic 二次校验 + 抓 raise 重试 |
| LLM 漏字段 (planning_tags 空) | 规则补默认值 ("低风险 POI" → 给 `rest_friendly`) |
| 不同 LLM 风格不一致 | 同一批用同一 model + 同一 temperature (建议 0.2 偏稳) |

### 5.3 增量 vs 重做

**增量** 优先于 **重做**:
- 已有 934 POI 的 enriched 大部分对, 只标红 ~15% 重打
- location_pools 一次性生成, 后续手工微调
- tag_mapping 一次抽出, 后续按需加词

---

## 6. 我的具体建议

**今天 (剩余时间)**:
- 把这份报告对齐后, 直接动手 **P0-A 集成 fetch_around** (1.5h)
- 这是 ROI 最高的一步, 不需要数据准备, 代码就能 ship

**明天**:
- **P0-B EnrichedLabel 脏点** (1.5h) — 写 audit 脚本, 跑全量, LLM 重打标红
- **P1-C location_pools** 开始 (我负责 prompt + 校验脚本, 你做种子区域确认)

**最关键的决策点**:
- ⚠️ **要不要做 location_pools** — 工程量 3h, 但能让"landmark_must" 场景从城市级泛推变 zone 级精推. 如果你觉得 P0-A 集成 fetch_around 后池子够丰富, location_pools 可以推到 P2
- ⚠️ **要不要做 user_profile 长期画像** — Hackathon 一次性 demo 看不到价值, 建议 P3 不做

---

## 7. 不在本报告范围

- **真接美团/大众点评接口** — 需要资质, hackathon 时间不够
- **小红书 UGC 爬取** — 用户已经在数据底座做了 (xhs), 本报告不重复
- **POI 质量分** (GPT §13 P2 第 9 点) — 太重, demo 用不上
- **行为反馈闭环** — P3, demo 一次性看不到
- **完整 5 模式 prompt 测试套** — v1.8 task 8 prompts 改完了, 真 LLM 验证留 e2e
