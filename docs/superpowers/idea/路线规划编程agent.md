# 路线规划编程 Agent 说明

> 目标：让后续代码 Agent 理解当前数据结构，并据此设计更稳定的路线推荐 / 规划 Prompt。  
> 核心原则：LLM 不直接从全量 POI 里瞎选，Planner 先做结构化候选池和评分，LLM 只在小候选集里解释、取舍和组织输出。

## 1. 当前数据是什么样

### 1.1 原始 mock POI

原始数据在：

```text
data/mock_dianping/深圳.json
data/mock_dianping/上海.json
data/mock_dianping/西安.json
```

每个城市 800 条 POI，总计 2400 条。

常用字段：

```text
openshopid        POI 唯一 id
name              名称
city              城市
address           地址
latitude          纬度
longitude         经度
categories        类目，例如 美食 / 休闲娱乐 / 购物 / 酒店 / 亲子 / 丽人
reviewTags        点评标签及命中数
special           特殊设施，例如 无障碍 / 提供婴儿椅 / 可包间
queueable         是否支持排队能力
bookable          是否支持预订
isBlackPearl      是否黑珍珠
star              星级
reviewCount       评论数
avgprice          人均价格
business_hour     营业时间
ugcs              用户评论片段
```

### 1.2 旧标签

旧标签在：

```text
data/poi_labels.json
```

用途：

- 当前 `DianpingClient` 会读取它。
- 只注入到 `POI.persona_labels`。
- 现有 `agents/tools.py::route_by_persona()` 依赖它。

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

### 1.3 新 enriched 标签

新标签在：

```text
data/poi_enriched_labels.json
```

这是后续路线规划 Agent 应该优先接入的数据。

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
      },
      "poi_role": "city_essential",
      "universal_level": "high",
      "must_consider": true,
      "manual_priority": 95,
      "planning_tags": ["photo_friendly", "transit_friendly"],
      "risk_tags": ["queue_heavy", "walk_heavy"],
      "district": "南山区",
      "city_zone": "west",
      "neighbor_zones": ["center", "north"],
      "suggested_slots": ["morning", "afternoon"],
      "min_stay_minutes": 90,
      "max_stay_minutes": 180,
      "label_sources": ["rules:v1"]
    }
  }
}
```

## 2. Planner 应该怎样使用数据

不要再做：

```text
全量搜索 POI
-> 直接交给 LLM 选点
-> LLM 输出路线
```

推荐流程：

```text
用户输入
-> Profiler 解析 ParsedIntent
-> 合并历史 UserPreferenceProfile
-> 读取 enriched labels
-> 构建三层候选池
-> 规则评分和路线组合
-> LLM 在候选集内做解释和轻量取舍
-> Critic 校验路线
```

三层候选池：

```text
city_essential:
  城市必去点，不被 persona 过滤掉。

persona_preferred:
  人群 / 兴趣偏好点，用于差异化。

connector:
  餐饮、休息、商场、夜景、下午茶，用于把路线串顺。
```

实际标签中餐饮单独是：

```text
poi_role = meal
```

Planner 可以把 `meal` 当作 connector 的强类型。

## 3. 推荐评分模型

先用简单可解释的加权分，不要上复杂模型。

```text
score =
  city_essential_bonus
  + manual_priority
  + must_visit_bonus
  + traveler_type_match
  + interest_match
  + planning_tag_match
  + rating_score
  + district_continuity_score
  + slot_fit_score
  - queue_penalty
  - walk_penalty
  - cross_zone_penalty
  - budget_penalty
  - duplicate_role_penalty
```

关键规则：

- `city_essential` 只保证进候选池，不等于必须塞进每条路线。
- `meal` 必须服务饭点，不要抢景点位置。
- `connector` 用于减少断裂感，不要让路线变成商场堆叠。
- `risk_tags` 不一定剔除 POI，更多是根据用户约束加惩罚。

## 4. Prompt 设计原则

LLM 输入里不要放全量 POI。

应该只放：

```text
ParsedIntent
UserPreferenceProfile 摘要
候选池 top N
已计算的路线约束
当前 day_template
需要输出的 JSON schema
```

LLM 必须遵守：

- 只能使用候选池里的 POI。
- 必须保留 `openshopid`。
- 不得编造 POI、地址、评分、路线时间。
- 不得把 `route_status=unavailable` 当作真实路线。
- 必须说明关键取舍，例如“少排队”和“吃得好”冲突时怎么选。
- 输出必须是结构化 JSON，文案解释作为字段，不要散文式自由输出。

## 5. 推荐 Planner Prompt

### 5.1 System Prompt

```text
你是一个本地即时路线规划 Agent。

你的任务不是写旅游攻略，而是在给定候选 POI、用户意图、历史偏好和路线约束的前提下，生成可执行的一日/半日路线。

你必须遵守：
1. 只能使用候选池中的 POI，不能编造 POI。
2. 必须保留每个 POI 的 openshopid。
3. city_essential 是城市骨架，不能因为 persona 直接忽略，但可以因为时间不足或路线不顺而不放入最终路线，并说明原因。
4. meal / connector 是补位点，用于安排饭点、休息和夜间收尾，不能喧宾夺主。
5. 优先保证区域连续性，避免同一天频繁跨区和回头路。
6. 用户本次明确要求优先于历史偏好。
7. 如果少排队、吃得好、少走路之间冲突，必须写出取舍理由。
8. 输出必须是 JSON，不输出 Markdown。
```

### 5.2 User Prompt Template

```text
用户意图：
{parsed_intent_json}

历史偏好：
{user_preference_profile_json}

路线模板：
{day_template_json}

路线硬约束：
{route_constraints_json}

候选池：
{
  "city_essential": [...],
  "persona_preferred": [...],
  "meal": [...],
  "connector": [...]
}

每个 POI 字段说明：
- openshopid: 唯一 id，必须原样输出
- name: 名称
- poi_role: POI 在路线中的角色
- district/city_zone/neighbor_zones: 区域连续性
- planning_tags: 正向体验标签
- risk_tags: 风险标签
- suggested_slots: 适合时间段
- min_stay_minutes/max_stay_minutes: 建议停留时间
- score: 规则侧预评分

请生成 3 个方案：
1. main: 综合最优
2. low_queue: 少排队/轻松版
3. interest_first: 兴趣优先版

输出 JSON schema：
{
  "plans": [
    {
      "variant": "main | low_queue | interest_first",
      "title": "string",
      "tradeoff": "string",
      "main_zone": "string",
      "stops": [
        {
          "openshopid": "string",
          "name": "string",
          "poi_role": "string",
          "slot": "morning | lunch | afternoon | afternoon_tea | dinner | evening",
          "stay_minutes": 90,
          "reason": "string",
          "risks": ["string"]
        }
      ],
      "why_this_route": "string",
      "warnings": ["string"]
    }
  ]
}
```

## 6. 候选池输入建议

每次给 LLM 的候选池不要太大：

```text
city_essential: 6-10 个
persona_preferred: 10-16 个
meal: 8-12 个
connector: 8-12 个
```

如果候选池太大，LLM 会开始“看心情选点”；如果太小，路线会僵。

推荐每个候选 POI 传这些字段：

```json
{
  "openshopid": "xxx",
  "name": "深圳湾公园",
  "categories": ["休闲娱乐"],
  "star": 4.5,
  "reviewCount": 2333,
  "avgprice": 0,
  "poi_role": "city_essential",
  "district": "南山区",
  "city_zone": "west",
  "neighbor_zones": ["center", "north"],
  "planning_tags": ["photo_friendly", "landmark"],
  "risk_tags": ["walk_heavy", "crowded_weekend"],
  "suggested_slots": ["afternoon", "evening"],
  "min_stay_minutes": 90,
  "max_stay_minutes": 180,
  "score": 92
}
```

不要把完整 UGC 长文本放进 Planner Prompt。UGC 应该已经被压缩成 `planning_tags / risk_tags / ai_notes`。

## 7. 多方案输出策略

推荐固定三种：

```text
main:
  综合最优，平衡距离、兴趣、餐饮和体验。

low_queue:
  少排队 / 少走路 / 更轻松。

interest_first:
  根据用户最强兴趣偏向美食、拍照、文化、购物或夜景。
```

三种方案不能只是换标题。

差异可以来自：

- 是否保留热门 city_essential。
- 是否选择排队风险更低的餐厅。
- 是否减少跨区。
- 是否把夜景/拍照点提前或延后。
- 是否减少 stop 数。

## 8. 动态调整 Prompt

### 8.1 replace_stop

输入：

```text
当前 day_plan
目标 stop
用户反馈 reason
同区 / 邻区候选替换池
用户 rejected_pois
```

System 规则：

```text
只替换目标 stop。
不要改变其他 stops 的顺序，除非原顺序因为替换后明显不合理。
优先保持同一 slot 和相近 poi_role。
避开 rejected_pois / been_there_pois。
输出 replacement 和需要重算的 transit segment index。
```

输出：

```json
{
  "action": "replace_stop",
  "target_day": 0,
  "target_stop_idx": 2,
  "replacement": {
    "openshopid": "xxx",
    "name": "xxx",
    "reason": "更近、同样适合拍照，且排队风险更低。"
  },
  "recompute_transit_between": [[1, 2], [2, 3]],
  "user_memory_update": {
    "rejected_pois": ["old_openshopid"]
  }
}
```

### 8.2 redo_day_or_half_day

System 规则：

```text
只重排指定半天/一天。
保留其他 day。
继承原始 ParsedIntent 和历史偏好。
加入新的用户约束。
避开 rejected_pois。
输出新的 stops 和取舍说明。
```

## 9. Critic Prompt 建议

Planner 生成后，Critic 只做检查，不重新写路线。

检查项：

```text
是否 POI 重复
是否同一天跨区过多
是否出现明显回头路
是否缺饭点
是否 stop 数过多
是否 city_essential 全被无理由忽略
是否用户明确 avoid 的 POI 又出现
是否 queue_heavy 与“少排队”冲突
是否 walk_heavy 与“少走路/银发/亲子”冲突
是否路线 segment 缺失或 unavailable 被当成真实路线
```

输出 patch：

```json
{
  "issues": [
    {
      "severity": "high",
      "day_index": 0,
      "stop_idx": 2,
      "issue": "用户要求少排队，但该餐厅有 queue_heavy。",
      "suggestion_type": "replace",
      "candidate_role": "meal"
    }
  ]
}
```

## 10. 第一阶段编码建议

优先级：

```text
P0 读取 data/poi_enriched_labels.json
P1 候选池分层：city_essential / persona_preferred / meal / connector
P2 基于 ParsedIntent 进行预评分
P3 给 LLM 的 prompt 改成小候选集 + JSON schema
P4 输出 main / low_queue / interest_first 三方案
P5 Critic 检查跨区、排队、重复、饭点
P6 接 replace_stop / redo_day_or_half_day
```

不要第一阶段就做：

- 全量复杂优化算法。
- 多城市无限扩展。
- 把完整 UGC 塞进 prompt。
- 让 LLM 决定真实交通时间。
- 大规模重构现有 Agent。

## 11. 最重要的实现判断

路线规划 Agent 的效果提升，不是靠 prompt 写得更玄，而是靠：

```text
更干净的候选池
更明确的 POI role
更可解释的 scoring
更严格的 JSON 输出约束
更小的 LLM 选择空间
更强的 Critic 校验
```

一句话：

> 让代码负责稳定性，让标签负责语义，让 LLM 负责解释和有限取舍。

