# mtagent 数据底座规范

> 日期：2026-05-12  
> 状态：数据清洗与后续 Agent 开发依据  
> 范围：POI 数据、用户数据、数据来源、清洗脚本、清洗 Agent 工作指南  
> 当前城市：深圳 / 上海 / 西安

## 0. 唯一数据口径

不要把“原料数据 / 中间产物 / 最终给 mtagent 用的数据”混在一起。

当前最终口径只有两类：

```text
data/poi_enriched_labels.json
data/user_profiles/{cookie_key}.json
```

- `data/poi_enriched_labels.json`：POI 结构化标签，后续 Planner 的唯一优先输入。
- `data/user_profiles/{cookie_key}.json`：用户历史偏好画像，后续 Profiler / Planner / Adjuster 读取。

以下文件都不是 Planner 的最终输入，只能算原料或中间产物：

```text
data/mock_dianping/*.json
data/real_sources/*.jsonl
data/poi_agent_label_tasks.jsonl
data/poi_agent_label_batches/*.jsonl
data/poi_agent_labels.json
data/poi_agent_label_summary.json
```

其中 `data/real_sources/*.jsonl` 是真实来源证据层：高德提供 POI 实体、坐标、评分、营业时间；小红书提供攻略语义证据。它们必须先经过 Agent 标注 / 合并，变成 `data/poi_enriched_labels.json` 同构的数据后，才算真正进入 mtagent 路线规划数据底座。

## 1. 当前主线

现在只做六件事：

| 序号 | 工作 | 交付物 | 验收标准 |
|---:|---|---|---|
| 1 | 规范 POI 数据长什么样 | 本文第 2-4 节 | Planner 能只看结构化标签做候选池 |
| 2 | 规范用户数据长什么样 | 本文第 5 节 | Profiler / Planner / Adjuster 有统一 profile 可读 |
| 3 | 做好 POI 低级 Agent 标注流程 | `scripts/build_poi_agent_label_tasks.py` + `scripts/validate_poi_agent_labels.py` | Agent 负责判断标签，脚本只生成任务和校验结果 |
| 4 | 做好用户数据清洗脚本 | `scripts/clean_user_profiles.py` | 可从 trip / event 构建 `data/user_profiles/*.json` |
| 5 | 写清数据从哪里收集 | 本文第 6 节 | 每类数据都有来源、用途、优先级和风险 |
| 6 | 写清要收集什么字段 | 本文第 7-8 节 | 产品同学和数据 Agent 可按字段清单执行 |

这一阶段不做 Planner 接入、不做多方案、不做 SSE 持久化。数据底座稳定后，再进入路线规划实现。

## 2. POI 原始数据契约

当前原始 POI 来自：

```text
data/mock_dianping/深圳.json
data/mock_dianping/上海.json
data/mock_dianping/西安.json
```

每个城市 800 条，共 2400 条。字段契约对齐大众点评开放平台，后续切真实接口时不改业务层，只替换数据来源。

### 2.1 必填字段

| 字段 | 类型 | 用途 | 清洗要求 |
|---|---|---|---|
| `openshopid` | string | POI 唯一 ID | 不允许为空，不允许跨城市重复 |
| `name` | string | 名称 | 保留原名，不做 LLM 改写 |
| `city` | string | 城市 | 只允许深圳 / 上海 / 西安 |
| `address` | string | 地址 | 用于 district fallback 和展示 |
| `latitude` | number | 纬度 | 必须在城市合理范围内 |
| `longitude` | number | 经度 | 必须在城市合理范围内 |
| `categories` | string[] | 一级类目 | 至少 1 个，优先保留点评类目 |
| `star` | number | 星级 | 0-5 |
| `reviewCount` | integer | 评论数 | >= 0 |

### 2.2 强推荐字段

| 字段 | 类型 | 用途 |
|---|---|---|
| `avgprice` | integer | 预算判断 |
| `business_hour` | string | 营业时间检查 |
| `district` | string | 区域连续性主字段 |
| `reviewTags` | object[] | 规则标签和 UGC 智慧压缩 |
| `ugcs` | object[] | AI 语义补标输入 |
| `special` | string[] | 无障碍、婴儿椅、包间、宠物友好等 |
| `queueable` | boolean | 排队能力和排队风险 |
| `bookable` | boolean | 是否建议预约 |
| `isBlackPearl` | integer | 高质量餐饮信号 |
| `dishs` | object[] | 餐厅特色和美食解释 |

### 2.3 不可靠字段

以下字段可以存，但第一阶段不作为强约束：

```text
shopDesc
headPic
shopPics
mShopInfoUrl / appShopInfoUrl
telephone
dealInfo
takeawayinfo
mallInfo
```

原因：mock 数据或真实接口权限可能不稳定，不能让核心规划依赖它们。

## 3. POI Agent 标注输出契约

第一阶段改为 Agent-first：低级 Agent 负责标注判断，脚本只负责切任务、校验格式、统计质量。

```text
原始 POI
-> scripts/build_poi_agent_label_tasks.py
-> data/poi_agent_label_tasks.jsonl
-> 低级 Agent 分批标注
-> data/poi_agent_labels.json
-> scripts/validate_poi_agent_labels.py
-> data/poi_agent_label_summary.json
```

现有 `scripts/label_pois.py` 暂时保留为兼容/对照工具，不再作为“唯一正确”的第一阶段标注来源。

### 3.1 Agent 标注任务

文件：

```text
data/poi_agent_label_tasks.jsonl
data/poi_agent_label_batches/*.jsonl
```

每一行是一个 POI 标注任务，包含：

```text
task_id
city
openshopid
input              POI 原始字段与压缩 UGC
allowed_values     枚举边界
required_output    必须回填的字段
labeling_rules     保守标注规则
```

低级 Agent 只能使用任务里的 POI 字段和枚举，不允许创造新字段、新 POI 或不存在的事实。

### 3.2 Agent 标注结果

文件：

```text
data/poi_agent_labels.json
```

格式：

```json
{
  "深圳": {
    "openshopid_xxx": {
      "traveler_types": ["情侣"],
      "modifiers": {
        "轻量体力": false,
        "重文化": false,
        "重美食": true,
        "怕排队": false
      },
      "poi_role": "meal",
      "universal_level": "low",
      "must_consider": false,
      "manual_priority": 50,
      "planning_tags": ["food", "food_quality", "good_value"],
      "risk_tags": ["queue_heavy"],
      "district": "南山区",
      "city_zone": "west",
      "neighbor_zones": ["center", "north"],
      "suggested_slots": ["lunch", "dinner"],
      "min_stay_minutes": 60,
      "max_stay_minutes": 90,
      "confidence": 0.82,
      "label_notes": "reviewTags 有菜品精致和等位久，适合饭点但有排队风险。"
    }
  }
}
```

### 3.3 校验与统计

文件：

```text
data/poi_agent_label_summary.json
```

由 `scripts/validate_poi_agent_labels.py` 生成。它只检查：

- `openshopid` 是否来自原始数据。
- 必填字段是否齐全。
- 标签是否都在枚举内。
- 数字范围是否合理。
- 是否漏标城市或 POI。
- 各城市标签分布是否异常。

### 3.4 旧版兼容标签

现有代码仍可能读取：

文件：

```text
data/poi_labels.json
```

用途：兼容当前 `DianpingClient` 和 `route_by_persona`。

格式：

```json
{
  "深圳": {
    "openshopid_xxx": {
      "traveler_types": ["情侣", "家庭亲子"],
      "modifiers": {
        "轻量体力": true,
        "重文化": false,
        "重美食": true,
        "怕排队": true
      }
    }
  }
}
```

### 3.5 新版路线规划标签

文件：

```text
data/poi_enriched_labels.json
```

用途：后续 Planner 的唯一优先输入。稳定后应由 `data/poi_agent_labels.json` 经校验/合并生成。

格式：

```json
{
  "深圳": {
    "openshopid_xxx": {
      "traveler_types": ["情侣"],
      "modifiers": {
        "轻量体力": false,
        "重文化": false,
        "重美食": true,
        "怕排队": false
      },
      "poi_role": "meal",
      "universal_level": "low",
      "must_consider": false,
      "manual_priority": 50,
      "planning_tags": ["food", "food_quality", "good_value"],
      "risk_tags": ["queue_heavy"],
      "district": "南山区",
      "city_zone": "west",
      "neighbor_zones": ["center", "north"],
      "suggested_slots": ["lunch", "dinner"],
      "min_stay_minutes": 60,
      "max_stay_minutes": 90,
      "label_sources": ["agent:v1"]
    }
  }
}
```

## 4. POI 标签枚举

### 4.1 `poi_role`

| 值 | 含义 | 规划规则 |
|---|---|---|
| `city_essential` | 城市必去 / 地标 | 必须进候选池，不等于必须进入最终路线 |
| `persona_preferred` | 人群 / 兴趣偏好点 | 根据 traveler_type、interest、score 排序 |
| `meal` | 餐饮点 | 服务 lunch / dinner，不抢景点 slot |
| `connector` | 补位连接点 | 咖啡、商场、休息、夜景、轻量活动 |
| `fallback` | 低优先级兜底点 | 数据稀疏时才使用 |

### 4.2 `planning_tags`

第一阶段允许：

```text
photo_friendly
food_quality
culture_friendly
family_friendly
couple_friendly
group_friendly
business_friendly
senior_friendly
solo_friendly
quiet
atmosphere
good_value
good_service
fast_service
transit_friendly
rain_friendly
night_friendly
rest_friendly
shopping_friendly
first_visit_friendly
landmark
food
private_room
premium_food
pet_friendly
```

### 4.3 `risk_tags`

第一阶段允许：

```text
queue_heavy
slow_service
pricey
hard_to_find
parking_hard
facility_old
smoky
small_portion
service_average
portion_mismatch
reservation_recommended
walk_heavy
crowded_weekend
```

## 5. 用户数据契约

用户数据分三层：本次意图、历史偏好、反馈信号。

### 5.1 本次意图 `ParsedIntent`

来源：Profiler 从用户自然语言中解析。

```json
{
  "city": "深圳",
  "days": 1,
  "traveler_type": "情侣",
  "budget_level": "适中",
  "pace": "佛系",
  "preferences": ["拍照", "美食"],
  "must_visit": ["深圳湾公园"],
  "avoid": ["排队", "太累"],
  "start_date": "2026-05-12",
  "modifiers": {
    "轻量体力": true,
    "重文化": false,
    "重美食": true,
    "怕排队": true
  }
}
```

优先级最高。历史偏好不能覆盖本次明确输入。

### 5.2 历史偏好 `UserPreferenceProfile`

来源：`scripts/clean_user_profiles.py` 从 trip context 和用户事件清洗。

输出文件：

```text
data/user_profiles/{cookie_key}.json
data/user_profile_summary.json
```

格式：

```json
{
  "schema_version": "user_profile:v1",
  "cookie_key": "demo_user",
  "updated_at": "2026-05-12T12:00:00Z",
  "preference_weights": {
    "photo_friendly": 3,
    "food_quality": 2,
    "culture_friendly": 0,
    "family_friendly": 0,
    "night_friendly": 1,
    "shopping_friendly": 0,
    "good_value": 1,
    "low_queue": 2,
    "low_walk": 2
  },
  "traveler_type_weights": {
    "情侣": 2
  },
  "city_weights": {
    "深圳": 3
  },
  "budget_level_weights": {
    "适中": 1
  },
  "pace_weights": {
    "佛系": 1
  },
  "modifiers": {
    "轻量体力": true,
    "重文化": false,
    "重美食": true,
    "怕排队": true
  },
  "must_visit": ["深圳湾公园"],
  "avoid_keywords": ["排队", "太累"],
  "loved_pois": [],
  "rejected_pois": [],
  "been_there_pois": [],
  "rejected_categories": [],
  "evidence": [
    {
      "source": "trip_context",
      "trip_id": "trip_xxx",
      "signals": ["city=深圳", "preference=photo_friendly"]
    }
  ]
}
```

### 5.3 用户反馈信号

后续 Adjuster 写入事件，数据清洗脚本再归并到 profile。

最小事件格式：

```json
{
  "cookie_key": "demo_user",
  "event_type": "feedback",
  "timestamp": "2026-05-12T12:00:00Z",
  "trip_id": "trip_xxx",
  "action": "replace_stop",
  "reason": "不想去世界之窗，换一个近一点的",
  "rejected_pois": ["openshopid_old"],
  "rejected_categories": ["K歌"]
}
```

## 6. 数据来源策略

| 数据 | 第一阶段来源 | 后续真实来源 | 用途 | 风险 |
|---|---|---|---|---|
| POI 基础字段 | `data/mock_dianping/*.json` | 大众点评开放平台 POI 详情 / 搜索 | 候选池、展示、地图定位 | 权限字段可能缺失 |
| reviewTags | mock 点评标签 | 大众点评标签/聚合点评词 | Agent 标注证据、风险识别 | mock 标签偏密 |
| UGC 评论 | mock UGC | 大众点评精选评论 | Agent 语义判断证据 | 不要在线实时总结 |
| 人工核心点 | `data/poi_manual_labels.json` | 产品同学维护 | 城市地标、误标修正 | 需要审查，不可无限膨胀 |
| 用户本次意图 | Profiler 输出 | 自然语言输入 | 本次规划约束 | LLM 可能漏字段 |
| 用户历史偏好 | `data/trips/*.json` + `data/user_events.jsonl` | cookie + 历史 trip / feedback | 隐式偏好 | 不能覆盖本次明确需求 |
| 地图路线 | AMap 或估算 | AMap 路线服务 | transit segment | 失败时不能画假路线 |

## 7. 产品同学应该收集什么

### 7.1 城市核心 POI 表

每个城市先收 20-40 个，不求多，求准。

| 字段 | 说明 |
|---|---|
| `city` | 城市 |
| `canonical_name` | 地标标准名 |
| `aliases` | 常见别名 |
| `poi_role` | 通常是 `city_essential` |
| `universal_level` | high / medium / low |
| `suggested_slots` | morning / afternoon / evening |
| `district` | 行政区或商圈 |
| `city_zone` | west / center / east 等 |
| `risk_tags` | queue_heavy / walk_heavy / crowded_weekend |
| `planning_tags` | landmark / photo_friendly / culture_friendly |
| `notes` | 为什么是核心点，适合什么场景 |

### 7.2 路线样本表

每个城市 10-20 条一日 / 半日高质量样本。

| 字段 | 说明 |
|---|---|
| `city` | 城市 |
| `scenario` | 情侣 / 家庭 / 银发 / 朋友 / 独行 |
| `time_window` | 半日 / 一日 / 夜间 |
| `stop_count` | 停靠点数量 |
| `stops` | 按顺序列出 |
| `main_district` | 主区域 |
| `cross_zone_reason` | 如果跨区，为什么合理 |
| `meal_strategy` | 午饭/晚饭怎么安排 |
| `bad_pattern` | 哪种排法明显不舒服 |

### 7.3 UGC 语义样本表

不是收长文案，而是收“可转成标签”的证据。

| 字段 | 说明 |
|---|---|
| `poi_name` | POI 名称 |
| `ugc_excerpt` | 1-3 条短评论 |
| `positive_tags` | 可确认 planning_tags |
| `risk_tags` | 可确认 risk_tags |
| `confidence` | 0-1 |
| `human_note` | 人工判断理由 |

## 8. 数据清洗 Agent 工作要求

### 8.1 每次清洗必须产出

```text
data/poi_agent_label_tasks.jsonl
data/poi_agent_label_batches/*.jsonl
data/poi_agent_labels.json
data/poi_agent_label_summary.json
data/poi_enriched_labels.json
data/user_profiles/*.json
data/user_profile_summary.json
```

如果某个输入不存在，要在 summary 中说明，不要静默假装已有数据。

### 8.2 每次清洗必须检查

```bash
PYTHONPATH=. python3 scripts/build_poi_agent_label_tasks.py
PYTHONPATH=. python3 scripts/validate_poi_agent_labels.py --labels data/poi_agent_labels.json
PYTHONPATH=. python3 scripts/clean_user_profiles.py
python3 -m py_compile scripts/build_poi_agent_label_tasks.py scripts/validate_poi_agent_labels.py scripts/clean_user_profiles.py
```

重点检查：

- `city_essential` 不能过宽。
- `meal` 应覆盖大部分餐饮 POI。
- `city_zone=unknown` 不应大面积出现。
- `queue_heavy` / `walk_heavy` 不应因为一个弱证据覆盖过多 POI。
- 用户 profile 中本次意图、历史偏好、反馈信号不能混成一个字段。
- 用户 profile 中的历史偏好只能作为默认倾向。

### 8.3 不允许做的事

- 不允许让 LLM 在线读取全量 UGC 再规划。
- 不允许把餐厅、KTV、酒店误标成城市地标。
- 不允许为了标签丰富而给所有 POI 打满 `photo_friendly` / `culture_friendly`。
- 不允许把历史偏好写死到 Planner prompt，必须保留“本次输入优先”。
- 不允许编造不存在的 openshopid、POI、用户行为或真实数据源。

## 9. 下一步编码顺序

推荐严格按下面顺序：

```text
1. 生成 data/poi_agent_label_tasks.jsonl 和分批任务
2. 让低级 Agent 完成 data/poi_agent_labels.json
3. 校验并稳定 data/poi_agent_label_summary.json
4. 补人工核心 POI：尤其西安真正地标
5. 合并生成 data/poi_enriched_labels.json
6. 稳定 data/user_profiles/*.json
7. 再让 Planner 读取 enriched labels 和 user profile summary
```
