# v1.9 Stage 3 — Adjuster v1 Design

**Created**: 2026-05-14
**Status**: Approved (pending user review)
**Parent spec**: `2026-05-14-v19-data-recommend-profile-adjust.md` (Stage 3 节)
**Scope**: 把 `agents/adjuster.py` 从 v0 stub 升级到 v1, 接入 SSE 增量事件, 联动 v1.9.1 Phase B 已落地的 cache, 前端加换/删/再来一版按钮

---

## 1. 用户场景

| # | 场景 | 触发 | 体验 |
|---|---|---|---|
| 1 | 换某个 stop | stop card 右侧 "换" | 同 slot 替换, 时间不动, < 3s |
| 2 | 删某个 stop | stop card 右侧 "删" | 删 + transit 自动重排 |
| 3 | 整天重排 | day 顶部 "再来一版" | 整天 stops 换一组, 排除旧 oid |
| 4 | 切 variant | variant chip 点击 | 主地图切换到另一个变体 |

---

## 2. 架构

### 2.1 ctx 持久化 (已有, 不动)
`agents/context.py::TripContext.save/load` 已实现, 写 `data/trips/{trip_id}.json`. `POST /api/plan/{trip_id}/adjust` 入口:

```
POST /api/plan/{trip_id}/adjust
  ↓ TripContext.load(trip_id)
  ↓ Adjuster.<operation>(ctx, ...)
  ↓ ctx.save()
  ↓ SSE 流: adjust.thinking → adjust.<op>_done → adjust.done
```

### 2.2 4 个 operation

```python
class AdjustRequest(BaseModel):
    operation: Literal["replace_stop", "remove_stop", "regenerate_day", "switch_variant"]
    day_index: int = 0
    slot_name: str = ""        # for replace/remove
    variant: str = ""          # for switch_variant
    user_hint: str = ""        # 自由文本 "想换辣一点的"

class Adjuster:
    async def replace_stop(self, ctx, day_index, slot_name, user_hint) -> Stop: ...
    async def remove_stop(self, ctx, day_index, slot_name) -> DayPlan: ...
    async def regenerate_day(self, ctx, day_index, user_hint) -> DayPlan: ...
    async def switch_variant(self, ctx, variant) -> None: ...
```

### 2.3 Cache 联动 (v1.9.1 Phase B 复用, 评委亮点)

`agents/adjuster.py::_pick_replacement_with_cache(ctx, day_index, slot_name)`:

1. 从 `data/poi_cache.json` 读所有 entry
2. 过滤: `city == ctx.intent.city` AND `enriched.city_zone == target_zone` AND `enriched.poi_role == target_role`
   - target_zone: 当前 stop 有 enriched → 用 stop.enriched.city_zone; 否则用 ctx.draft_route 当天的 anchor_district 兜底
   - target_role: 当前 stop 有 enriched → 用 stop.enriched.poi_role; 否则用 `_infer_role_from_categories(stop.poi.categories)` 兜底
3. 排除: 当天 used openshopid / disliked (ctx.user_marked.disliked, 后续 Stage 4) / 同 cache_key 的当前 stop
4. 按 seen_count desc + manual_priority desc 排序, 取 top 1
5. miss → 落 candidate_pool 同 bucket 次高分

**LLM 调用**: replace_stop 在 cache + pool 给出 1-3 个候选后, 调一次轻量 LLM (qwen-turbo) 带 user_hint 做最终决策. 没 user_hint 时跳过 LLM, 直接取 top 1.

### 2.4 regenerate_day 排除

`plan_one_variant` 加 `excluded_oids: set[str] = set()` 参数 (默认空 → 兼容老调用). 在 `flatten_candidate_pool` 之后做一次过滤. 通过这种方式避免新一天又出旧 POI.

### 2.5 switch_variant

后端最轻量: `ctx.draft_route = ctx.variants[variant]` + `ctx.save()`, emit `adjust.variant_switched`. 前端拿到 ack 后切主地图显示 (variants 数据前端已经有, 不重传).

---

## 3. SSE 事件

| 事件名 | payload | 用途 |
|---|---|---|
| `adjust.thinking` | `{operation, day_index}` | 前端显示 spinner |
| `adjust.stop_replaced` | `{day_index, slot_name, old_oid, new_stop: {...}, source: "cache"\|"pool"}` | 单 stop 替换, source 显示徽章 |
| `adjust.stop_removed` | `{day_index, removed_oid, new_day_plan: {stops, transit_segments}}` | 删后整天数据 |
| `adjust.day_replaced` | `{day_index, new_day_plan}` | 整天替换 |
| `adjust.variant_switched` | `{variant}` | ack, 前端切显示 |
| `adjust.done` | `{trip_id}` | 流结束 |

老 `trip.started / day_done / instant_variants_*` 等 SSE 事件全不动.

---

## 4. 文件清单

### 新增 / 重写
| 文件 | 动作 | 行数估计 |
|---|---|---|
| `agents/adjuster.py` | 重写 v0 stub → v1 | ~250 行 |
| `api/routes.py` | 加 `POST /api/plan/{trip_id}/adjust` SSE endpoint | +100 行 |
| `agents/prompts/adjuster.md` | LLM prompt 重写 (替换候选选择) | ~40 行 |
| `tests/test_adjuster_v1.py` | 新建 | ~250 行 |
| `web/plan_stack.html` | 加换/删/再来一版按钮 + JS hookup | +150 行 |

### 改动 (小修)
| 文件 | 动作 |
|---|---|
| `agents/planner_instant.py` | `plan_one_variant` 加 `excluded_oids` 参数 (default empty) |
| `dianping/schemas.py` | 加 `AdjustRequest` pydantic |

---

## 5. 测试

| Test | 验证 |
|---|---|
| `test_replace_stop_hits_cache` | cache 有同 zone+role → 不调 LLM, source="cache" |
| `test_replace_stop_falls_to_pool` | cache 空 → 落 candidate_pool, source="pool" |
| `test_replace_stop_excludes_used_and_self` | 当天 used + 同 oid 不被选 |
| `test_remove_stop_reduces_and_reflows` | stops -1 + transit 重算 |
| `test_regenerate_day_excludes_old_oids` | 新一天 stops 跟旧不重叠 |
| `test_switch_variant_updates_draft_route` | ctx.draft_route 切到目标 variant |
| `test_post_adjust_emits_correct_sse` (4 个) | 各 operation 发对应事件 |

---

## 6. 不变量 (必须保留)

- ❗ 老 SSE 事件名全保留 (`trip.started` / `day_done` / `instant_variants_*` / `chat: must_visit_warning` 等不动)
- ❗ `ctx.variants` schema 不变 (3 个 variant 仍是 main / low_queue / interest_first)
- ❗ `Adjuster.run(ctx, feedback)` 老 contract 删掉 (老的 stub method, 无调用方; v1 用具名 method)
- ❗ baseline 295 passed + 1 flaky 不能再增加 fail
- ❗ LLM 调用边界: replace_stop 仅在 user_hint 非空时调一次 qwen-turbo 二选; regenerate_day 复用 plan_one_variant 链路 (本来就调 LLM, 不算新增); remove_stop / switch_variant 零 LLM
- ❗ cache 联动只读 `data/poi_cache.json`, 不写 (写是 Stage 4 的事)

---

## 7. 不在 Stage 3 范围

- ❌ User profile EMA 更新 (Stage 4)
- ❌ disliked 写回 user_marked (Stage 4)
- ❌ Adjuster 的 critic 链路 (v2)
- ❌ 多 stop 同时换 (v2)
- ❌ "再给我一版" 但保留某个 stop (v2)

---

## 8. 工程量

| 阶段 | 时间 |
|---|---|
| adjuster.py 4 method 实现 | 2h |
| routes.py SSE endpoint | 1h |
| 单测 (10+ 个) | 1.5h |
| 前端 JS hookup + 按钮 | 1.5h |
| E2E 浏览器联调 | 0.5h |
| **合计** | **~6.5h** |

---

## 9. Acceptance

- 浏览器 (Scene A 万象天地 anchor mode):
  - 点 "换" 任一 stop → 同 city_zone 替换, 显示 "来自 cache" 徽章 (cache 命中时)
  - 点 "删" → stop 消失, 时间重排
  - 点 day 顶部 "再来一版" → 整天换一组, 旧 POI 不重现
  - 点 variant chip → 主地图切换
- curl test: 4 个 op 都能 POST 出对应 SSE 事件流
- 测试: baseline 不破 + 新增 10+ 个 adjuster 测试全过
