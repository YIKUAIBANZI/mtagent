# mtagent 参考项目调研与代码助手交接报告

> 日期：2026-05-12  
> 状态：产品 / 架构 / 后续实现交接稿  
> 目标读者：后续协作的代码助手、产品同学、项目组成员  
> 参考项目：[TREK](https://github.com/mauriceboe/TREK/tree/main)、[Funizy](https://funizy.com/)、[Funizy Blog](https://funizy.com/blog)

## 1. 结论先行

mtagent 不应该只做“AI 生成一份旅行清单”，而应该做成一个可保存、可修改、可解释的本地路线规划产品。

从 TREK 可以学习：

- 把一次旅行当成一个长期可编辑的 `Trip workspace`，而不是一次性文本结果。
- 地图不只是展示页，而应该是计划编辑器的一部分。
- 路线、日期、地点、顺序、时间都应该结构化保存，方便后续调整。
- AI 能力应该通过结构化工具操作行程，而不是每次重写整份计划。

从 Funizy 可以学习：

- 入口要轻，用户可以直接问“现在去哪”“今天怎么安排”。
- 个性化不只是人群标签，而是把用户兴趣、日期、现场状态和城市节奏一起考虑。
- 一日计划要关注可走性、安全感、区域聚合和实时活动，而不是只堆景点。

mtagent 当前最值得做的方向：

```text
P0: POI 三层候选池：城市必去 / 人群偏好 / 补位连接点
P1: 区域连续性：按 district / zone 控制跨区跳跃和回头路
P2: 地图可信渲染：不要画假的两点直线，不要重复画路线
P3: 用户调整闭环：replace_stop / redo_day
P4: 持久化任务：SSE 只是展示通道，生成任务必须后台继续跑
P5: 对外呈现：路线可解释、可恢复、可编辑
```

## 2. 当前问题定义

目前需要解决的不是单个算法问题，而是一组产品可信度问题：

- LLM 选 POI 容易变成“看起来合理”，但实际漏掉城市地标。
- 按 persona 硬筛会误伤故宫、长城、天安门这类所有人都该考虑的点。
- 大城市路线可能跨区太多，例如深圳宝安、南山、福田来回跳。
- 地图路线有重复绘制、两点直线 fallback，用户会误以为是真实路线。
- 用户不满意某个景点或某一天时，系统缺少局部修改能力。
- SSE 断开后任务可能丢失，用户关闭浏览器会失去生成结果。
- 历史聊天和历史行程没有沉淀，无法支持“接着上次继续”。

核心产品判断：

> 城市必去点是骨架，persona 点是性格，补位点是胶水，区域连续性是舒适度，持久化任务是可靠性。

## 3. TREK 可学习点

TREK 的公开 README 把它定位为一个 self-hosted travel planner，重点能力包括拖拽式日程、交互地图、地点搜索、路线优化、天气、预算、打包清单、文件附件、PDF 导出、多人实时协作、PWA 离线等。对 mtagent 最有价值的不是这些功能全部照搬，而是它的产品组织方式。

### 3.1 Trip 是一个工作台，不是一次回答

TREK 把旅行计划拆成：

- trip
- day
- place
- assignment
- notes
- route
- member / collaboration

这说明旅行规划产品的核心对象应该是可持续编辑的数据结构。

mtagent 对应落地：

```text
TripJob
  trip_id
  conversation_id
  status
  user_input
  parsed_intent
  candidate_pools
  draft_route
  final_route
  events
  created_at
  updated_at
```

```text
DayPlan
  day_index
  title
  main_zone
  stops[]
  transit_segments[]
  warnings[]
```

```text
Stop
  poi_id
  poi_role
  time_slot
  reason
  source
```

### 3.2 地图应该能参与编辑

TREK 的地图能力包含地点 pin、分类筛选、路线可视化、排序和导出。mtagent 当前更像“AI 生成后地图展示”，后续应该逐步变成“地图上也能理解和调整计划”。

建议 mtagent 第一阶段只做这些：

- 按天切换地图 pin。
- 按类型筛选：景点 / 餐饮 / 休息 / 夜景。
- 点击 POI 能触发替换。
- 路线 segment 有明确状态：`real_route` / `estimated` / `unavailable`。
- 如果没有真实路线点，不画假直线。

暂时不要做：

- 多人协作。
- 文件附件。
- 预算、打包清单。
- 酒店和航班管理。
- PWA 离线。

这些功能对 hackathon 主线帮助不大，容易稀释重点。

### 3.3 AI 应该操作结构化工具

TREK 的 MCP 文档中列出了很多结构化工具，例如 `assign_place_to_day`、`reorder_day_assignments`、`update_assignment_time`、`move_assignment` 等。

这对 mtagent 的启发是：

- 不要让 LLM 直接重写整份行程。
- 让 LLM 或 Agent 输出结构化动作。
- 后端负责校验、应用动作、重算局部路线。

mtagent 可以先定义这几类动作：

```json
{
  "action": "replace_stop",
  "trip_id": "trip_123",
  "day_index": 2,
  "stop_id": "stop_456",
  "constraints": {
    "same_role": true,
    "nearby_only": true,
    "avoid_poi_ids": ["poi_001"]
  }
}
```

```json
{
  "action": "redo_day",
  "trip_id": "trip_123",
  "day_index": 2,
  "reason": "too_tiring",
  "constraints": {
    "keep_other_days": true,
    "reduce_walking": true
  }
}
```

## 4. Funizy 可学习点

Funizy 首页强调 “Your perfect day in any city”，入口是 “what can I do now?” 和 “create daily plan”。它的博客内容反复强调兴趣优先、实时活动、日期相关、walkable neighborhood、solo-friendly、hidden gems 等。

这对 mtagent 的价值在于：它不是只把旅行当成多日攻略，而是把“今天、现在、这个人”作为核心场景。

### 4.1 轻入口

mtagent 可以保留长行程规划，但建议增加轻入口：

```text
今天在深圳南山，下午 3 点后还可以去哪？
我现在在上海外滩附近，晚上想轻松一点。
北京两天第一次来，别太累。
```

这类需求不一定需要完整多日规划，但非常适合 hackathon 展示“现在就出发”。

第一阶段可做成同一个 Planner 的不同 mode：

```text
mode = full_trip
mode = today_plan
mode = now_nearby
```

### 4.2 个性化不是硬分类

Funizy 的表达更接近兴趣和场景，而不是简单 persona。

mtagent 不应只使用：

```text
情侣 / 亲子 / 银发 / 朋友
```

还应该提取：

```text
兴趣：文化 / 拍照 / 美食 / 购物 / 展览 / 自然 / 夜景
节奏：轻松 / 正常 / 紧凑
体力：低 / 中 / 高
日期：工作日 / 周末 / 节假日 / 特定活动日
当前位置：如果有
结束位置：如果有
```

对应到 POI 选择时：

- 城市必去点不被 persona 删掉。
- persona 只影响排序、节奏、讲解和补位。
- 兴趣标签影响候选池扩展。
- 体力和节奏影响每天 stop 数和跨区惩罚。

### 4.3 日期和事件意识

Funizy 博客强调许多旅行计划忽略具体日期和 live events。mtagent 短期不一定能接真实活动 API，但可以先做模拟版：

```text
date_context
  weekday
  weekend
  holiday_like
  weather_hint
  crowd_level_hint
  city_event_hint
```

用途：

- 周末热门景点增加排队惩罚。
- 晚上可加入夜景 / 商圈 / 演出类补位。
- 雨天提高室内 POI 权重。
- 节假日减少跨区和高强度路线。

## 5. POI 数据设计建议

当前 POI 选择应从“一堆 POI 给 LLM 选”改成“三层候选池 + 评分 + LLM 解释”。

### 5.1 三层 POI

```text
city_essential
  城市必去 / 地标 / 首次到访强相关
  不能被 persona 过滤掉

persona_preferred
  对某类人或兴趣明显更合适
  用于差异化体验

connector
  餐饮 / 咖啡 / 商场 / 休息 / 夜景
  用于把一天串顺
```

建议扩展标签：

```json
{
  "poi_id": "bj_forbidden_city",
  "poi_role": "city_essential",
  "universal_level": "high",
  "district": "东城区",
  "city_zone": "center",
  "neighbor_zones": ["west_center", "north_center"],
  "persona_labels": ["culture", "photo"],
  "pace_tags": ["walk_heavy", "queue_heavy"],
  "time_tags": ["morning", "afternoon"],
  "connector_tags": [],
  "manual_priority": 100
}
```

### 5.2 评分思路

推荐使用简单可解释的加权分，不要一开始上复杂模型。

```text
score =
  city_essential_bonus
  + must_visit_bonus
  + persona_match_score
  + interest_match_score
  + rating_score
  + district_continuity_score
  + time_slot_fit_score
  - crowd_penalty
  - walking_penalty
  - cross_zone_penalty
  - duplicate_category_penalty
```

关键规则：

- `city_essential_bonus` 只保证进入候选池，不保证每天都塞进去。
- 如果城市必去点太重，例如长城，应独立成半天或一天主锚点。
- persona 影响 `score`，不应该直接决定“能不能去”。
- filler / connector 不能抢主景点位置，只能补 meal/rest/night slot。

## 6. 区域连续性设计

大城市不能只看直线距离，也不能强制同区。应使用 district / zone / neighbor 组合。

推荐模型：

```json
{
  "district": "南山区",
  "city_zone": "west",
  "neighbor_zones": ["center"],
  "transfer_weight": 1.0
}
```

路线规则：

```text
同区：优先
邻区：允许
远区：只有 city_essential / must_visit / 强兴趣点才允许
一天跨区次数：默认 <= 1
回头路：高惩罚
稀疏区域：可以放一个高价值 anchor，然后接到邻近丰富区域
```

深圳例子：

- 深圳湾公园 -> 世界之窗 -> 福田：可以接受，因为方向连贯，跨区不多。
- 宝安 -> 福田 -> 南山 -> 宝安：应强烈惩罚，因为来回跳。

Planner 应该先确定当天 `main_zone`，再选择 anchor 和补位点。

## 7. 地图与路线可信度

当前重点不是让地图看起来丰富，而是不能误导用户。

必须避免：

- 路线搜索失败后画两点直线。
- 同一段路线被 SSE 事件和最终 trip 渲染重复绘制。
- 地图上显示路线，但后端没有对应 `transit_segments` 数据。

推荐约定：

```text
TransitSegment
  from_stop_id
  to_stop_id
  mode
  duration_minutes
  distance_meters
  polyline_points
  route_status: real_route / estimated / unavailable
  provider
  error_message
```

前端规则：

- `real_route`：画真实 polyline。
- `estimated`：可以画虚线，文案标注估算。
- `unavailable`：不画线，只显示“路线暂不可用”。
- 每个 segment 用稳定 id 去重。

## 8. 调整闭环设计

用户反馈分两层。

### 8.1 替换一个景点

入口：

```text
用户不喜欢某个 POI
用户去过这个 POI
用户觉得这个 POI 不适合
```

行为：

- 保持同一天。
- 保持同一时间槽。
- 保持同一 POI role 或兼容 role。
- 优先同区或邻区。
- 避免用户 dislike / been_there 的 POI。
- 只重算相邻两段 transit。

### 8.2 重排某一天

入口：

```text
这一天太累
这一天不感兴趣
这一天跨区太多
这一天想换成亲子 / 拍照 / 美食主题
```

行为：

- 只改指定 day。
- 其他 day 保持稳定。
- 继承 trip intent。
- 加入新的 feedback constraints。
- 重新生成当天 candidate pool 和 transit。

后端应该由 `Adjuster` 负责，不建议塞回 `Planner` 主流程。

## 9. SSE、后台任务与历史记录

关键原则：

> SSE 是展示通道，不是任务本身。

正确流程：

```text
POST /api/trips
  创建 TripJob
  返回 trip_id
  后台继续生成

GET /api/trips/{trip_id}
  查询当前状态和已有结果

GET /api/trips/{trip_id}/events
  返回已持久化事件

GET /api/trips/{trip_id}/stream
  订阅后续事件

GET /api/conversations
  历史对话列表

GET /api/conversations/{conversation_id}
  恢复消息、摘要、关联 trip
```

hackathon 阶段可以先用文件存储：

```text
data/conversations/{conversation_id}.json
data/trips/{trip_id}.json
data/trip_events/{trip_id}.jsonl
```

以后再迁 SQLite / Postgres。

事件建议：

```json
{
  "event_id": 12,
  "trip_id": "trip_123",
  "type": "planner.day_done",
  "payload": {},
  "created_at": "2026-05-12T12:00:00+08:00"
}
```

恢复逻辑：

- 用户重新打开历史 trip。
- 先拉 `/events` 重放已经发生的事件。
- 如果 job 还在 running，再接 `/stream`。
- 如果 completed，直接展示 final_route。

## 10. Agent 编排建议

不要为了“多 agent”而拆太碎。第一阶段建议保持 5 个职责：

```text
Profiler
  解析用户输入：城市、天数、出发时间、persona、兴趣、节奏、预算、must_visit、avoid。

Planner
  建候选池：city_essential / persona_preferred / connector。
  做区域连续性规划。
  产出 DayPlan、Stop、TransitSegment。

Critic
  检查路线质量：重复 POI、跨区过多、回头路、时间不合理、过度疲劳、营业时间冲突。
  输出结构化 warning 或 patch suggestion。

Adjuster
  处理 replace_stop / redo_day。
  应用用户反馈。
  只改局部，不重写整个 trip。

Labeler / Research Pipeline
  离线生成和维护 POI 标签。
  把产品同学调研转成模板、规则和 manual labels。
```

LLM 最适合做：

- 意图理解。
- 候选点之间的解释和取舍。
- 用户反馈的语义归因。
- 最终文案。

LLM 不适合直接负责：

- 从全量 POI 中盲选。
- 路线几何正确性。
- 跨区成本计算。
- SSE / job 状态管理。

## 11. 建议给代码助手的第一阶段任务

第一阶段不要同时做所有事，推荐按这个顺序落地。

### Task 1: POI role 数据结构

目标：

- 给 POI 增加 `poi_role`、`universal_level`、`district`、`city_zone` 等扩展字段。
- 增加每个城市的 `city_essential` 手工清单。
- 修改 persona filtering，保证 city essentials 不会被过滤掉。

涉及文件可能包括：

- `scripts/label_pois.py`
- `dianping/client.py`
- `dianping/schemas.py`
- `agents/tools.py`
- `agents/planner.py`
- `data/poi_labels.json`

验收：

- 北京 / 上海 / 西安 / 深圳的核心地标不会因为 persona 被剔除。
- persona 仍然会影响排序和补位选择。

### Task 2: district / zone 连续性评分

目标：

- 为 POI 增加 district / zone。
- Planner 每天选择一个 `main_zone`。
- 跨远区增加惩罚，但允许 city essential / must_visit。

验收：

- 深圳路线不会出现宝安、福田、南山反复横跳。
- 深圳湾公园 -> 世界之窗 -> 福田这类邻接流动仍可出现。

### Task 3: 地图路线渲染修复

目标：

- 移除“路线失败后画实线直连”的误导行为。
- 每段路线有唯一 segment id，避免重复绘制。
- 前端按 `route_status` 决定真实线、虚线或不画线。

涉及文件可能包括：

- `web/plan_stack.html`
- `web/map.html`
- `api/routes.py`
- `dianping/schemas.py`

验收：

- 路线失败时不出现假直线。
- 同一天路线不会重复叠线。
- 用户能看到路线不可用或估算状态。

### Task 4: Adjuster 局部修改

目标：

- 实现 `replace_stop`。
- 实现 `redo_day`。
- 保存用户 dislike / been_there。
- 局部重算 transit。

涉及文件可能包括：

- `agents/adjuster.py`
- `api/routes.py`
- `dianping/schemas.py`

验收：

- 替换一个 POI 不影响其他天。
- 重排一天不影响其他天。
- 被 dislike 的 POI 不再被推荐回来。

### Task 5: TripJob + SSE 持久化

目标：

- 将当前 `/api/plan/stream` 从“连接即任务”改造成“订阅任务事件”。
- 新增 trip job 文件存储。
- 支持浏览器关闭后恢复。

涉及文件可能包括：

- `api/routes.py`
- 新增 `api/storage.py` 或 `agents/job_store.py`
- `web/plan_stack.html`

验收：

- 关闭浏览器后任务仍可完成。
- 重新打开历史 trip 能看到结果。
- 已发生事件可以重放。

## 12. 不建议第一阶段做的事

不要照搬 TREK 的完整旅行管理系统：

- 不做预算。
- 不做打包清单。
- 不做文件附件。
- 不做多人实时协作。
- 不做复杂权限系统。
- 不做酒店、航班、票据管理。

不要把 Funizy 的内容营销形态照搬过来：

- 不需要大量博客。
- 不需要一开始做付费 token。
- 不需要为了个性化写很多营销文案。

mtagent 的 hackathon 优势应该集中在：

- 本地 POI 数据模拟完整。
- AI 能理解用户。
- 路线规划有结构、有地图、有可调整闭环。
- 结果能保存和恢复。

## 13. 最小可验证 Demo 流程

推荐演示流程：

```text
1. 用户输入：
   “第一次来深圳，两天，情侣，想拍照和吃饭，不想太累。”

2. Profiler 输出：
   city=深圳, days=2, persona=couple, interests=[photo, food], pace=relaxed

3. Planner 生成：
   Day 1: 南山主区域，城市必去 + 拍照 + 晚餐
   Day 2: 福田/罗湖或相邻区域，减少跨区

4. 地图展示：
   按天显示 POI 和真实路线；失败路线不画假直线。

5. 用户反馈：
   “我不想去世界之窗，换一个。”

6. Adjuster：
   只替换该 POI，保留当天结构，重算邻接路线。

7. 用户关闭浏览器再打开：
   历史 trip 能恢复，SSE events 可重放。
```

## 14. 风险点

- POI 标签如果只靠规则生成，会有错标，需要手工 top POI 修正。
- district / zone 如果只靠文本字段，可能不够准；但 hackathon 阶段可以先够用。
- 路线 polyline 依赖地图服务，失败时必须有降级展示。
- Adjuster 如果没有保存 candidate pool，会退化成全量重排。
- SSE 持久化如果一次做太复杂，会拖慢主线；第一阶段用 JSON / JSONL 即可。

## 15. 最终建议

给代码助手的核心指令：

> 请优先把 mtagent 从“一次性 AI 文本规划”升级成“结构化、可保存、可局部调整的路线计划”。不要照搬 TREK 的大而全功能，也不要只学 Funizy 的轻入口。第一阶段重点做 POI 三层候选池、区域连续性、地图可信渲染、Adjuster 局部修改、TripJob 持久化。

