# 美团 AI Hackathon 赛题 05 · 项目改造方案

> **文档目的:** 把 `travel-agent`(原 TripAgent)项目改造为美团 AI Hackathon 赛题 05 参赛方案的完整交接文档
> **目标读者:** Claude Code(继续推进项目的 AI agent)
> **作者:** Banz × Claude(Anthropic)
> **截止日期:** 2026-06-07
> **当前阶段:** 已完成赛题分析、数据源调研、API 字段映射、测试计划设计;待审核 appkey;代码改造未开始

---

## 0. 快速开始(如果你是接管的 cc,先看这里)

**项目目标:** 改造现有 travel-agent 代码,参赛美团 AI Hackathon 赛题 05(命题:用 LLM × POI × UGC × 用户偏好,生成"直接用、不踩雷"的个性化路线)。

**5 个核心改动方向(按重要性排序):**

1. **数据源切换** —— 高德 POI + 小红书 UGC,改成大众点评开放平台 API(`poiopen.dianping.com`)
2. **架构改造** —— 当前 `/plan/custom` 同步反思循环 4 分钟,改成 < 10 秒主路径 + 异步背景 critic(评委硬约束 10 秒内出路线)
3. **Agent 包装** —— 当前单 Agent + 状态机,包装成 4-Agent 协作叙事(Profiler / Planner / Critic / Adjuster),对位评委的"多 Agent 协作"加分项
4. **体验升级** —— 加多方案对比(N=2 路线并行生成)、自然语言实时调整、反馈闭环(用户拒了什么,写回 profile)
5. **前端聚焦** —— 现有 4 套(`index.html` / `plan.html` / `plan_stack.html` / `atelier.html`)只留 `plan_stack.html`,其他删除或归档

**当前阻塞:**
- 等大众点评 appkey/session 审核(用比赛名义申请,几天到一两周)
- 等主办方回复:赛题指定的接入方式是不是 `poiopen.dianping.com`?是否提供 sandbox / 数据 dump?

**接管后第一件事:** 先看第 8 章"立即可以开始的工作",再确认第 9 章"风险与未决问题"是否已有更新。

---

## 1. 比赛背景

**赛事:** 美团 2026 AI Hackathon
**赛题:** 赛题 05 ——「现在就出发 · AI 本地路线智能规划」
**截止时间:** 2026-06-07
**团队:** Banz(主开发) + BIT 在读研究生队友(分工待定)
**提交平台:** 美团 NoCode 平台(只是提交入口,主体工程仍在自有服务器)

**赛题命题原文(评委交底):**

> "用 LLM × POI 数据 × UGC 智慧 × 用户偏好,自动生成「直接用、不踩雷」的个性化路线方案。"

**任务描述(端到端流程):**
1. 用户输入游玩 / 出行目标
2. 系统结合 POI 数据与服务、用户评价语料等数据源
3. 自动生成多维度最优路线方案
4. 支持按时空、偏好等约束动态调整

**两大交付目标(并列等权重):**
- **路线生成** —— 根据用户意图自动串联多个 POI,生成完整路线安排
- **多条件与个性化** —— 满足差异化条件约束,结合用户历史偏好生成差异化方案

---

## 2. 评委评分维度(必须命中)

### 2.1 三大评分维度:完整性 + 创新性 + 应用效果

#### 完整性
- **路线可用性:** 生成路线是否合理可执行、时间安排是否现实、POI 覆盖是否准确
- **多约束满足:** 能否同时兼顾时间、距离、偏好、排队等约束,冲突时处理是否合理

#### 创新性
- **体验创新:** 是否支持自然语言实时调整、反馈闭环、多方案对比等交互设计
- **技术创新:** 独特的 LLM + 搜索/规划融合(ReAct、Tool Use、多 Agent 协作等)

#### 应用效果
- **综合考察:** 代码结构、部署简便性、文档完整性、方案可行性
- **加分项:** 良好的可维护性与工程实践

### 2.2 硬约束(CONSTRAINTS,不达标直接淘汰)
- **响应时间:** 路线生成 < 10 秒
- **POI 类型:** 至少覆盖 餐饮 + 娱乐/文化 两类
- **路线规模:** 支持 ≥ 3 个 POI 串联

### 2.3 隐性 Anchor:"直接用、不踩雷"

赛题命题原文加了引号特别强调,意味着评委关心:
- 店是不是关门 / 限流进不去 / 临时改造 / 广告水货
- 攻略时效性(不能用过时数据)
- 推荐的 POI 用户去了能不能真用

**这是隐藏的高优先级评分项。** 现有项目的 `check_poi_status.py` 三层证据金字塔正好对位,要放大这个强项。

---

## 3. 现有项目诊断(travel-agent / TripAgent)

### 3.1 项目地址
`~/Desktop/sth/travel-agent`

### 3.2 现有架构
- **后端:** FastAPI + uvicorn,Python 3.14
- **LLM:** 通义千问 qwen-plus(OpenAI 兼容,通过 dashscope)
- **数据源:** 高德 POI + 小红书 UGC + Exa 实时搜索
- **存储:** SQLite + Redis(实际只用了 JSON 文件)
- **前端:** 4 套并存,Jinja2 + Alpine.js + 高德 JS SDK

### 3.3 强项(在赛题语境下要保留并放大)

| 模块 | 价值 | 对位赛题 |
|---|---|---|
| `tools/check_poi_status.py` 三层证据金字塔(规则 → 高德权威 → Exa LLM judge) | "不踩雷"工程的核心 | 直接打中赛题隐性 anchor |
| `fabricated_name` 白名单约束 | 防 LLM 编造不存在的店,保证路线可执行 | 路线可用性 |
| `agent/architect_toolloop.py` 反思循环(propose → critique → revise) | 对位 Reflexion 范式 | 技术创新(Tool Use + 反思) |
| `tools/cluster_pois.py` Anchor & Orbit 聚类(K-means + 节假日热门度规避) | 一天一片区,不折返 | 路线可用性 + 多约束满足 |
| `pipeline/ranker.py` 类型化排序(A-F 六种 traveler_type) | 个性化雏形 | 多条件与个性化 |

### 3.4 弱项(必须补,否则丢分)

| 缺口 | 评委要求 | 必须做 |
|---|---|---|
| 历史偏好不存在 | 赛题原文"结合用户历史偏好生成差异化方案" | 必做 |
| 动态调整不存在 | 评委明确点名,且 4 分钟流程违反 10 秒硬约束 | 必做 |
| 多方案对比不存在 | 评委明确点名"多方案对比交互设计" | 必做(免费分) |
| 反馈闭环不存在 | 评委明确点名 | 必做 |
| eval 集是空话 | BLUEPRINT 写"≥ 4.0/5"但代码里没有测试集 | 应做 |

### 3.5 错位(必须改)

- **数据源不是点评/美团** —— 用了高德 + 小红书,赛题方明确要"点评 POI 数据 + UGC 智慧",**这是政治正确的硬错位**
- **前端 4 套并存** —— 研发期遗留,demo 时只能演示一套,需聚焦
- **`api/custom_plan.py` 同步阻塞 4 分钟** —— `asyncio.to_thread` 包了同步函数,但 LLM 反思循环本身就是几分钟级,不可能压进 10 秒

---

## 4. 战略调整方向

### 4.1 数据源切换:高德 + 小红书 → 大众点评

**为什么:**
- 赛题命题原文:"点评 POI 数据、UGC 智慧"——主办方就是点评/美团生态
- 不换数据源,评委一上来就觉得跑偏题
- 点评开放平台 API 字段比高德更丰富(`avgprice` / `queueInfo` / `reviewTags` / `dishs` / `isBlackPearl`)

**怎么换:** 见第 5 章字段映射 + 第 7 章代码改造路径

**保留兜底:** 高德 POI / 路径规划继续用(点评不给路径数据,公交数据下载 + 解析工程量大,hackathon 不划算)

### 4.2 架构改造:同步阻塞 → 主路径 + 异步背景

**问题:** 评委硬约束"路线生成 < 10 秒",当前 `/plan/custom` 同步跑 propose → critique → revise × N 轮,4-6 分钟级。

**解法:** 拆成两条轨道
- **主路径(< 10 秒,流式):** 工具并发(POI 搜索 / 详情 / 排队 / 路径)→ 一次 LLM 编排 → 流式吐出
- **背景路径(异步):** critique + revise 在主结果之后跑,有问题用 toast / 红点推送优化建议("发现 2 处可优化,要应用吗?")

**核心:** 反思循环不删,改成异步,**既保 10 秒又保留技术叙事**

### 4.3 Agent 包装:单 Agent → 多 Agent 协作叙事

**为什么:** 评委明确点名"多 Agent 协作"作为创新性加分项

**怎么做(代码不大改,主要是命名 + 架构图):**

| Agent | 职责 | 对应现有代码 |
|---|---|---|
| **Profiler** | 意图识别 + 拉用户历史偏好 | `api/agent.py` 的 INIT 阶段 + 新增 user profile 文件 |
| **Planner** | 并发调用 POI / UGC / 排队 / 路径四个工具,单次 LLM 编排,流式吐草稿 | `agent/architect_toolloop.py` 的 propose 部分 + 新增工具并发层 |
| **Critic** | 异步背景跑反思循环,推送优化建议 | `agent/architect_toolloop.py` 的 critique + revise,改成异步 |
| **Adjuster** | 响应用户实时调整,触发单天 regen,**把"用户拒了什么"写回 Profiler 的偏好库** | 新增模块,部分复用 `architect` 的局部 regen |

**比赛 PPT 上画一张 4-Agent 架构图,直接打中 3 个评分维度:** 完整性(Planner 出可用路线 + Critic 异步保多约束) + 创新性体验(Adjuster 闭环) + 创新性技术(多 Agent + ReAct + 流式)

### 4.4 三大体验创新(评委明确点名)

#### 4.4.1 自然语言实时调整
用户说"第 3 天换一个不要这家",Adjuster 触发**单天 regen**,**不重跑全程**,30 秒内出结果。

#### 4.4.2 反馈闭环
用户拒了 POI X → Adjuster 写回 Profiler 的 user profile("用户不喜欢 X 类型")→ 下次规划自动避开。**最小可行版本:cookie + JSON 文件存,不需要账号系统。**

#### 4.4.3 多方案对比
同一个输入用 N=2 个不同 prompt **并行生成两条路线**,比如:
- "暴走打卡版"(密度高、网红多、节奏快)
- "佛系慢游版"(精选少、人均高、留白多)

代码量极低(prompt 模板换两套,Promise.all 并发),但演示效果极强。**几乎免费的分,不做亏大了。**

### 4.5 流式 reveal UI(10 秒等待不能白等)

**绝对不要转圈进度条**,渐进式展示真实在做的事:

| 时间 | 显示 | 背后真实在做 |
|---|---|---|
| 0-2s | "正在理解需求" + 关键词标签飞出来(深圳 / 3 天 / 情侣) | Profiler 意图识别 + 历史偏好读取 |
| 2-5s | "正在挑选 POI" + 候选卡片一张张滑入 | Planner 并发调用搜索 / 详情 / 路径 |
| 5-8s | "正在编排路线" + 时间轴一段段画 | Planner LLM 编排,流式吐 |
| 8-10s | "正在做不踩雷检查" + 状态徽章一个个亮起 | Planner 兜底状态校验 |

**这种"工厂流水线"叙事评委爱看,把多 Agent 协作过程具象化** —— 现有 `web/atelier.html` 的 thinking 三态已有雏形,改造成本低。

---

## 5. 大众点评 API 完整字段映射

### 5.1 三个最重要的发现(更新心智模型)

#### 发现 1:UGC 评论嵌在 POI 详情里,不是独立 API

`getsinglepoi` 一次返回就包含 `ugcs` 列表(nick / score / content / photos / addtime / ispithy)、`reviewTags`(标签 + 命中次数)、`reviewCount`。

→ **不需要做评论爬虫**,`pipeline/cleaner.py` 的 LLM 提取地点逻辑可以直接砍掉。

#### 发现 2:`/router/ugc/upload` 是上传不是查询

这是给三方(比如携程)把游记**推给点评**用的接口,**不是让我们拉评论**。

→ **不要误用!** 评论只能通过 POI 详情拿。

#### 发现 3:`reviewTags` 是真正的金矿

长这样:`[{tag:"环境优雅", hit:128}, {tag:"上菜慢", hit:45}, ...]`

→ **既是"不踩雷"信号源**(看 hit 高的负面 tag),**又是个性化匹配源**(亲子 / 情侣 / 商务 等 tag 间接体现)
→ `tools/check_poi_status.py` 现在用 Exa + LLM 推断的逻辑,可以**用 reviewTags 替代**(权威 × 便宜 × 快)

### 5.2 赛题需求 × 点评字段映射表

| 赛题需求 | 点评字段 | 来源 endpoint | 之前的方案 | 动作 |
|---|---|---|---|---|
| **基础属性** | | | | |
| 唯一 ID | `openshopid` | 详情 / 搜索 | 高德 id | 替换 |
| 名字 | `name` + `branch_name` | 详情 | name | 注意拼分店名 |
| 坐标 (GCJ-02) | `latitude` / `longitude` | 详情 / 搜索 | GCJ-02 | **可直接迁移,坐标系一致** |
| 城市 / 商场 | `city` / `mallInfo` | 详情 | district | 升级,有商场维度 |
| 类目 | `categories`(叶子类目 list) | 详情 | 你写了 manual override | **替换,不再需要手工修正** |
| 营业状态 | `openstatus` (0/1) | 详情 | 从名字抓"暂停营业" | **替换,权威靠谱多了** |
| 营业时间 | `business_hour` | 详情 | 高德 biz_ext.opentime | 替换 |
| 高质量标志 | `highquality` | 详情 | ✗ | **新增,排序权重直接用** |
| 黑珍珠 | `isBlackPearl` | 详情 | ✗ | **品质背书,demo 加分** |
| **决策辅助** | | | | |
| 人均消费 | `avgprice` (int) | 详情 | ✗ | **预算约束的物质基础** |
| 平均星级 | `star` (float) | 详情 | rating | 替换 |
| 评论数 | `reviewCount` | 详情 | 高德是热度不是评论数 | 替换,置信度更高 |
| 推荐菜 | `dishs`(菜名/图/价格/推荐次数) | 详情 | LLM 自己编 | **替换,真实数据** |
| 商户特色服务 | `special` list | 详情 | ✗ | **个性化匹配源** |
| 团单优惠 | `dealInfo` | 详情 | ✗ | **美团生态加分项** |
| 是否外卖 / 排号 / 预订 | `takeawayable` / `queueable` / `bookable` | 详情 | ✗ | **多约束信号** |
| **UGC 维度** | | | | |
| 评论文本 | `ugcs.item.content` | 详情(嵌套) | XHS 单独爬 | **替换,无需独立爬虫** |
| 评论时间 | `ugcs.item.addtime` | 详情 | ✗ | **时效性降权** |
| 评论星级 | `ugcs.item.score` (0-5 半星) | 详情 | ✗ | 新增 |
| 评论图片 | `ugcs.item.photos` | 详情 | XHS 图(易过期) | **替换,稳定** |
| 优质评论标志 | `ugcs.item.ispithy` | 详情 | ✗ | **头部评论筛选** |
| 评论标签 + 命中数 | `reviewTags` | 详情 | ✗ | **🔥 踩雷+个性化的核心信号** |
| **实时与路线** | | | | |
| 实时排队 | `queueInfo.msg` / `shortMsg` | **`/realtime/getcoopinfo` 单调** | Exa + LLM 推断 | **替换,工具瘦身** |
| 商场人气榜 | `mallInfo.popularShops` | 详情 | ✗ | **商场内行程的灵感来源** |
| 公交数据 | line/stop/station/exit URL 列表 | `/s3/getpublictransit` | ✗(用高德路径) | **不建议接(工程量大)** |

### 5.3 < 10 秒响应的调用链设计

| 阶段 | 调用 | 并发? | 预估耗时 | 备注 |
|---|---|---|---|---|
| 0. 城市校验 | `/city/opencity` | 启动时一次 | ~0(缓存) | 看你的城市在不在白名单 |
| 1. POI 召回 | `/poisearch/search` × 类目 | 并发 | ~300ms | 餐饮 / 娱乐 / 文化 三路并发搜 |
| 2. POI 详情(批量) | `/poi/batchgetpoi`(单次最多 100) | 一次批 | ~500ms-1s | 一次拿全:评论 + 推荐菜 + 标签 + 人均 |
| 3. 实时排队 | `/realtime/getcoopinfo` × M | 并发 | ~400ms | M=候选 POI 数,只对最终入选的查 |
| 4. LLM 编排 | qwen-plus 一次,流式 | - | 2-4s | 主路径 |
| **合计** | | | **4-6s** | 留 4s buffer 给前端流式 reveal |

**关键:** 第 2 步用 batch 而不是 N 次单查—— `batchgetpoi` 单次 100 个 POI,比 N 次 `getsinglepoi` 快 10 倍以上。

### 5.4 关键判断与跳过项

**不接的 endpoint:**
- `/router/ugc/upload`:**反向接口**(三方推 UGC 给点评),我们用不上
- `/router/s3/getpublictransit`:返回的是公交数据 ZIP 下载链接,要自己解析,工程量大,**用高德路径规划替代**
- `/router/realtime/getpoiphone`:我们不打电话
- `/router/callback/notifychange`:要部署回调端点,初期不做

**坐标系:GCJ-02**(和高德一致,迁移友好,`pipeline/mapper.py` 不用动)

**没有的字段(要 fallback):**
- 评分分布(1-5 星各占多少):无,只有平均 `star`
- 显式人群标签(亲子/情侣/商务):无,**通过 `reviewTags` 间接识别**

**潜在阻塞:** 搜索接口的 `distance` / `shopaddress` / `category` 字段标了"需申请权限",**默认拿不到** —— 测试时第一件事确认这一点

---

## 6. API 测试计划 + Python Helper

### 6.1 API 测试优先级清单

| 优先级 | 接口名 | URL(POST) | 业务参数(除公共参数外) | 关键返回字段 | 测试目的 |
|---|---|---|---|---|---|
| 🔥 P0 | 授权城市 | `/router/city/opencity` | (无) | `data: [城市列表]` | 验签流程跑通的最简测试 |
| 🔥 P0 | POI 搜索 | `/router/poisearch/search` | `keyword` / `lat` / `lng` / `city` / `radius` / `categories` / `page` / `limit` | `records[].openshopid`, `name` | 路线起点,验证关键词能搜到 POI |
| 🔥 P0 | POI 详情 | `/router/poi/getsinglepoi` | `openshopid` | `latitude` `longitude` `categories` `business_hour` `openstatus` `avgprice` `star` `reviewCount` `ugcs` `reviewTags` `dishs` `isBlackPearl` `queueable` `special` `mallInfo` `dealInfo` | **demo 的命脉**——所有核心字段都从这里来 |
| 🔥 P0 | 实时排队 | `/router/realtime/getcoopinfo` | `openshopid` | `queueInfo.msg`, `queueInfo.shortMsg` | "不想排队"的物质基础 |
| ⭐ P1 | 批量 POI 详情 | `/router/poi/batchgetpoi` | `multiopenshopid`(逗号分隔, ≤ 100) | (同 POI 详情但 list) | 10 秒响应必需,N 次单查会超时 |
| ⭐ P1 | 分页查城市 POI | `/router/poi/pagequerypoi` | `cityname` / `page` | `records[]` | 预爬城市全量数据(仅离线跑) |
| ◯ P2 | 菜品榜单 | `/router/dish/dishlist` | `dishname` / `ip` | `dishVo` / `searchList` | 锦上添花的美食维度 |
| ◯ P2 | 拍照识店 | `/router/imagerecognition/querypoi` | `imgdata` / `datatype` / `lat` / `lng` / `coordtype` | `predictShops[]` | 创新加分(拍照加入路线) |
| ◯ P2 | 拍照识菜 | `/router/imagerecognition/queryspu` | `imgdata` / `datatype` / `sputype` | `name` list | 创新加分 |
| ❌ 跳过 | UGC 上传 | `/router/ugc/upload` | — | — | 反向接口,我们用不上 |
| ❌ 跳过 | 公交数据 | `/router/s3/getpublictransit` | — | — | 工程量大,用高德路径替代 |
| ❌ 跳过 | POI 电话 | `/router/realtime/getpoiphone` | — | — | 我们不打电话 |
| ❌ 跳过 | POI 变更回调 | `/router/callback/notifychange` | — | — | 要部署回调端点,初期不做 |

### 6.2 推荐测试顺序(由易到难,逐级验证)

| 步骤 | 接口 | 你能确认什么 |
|---|---|---|
| 1 | 授权城市 | 你的签名流程、appkey/session 都没问题 |
| 2 | POI 搜索 | 关键词召回正常,拿到第一个 `openshopid` |
| 3 | POI 详情 | 核心字段(尤其 `ugcs` / `reviewTags` / `avgprice`)质量够不够 demo |
| 4 | 实时排队 | "不踩雷"信号够不够准 |
| 5 | 批量 POI 详情 | 100 个 id 一次返回的耗时,验证 < 10 秒可达 |

走通 1-4,MVP 数据层就立得起来了。

### 6.3 测 POI 详情时,重点核对这几个字段(决定 demo 能否成立)

| 字段 | 期望情况 | 怎么算"质量够" | 不够的 fallback |
|---|---|---|---|
| `ugcs` | list, ≥ 3 条 | content 有完整文本,不是省略号截断 | 用 `reviewTags` 替代叙事 |
| `reviewTags` | list, ≥ 5 个 tag | 既有正面("环境好")也有负面("上菜慢"),hit 数差异大 | 这个字段不行,踩雷信号就塌了,只能回退到 Exa |
| `avgprice` | int, 餐饮类 > 0 | 数字真实(不是 0 或离谱大) | LLM 从 dishs.price 估算 |
| `star` | float, 0~5,半星精度 | 大部分 POI 应该有 | 0 表示无评分,要降权处理 |
| `dishs` | 餐饮类应有 list | 至少 3 道菜,带 `recommendCount` | LLM 从评论文本抽 |
| `business_hour` | string,可解析 | 类似 "10:00-22:00",别给一坨自由文 | 高德兜底 |
| `openstatus` | 0 或 1 | 1 才能放进路线 | — |
| `isBlackPearl` | 0 或 1 | 大部分 0,极少 1 | demo 里突出黑珍珠的高级感 |
| `mallInfo.popularShops` | 商场内有 | 商场类 POI 应该非空 | — |

### 6.4 加签算法

参数名小写 → ASCII 升序排序 → 拼接(key + value + key + value...)→ 前后包 appsecrect → utf-8 编码 → MD5 → hex 小写

例:`a=1, b=2, ab=3, appsecrect=xyz` → 排序 `ab=3, a=1, b=2` → 拼接 `ab3a1b2` → 包 `xyzab3a1b2xyz` → MD5

**容易错的两点:**
1. **参数名小写**(很多人忘了)
2. **前后都要包 appsecrect**(不是只包前面或后面)

**timestamp 是毫秒**,30 分钟内有效 ——`int(time.time() * 1000)`

**session 不同接口可能不同**,文档多次说明

### 6.5 Python Helper(直接 copy 跑)

```python
import hashlib
import time
import requests

APPKEY = "你的appkey"
APPSECRECT = "你的appsecrect"
SESSION = "你的session"  # 注意不同接口可能不同
BASE = "https://poiopen.dianping.com"


def _sign(params: dict, appsecrect: str) -> str:
    """点评加签:key 小写 → ASCII 排序 → 拼接 → 前后包 appsecrect → MD5 hex 小写"""
    items = [(k.lower(), str(v)) for k, v in params.items()
             if v not in (None, "") and k.lower() != "appsecrect"]
    items.sort(key=lambda x: x[0])
    concat = "".join(f"{k}{v}" for k, v in items)
    raw = f"{appsecrect}{concat}{appsecrect}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest().lower()


def call(endpoint: str, biz: dict = None, session: str = SESSION) -> dict:
    """调点评 API 通用包装,自动加签 + 加公共参数"""
    biz = biz or {}
    params = {
        "appkey": APPKEY,
        "session": session,
        "timestamp": str(int(time.time() * 1000)),
        **{k: v for k, v in biz.items() if v not in (None, "")},
    }
    params["sign"] = _sign(params, APPSECRECT)
    resp = requests.post(f"{BASE}{endpoint}", json=params, timeout=10)
    return resp.json()


# 五步测试 ↓↓↓
if __name__ == "__main__":
    # 1. 授权城市(最简单,验证签名流程)
    print(call("/router/city/opencity"))

    # 2. 搜索(拿第一个 openshopid)
    r = call("/router/poisearch/search", {
        "keyword": "火锅", "city": "深圳", "radius": 3000, "limit": 5,
    })
    print(r)
    shop_id = r["records"][0]["openshopid"]

    # 3. POI 详情(核心,看字段质量)
    detail = call("/router/poi/getsinglepoi", {"openshopid": shop_id})
    print(detail)
    # 重点核对:
    print("ugcs 数量:", len(detail["data"].get("ugcs", [])))
    print("reviewTags:", detail["data"].get("reviewTags"))
    print("avgprice:", detail["data"].get("avgprice"))
    print("dishs 数量:", len(detail["data"].get("dishs", [])))

    # 4. 实时排队
    print(call("/router/realtime/getcoopinfo", {"openshopid": shop_id}))

    # 5. 批量(测延迟)
    ids = ",".join([shop_id])  # 真正测时拿 5-10 个
    print(call("/router/poi/batchgetpoi", {"multiopenshopid": ids}))
```

**注:** 接口请求体格式按 JSON body 写了,**如果点评要求 form-urlencoded**(`Content-Type: application/x-www-form-urlencoded`),把 `json=params` 改成 `data=params` 即可。两种都试一下,反正第一步授权城市能跑通就说明对了。

---

## 7. 代码改造路径(目录级别)

### 7.1 数据层

#### `pipeline/cleaner.py` —— 砍 70%
- **现在:** 小红书原文 → LLM 提取地点 → Geocoding 补坐标(三步,~400 行)
- **点评世界:** POI 是结构化的,坐标自带,评论本身就绑在 POI 上
- **改后:** 留一个轻量的"点评 raw → 内部 schema"适配层,< 100 行

#### `tools/match_pois.py` —— 简化
- **现在:** normalize + contain + fuzzy + amap_fallback 四层(~250 行)
- **点评世界:** `/poisearch/search` 关键词 + 城市直接搜,大部分一次命中
- **改后:** 点评搜索为主 + 高德 fallback 兜底

#### `tools/check_poi_status.py` —— 重新设计
- **现在:** 规则 → 高德 → Exa → LLM judge(四层金字塔,~200 行)
- **点评世界:** `openstatus` + `reviewTags` 直接判,Exa 只在异常或高峰节假日时兜底
- **改后:** 两层(权威字段直判 + Exa 兜底),省掉 LLM judge,**延迟和成本都降**

#### `scrapers/xhs_scraper.py` —— 归档
- 不再使用,但保留代码作为"我们做过 UGC 爬虫"的历史证据
- 移到 `archive/` 目录

### 7.2 Agent 层

#### `api/agent.py` —— 拆为 4-Agent

新建目录 `agents/`:

```
agents/
├── __init__.py
├── profiler.py    # 拉历史偏好(从 data/user_profiles/{cookie_key}.json),识别意图
├── planner.py     # 主路径,工具并发 + 单次 LLM 编排,流式
├── critic.py      # 异步背景反思
└── adjuster.py    # 实时调整 + 反馈闭环
```

复用 `agent/architect_toolloop.py` 的 propose / critique / revise 函数,但拆到不同 agent 里。

#### `api/custom_plan.py` —— 改为流式 SSE

- **现在:** 同步阻塞返回 JSON
- **改后:** Server-Sent Events 流式,每个工具调用、LLM token 都流出来给前端 reveal

### 7.3 前端

**只留 `plan_stack.html`**(卡片堆叠版,最像产品),其他三个移到 `archive/`:
- `index.html` → `archive/`
- `plan.html` → `archive/`
- `atelier.html` → 提取 thinking 三态部分到 `plan_stack.html`,本体归档

**新增功能(在 `plan_stack.html` 里):**
- 多方案对比(顶部 tab 切换"暴走版" / "佛系版")
- 实时调整入口(每个 stop 卡片右边加"换一个"按钮)
- 反馈闭环 UI(被替换的 POI 显示"已学习,不再推荐此类")
- 流式 reveal 阶段(0-2s / 2-5s / 5-8s / 8-10s,接 SSE 事件)

### 7.4 用户偏好持久化

新建 `data/user_profiles/{cookie_key}.json`,结构:

```json
{
  "cookie_key": "abc123",
  "preferences": {
    "loved_categories": ["景观", "文化"],
    "rejected_categories": ["夜店", "KTV"],
    "loved_pois": ["openshopid_xxx"],
    "rejected_pois": ["openshopid_yyy"],
    "avg_budget_per_day": 800,
    "avg_walking_pref": "moderate",
    "preferred_review_tags": ["环境优雅", "服务好"],
    "rejected_review_tags": ["上菜慢", "服务差"]
  },
  "history": [
    {"trip_id": "...", "city": "深圳", "satisfied": true, "completed_at": "2026-04-29"}
  ]
}
```

Profiler 每次启动读这个文件,写到 LLM 的 system prompt 里。Adjuster 每次用户操作写回。

---

## 8. 立即可以开始的工作(审核期间不闲着)

### 8.1 已完成
- [x] 赛题分析
- [x] 数据源调研
- [x] 点评 API 字段映射
- [x] 测试计划设计

### 8.2 进行中
- [ ] 申请大众点评开放平台 appkey/session(用比赛名义)
- [ ] 等主办方回复(接入方式 + 数据 dump)

### 8.3 审核期间立即开始的(不依赖 appkey)

**Priority 0:**
- [ ] **写 mock 层**:创建 `mocks/dianping_mock.py`,从文档示例抄 JSON 造 5-10 个 POI 假数据,模拟所有要测的 endpoint 响应
- [ ] **Adapter 层先行**:写 `adapters/dianping_adapter.py`,把点评 raw 字段转成内部 schema(用 mock 数据驱动)
- [ ] **重构 `pipeline/cleaner.py`**:按新 schema 改,< 100 行的轻量适配
- [ ] **重构 `tools/match_pois.py`**:简化为点评搜索为主 + 高德 fallback
- [ ] **重构 `tools/check_poi_status.py`**:两层金字塔(reviewTags 直判 + Exa 兜底)

**Priority 1:**
- [ ] 拆分 4-Agent 目录结构(`agents/profiler.py` / `planner.py` / `critic.py` / `adjuster.py`)
- [ ] `api/custom_plan.py` 改造为 SSE 流式
- [ ] `data/user_profiles/` 用户偏好持久化(JSON 文件)
- [ ] 前端:聚焦 `plan_stack.html`,把其他 3 个移到 `archive/`

**Priority 2:**
- [ ] 多方案对比(N=2 并行生成,前端 tab 切换)
- [ ] 实时调整 UI(每个 stop 卡片"换一个"按钮)
- [ ] 反馈闭环 UI("已学习,不再推荐此类"提示)
- [ ] 流式 reveal 阶段 UI(0-2s / 2-5s / 5-8s / 8-10s)

### 8.4 拿到 appkey 之后
- [ ] 跑 Python helper 的 5 步测试(授权城市 → 搜索 → 详情 → 排队 → 批量)
- [ ] 把 5 个返回的 JSON 贴回来(给 Banz 或 Claude review)
- [ ] 验证字段质量(`ugcs` / `reviewTags` / `avgprice` / `dishs` 是否够 demo)
- [ ] 把 mock 数据替换成真数据
- [ ] 跑通完整 pipeline,测延迟是否 < 10 秒

### 8.5 demo 准备(最后 1 周)
- [ ] 准备 3-5 个典型 demo query("情侣 3 天深圳"、"亲子 2 天上海"、"美食 1 天广州" 等)
- [ ] 录演示视频(展示 < 10 秒响应、流式 reveal、多方案对比、实时调整、反馈闭环)
- [ ] PPT(4-Agent 架构图、技术亮点 reviewTags 应用、检查点状态金字塔)
- [ ] README 完善(部署方式、架构图、技术选型说明)

---

## 9. 风险与未决问题

### 9.1 数据源风险(最高优先级)
- **`poiopen.dianping.com` 是不是赛题指定接入方式?** 主办方可能给的是另一套 sandbox / 内部 API
- **个人/学生能不能拿到 appkey?** 商户开放平台默认对企业,个人申请大概率被拒或限流
- **数据缓存条款:** 点评开放平台历史上对 UGC 缓存管得很严("伪开放"批评),可能限制不让长期存储原始评论数据 —— **如果限制还在,你的整个数据策略需要调整**

**对冲动作:** 同时追主办方 + 申请公开 key + 准备 fallback 到高德 + Exa 的现有方案

### 9.2 字段权限风险
- 搜索接口的 `distance` / `shopaddress` / `category` 标了"需申请权限",**默认拿不到**
- 如果不给,要多一次详情查询补字段(性能受影响)
- 测试时第一件事确认这个

### 9.3 时间风险
- 距离截止 2026-06-07 还有约 30 天
- appkey 审核 1-2 周
- 留给开发 + 调试 + 演示 ≤ 18 天

**对冲动作:** mock 先行,审核期完成所有不依赖真数据的代码改造

### 9.4 队友分工未定
- **Banz 还没确认 BIT 队友的具体分工**
- **推荐切法:** Banz 主搞后端 4-Agent + 数据接入,队友主搞前端 plan_stack 升级 + 流式 reveal
- 当前阻塞:之前因 dual-driver 协作模式过度设计 overload,**这个卡点必须解决,否则继续堆功能只会更慌**

### 9.5 eval 集仍未建立
- BLUEPRINT 写"行程合理性 ≥ 4.0/5",但还没建测试集
- **推荐:** hackathon 阶段做 5-10 个典型 query 的 case 集,每次架构改动跑一遍人工对比
- 例 case:
  - "情侣 3 天深圳,预算 4000,喜欢拍照"
  - "亲子 4 天上海,孩子 5 岁,不能太累"
  - "美食 2 天广州,人均 200 内"
  - "文化深度 5 天西安,喜欢博物馆"
  - "穷游 7 天大理,预算 3000"

### 9.6 NoCode 平台限制未知
- 美团 NoCode 平台到底有什么限制?是只接 Webhook 还是要把整个 app 放上去?
- 如果限制 Python 后端,FastAPI 这套可能要重写一部分
- **要问主办方**

---

## 10. 决策依据(给 cc 的"为什么"备忘)

### 10.1 为什么数据源必须切到点评?
赛题命题原文使用了"乘号":"LLM × POI × UGC × 用户偏好"——任何一个为零整体为零。"POI 数据"和"UGC 智慧"在赛题语境下都默认指主办方生态(美团/点评)。用高德 + 小红书,评委一上来就觉得跑偏题。

### 10.2 为什么反思循环要拆成异步?
"路线生成 < 10 秒"是评委硬约束(写在 CONSTRAINTS 里)。当前 propose → critique → revise 同步串行,光 propose 就 30 秒+,不可能压进 10 秒。但反思循环本身是技术叙事的卖点(对位 Reflexion 范式),不能砍。**异步是唯一既保 10 秒又保叙事的解法。**

### 10.3 为什么要做多方案对比?
评委 PPT 「体验创新」 那一栏明确写了"多方案对比交互设计"。代码量极低(两套 prompt + Promise.all),不做就是白送的分。

### 10.4 为什么要 4-Agent 包装?
评委 「技术创新」 栏明确点名"多 Agent 协作"作为创新点。当前是单 Agent + 状态机,功能上可以等价于多 Agent,但**叙事上不如 4-Agent 架构图直观**。命名 + 架构图改造,代码改动有限,但讲故事威力大。

### 10.5 为什么用户历史偏好用 cookie + JSON?
赛题原文:"结合用户历史偏好生成差异化方案"——必须做,否则丢分。但 hackathon 不需要做账号系统(过度工程),**cookie 作为 anonymous user key + JSON 文件存 profile** 是最小可行方案,能在 demo 里讲"系统记得你之前去过哪、不喜欢什么"的故事。

### 10.6 为什么前端只留 plan_stack.html?
现有 4 套前端是研发期反复探索的痕迹,但 demo 只能演示一个。`plan_stack.html` 卡片堆叠版最像产品 —— 暖米色 + Instrument Serif,有产品质感而不是研发原型。其他三个保留代码作为"探索过的 UI 方向"证据,但不进 demo。

### 10.7 为什么 `reviewTags` 是金矿?
这个字段一行解决两个赛题需求:
- **不踩雷:** hit 数高的负面 tag(如"上菜慢", hit=45)就是踩雷信号
- **个性化:** "亲子友好"、"约会氛围"这类 tag 直接对位 traveler_type

而且是**权威预聚合数据**,不需要 LLM 二次抽取,既快又准。把 `check_poi_status.py` 的四层金字塔降为两层,延迟和成本都受益。

### 10.8 为什么不做公交数据接入?
`/router/s3/getpublictransit` 返回的是公交线路 / 站点 / 地铁出入口的全城数据**下载链接**(ZIP 文件)。要拿到 URL 后下载 + 解析 + 自己跑路径算法 —— 这是给做地图产品的公司用的。Hackathon 一个月不划算,**直接调高德路径规划 API 性价比高得多**。

---

## 11. 附录

### 11.1 决策时间线

| 日期 | 事件 |
|---|---|
| 2026-04-19 | BLUEPRINT.md v0.1 完成,五一深圳行程为主要场景 |
| 2026-05-初 | 完成 Architect 反思循环 + check_poi_status 三层金字塔 |
| 2026-05-? | 美团 hackathon 赛题确认,主战场切换 |
| 2026-05-07(本次会话) | 完成赛题分析、数据源切换决策、点评 API 字段映射、测试计划 |
| 2026-05-中(申请期) | mock 先行 + 数据层重构 |
| 2026-05-末 | 拿到 appkey,真数据接入,跑通主路径 |
| 2026-06-初 | demo 打磨 + 演示视频 |
| 2026-06-07 | 截止 |

### 11.2 关键文件清单(改造前)
- `BLUEPRINT.md` —— 项目定位文档(已过时一部分,五一场景部分仍有效)
- `CLAUDE.md` —— 给 Claude Code 的项目说明
- `TODO.md` —— 旧迭代清单
- `api/custom_plan.py` —— 同步反思循环,要改流式
- `agent/architect_toolloop.py` —— 反思循环核心,要拆成 Critic agent
- `tools/check_poi_status.py` —— 三层金字塔,要简化
- `tools/cluster_pois.py` —— Anchor & Orbit,保留
- `tools/match_pois.py` —— 四层匹配,要简化
- `tools/check_poi_status.py` —— 状态校验,要简化
- `pipeline/cleaner.py` —— LLM 提取地点,大砍
- `pipeline/ranker.py` —— 类型化排序,保留
- `pipeline/food_matcher.py` —— 美食匹配,点评世界用 dishs 字段替代
- `pipeline/web_search.py` —— Exa 兜底,保留为 fallback
- `pipeline/mapper.py` —— 高德地图链接,保留(坐标系 GCJ-02 一致)
- `scrapers/amap_scraper.py` —— 高德 POI 爬虫,降级为 fallback
- `scrapers/xhs_scraper.py` —— 小红书爬虫,归档
- `web/index.html` —— 对话式前端,归档
- `web/plan.html` —— 列表+地图,归档
- `web/plan_stack.html` —— **保留并升级为主前端**
- `web/atelier.html` —— 三态对话式,提取 thinking 部分到 plan_stack 后归档

### 11.3 关键链接
- **比赛群:** (Banz 知道,要追主办方)
- **大众点评开放平台:** https://poiopen.dianping.com
- **赛题文档(API 接入):** https://poiopen.dianping.com/instructions/doc/poi.html
- **赛题文档(指南):** https://poiopen.dianping.com/instructions/guide.html
- **GitHub:** YIKUAIBANZI/travel-agent(假定)

### 11.4 Banz 个人偏好(如果 cc 跟 Banz 直接对话)
- 默认中文回复,适中长度(结论 + 关键细节 + 示例)
- 少用 bullet,优先散文 + 关键词加粗
- 默认先搜索英文资料源,优先 youtube / x / reddit / google,缺再搜中文
- 回答不清楚的问题先搜索,不要硬猜
- 问题有歧义时先问清楚再回答
- 给建议时先分析利弊再给倾向性建议
- 方向有问题直接说,不用顾虑情绪
- 技术问题代码适量,配合文字解释
- 复杂问题先聊透再给具体操作
- 多用苏格拉底提问激发 Banz 思考
- 称呼 Banz
- IDEA 快捷键提供 Mac 和 Windows 双版本
- Banz 是 CS/AI 本科生 + 学生独立开发者品牌,在深圳

---

> **给 cc 的最后一句话:**
>
> 这个项目的核心矛盾不是技术,是判断 —— 判断哪些功能对评委有分、哪些是技术债、哪些是免费分(比如多方案对比)。
>
> **接管后第一件事不是开始写代码,是先和 Banz 对齐第 8 章 "立即开始的工作" 是否准确,以及第 9 章 "风险与未决问题" 是否已有更新(尤其 9.1 数据源风险和 9.4 队友分工)。**
>
> 如果 Banz 说"按报告执行就行,别问了",那从 8.3 Priority 0 的 mock 层开始动手。
