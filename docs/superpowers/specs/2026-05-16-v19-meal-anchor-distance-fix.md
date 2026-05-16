# v1.9 Bug Fix: meal stop 强制 day-anchor 半径过滤

**Date**: 2026-05-16
**Status**: design → implement
**Bug**: 西安 1天朋友团 trip, 3 站排成 [大雁塔(南) → 长安大牌档·建章宫宴 凤城九路店(北 14.5km) → 长安十二时辰(南)], 跨城吃饭

## 根因

`candidate_pool.py:230-242` 的距离过滤只在 `intent.anchor_lng is not None` 时生效:

```python
if not is_must and intent.anchor_lng is not None and intent.anchor_lat is not None:
    d = _haversine_km(...)
    if d > (intent.anchor_radius_km or 3.0) * 2:
        continue
```

但用户文本"西安 1天朋友团"没指定起点 → `intent.anchor_lng=None` → 距离过滤跳过.

后续 `plan_one_variant` (line 286-298) 在 anchor 缺失时取 `flat_pois[0]` 作 day-anchor (这里是"大雁塔"). 但这个 day-anchor 没有再被用于过滤 meal 桶, LLM 看到 30 个 POI (含远店) 凭品牌+评分选 — 选了"长安大牌档·建章宫宴"凤城九路店 (距大雁塔 14.5km).

## 修复

在 `plan_one_variant` 内, anchor 选定后, 对 flat_pois 中 **meal role POI** 强制按 day-anchor 距离硬过滤 (`MEAL_ANCHOR_RADIUS_KM = 5.0`). 其他桶不动 (city_essential / persona_preferred / connector 跨距离合理).

```python
anchor = (anchor_name, anchor_lat, anchor_lng)

# v1.9 修复: meal POI 强制 day-anchor 5km 内
flat_pois = _filter_meal_by_anchor_distance(
    flat_pois, anchor_lat, anchor_lng, MEAL_ANCHOR_RADIUS_KM
)
```

Helper:

```python
def _filter_meal_by_anchor_distance(
    pois: list[POI], anchor_lat: float, anchor_lng: float, radius_km: float
) -> list[POI]:
    """删除 meal-role POI 中距 (anchor_lat, anchor_lng) > radius_km 的.
    非 meal POI 不动. anchor 坐标为 0 (无 anchor) 时不过滤.
    """
```

## 不变量

- ❗ 老 anchor_explore 路径 (planner_instant.py:207-280) 已有半径过滤, 不受影响
- ❗ 无 day-anchor (flat_pois 空, anchor_lat=anchor_lng=0.0) 时, helper 不过滤
- ❗ 非 meal POI (city_essential / persona / connector) 完全不过滤
- ❗ build_candidate_pool 内部不动 — 修复在 plan_one_variant 层
- ❗ 测试 baseline 333 passed 不破

## 测试

`tests/test_meal_anchor_filter.py`:

1. `test_far_meal_removed`: anchor (34.218, 108.964) + meal POI 距离 14.5km → 被删
2. `test_near_meal_kept`: anchor 同上 + meal POI 距 2km → 保留
3. `test_non_meal_kept_regardless_of_distance`: city_essential POI 距 20km → 保留 (不过滤)
4. `test_no_anchor_skips_filter`: anchor=(0, 0) → 不过滤, 全保留
5. `test_radius_boundary`: 距离恰好等于 radius → 保留 (`<= radius_km`)

E2E 真测: 重新跑西安 1天朋友团, 验所有 meal-role stop 距 day_plan.anchor_district POI 距离 <= 5km.

## 阈值选择 `MEAL_ANCHOR_RADIUS_KM = 5.0`

- 西安市三环内尺度 ~10-15km, 5km 半径能覆盖大唐不夜城/雁塔/钟楼/小寨等核心区
- 大于市内步行/打车 1 站 (~3km), 小于跨城 (~10km+)
- 用户没指定起点时, day-anchor 是 city_essential 顶部景点, 它周边 5km 应有充足 meal 选项

## 关键决策: 严格模式 (无 fallback)

实测西安 mock 数据所有 98 个食店都在城北 12-15km, 大雁塔 5km 内 0 个 meal POI.
最初版本加了 fallback "5km 不够就取最近 N 个", 但 e2e 测试显示这会把建章宫宴
(14.68km) 重新拉回, 跟用户原始反馈 "跨城不好" 相违背.

**最终决策**: 严格模式. 5km 没有就**砍掉 meal slot**, LLM 会 graceful 跳过.
跟用户偏好对齐: 删 stop > 跨城.

副作用: 数据稀疏 city 下午饭会被砍 (西安实测). 这是数据底座的问题, 单独修复.

`_is_meal_poi` 用 OR 逻辑 (enriched.poi_role == 'meal' OR categories 含 '美食'),
防止数据底座错标 (建章宫宴在西安数据被标成 city_essential 但 categories=['美食']).

## 工程量

- spec: 15min
- helper + plan_one_variant 集成: 20min
- 单测 5 个: 30min
- 回归 + e2e: 25min
- commit + push: 10min
- 总 ~100min
