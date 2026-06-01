# POI 标签质量诊断报告

> 日期：2026-05-12
> 数据范围：深圳/上海/西安各 800 POI（共 2400）
> 脚本版本：`scripts/label_pois.py` (rules:v1 修复后)
> AI 补标：`scripts/ai_label_tasks.py` (Stage 2)

---

## 一、已修复问题

### 1.1 transit_friendly 覆盖率 97% → 66% ✅

| 城市 | 修复前 | 修复后 |
|------|--------|--------|
| 深圳 | 776/800 (97.0%) | 532/800 (66.5%) |
| 上海 | 773/800 (96.6%) | 522/800 (65.2%) |
| 西安 | 775/800 (96.9%) | 546/800 (68.2%) |

**修复方式**：transit_friendly 不再从 UGC 文本匹配，改为只从 address（不含UGC）匹配"地铁/公交"，以及 reviewTags "交通方便"。

### 1.2 quiet 覆盖率 90% → 77% ✅

| 城市 | 修复前 | 修复后 |
|------|--------|--------|
| 深圳 | 718/800 (89.8%) | 619/800 (77.4%) |
| 上海 | 721/800 (90.1%) | 613/800 (76.6%) |
| 西安 | 715/800 (89.4%) | 613/800 (76.6%) |

**修复方式**：
- 规则阶段：从 UGC 正则中去掉"聊天""休息"（行为词），只保留"安静""坐一坐"
- AI 阶段：对无 reviewTag "环境优雅"支持且 UGC 无安静正面证据的 POI，移除 quiet 标签（61个）

### 1.3 city_zone=unknown 完全消除 ✅

| 城市 | 修复前 | 修复后 |
|------|--------|--------|
| 深圳 | 182 unknown | **0** |
| 上海 | 136 unknown | **0** |
| 西安 | 14 unknown | **0** |

**修复方式**：`infer_district()` 优先使用 POI 原始 `district` 字段（800/800 都有），只在字段为空时回退到地址文本匹配。

### 1.4 西安 city_essential 误标清除 ✅

| 修复前 | 修复后 |
|--------|--------|
| 7个（钟楼KTV、回民街KTV 等全误标） | 0个（数据中确实无真地标 POI） |

**修复方式**：
- `LANDMARK_FALSE_POSITIVE_TERMS` 补充了 KTV、湘菜、川菜、粤菜、家宴等
- `is_city_essential()` 改为要求 name 以关键词开头（不含 false positive 后缀）
- 西安 mock 数据全是衍生店铺（"钟楼日料店"、"回民街烧烤摊"等），没有真正的地标 POI 本身

### 1.5 上海 city_essential 精准化 ✅

| 修复前 | 修复后 |
|--------|--------|
| 35个（含外滩家宴上海菜等误标） | 18个 |

### 1.6 上海 ZONE_BY_DISTRICT 补全 ✅

补全了杨浦区 → north，NEIGHBOR_ZONES 也同步更新。

### 1.7 photo_friendly / rest_friendly 收窄 ✅（AI 阶段）

- photo_friendly: ~89% → ~85%（移除95个无UGC拍照证据的标签）
- rest_friendly: ~55% → ~50%（移除165个无WiFi且UGC无休息证据的标签）

### 1.8 queue_heavy 交叉验证 ✅（AI 阶段）

移除11个仅由规则正则匹配但 UGC 排队证据不足的 queue_heavy 标签。

---

## 二、最终标签分布总览

### poi_role

| 角色 | 深圳 | 上海 | 西安 |
|------|------|------|------|
| meal | 394 (49.2%) | 400 (50.0%) | 400 (50.0%) |
| persona_preferred | 240 (30.0%) | 202 (25.2%) | 229 (28.6%) |
| connector | 81 (10.1%) | 100 (12.5%) | 91 (11.4%) |
| city_essential | 51 (6.4%) | 18 (2.2%) | 0 (0.0%) |
| fallback | 34 (4.2%) | 80 (10.0%) | 80 (10.0%) |

### city_zone（unknown 已完全消除）

| 城市 | 区域分布 |
|------|----------|
| 深圳 | west 44.8%, center 32.2%, east 14.2%, north 8.8% |
| 上海 | center 58.8%, east 20.8%, west 10.2%, north 10.2% |
| 西安 | south 59.2%, center 40.8% |

### planning_tags（高频前5）

| 标签 | 深圳 | 上海 | 西安 |
|------|------|------|------|
| food_quality | 88.5% | 85.0% | 88.5% |
| culture_friendly | 86.5% | 86.8% | 85.5% |
| photo_friendly | 85.9% | 84.1% | 86.1% |
| quiet | 77.4% | 76.6% | 76.6% |
| family_friendly | 67.8% | 67.8% | 68.5% |

### label_sources（数据来源）

| 来源 | 深圳 | 上海 | 西安 |
|------|------|------|------|
| rules:v1 | 800 | 800 | 800 |
| ai:ugc | 89 | 83 | 85 |

---

## 三、残留问题（需后续迭代）

### 3.1 food_quality / culture_friendly / photo_friendly 仍偏高（85-88%）

这三个标签的高覆盖率主要来自 mock 数据中 reviewTag 分布偏密（"菜品精致"、"本地特色"、"出片漂亮" 各占 60%+）。
- **非规则问题**，而是 mock 数据本身的 reviewTag 生成逻辑偏向均匀分布
- 后续如接入真实大众点评数据，覆盖率会自然下降
- 可在第三阶段人工抽查时对高分 POI 做校正

### 3.2 独行 traveler_type 覆盖率极低（0.5-1.4%）

文档已标注为已知问题。mock 数据中缺乏独行语义标签。可考虑：
- 在 fallback 逻辑中适当提升独行比例
- 或在 AI 补标阶段检测 UGC 中的"一个人""独自"等关键词（已在 ai_label_tasks.py 中实现 solo_friendly planning_tag）

### 3.3 西安 city_essential 为 0

西安 mock 数据中全部 POI 都是地标名+店铺后缀的衍生店（如"钟楼日料店"），没有真正的地标 POI。如需补充西安地标，需要在数据源层面添加真正的景点 POI。

---

## 四、第二阶段 AI 补标统计

| 指标 | 数值 |
|------|------|
| 总 AI 任务数 | 480 |
| 实际补标 POI | 257 |
| 跳过（低置信度） | 223 |
| 标签新增 | 4 (night_friendly×2, family_friendly×1, queue_heavy×1) |
| 标签移除 | 332 (rest_friendly×165, photo_friendly×95, quiet×61, queue_heavy×11) |
| poi_role 修正 | 2 |

---

## 五、交付物清单

### 第一阶段（规则标签）
- [x] `scripts/label_pois.py` — 已修复 6 处规则问题
- [x] `data/poi_labels.json` — 旧版 persona 标签（2400 POI）
- [x] `data/poi_enriched_labels.json` — 新版路线规划标签（2600 KB）
- [x] `data/poi_ai_label_tasks.jsonl` — AI 补标任务（480 个）
- [x] `data/poi_label_summary.json` — 标签分布统计

### 第二阶段（AI 语义补标）
- [x] `scripts/ai_label_tasks.py` — AI 补标脚本
- [x] `data/poi_ai_labels.json` — AI 补标结果（257 POI）
- [x] `data/poi_enriched_labels.json` — 合并后的最终标签（含 rules:v1 + ai:ugc 来源）

---

## 六、travel-agent 数据兼容性说明

`/Users/yikuaibanz1/Desktop/sth/travel-agent/data/cleaned/` 下的数据与 `mock_dianping` **完全不兼容**：
- 不同 schema（无 openshopid、reviewTags、special 等关键字段）
- 不同数据源（travel-agent 是多平台汇总，mock_dianping 是纯大众点评）
- 上海数据有重叠但 POI 零交集

如需对 travel-agent 数据做标签，需要另写一套适配脚本。
