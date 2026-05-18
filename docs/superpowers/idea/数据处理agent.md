# 数据处理 Agent 任务说明

> 目标：让低级 Agent 完成 POI 第一阶段标注，并用脚本做任务分发、格式校验和质量统计。  
> 当前任务生成脚本：`scripts/build_poi_agent_label_tasks.py`  
> 当前标签校验脚本：`scripts/validate_poi_agent_labels.py`  
> 当前城市：深圳、上海、西安  
> 当前原始数据：`data/mock_dianping/{深圳,上海,西安}.json`

## -1. 先分清最终数据和中间产物

最终给 mtagent 后续规划链路用的数据只有：

```text
data/poi_enriched_labels.json
data/user_profiles/{cookie_key}.json
```

其他文件都只是原料、任务或校验产物：

- `data/mock_dianping/*.json`：mock POI 原料。
- `data/real_sources/*.jsonl`：高德 / 小红书真实来源证据层，不是 Planner 最终输入。
- `data/poi_agent_label_tasks.jsonl` 和 `data/poi_agent_label_batches/*.jsonl`：给低级 Agent 的标注任务。
- `data/poi_agent_labels.json`：低级 Agent 回填结果。
- `data/poi_agent_label_summary.json`：校验统计。

判断一个 POI 数据文件能不能直接给 mtagent 用，只看它是否已经合并成 `poi_enriched_labels` 同构结构。`amap_poi_*.jsonl`、`merged_real_poi_candidates.jsonl` 都不能直接替代 `data/poi_enriched_labels.json`。

## 0. 当前唯一主线

现在不要继续扩 Planner、地图、SSE 或 Adjuster。数据处理 Agent 的主线只做六件事：

```text
1. 规范 POI 数据是什么样。
2. 规范用户数据是什么样。
3. 做好 POI 低级 Agent 标注流程。
4. 做好用户数据清洗脚本。
5. 写清数据来源从哪里收集。
6. 写清每类数据要收集什么字段。
```

统一规范见：

```text
docs/superpowers/specs/2026-05-12-mtagent-data-foundation-spec.md
```

本文件是给数据清洗 Agent 的执行指南。任何脚本或标签改动，都要能回到上面这份 spec 里解释清楚。

## 1. 总原则

POI / UGC 数据处理不要放在线上规划链路里实时做。

当前原则：

```text
低级 Agent 负责判断标签。
脚本只负责生成任务、校验格式、统计质量。
```

推荐流程：

```text
离线数据处理：
  原始 POI + UGC
  -> 生成低级 Agent 标注任务
  -> 低级 Agent 按 schema 标注
  -> 校验 agent 标注结果
  -> 人工核心点校正
  -> 生成结构化标签文件

在线路线规划：
  只读取结构化标签
  -> 快速筛选 / 评分 / 组合路线
  -> LLM 负责解释和局部语义取舍
```

原因：

- 10 秒内生成路线，不能在线总结大量 UGC。
- 离线标签可复现、可调试、可人工抽查；Agent 负责语义判断，脚本负责防止格式漂移。
- 规划质量主要取决于结构化标签，而不是每次让 LLM 重新猜。

## 2. 当前脚本产物

运行：

```bash
PYTHONPATH=. python3 scripts/build_poi_agent_label_tasks.py
PYTHONPATH=. python3 scripts/validate_poi_agent_labels.py --labels data/poi_agent_labels.json
PYTHONPATH=. python3 scripts/clean_user_profiles.py
```

会生成：

```text
data/poi_agent_label_tasks.jsonl
  给低级 Agent 标注 POI 的全量任务。

data/poi_agent_label_batches/*.jsonl
  按城市和批次切好的任务，方便多个低级 Agent 分工。

data/poi_agent_labels.json
  低级 Agent 回填的第一阶段结构化标签。

data/poi_agent_label_summary.json
  Agent 标注结果的校验和分布统计。

data/poi_enriched_labels.json
  最终给 Planner 的路线规划标签。稳定后应由 agent labels 校验/合并生成。

data/user_profiles/{cookie_key}.json
  用户历史偏好画像，后续 Profiler / Planner / Adjuster 读取。

data/user_profile_summary.json
  用户画像清洗统计，方便检查是否有历史偏好信号。
```

当前兼容性说明：

- `scripts/label_pois.py` 暂时保留为历史规则基线和对照工具，不作为新方向的唯一标注来源。
- `data/poi_labels.json` 仍是旧版兼容标签，当前部分代码还会读取。
- `data/poi_enriched_labels.json` 是后续 Planner 应读取的最终标签文件。
- 用户画像脚本只读 `data/trips/*.json` 和可选的 `data/user_events.jsonl`，不会影响 POI 标签。

## 3. 第一阶段：低级 Agent 标注

第一阶段不再让脚本直接决定标签。脚本先生成任务，低级 Agent 按统一 schema 回填标签。

### 3.1 输入字段

主要使用原始 POI 的这些字段：

```text
openshopid
name
city
address
latitude / longitude
categories
reviewTags
special
queueable
bookable
isBlackPearl
star
reviewCount
avgprice
business_hour
ugcs
```

### 3.2 输出标签

`data/poi_agent_labels.json` 中每个 POI 必须包含：

```json
{
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
  "confidence": 0.82,
  "label_notes": "真正城市地标，评论和名称都支持首次到访强相关。"
}
```

### 3.3 关键标签含义

`poi_role`：

```text
city_essential     城市必去 / 地标
persona_preferred  人群偏好点
meal               餐饮点
connector          补位连接点，例如商场、休息、轻量活动
fallback           低优先级兜底点，例如酒店类或弱相关点
```

`planning_tags`：

```text
photo_friendly
food_quality
culture_friendly
family_friendly
couple_friendly
group_friendly
business_friendly
quiet
atmosphere
good_value
transit_friendly
rain_friendly
night_friendly
rest_friendly
shopping_friendly
first_visit_friendly
landmark
```

`risk_tags`：

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

## 4. 第二阶段：AI 语义补标

第二阶段暂时降级为可选。因为第一阶段已经由低级 Agent 直接做语义标注，第二阶段只在发现标签质量不稳时启用。

输入文件：

```text
data/poi_agent_label_tasks.jsonl
```

每一行是一个 POI 标注任务，包含：

```text
POI 基础信息
allowed_values
reviewTags
special
ugc_excerpt
expected_output_fields
```

低级 Agent 需要输出第一阶段标签文件：

```text
data/poi_agent_labels.json
```

推荐格式：

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
      "poi_role": "connector",
      "universal_level": "medium",
      "must_consider": false,
      "manual_priority": 55,
      "planning_tags": ["photo_friendly", "night_friendly"],
      "risk_tags": ["queue_heavy"],
      "district": "南山区",
      "city_zone": "west",
      "neighbor_zones": ["center", "north"],
      "suggested_slots": ["evening"],
      "min_stay_minutes": 60,
      "max_stay_minutes": 120,
      "confidence": 0.82,
      "label_notes": "UGC 多次提到夜景和拍照，适合作为夜间补位点。"
    }
  }
}
```

生成 `data/poi_agent_labels.json` 后，运行：

```bash
PYTHONPATH=. python3 scripts/validate_poi_agent_labels.py --labels data/poi_agent_labels.json
```

校验通过后，再进入人工校正或最终合并。脚本不替 Agent 改标签。

## 5. 低级 Agent 标注规则

低级 Agent 标注时必须保守。

必须遵守：

- 不要创造新的 `openshopid`。
- 不要创造不存在的 POI。
- 不要把“某地标附近的店”标成 `city_essential`。
- `city_essential` 只给真正地标、首次到访强相关 POI。
- 如果只是餐厅、咖啡、商场、书店，应优先标成 `meal` 或 `connector`。
- `queue_heavy` 只给明确排队 / 等位风险，不要把“上菜慢”误判成排队。
- `walk_heavy` 只给明显范围大、步行多、游览强度高的点。
- `confidence < 0.6` 可以输出，但 `label_notes` 必须说明不确定原因。

建议低级 Agent 重点判断：

```text
photo_friendly
night_friendly
rain_friendly
rest_friendly
walk_heavy
queue_heavy
family_friendly
senior_friendly
solo_friendly
poi_role 是否被规则误判
suggested_slots 是否更合理
```

## 6. 第三阶段：人工抽查入口

第三阶段由人来做核心 POI 抽查。

人工修正文件：

```text
data/poi_manual_labels.json
```

格式和 Agent 标签类似，但只写需要覆盖的字段：

```json
{
  "深圳": {
    "openshopid_xxx": {
      "poi_role": "city_essential",
      "universal_level": "high",
      "must_consider": true,
      "manual_priority": 100,
      "planning_tags": ["landmark", "photo_friendly"],
      "risk_tags": ["walk_heavy"],
      "risk_tags_remove": ["queue_heavy"],
      "suggested_slots": ["afternoon", "evening"],
      "label_notes": "人工确认：深圳首次到访高优先级地标。"
    }
  }
}
```

脚本合并优先级：

```text
Agent 标注 < 人工修正
```

## 7. 检查标准

每次生成任务、回填 Agent 标签或人工修正后，运行：

```bash
PYTHONPATH=. python3 scripts/build_poi_agent_label_tasks.py
PYTHONPATH=. python3 scripts/validate_poi_agent_labels.py --labels data/poi_agent_labels.json
PYTHONPATH=. python3 scripts/clean_user_profiles.py
```

然后检查：

```bash
jq '.cities[\"深圳\"].poi_roles' data/poi_agent_label_summary.json
jq '.cities[\"上海\"].poi_roles' data/poi_agent_label_summary.json
jq '.cities[\"西安\"].poi_roles' data/poi_agent_label_summary.json
jq '.profile_count' data/user_profile_summary.json
```

重点看：

- `city_essential` 不能过多。
- `meal` 应该大致覆盖餐饮 POI。
- `connector` 不能完全缺失。
- `queue_heavy` 不能覆盖绝大多数 POI。
- `city_zone=unknown` 如果过多，说明 district 规则还要补。
- 用户 profile 不能把本次意图、历史偏好、反馈信号混成一个字段。
- 历史偏好只能做默认倾向，不能覆盖用户本次明确输入。

当前已知情况：

- `独行` 覆盖率偏低，因为 mock 数据里独行语义较少。
- 西安 `city_essential` 偏少，需要人工补核心点。
- 上海 / 深圳有部分商圈衍生 POI，需要人工抽查 top POI。

## 8. 交付物

数据处理 Agent 第一阶段交付：

```text
已生成 data/poi_agent_label_tasks.jsonl
已生成 data/poi_agent_label_batches/*.jsonl
已由低级 Agent 完成 data/poi_agent_labels.json
已通过 scripts/validate_poi_agent_labels.py 校验
已生成 data/poi_agent_label_summary.json
已生成 data/user_profiles/{cookie_key}.json
已生成 data/user_profile_summary.json
```

数据处理 Agent 第二阶段交付：

```text
人工校正 data/poi_manual_labels.json
合并生成 data/poi_enriched_labels.json
说明低级 Agent 标注样本数量、主要修正点、风险点
```

## 9. 数据来源与采集清单

第一阶段数据来源不要发散：

```text
POI 基础数据：
  当前来自 data/mock_dianping/*.json。
  后续来自大众点评开放平台 POI 搜索 / POI 详情接口。

UGC 智慧：
  当前来自 mock POI 的 reviewTags 和 ugcs。
  后续来自点评 reviewTags、精选评论、设施字段和排队/预订能力。

人工校正：
  后续维护 data/poi_manual_labels.json。
  只修核心地标、明显误标、城市区域和高价值 POI。

用户数据：
  当前来自 data/trips/*.json。
  后续来自 cookie_key、用户输入、Profiler intent、Adjuster feedback、trip completion。

路线样本：
  产品同学人工整理 20-30 条一日/半日路线样本。
  用来指导 day_template、区域连续性和路线节奏，不直接塞进 Planner。
```

必须采集的 POI 字段：

```text
openshopid
name
city
address
district
latitude
longitude
categories
star
reviewCount
avgprice
business_hour
reviewTags
ugcs
special
queueable
bookable
isBlackPearl
dishs
```

必须采集的用户字段：

```text
cookie_key
free_text
ParsedIntent(city/days/traveler_type/budget_level/pace/preferences/must_visit/avoid/modifiers)
Feedback(action/target_day/target_stop_idx/reason/rejected_pois/been_there_pois)
trip_id
created_at
updated_at
```

## 10. 数据清洗 Agent 禁区

不要做这些事：

- 不要把完整 UGC 长文本直接交给线上 Planner。
- 不要把“地标附近的店”标成 `city_essential`。
- 不要让 `city_essential` 变成“所有热门店”的别名。
- 不要让 `photo_friendly`、`culture_friendly`、`food_quality` 无差别覆盖全量 POI。
- 不要在用户 profile 里编造用户没表达过的偏好。
- 不要让历史偏好覆盖本次明确需求。
- 不要在数据清洗阶段改 Planner 逻辑；清洗只产出稳定结构化数据。
