# v1.9 数据/推荐/用户画像/换计划 — 总 Spec

**Date**: 2026-05-14
**Status**: 待实施 (clear 后 resume 起点)
**Hackathon DDL**: 2026-06-07 (剩 ~24 天)
**Base**: v1.8 已 ship 锚点驱动 + 5 类 trip_mode 路由 (commit `7cb5acc` HEAD on main)

---

## 0. 当前已完成 (v1.8 baseline, 不要重复做)

- ✅ 5 mode 路由 (anchor_explore / layover_eat / layover_explore / landmark_must / multi_day)
- ✅ 高德 geocode + place around (`agents/anchor.py`, **fetch_around 已写但还没集成到 pool**)
- ✅ candidate_pool 加 anchor distance_penalty + radius filter
- ✅ Profiler 集成 trip_router + anchor 解析
- ✅ 前端 anchor_explore 画半径圈 + ★ marker
- ✅ Track A 修复 (fallback 去重 / slot-aware meal / chat 自相矛盾)
- ✅ 测试 223 passed + 1 known flaky
- ✅ Push 到 origin/main (https://github.com/YIKUAIBANZI/mtagent.git)

**v1.8 e2e 验证暴露的核心痛点 (v1.9 P0 修这个)**:
- Scene A 万象天地: anchor 几何正确, 但 stops 只有 2 个 (meal 桶在 4km 内空)
- Scene B 上海站: anchor 正确, 但 stops 只有 1 个且是公园 (不是美食)
- 根因: mock_dianping 在锚点半径内 POI 稀疏, 且 `anchor.fetch_around` 没接进候选池

---

## 1. v1.9 四阶段目标

| 阶段 | 解决什么 | 工程量 | 优先级 |
|---|---|---|---|
| **Stage 1: 数据 + 推荐** | 锚点池稀疏 / enriched 脏点 / tag mapping 散落 | ~6h | P0 |
| **Stage 2: 持久用户数据 + 冷启动** | 首次使用收集偏好 → 注入推荐权重 | ~5h | P0 |
| **Stage 3: 换地点换计划 (Adjuster v1)** | 用户改一个 stop / 删 stop / 换 variant | ~6h | P1 |
| **Stage 4: 行为反馈 → user_profile 写回** | 跨会话保存习惯, 下次冷启动用 | ~3h | P1 |

**总 ~20h**, 跟剩余 hackathon 时间匹配.

---

## Stage 1: 数据 + 推荐 (P0)

### 1.1 集成 anchor.fetch_around 进 candidate_pool [P0-A]

**问题**: v1.8 写了 `fetch_around` + `merge_with_local_pool`, 但没接进 `planner_instant.plan_one_variant`. 锚点半径内本地 POI 不够时仍只用 mock 池.

**做法**:

修改 `agents/planner_instant.py:plan_one_variant`:
- 在 `flatten_candidate_pool` 之前, 如果 `intent.anchor_lng/lat` 存在 + `intent.trip_mode in (anchor_explore, layover_eat, layover_explore)`:
  - 调 `fetch_around(lng, lat, radius_m, types)`, types 按 trip_mode 选 (layover_eat 偏餐饮 050000)
  - 用 `merge_with_local_pool` 合本地 + 高德 POI
  - 合后 POI 进 `build_candidate_pool`

修改 `agents/candidate_pool.py:build_candidate_pool`:
- 接受合并后的 POI (含无 enriched 的高德 POI)
- 无 enriched 的 POI 走 fallback 评分 (用 categories 推 poi_role: 美食→meal, 景点→city_essential, 购物→connector)
- 加 `_infer_role_from_categories(categories) -> PoiRole` helper

**测试**:
- `tests/test_planner_instant_v19_amap_integration.py`:
  - mock fetch_around 返回 10 个 POI, 合本地 5 个 → pool 总数 ≥ 10
  - layover_eat 模式 types 应含 "050000"
  - anchor_explore 模式 types 用 default (餐饮+购物+休闲+景点)

**Acceptance**:
- Scene A 万象天地: stops 数从 2 → 4 (满槽位)
- Scene B 上海站: stops 数从 1 → 4, 至少 2 个是美食 (layover_eat)
- 188 baseline 不破, 新增 3 测试

**工程量**: 2h

---

### 1.2 EnrichedLabel 脏点扫描 + 修复 [P0-B]

**问题**: 西安城墙 categories=美食 (脏点污染 meal 桶), 类似的还有其它 POI.

**做法**:

新建 `scripts/audit_enriched.py`:
```python
RULES = [
    # 类型矛盾
    ("城墙|古城|塔|寺|博物馆" in name) and ("美食" in categories),
    ("酒店|宾馆" in name),                  # 不应进路线
    # 角色错位
    poi_role == "meal" and not any("美食" in c for c in categories),
    poi_role == "city_essential" and manual_priority < 70,
    # 字段薄
    city_zone == "",
    len(planning_tags) < 2,
]
```

输出 `data/generated/enriched_audit_report.json` 列标红 POI.

新建 `scripts/refix_enriched.py`:
- 读 audit_report, 逐个跑 LLM 重打 (qwen-plus, temperature=0.2)
- prompt 要求: 必须从规定词表选 planning_tags, categories 跟 name 矛盾时以 name+reviewTags 为准
- 输出新 `data/poi_enriched_labels.json` + `data/poi_agent_labels.json` patch (防止重生成回弹)

**测试**:
- `tests/test_enriched_audit.py`: 输入 5 个明确脏 POI, 验 audit 全标红
- `tests/test_enriched_smoke.py`: 跑完修复后再 audit, 标红率 < 3%

**Acceptance**:
- 西安城墙 / 鼓楼 / 兵马俑 等 不再出现在 meal 桶
- audit 标红率从 ~15% 降到 < 3%

**工程量**: 1.5h (audit 1h + refix 跑 0.5h)

---

### 1.3 tag_mapping.json 抽出 [P1-C]

**问题**: 用户兴趣词 ↔ planning_tags 映射散落在 `candidate_pool.py:31 INTEREST_TO_TAG`, Profiler / Planner / score_poi 各处可能不一致.

**做法**:

新建 `data/tag_mapping.json`:
```json
{
  "user_interest_to_planning_tags": { ... 现有 INTEREST_TO_TAG ... },
  "user_constraints_to_risk_tags": {
    "avoid_queue": ["queue_heavy", "crowded_weekend"],
    "avoid_walking": ["walk_heavy"],
    "avoid_cross_district": ["far_from_anchor"],
    "need_meal": []
  },
  "review_tag_to_planning_tags": {  
    "环境优雅": ["rest_friendly", "couple_friendly"],
    "适合约会": ["couple_friendly"],
    "出片漂亮": ["photo_friendly"],
    "本地特色": ["local_food"],
    ... (从 mock_dianping 真实 reviewTags top 50 反向归纳)
  },
  "review_tag_to_risk_tags": {
    "等位久": ["queue_heavy"],
    "价格偏贵": ["pricey"],
    ...
  }
}
```

新建 `agents/tag_mapping.py` loader:
```python
def load_tag_mapping() -> TagMapping  # pydantic model
def expand_user_signals(intent: ParsedIntent) -> tuple[set[str], set[str]]
    """returns (positive_planning_tags, negative_risk_tags)"""
```

修改 `agents/candidate_pool.py:score_poi`:
- 删除硬编码 INTEREST_TO_TAG
- 调 `expand_user_signals(intent)` 拿 positive/negative tag 集
- 命中 positive → 加分, 命中 negative → 减分

**测试**:
- `tests/test_tag_mapping.py`: load + expand 验证
- 现有 `tests/test_candidate_pool_v17.py` 全 PASS (改完不破)

**Acceptance**:
- INTEREST_TO_TAG 从代码消失
- 真 LLM 路径 e2e 跑通

**工程量**: 1h

---

### 1.4 (推迟到 v2.0) location_pools.json

**理由**: P0-A 集成 fetch_around 后, 候选池来源已经从"mock 静态"变"mock + 高德实时". landmark_must 场景靠 mock_dianping 的 city_essential 桶已经够用. location_pools 是质量优化, **不解决 v1.9 P0 痛点**, 推后.

---

## Stage 2: 持久用户数据 + 冷启动 (P0)

### 2.1 UserProfile schema 定义

新建 `dianping/schemas.py:UserProfile`:

```python
class UserProfile(BaseModel):
    """长期画像 — 跨 session 持久化."""
    
    user_id: str                          # cookie_key / fingerprint
    
    # 冷启动收集
    transport_preference: Literal["walk", "bike", "transit", "drive"] = "transit"
    style_preference: list[Literal["打卡", "美食", "拍照", "citywalk", "购物", "夜生活"]] = []
    safety_margin_pref: Literal["tight", "normal", "loose"] = "normal"  # 紧张/正常/从容
    anchor_radius_pref_km: float = 4.0    # walk=2 / bike=4 / transit=6
    avg_budget_per_meal: int = 100
    
    # 行为反馈累计 (Stage 4 写入)
    loved_planning_tags: dict[str, float] = {}      # tag → weight 0-1
    rejected_risk_tags: dict[str, float] = {}
    history_variant_choice: dict[str, int] = {}     # variant_name → 选了几次
    
    # 元数据
    created_at: str
    updated_at: str
    session_count: int = 0
    cold_started: bool = False            # 冷启动表单填过了
```

### 2.2 持久化策略

**方案**: 本地 JSON 文件 + cookie_key

- 后端: `data/user_profiles/<cookie_key>.json` (跟 ctx 同目录)
- 前端: localStorage 存 `cookie_key` (UUID v4 首次生成)
- 每次 SSE 请求 body 加 `cookie_key`, 路由 `api/plan/stream` 读取 + 注入 Profiler

**为什么不用数据库**: hackathon 不需要扩展性, 文件够用; 也避免引入 SQLite/Postgres.

修改:
- `api/routes.py:StreamRequest` 加 `cookie_key: Optional[str] = None`
- `agents/context.py:TripContext` 加 `user_profile: Optional[UserProfile] = None`
- 新建 `agents/user_profile.py`:
  - `load_user_profile(cookie_key) -> Optional[UserProfile]`
  - `save_user_profile(profile)`
  - `create_empty_profile(cookie_key) -> UserProfile`

### 2.3 冷启动表单

**触发**: 首次进 plan_stack.html (localStorage 没 cookie_key) → 弹 modal

**前端 modal** (`web/plan_stack.html` 加 modal HTML + JS):

字段 (用户拍板时确认):
1. **你怎么出行?** [步行/骑行/公交+地铁/打车] — 单选
2. **你喜欢什么?** [打卡/美食/拍照/citywalk/购物/夜生活] — 多选 ≤ 3
3. **赶时间紧张吗?** [我比较紧张/普通/我从容] — 单选
4. **预算每顿大约?** [< 50 / 50-150 / 150-300 / 300+] — 单选

填完 → 后端 `POST /api/profile/init` 落 JSON → localStorage 存 cookie_key.

**注入推荐**:

修改 `agents/profiler.py:Profiler.run`:
- 跑完 LLM + trip_router 后, 如果 ctx 有 user_profile:
  - intent.anchor_radius_km 没设 → 用 user_profile.anchor_radius_pref_km
  - intent.safety_margin_min 没设 + trip_mode=layover → 加 buffer 按 safety_margin_pref
  - intent.interests 合并 user_profile.style_preference (去重)

### 2.4 测试

- `tests/test_user_profile_persistence.py`:
  - create → save → load round-trip
  - load 不存在的 cookie_key 返 None
- `tests/test_profiler_with_user_profile.py`:
  - profile 有 walk preference → anchor_radius_km = 2.0
  - profile 有 "美食" + LLM intent.interests 含 "美食" → 不重复

**Acceptance**:
- 首次进站弹 modal, 填完不再弹
- 用户填 "走着去" + 输入 "万象天地附近" → anchor_radius_km = 2km (不是默认 4)
- 跨刷新 cookie_key 持久, profile 保留

**工程量**:
- schema + 持久化 1.5h
- 前端 modal 1.5h
- profiler 注入 + 测试 1h
- 联调 0.5h
- **小计 4.5h**

---

## Stage 3: 换地点换计划 (Adjuster v1, P1)

### 3.1 当前状态

`agents/adjuster.py` 是 v0 stub (CLAUDE.md 提). Critic 也是 stub.

### 3.2 用户场景

1. **换某个 stop** — "把午饭那个换成另一家"
2. **删某个 stop** — "下午那个不去了, 帮我重排"
3. **整体重排** — "再给我一版, 这版我不满意"
4. **换 variant** — "切换到 low_queue 那个"

### 3.3 设计

新建 SSE 增量更新事件 (兼容 v1.6/v1.7):

```
adjust.request    -> 客户端发起调整 (POST /api/plan/{id}/adjust)
adjust.thinking   -> 后端开始
adjust.stop_replaced  -> 单 stop 替换 (day_index + slot_name + new_poi)
adjust.day_replaced   -> 整天替换 (day_index + new_stops)
adjust.done       -> 完成
```

新建 `agents/adjuster.py:Adjuster` v1:

```python
class AdjustRequest(BaseModel):
    trip_id: str
    operation: Literal["replace_stop", "remove_stop", "regenerate_day", "switch_variant"]
    target: dict  # 视 operation 不同含 day_index / slot_name / variant 等
    user_hint: str = ""  # "想换辣一点的"

class Adjuster:
    async def replace_stop(...) -> Stop  # 从候选池 (排除 used) 选 next best
    async def remove_stop(...) -> DayPlan  # 删 + 重排时间
    async def regenerate_day(...) -> DayPlan  # 复用 plan_one_variant
    async def switch_variant(...) -> None   # ctx.draft_route = ctx.variants[variant]
```

新建 `api/routes.py:POST /api/plan/{trip_id}/adjust`:
- 加载 ctx
- 调 Adjuster 对应方法
- 流式 emit 增量事件

### 3.4 前端

`web/plan_stack.html` 加:
- 每个 stop card 右侧 "换" / "删" 按钮
- variant chip 加点击切换
- "再来一版" 按钮 触发 regenerate_day

### 3.5 测试

- `tests/test_adjuster_v1.py`:
  - replace_stop 选 candidate_pool 里下一个高分 POI
  - remove_stop 删后 stops 减 1
  - regenerate_day 跑 plan_one_variant
  - switch_variant 切 ctx.draft_route

**Acceptance**:
- 浏览器点 "换" → 单 stop 替换 (< 3s)
- 点 "删" → 时间重排
- 点 "再来一版" → 整天重排
- 点 variant chip → 主地图切换

**工程量**: 6h
- adjuster.py 实现 2h
- routes.py 路由 1h
- 前端 UI 2h
- 测试 + 联调 1h

---

## Stage 4: 行为反馈 → user_profile 写回 (P1)

### 4.1 反馈采集点

| 事件 | 写入 user_profile |
|---|---|
| trip.complete 时用户选了 variant=low_queue | `history_variant_choice["low_queue"] += 1` |
| 用户点 "换" 替换某 POI | 该 POI 的 planning_tags 进 `rejected_risk_tags` |
| 用户保留某 POI (没换) | 该 POI 的 planning_tags 进 `loved_planning_tags` |
| trip 完成 (status=ok) | session_count += 1, updated_at = now |
| 用户 "再来一版" | variant 选择本身计 1, 但当前 variant 的 tags 不算"loved" |

### 4.2 实现

修改 `agents/user_profile.py`:
```python
async def record_feedback(
    cookie_key: str,
    event_type: Literal["variant_chosen", "stop_replaced", "stop_kept", "trip_complete"],
    payload: dict,
):
    profile = load_user_profile(cookie_key) or create_empty_profile(cookie_key)
    # 按 event_type 更新对应字段, EMA 衰减 (weight = 0.9 * old + 0.1 * new)
    save_user_profile(profile)
```

修改 `api/routes.py`:
- 加 `POST /api/feedback` 接收前端事件
- trip.complete 自动调 record_feedback

修改 `agents/candidate_pool.py:score_poi`:
- 如果 intent.user_profile_loved_tags 存在 (从 ctx 注入), POI planning_tags 命中 → 加分
- intent.user_profile_rejected_tags 命中 risk_tags → 扣分

### 4.3 测试

- `tests/test_feedback_loop.py`:
  - 记录 stop_replaced → loved_planning_tags 该 tag 权重下降
  - 跨 2 个 session, 第二次 score_poi 反映第一次反馈
- E2E:
  - 1) 跑 trip 1, 换掉某 photo_friendly POI
  - 2) 跑 trip 2, 同请求, photo_friendly 分变低 → 推荐改变

**Acceptance**:
- 第一次会话: photo_friendly POI 推到前面
- 用户换掉它 + 触发 feedback
- 第二次会话 (同 cookie_key 同请求): photo_friendly POI 不再优先

**工程量**: 3h
- record_feedback + 持久化 1h
- score_poi 注入 user_profile 1h
- 前端事件触发 + 测试 1h

---

## 2. 依赖关系图

```
Stage 1 (数据 + 推荐)
   ├─ P0-A fetch_around 集成 -----┐
   ├─ P0-B 脏点修复               ├─→ Stage 2 用得到 (推荐质量好的 POI)
   └─ P1-C tag_mapping ----------┘
                                  ↓
Stage 2 (持久 + 冷启动)
   ├─ UserProfile schema
   ├─ 持久化
   └─ 冷启动表单 -----------------┐
                                  ↓
Stage 3 (Adjuster)               依赖 ctx.user_profile (score 注入)
   ├─ adjuster.py
   ├─ /adjust 路由
   └─ 前端换/删/重排 -------------┐
                                  ↓
Stage 4 (反馈闭环)
   ├─ record_feedback
   └─ score_poi 注入 user_profile
```

**关键决策**: Stage 1 必须先做完 (否则 Stage 3 换 stop 时候选池仍稀疏), Stage 2 是 Stage 4 的前提.

---

## 3. 关键不变量 (v1.9 各阶段都要守)

- ❗ 测试基线 223 PASS + 1 known flaky, 不能破
- ❗ ParsedIntent 老 3 必填字段 (city/days/traveler_type) 不动
- ❗ v1.6 多日 SSE 路径不动
- ❗ v1.7 instant 路径不动 (新 trip_mode 走分流, 不影响 SSE 事件)
- ❗ v1.8 anchor 路径不动 (Stage 1 是补 pool, 不改路由)
- ❗ TripContext.save/load 接口稳定 (Stage 2 加 user_profile 是 optional)
- ❗ 旧 SSE 事件名全保留 (Stage 3 新事件 adjust.* 是新增, 不替换)
- ❗ score_poi 不依赖 reviewCount/avgprice
- ❗ "终南山古楼观钟楼" demote 不能回弹

---

## 4. 文件清单

### 新增 (Stage 1)
- `scripts/audit_enriched.py`
- `scripts/refix_enriched.py`
- `data/tag_mapping.json`
- `agents/tag_mapping.py`
- `tests/test_enriched_audit.py`
- `tests/test_tag_mapping.py`
- `tests/test_planner_instant_v19_amap_integration.py`

### 新增 (Stage 2)
- `agents/user_profile.py`
- `data/user_profiles/.gitkeep`
- `web/plan_stack.html` 加 modal (in-file)
- `tests/test_user_profile_persistence.py`
- `tests/test_profiler_with_user_profile.py`

### 新增 (Stage 3)
- `api/routes.py` 加 `/adjust` 路由 (in-file)
- `tests/test_adjuster_v1.py`

### 新增 (Stage 4)
- `tests/test_feedback_loop.py`

### 修改
- `agents/planner_instant.py` (Stage 1: 集成 fetch_around)
- `agents/candidate_pool.py` (Stage 1: tag_mapping + Stage 4: user_profile 注入)
- `agents/profiler.py` (Stage 2: profile 注入)
- `agents/adjuster.py` (Stage 3: 从 stub 升级)
- `agents/context.py` (Stage 2: user_profile 字段)
- `api/routes.py` (Stage 2: cookie_key 处理 + Stage 3: /adjust)
- `web/plan_stack.html` (Stage 2: modal + Stage 3: 换/删按钮 + Stage 4: 反馈事件)
- `dianping/schemas.py` (Stage 2: UserProfile + 新 Adjuster events)

---

## 5. 推荐执行顺序 (resume 后直接对照)

```
Day 1 (8h):
  09:00-11:00  Stage 1.1 集成 fetch_around (2h)
               浏览器再过 Scene A/B 看 stops 数量
  11:00-12:30  Stage 1.2 enriched 脏点修复 (1.5h)
  14:00-15:00  Stage 1.3 tag_mapping 抽出 (1h)
  15:00-19:30  Stage 2.1-2.3 user_profile + 冷启动 (4.5h)

Day 2 (6h):
  09:00-15:00  Stage 3 Adjuster v1 全部 (6h)

Day 3 (3h):
  09:00-12:00  Stage 4 反馈闭环 (3h)

Day 4+: Hackathon polish (demo 视频 / 前端动效 / 真 LLM e2e 调优)
```

---

## 6. resume 后第一步

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
git log --oneline -3                     # 确认在 7cb5acc 之后
PYTHONPATH=. venv/bin/pytest tests/ -q --ignore=tests/test_user_profile_cleaning.py
# 预期: 223 passed + 1 known flaky
cat docs/superpowers/specs/2026-05-14-v19-data-recommend-profile-adjust.md
# 然后从 Stage 1.1 开始, 走 superpowers:writing-plans 出实施计划
```

---

## 7. 不在 v1.9 范围 (推到 v2.0+)

- ❌ location_pools.json (Stage 1 P0-A 集成 fetch_around 后池子够, 这个推后)
- ❌ city_profiles.json (P3, demo 看不出差别)
- ❌ route_slot_rules.json 抽出 (P3, _SLOT_DEFS 在代码里也能跑)
- ❌ 几何算法 solve_cycle / solve_layover (v1.8 spec §4, candidate_pool distance_penalty 已能让 LLM 选近的)
- ❌ Critic ReAct 真实化 (v2 范围)
- ❌ 真接美团/大众点评接口 (需资质)
- ❌ 跨城多日 (老多日逻辑不支持)
- ❌ 协同过滤/向量推荐 (Stage 4 用 EMA 反馈, 不上 ML)
