# mtagent 本轮对话完整总结

> 日期：2026-05-12  
> 用途：开启新对话时的上下文交接  
> 项目：美团 2026 AI Hackathon 赛题 05「现在就出发 · AI 本地路线智能规划」  
> 工作区：`/Users/yikuaibanz1/Desktop/sth/mtagent`

## 1. 本轮对话总目标

这轮主要围绕 mtagent 的产品方向、POI 设计、用户设计、路线规划策略、数据处理 pipeline 和后续代码 Agent 交接展开。

核心共识：

> mtagent 不应该做泛泛的“AI 旅行攻略生成器”，而应该做一个面向深圳、上海、西安的一日 / 半日本地即时路线规划助手，结合点评 POI、UGC 标签、用户偏好和真实路线服务，在 10 秒内生成可直接执行的个性化路线，并支持用户动态调整。

## 2. 赛题理解

赛题强调：

- 用户需要把多个目的地串成高效路线。
- 用户有“想吃好又不想排队”“时间预算二选一”等多重决策负担。
- 现有搜索 / 推荐需要用户反复筛选、自行组合。
- 系统要结合 POI 数据、服务、UGC 智慧和用户个性偏好。
- 自动生成多维度最优路线方案。
- 支持按时空、偏好等约束动态调整。

交付目标：

- 路线生成：根据用户意图自动串联多个 POI，生成完整路线安排。
- 多条件与个性化：满足差异化条件约束，结合用户历史偏好生成差异化方案。

评委关注点：

- 完整性：流程是否完整，路线是否可执行。
- 创新性：是否有自然语言调整、反馈闭环、多方案、ReAct / Tool Use / Multi-Agent 等。
- 应用效果：代码结构、部署简便性、文档完整性、方案可行性。

赛题约束：

- 路线生成响应时间 `< 10s`。
- POI 类型至少覆盖餐饮 + 娱乐 / 文化两类。
- 路线规模支持 `>= 3` 个 POI 串联。

## 3. 已确认产品范围

### 3.1 城市范围

第一阶段只支持：

- 深圳
- 上海
- 西安

原因：

- 当前 mock 数据只覆盖这三个城市。
- 路线质量比城市数量更重要。
- 每个城市都需要区域规则、核心 POI、人工校正。

### 3.2 场景范围

第一阶段主打一日 / 半日规划。

不把多日旅行作为主线，因为赛题名称是“现在就出发”，一日 / 半日更贴“即时本地路线规划”。

### 3.3 位置策略

支持：

- 用户不输入当前位置时，系统默认城市中心 / 热门商圈 / 推荐起点。
- 用户可以手动输入当前位置，例如“我现在在深圳湾公园附近”。

第一阶段不强依赖浏览器定位权限，先支持文本输入位置。

### 3.4 多方案策略

建议输出：

```text
主方案：
  综合最优。

少排队 / 轻松版：
  降低 queue_heavy、walk_heavy 和跨区成本。

兴趣优先版：
  根据用户最强兴趣偏向美食 / 拍照 / 文化 / 购物 / 夜景。
```

三种方案不能只是换标题，要有真实取舍。

## 4. POI 设计共识

POI 不是一个扁平地点，而应该有路线角色。

### 4.1 三层 POI 候选池

第一层：城市必去 / 城市地标

```text
poi_role = city_essential
```

特点：

- 对第一次来的人高度相关。
- 不能因为 persona 被过滤掉。
- 只因为时间、距离、预约、体力等因素调整安排方式。

例子：

- 深圳：深圳湾公园、世界之窗、欢乐海岸、莲花山、华强北、东门老街。
- 上海：外滩、陆家嘴、东方明珠、豫园、南京东路、人民广场、武康路。
- 西安：钟楼、大雁塔、回民街、城墙、兵马俑等。

关键规则：

> city_essential 不等于每次都塞进路线，而是必须进入候选池，并有较高基础权重。

第二层：人群 / 兴趣偏好点

```text
poi_role = persona_preferred
```

特点：

- 对某些 persona 或兴趣明显更适合。
- 用于生成差异化。

例子：

- 情侣：拍照、氛围、夜景、精致餐厅。
- 亲子：儿童友好、室内、休息方便、动线简单。
- 银发：文化、低步行、交通方便、少排队。
- 朋友：热闹、娱乐、夜生活、多人餐饮。
- 独行：安全、好逛、轻量、咖啡 / 展览。

第三层：补位连接点

```text
poi_role = meal / connector / fallback
```

作用：

- 安排饭点。
- 补休息点。
- 减少路线断裂。
- 作为夜景 / 商圈 / 咖啡 / 商场收尾。

关键句：

> 城市必去点是骨架，persona 点是性格，补位点是胶水，区域连续性是舒适度，持久化任务是可靠性。

## 5. 用户设计共识

用户不应该只用“情侣 / 亲子 / 银发”表示。需要分四层。

### 5.1 本次意图

```text
city
time_window：半日 / 一日 / 上午 / 下午 / 晚上
start_location
end_location
must_visit
avoid
```

### 5.2 人群与兴趣

```text
traveler_type：情侣 / 家庭亲子 / 银发 / 独行 / 商务 / 朋友团
interests：拍照 / 美食 / 文化 / 购物 / 展览 / 自然 / 夜景
```

### 5.3 约束

```text
pace：佛系 / 适中 / 暴走
budget_level：性价比 / 适中 / 精致
avoid_queue：怕排队
avoid_walking：少走路
avoid_cross_district：不想跨区太多
need_meal：是否必须安排餐饮
```

### 5.4 历史偏好

用户希望开启新对话时，系统自动整理上一次历史信息，作为隐式偏好注入下一次 prompt。

推荐结构：

```json
{
  "likes": ["拍照", "轻松路线", "环境好的餐厅"],
  "dislikes": ["排队久", "跨区太多"],
  "pace": "佛系",
  "budget_level": "适中",
  "been_there_pois": ["世界之窗"],
  "rejected_pois": ["某餐厅"],
  "last_city": "深圳",
  "notes": "用户更喜欢一日内区域连贯，不喜欢太赶。"
}
```

优先级：

```text
本次明确输入 > 本次隐含约束 > 历史偏好 > 默认偏好
```

历史偏好不能覆盖用户本次新需求。

## 6. UGC / POI 数据处理共识

结论：

> 脚本保证稳定，AI 补语义，人工兜核心点。在线规划只用加工好的结构化数据。

不要每次线上规划时临时让 LLM 总结 UGC，因为：

- 慢，不利于 10 秒响应。
- 不稳定，不可复现。
- 成本高。
- 很难调试路线错是标签错还是规划错。

推荐离线 pipeline：

```text
原始 POI + UGC
-> 规则脚本生成基础标签
-> 高级 LLM / AI 离线补语义标签
-> 人工抽查核心 POI
-> 生成 poi_enriched_labels.json
-> 在线 Planner 只读取结构化标签
```

## 7. 数据处理脚本现状

### 7.1 修改过的脚本

- `scripts/label_pois.py`
- `scripts/ai_label_tasks.py`

### 7.2 当前生成物

- `data/poi_labels.json`
  - 旧版 persona 标签，现有 `DianpingClient` 仍可读取。

- `data/poi_enriched_labels.json`
  - 最终合并标签，给后续路线规划用。

- `data/poi_ai_label_tasks.jsonl`
  - AI / 语义补标任务，共 480 条。

- `data/poi_ai_labels.json`
  - AI 补标结果，约 56 KB，257 个 POI 有补标。

- `data/poi_label_summary.json`
  - 标签分布统计。

- `data/poi_label_diagnosis.md`
  - 数据 Agent 生成的诊断报告。

### 7.3 当前脚本能力

`scripts/label_pois.py` 支持：

- 规则标签生成。
- 旧版 `poi_labels.json` 兼容输出。
- enriched 标签输出。
- AI 标签合并。
- 人工标签合并。
- AI 任务生成。
- 标签分布 summary。

`scripts/ai_label_tasks.py` 支持：

- 读取 `data/poi_ai_label_tasks.jsonl`。
- 用规则式 UGC 语义启发生成 `data/poi_ai_labels.json`。
- 对 `photo_friendly`、`quiet`、`rest_friendly`、`queue_heavy` 等标签做增删。

注意：

> `scripts/ai_label_tasks.py` 当前不是严格意义的高级 LLM 调用，它是规则式语义补标脚本。后续如果要真正使用高级 LLM，应替换或新增 LLM batch 标注器。

## 8. 数据检查与修复结果

检查时发现并修复了两个关键问题。

### 8.1 AI 任务污染问题

问题：

`label_pois.py` 原来会用“已经合并 AI 标签后的 label”生成下一轮 `poi_ai_label_tasks.jsonl`。这样再跑 `scripts/ai_label_tasks.py` 会认为没有新增可修正内容，并把 `data/poi_ai_labels.json` 覆盖成空结果。

修复：

`poi_ai_label_tasks.jsonl` 现在永远基于纯规则标签 `base_label` 生成。

相关位置：

```text
scripts/label_pois.py
base_label = build_enriched_label(poi)
city_task_candidates.append((ai_task_score(poi, base_label), build_ai_task(poi, base_label)))
label = merge_override(base_label, ai_overrides, "ai:ugc")
```

### 8.2 AI 输出不稳定问题

问题：

`scripts/ai_label_tasks.py` 使用 `list(set(...))` 生成 `suggested_slots`，导致同样内容多跑几次 hash 变化。

修复：

新增固定顺序：

```text
SLOT_ORDER = ["morning", "lunch", "afternoon", "afternoon_tea", "dinner", "evening"]
ordered_slots(...)
```

现在 `data/poi_ai_labels.json` 多次运行 hash 稳定。

### 8.3 最终结构校验结果

最终校验：

```text
深圳：800 POI，89 个 AI 补标已合并
上海：800 POI，83 个 AI 补标已合并
西安：800 POI，85 个 AI 补标已合并

badRole: 0
badSlot: 0
missingFields: 0
unknownZone: 0
must_consider mismatch: 0
```

最终 `poi_role` 分布：

```text
深圳：
  city_essential: 51
  persona_preferred: 240
  meal: 394
  connector: 81
  fallback: 34

上海：
  city_essential: 18
  persona_preferred: 202
  meal: 400
  connector: 100
  fallback: 80

西安：
  city_essential: 0
  persona_preferred: 229
  meal: 400
  connector: 91
  fallback: 80
```

西安 `city_essential = 0` 的原因：

- mock 数据里大多是“钟楼日料店 / 回民街烧烤摊 / 大雁塔茶餐厅”这类衍生店。
- 没有真正的“钟楼 / 大雁塔 / 回民街”地标本体。
- 后续需要人工补充或从数据源层新增真正地标 POI。

## 9. 地图与 route_status 共识

虽然目标是使用真实路径，但真实路径服务可能失败。

因此每段路线需要状态：

```text
real_route:
  真实路径成功，可以画实线。

estimated:
  没有完整路径，但有估算时间 / 距离，可以画虚线并标注估算。

unavailable:
  路线失败，不画两点直线，只提示路线暂不可用。
```

关键原则：

> 地图不能用两点直线伪装真实路线。

当前已知风险：

- 前端可能在 AMap 路线失败时画直线。
- 同一段路线可能被 SSE 事件和最终 trip 渲染重复绘制。

建议：

- 后端持久化 `transit_segments`。
- 前端按 segment id 去重。
- 只有 `route_status = real_route` 才画真实实线。
- `estimated` 用虚线。
- `unavailable` 不画线。

## 10. 区域连续性共识

大城市不能绝对同区，也不能随意跨区。

推荐规则：

```text
同区：优先
邻区：允许
远区：只有 city_essential / must_visit / 强兴趣点才允许
一天跨区次数：默认 <= 1
回头路：高惩罚
稀疏区域：允许先去一个高价值 anchor，再接到邻近丰富区域
```

深圳例子：

```text
深圳湾公园 -> 世界之窗 -> 福田
可以接受，因为方向相对连贯。

宝安 -> 福田 -> 南山 -> 宝安
应强烈惩罚，因为来回跳。
```

## 11. 用户动态调整共识

支持两种调整。

### 11.1 替换一个点

用户场景：

```text
我不喜欢这个景点。
我去过这里了。
这个地方太远。
这个餐厅排队太久。
```

系统行为：

- 保持同一天 / 同一半天。
- 保持同一时间槽。
- 优先同区或邻区。
- 尽量保持同类角色。
- 避开用户明确不喜欢 / 去过的 POI。
- 只重算相邻路线段。

### 11.2 重排半天 / 一天

用户场景：

```text
这半天太累了。
今天都不太喜欢。
我想改成美食为主。
我想少走路。
```

系统行为：

- 只重排指定时间段。
- 其他部分保持稳定。
- 继承用户本次意图和历史偏好。
- 加入新的约束。
- 重新跑候选池和路线评分。

## 12. SSE、后台任务与聊天历史

关键原则：

> SSE 是展示通道，不是任务本身。

推荐模型：

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

Hackathon 阶段可以先用文件存储：

```text
data/conversations/{conversation_id}.json
data/trips/{trip_id}.json
data/trip_events/{trip_id}.jsonl
```

这能支持：

- 浏览器关闭后任务继续跑。
- 用户回到历史 trip。
- 重放已发生 SSE event。
- 新对话自动参考上次偏好摘要。

## 13. Agent 编排共识

不要为了多 Agent 而拆太碎。

推荐职责：

```text
Profiler
  解析用户输入，产出结构化 intent。

CandidateBuilder
  根据城市、时间、位置、偏好构建三层 POI 候选池。

Scorer / Planner
  对 POI 打分，组合路线，处理时间和区域连续性。

Critic
  检查重复、跨区过多、排队风险、营业时间、路线不可用。

Adjuster
  处理换一个点、重排半天/一天。

MemorySummarizer
  把历史对话沉淀成用户偏好摘要。

Labeler / Data Processing Agent
  离线生成和维护 POI 标签。
```

LLM 最适合：

- 意图理解。
- 候选点之间的解释和取舍。
- 用户反馈语义归因。
- 最终文案。

LLM 不适合直接负责：

- 从全量 POI 中盲选。
- 路线几何正确性。
- 跨区成本计算。
- SSE / job 状态管理。

## 14. 参考项目调研结论

### 14.1 TREK

参考项目：

- `https://github.com/mauriceboe/TREK/tree/main`

可学习：

- 把 trip 当成长期可编辑 workspace，而不是一次性回答。
- 地图是计划编辑器的一部分。
- 行程、日期、地点、顺序、时间都结构化保存。
- AI 应该通过结构化工具操作 trip。

不建议第一阶段照搬：

- 多人协作。
- 预算。
- 打包清单。
- 文件附件。
- PWA 离线。
- 复杂账号权限。

### 14.2 Funizy

参考项目：

- `https://funizy.com/`
- `https://funizy.com/blog`

可学习：

- 入口轻，例如“what can I do now?”。
- 个性化不是硬 persona，而是兴趣、日期、当前位置、即时状态。
- 一日计划要关注 walkable neighborhood、安全感、区域聚合和实时活动。

mtagent 应取中间：

> TREK 教我们把路线做成可持续编辑的旅行工作台；Funizy 教我们把入口做轻，把个性化讲清楚。mtagent 应该 AI 生成强，但结果必须能保存、能改、能解释。

## 15. 已创建的文档

本轮新增 / 更新了这些文档：

```text
docs/superpowers/idea/2026-05-12-mtagent-product-architecture-directions.md
docs/superpowers/idea/2026-05-12-reference-projects-and-mtagent-handoff-report.md
docs/superpowers/idea/2026-05-12-hackathon-direction-deepening-report.md
docs/superpowers/idea/数据处理agent.md
docs/superpowers/idea/路线规划编程agent.md
docs/superpowers/idea/2026-05-12-mtagent-conversation-summary-for-next-chat.md
```

用途：

- `mtagent-product-architecture-directions`：早期产品和架构方向。
- `reference-projects-and-mtagent-handoff-report`：TREK / Funizy 调研交接。
- `hackathon-direction-deepening-report`：赛题深化和明确方向。
- `数据处理agent`：给数据处理 Agent 看。
- `路线规划编程agent`：给后续路线规划代码 Agent 看，包含 prompt 设计。
- 当前文件：下一轮对话上下文总结。

## 16. 当前工作区变更状态

当前有这些新增 / 修改：

```text
M  scripts/label_pois.py
?? scripts/ai_label_tasks.py
?? data/poi_ai_label_tasks.jsonl
?? data/poi_ai_labels.json
?? data/poi_enriched_labels.json
?? data/poi_label_diagnosis.md
?? data/poi_label_summary.json
?? docs/superpowers/idea/
```

注意：

- `data/poi_labels.json` 仍按旧格式生成，当前 git 状态里没有显示修改。
- `docs/superpowers/idea/` 目录下包含多份本轮新增的文档。
- `docs/superpowers/idea/.DS_Store` 也在目录中，但这不是本轮核心交付物，后续提交时可忽略或删除。

## 17. 验证过的命令

成功运行：

```bash
PYTHONPATH=. python3 scripts/label_pois.py
python3 scripts/ai_label_tasks.py
python3 -m py_compile scripts/label_pois.py scripts/ai_label_tasks.py
```

完整 pytest 未作为有效验证，因为当前环境缺少 `fastapi`，加载 `tests/conftest.py` 时会失败。

## 18. 当前仍需注意的问题

### 18.1 AI 补标还不是高级 LLM

`scripts/ai_label_tasks.py` 当前是规则式 UGC 语义补标脚本，不是真正的高级 LLM。

后续建议：

- 要么改名为 `rule_refine_ugc_labels.py`。
- 要么新增真正的 LLM batch 标注器。
- 不要在对外文档中把当前脚本说成已经接入高级 LLM。

### 18.2 西安缺真正地标本体

西安 `city_essential = 0`，需要第三阶段人工补：

- 钟楼
- 大雁塔
- 回民街
- 西安城墙
- 大唐不夜城
- 兵马俑
- 陕西历史博物馆

否则西安路线会缺城市骨架。

### 18.3 标签仍需人工抽查

需要重点抽查：

- 深圳 `city_essential` 是否过宽。
- 上海 `city_essential` 是否准确。
- 餐厅是否被误标为地标。
- `queue_heavy` 是否过严或过松。
- `photo_friendly / food_quality / culture_friendly` 因 mock 数据标签密度偏高，可能仍偏泛。

### 18.4 Planner 尚未接入 enriched 标签

目前 `DianpingClient` 仍只把旧 `poi_labels.json` 注入到 `persona_labels`。

后续路线规划代码 Agent 要做：

- 读取 `data/poi_enriched_labels.json`。
- 将 enriched label 贴到 POI 或在候选池构建时 join。
- 使用 `poi_role / planning_tags / risk_tags / district / city_zone / suggested_slots` 做评分。

## 19. 下一轮建议优先级

推荐下一轮从这里接着做：

```text
P0: 让 Planner 读取 data/poi_enriched_labels.json
P1: 构建三层候选池：city_essential / persona_preferred / meal / connector
P2: 加入 POI score：偏好匹配、风险惩罚、区域连续性、slot fit
P3: 修改 Planner Prompt：只给 LLM 小候选集和 JSON schema
P4: 输出 main / low_queue / interest_first 三方案
P5: Critic 检查跨区、排队、重复、缺饭点、city_essential 缺失
P6: 接 replace_stop / redo_day_or_half_day
P7: 再做 TripJob / SSE 持久化
```

## 20. 下一轮对话开场建议

可以在新对话里这样开头：

```text
我们继续 mtagent 项目。
请先阅读：
docs/superpowers/idea/2026-05-12-mtagent-conversation-summary-for-next-chat.md
docs/superpowers/idea/路线规划编程agent.md
docs/superpowers/idea/数据处理agent.md

当前目标：
把 Planner 接入 data/poi_enriched_labels.json，完成三层候选池和路线推荐 prompt 改造。

注意：
1. 不要让 LLM 从全量 POI 里选。
2. city_essential 不被 persona 过滤。
3. meal / connector 用来补饭点和路线连贯性。
4. route_status 不能画假直线。
5. AI 补标脚本当前是规则式，不是真 LLM。
```

