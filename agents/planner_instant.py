"""v1.7 即时出发: 单日/半日 路线规划入口.

跟旧 Planner.run (多日 anchor × category × cluster) 并行的轻量路径:
  1. 直接从 data/mock_dianping/<city>.json 加载 POI (不走 dianping HTTP client)
  2. attach EnrichedLabel
  3. build_candidate_pool(variant) → 4 桶
  4. 复用 v1.6 Planner.compose_one_day (LLM 流式 + transit) 出单天 plan
  5. 三 variant (main / low_queue / interest_first) 各跑一遍

老路径不动. 进入条件: ctx.intent.time_window in 半日/一日.
"""

from __future__ import annotations

import json
from datetime import time
from pathlib import Path
from typing import Awaitable, Callable, Optional

from pydantic import BaseModel

from agents.candidate_pool import Variant, build_candidate_pool
from agents.poi_decision_signals import prefer_pois_by_decision_signals
from agents.tools import DaySlotSpec, DayTemplate
from dianping.schemas import (
    DayPlan,
    EnrichedLabel,
    ParsedIntent,
    PersonaLabels,
    POI,
)

# v1.7 即时出发 slot 模板. 跟旧 _SLOT_DEFS 数值对齐, 但按 time_window 选子集.
_INSTANT_SLOT_NAMES: dict[Optional[str], list[str]] = {
    "半日_上午": ["上午景点", "午饭"],
    "半日_下午": ["下午", "下午茶", "晚饭"],
    "半日_夜间": ["晚饭", "夜场"],
    "一日": ["上午景点", "午饭", "下午", "晚饭"],
    # 多日 / None: 不走这里 (routes.py 应把多日 fallback 给旧 Planner)
}

_SLOT_DEFS: dict[str, dict] = {
    "上午景点": dict(
        start=time(9, 0),
        end=time(12, 0),
        # 兼容大众点评体系（景点/历史文化）和高德体系（风景名胜/公园广场/科教文化服务）
        category_pool=[
            "景点",
            "历史文化",
            "自然风光",
            "风景名胜",
            "风景名胜相关",
            "公园广场",
            "公园",
            "科教文化服务",
            "科教文化场所",
            "博物馆",
            "纪念馆",
            "休闲娱乐",
            "亲子",
        ],
        is_meal=False,
        min_stay_minutes=60,
        max_stay_minutes=180,
    ),
    "午饭": dict(
        start=time(12, 0),
        end=time(13, 30),
        category_pool=[
            "美食",
            "餐饮服务",
            "中餐厅",
            "西餐厅",
            "小吃快餐",
            "火锅",
            "日本料理",
            "烧烤",
            "面包甜点",
        ],
        is_meal=True,
        min_stay_minutes=60,
        max_stay_minutes=90,
    ),
    "下午": dict(
        start=time(13, 30),
        end=time(17, 0),
        category_pool=[
            "景点",
            "历史文化",
            "自然风光",
            "风景名胜",
            "风景名胜相关",
            "公园广场",
            "公园",
            "科教文化服务",
            "博物馆",
            "购物",
            "休闲娱乐",
            "商场",
            "购物服务",
        ],
        is_meal=False,
        min_stay_minutes=90,
        max_stay_minutes=180,
    ),
    "下午茶": dict(
        start=time(15, 30),
        end=time(16, 30),
        category_pool=[
            "美食",
            "餐饮服务",
            "咖啡厅",
            "冷饮店",
            "甜品",
            "下午茶",
        ],
        is_meal=False,
        optional=True,
        min_stay_minutes=30,
        max_stay_minutes=60,
    ),
    "晚饭": dict(
        start=time(18, 0),
        end=time(20, 0),
        category_pool=[
            "美食",
            "餐饮服务",
            "中餐厅",
            "西餐厅",
            "小吃快餐",
            "火锅",
            "烧烤",
            "海鲜",
            "夜宵",
        ],
        is_meal=True,
        min_stay_minutes=60,
        max_stay_minutes=120,
    ),
    "夜场": dict(
        start=time(20, 0),
        end=time(22, 0),
        category_pool=[
            "休闲娱乐",
            "娱乐场所",
            "KTV",
            "酒吧",
            "影剧院",
            "风景名胜",
            "公园广场",
        ],
        is_meal=False,
        optional=True,
        min_stay_minutes=60,
        max_stay_minutes=120,
    ),
}


def is_instant_window(intent: ParsedIntent) -> bool:
    """ctx.intent 是否触发 v1.7 即时出发路径."""
    tw = intent.time_window
    return tw in _INSTANT_SLOT_NAMES


def make_instant_template(
    time_window: Optional[str], required_slots=None
) -> DayTemplate:
    """Build a single-day template fitting the time_window.

    Fallback (unknown / None): 全天 4 slot 跟旧 'pace=适中' 一致.
    v1.9.2: required_slots 里用户明确要求的 slot (如 "下午茶") 若不在模板里则按时间插入.
    """
    names = list(
        _INSTANT_SLOT_NAMES.get(time_window) or ["上午景点", "午饭", "下午", "晚饭"]
    )
    if required_slots:
        for rs in required_slots:
            sn = rs.slot_name
            if sn in _SLOT_DEFS and sn not in names:
                new_start = _SLOT_DEFS[sn]["start"]
                idx = next(
                    (
                        i
                        for i, n in enumerate(names)
                        if _SLOT_DEFS.get(n, {}).get("start", time(0, 0)) > new_start
                    ),
                    len(names),
                )
                names.insert(idx, sn)
    slots = [DaySlotSpec(name=n, **_SLOT_DEFS[n]) for n in names]
    return DayTemplate(day_index=0, slots=slots)


def load_city_pois_from_mock(city: str) -> list[POI]:
    """Load POIs from data/mock_dianping/<city>.json + attach enriched + persona labels.

    Used when v1.7 instant 路径要绕开 HTTP client. Fall back to empty list if file missing.
    """
    path = Path(f"data/mock_dianping/{city}.json")
    if not path.exists():
        return []
    enriched_path = Path("data/poi_enriched_labels.json")
    enriched_map: dict[str, dict] = {}
    if enriched_path.exists():
        enriched_all = json.loads(enriched_path.read_text(encoding="utf-8"))
        enriched_map = enriched_all.get(city, {})
    labels_path = Path("data/poi_labels.json")
    labels_map: dict[str, dict] = {}
    if labels_path.exists():
        labels_all = json.loads(labels_path.read_text(encoding="utf-8"))
        labels_map = labels_all.get(city, {})

    raw_list = json.loads(path.read_text(encoding="utf-8"))
    pois: list[POI] = []
    for raw in raw_list:
        try:
            poi = POI(**raw)
        except Exception:
            continue
        # attach enriched
        en = enriched_map.get(poi.openshopid)
        if en:
            poi.enriched = EnrichedLabel(**en)
        # attach legacy persona_labels (兼容 route_by_persona 老路径)
        pl = labels_map.get(poi.openshopid)
        if pl:
            poi.persona_labels = PersonaLabels(**pl)
        pois.append(poi)
    return pois


# v1.9 meal anchor 距离过滤: 防止跨城吃饭 (用户没指定 anchor 时, day-anchor 取
# flat_pois[0], 但 build_candidate_pool 的距离过滤要求 intent.anchor_lng 不为 None
# 才生效, 漏过远 meal POI. 这个 helper 在 plan_one_variant 内 anchor 选定后, 对
# meal-role POI 强制半径过滤, 非 meal POI 不动)
MEAL_ANCHOR_RADIUS_KM = 5.0


def _is_meal_poi(poi: POI) -> bool:
    """meal 判定: 任一信号命中即视为 meal.

    用 OR 逻辑而非"enriched 优先" — 数据底座中部分餐厅被错标成 city_essential
    (例如建章宫宴), 但 categories='美食' 是可靠的硬证据.
    """
    if poi.enriched is not None and poi.enriched.poi_role == "meal":
        return True
    if poi.categories and any("美食" in c for c in poi.categories):
        return True
    return False


def _filter_meal_by_anchor_distance(
    pois: list[POI],
    anchor_lat: float,
    anchor_lng: float,
    radius_km: float = MEAL_ANCHOR_RADIUS_KM,
) -> list[POI]:
    """删除 meal POI 中距 anchor > radius_km 的. 严格过滤, 无兜底.

    设计选择: 数据稀疏 (例: 西安 mock 食店全在城北) 时 meal 候选会被全部过滤,
    LLM 会跳过午饭 slot — 这跟用户的反馈 "跨城吃饭不好" 一致 (删 stop 比远跑好).

    非 meal POI 不动. anchor 坐标为 0 (无效) 时直接返回原列表.
    """
    if not anchor_lat or not anchor_lng:
        return pois
    from agents.anchor import _haversine_km

    kept: list[POI] = []
    for p in pois:
        if not _is_meal_poi(p):
            kept.append(p)
            continue
        # v1.10: text_search 命中的 meal POI (must_consider) 是用户明示, 豁免距离过滤
        if p.enriched and p.enriched.must_consider:
            kept.append(p)
            continue
        d = _haversine_km((anchor_lng, anchor_lat), (p.longitude, p.latitude))
        if d <= radius_km:
            kept.append(p)
    return kept


# v1.9.3 required_slots → 高德 typecode 精准搜索
_CATEGORY_TO_AMAP_TYPE: dict[str, str] = {
    "咖啡": "050700",
    "甜品": "050700",
    "奶茶": "050301",
    "茶饮": "050301",
    "西餐": "050200",
    "西式": "050200",
    "牛排": "050200",
    "披萨": "050200",
    "火锅": "050100",
    "川菜": "050100",
    "素食": "050100",
    "蔬食": "050100",
}


def _slot_typecodes(required_slots) -> str | None:
    """把 required_slots 里的 categories 映射到高德 typecode 字符串, 无映射返 None."""
    codes: set[str] = set()
    for rs in required_slots or []:
        for cat in rs.categories:
            tc = _CATEGORY_TO_AMAP_TYPE.get(cat)
            if tc:
                codes.add(tc)
    return "|".join(sorted(codes)) if codes else None


def _point_to_segment_dist_km(
    p: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    """Approximate distance (km) from point p to line segment a→b (lng/lat pairs)."""
    from agents.anchor import _haversine_km as _hv

    ax, ay = a
    bx, by = b
    px, py = p
    ab2 = (bx - ax) ** 2 + (by - ay) ** 2
    if ab2 < 1e-12:
        return _hv(p, a)
    t = max(0.0, min(1.0, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / ab2))
    proj = (ax + t * (bx - ax), ay + t * (by - ay))
    return _hv(p, proj)


def _corridor_filter(
    pois: list[POI],
    waypoints: list,  # list[WaypointResolution]
    width_km: float = 0.5,
) -> list[POI]:
    """Keep POIs within width_km of any segment of the waypoint path."""
    if len(waypoints) < 2:
        return pois
    segments = [
        (
            (waypoints[i].lng, waypoints[i].lat),
            (waypoints[i + 1].lng, waypoints[i + 1].lat),
        )
        for i in range(len(waypoints) - 1)
    ]
    result = []
    for p in pois:
        pt = (p.longitude, p.latitude)
        if any(_point_to_segment_dist_km(pt, a, b) <= width_km for a, b in segments):
            result.append(p)
    return result


def _reorder_for_variant(pois: list[POI], variant: Variant) -> list[POI]:
    """无 enriched 时按 variant 重排候选，让三个 variant 收到不同的 top-N.

    - main: 不变（star 高的在前）
    - low_queue: 把 star≥4.8 的热门 POI 沉到后半，突出评分略低但独特的
    - interest_first: 把 categories 包含"文化/历史/艺术"的提前
    """
    if variant == "main":
        return pois

    if variant == "low_queue":
        # 热门高星沉底，给冷门让位
        hot = [p for p in pois if (p.star or 0) >= 4.8]
        rest = [p for p in pois if (p.star or 0) < 4.8]
        return rest + hot

    if variant == "interest_first":
        CULTURE_KW = {"历史", "文化", "艺术", "博物", "古迹", "遗址", "寺", "庙", "故"}

        def _is_culture(p: POI) -> bool:
            cats = " ".join(p.categories or []) + (p.name or "")
            return any(kw in cats for kw in CULTURE_KW)

        culture = [p for p in pois if _is_culture(p)]
        other = [p for p in pois if not _is_culture(p)]
        return culture + other

    return pois


def flatten_candidate_pool(
    intent: ParsedIntent, variant: Variant, pois: list[POI]
) -> list[POI]:
    """Build candidate pool then flatten to a single list for compose_one_day.

    Order: city_essential → persona_preferred → connector → meal.
    Score-sorted within each bucket. compose_one_day will let LLM pick stops
    from this flat list keyed by openshopid.

    Cap total at 30 (compose_one_day prompt cap).
    """
    pool = build_candidate_pool(pois=pois, intent=intent, variant=variant)
    flat: list[POI] = []
    seen: set[str] = set()
    for bucket in (
        pool.city_essential,
        pool.persona_preferred,
        pool.connector,
        pool.meal,
    ):
        for p in bucket:
            if p.openshopid in seen:
                continue
            flat.append(p)
            seen.add(p.openshopid)
    return flat[:30]


class VariantPlan(BaseModel):
    """One variant result. transit_segments shape mirrors compose_one_day output."""

    variant: Variant
    day_plan: DayPlan
    transit_segments: list[dict]
    error: Optional[str] = None  # if LLM failed, fallback path used


async def plan_one_variant(
    *,
    intent: ParsedIntent,
    variant: Variant,
    planner,  # Planner instance with compose_one_day
    amap,
    pois: list[POI],
    on_partial: Optional[Callable[[int, list[str]], Awaitable[None]]] = None,
    excluded_oids: Optional[set[str]] = None,
    pre_fetched_pois: Optional[
        list[POI]
    ] = None,  # v1.9.4: 共享 Amap fetch 结果，跳过内部重复抓取
) -> VariantPlan:
    """Run one variant end-to-end: pool → compose_one_day → DayPlan + segments.

    On compose_one_day failure (PlannerLLMError) → fallback synth using top-N pool POIs.

    v1.9 Stage 3: `excluded_oids` 用于 regenerate_day — flatten 后过滤掉这批 POI,
    避免新一天又出现旧 stops 的 POI. 默认 None / 空 = 兼容老调用.
    """
    from agents.planner import PlannerLLMError, _synthesize_fallback_route
    from agents.transits import compute_day_transits as _compute_day_transits

    # v1.9.4: 若调用方已预取 Amap POI（并行 variant 场景），直接用，跳过内部重复抓取
    if pre_fetched_pois is not None:
        pois = pre_fetched_pois
    # v1.9 / v1.9.1: anchor 模式下拉高德周边 POI → cache 层 → 合进本地池 (扩 pool)
    elif (
        intent.anchor_lng is not None
        and intent.anchor_lat is not None
        and intent.trip_mode in ("anchor_explore", "layover_eat", "layover_explore")
    ):
        from agents import anchor as _anchor_mod
        from agents.anchor import _haversine_km, _norm_name

        types = (
            "050000"
            if intent.trip_mode == "layover_eat"
            else "050000|060000|080000|110000"
        )
        radius_m = int((intent.anchor_radius_km or 3.0) * 1000)
        try:
            around = await _anchor_mod.fetch_around(
                lng=intent.anchor_lng,
                lat=intent.anchor_lat,
                radius_m=radius_m,
                types=types,
                limit=50,
            )
        except Exception:
            around = []
        if around:
            # 直接用 typecode→categories 转换，跳过 LLM enrich (避免 N 次 LLM 拖慢冷启动)
            from agents.poi_cache import _around_to_poi

            amap_enriched = [_around_to_poi(ap, intent.city, None) for ap in around]

            # 半径过滤 + 与 local_pois 去重 (替代 merge_with_local_pool 老路径)
            anchor_pt = (intent.anchor_lng, intent.anchor_lat)
            radius_km = radius_m / 1000.0
            kept_local: list[POI] = []
            seen_keys: set[tuple[str, int, int]] = set()
            for lp in pois:
                if _haversine_km(anchor_pt, (lp.longitude, lp.latitude)) > radius_km:
                    continue
                k = (
                    _norm_name(lp.name),
                    round(lp.latitude, 3),
                    round(lp.longitude, 3),
                )
                if k in seen_keys:
                    continue
                seen_keys.add(k)
                kept_local.append(lp)
            kept_amap: list[POI] = []
            for ap in amap_enriched:
                if _haversine_km(anchor_pt, (ap.longitude, ap.latitude)) > radius_km:
                    continue
                k = (
                    _norm_name(ap.name),
                    round(ap.latitude, 3),
                    round(ap.longitude, 3),
                )
                if k in seen_keys:
                    continue
                seen_keys.add(k)
                kept_amap.append(ap)
            kept_local.sort(
                key=lambda p: (
                    -(p.enriched.manual_priority if p.enriched else 0),
                    _haversine_km(anchor_pt, (p.longitude, p.latitude)),
                )
            )
            kept_amap.sort(
                key=lambda p: _haversine_km(anchor_pt, (p.longitude, p.latitude))
            )
            pois = kept_local + kept_amap

    # v1.9.3 Multi-waypoint + category-targeted fetch（仅在没有预取结果时执行）
    extra_wps = getattr(intent, "geocoded_waypoints", [])
    if pre_fetched_pois is None and len(extra_wps) >= 2:
        from agents import anchor as _anchor_mod
        from agents.poi_cache import _around_to_poi

        existing_oids = {p.openshopid for p in pois}
        for wp in extra_wps[1:]:  # skip first (already fetched as primary anchor)
            try:
                extra_around = await _anchor_mod.fetch_around(
                    lng=wp.lng,
                    lat=wp.lat,
                    radius_m=int((intent.anchor_radius_km or 2.0) * 1000),
                    types=_anchor_mod.DEFAULT_AROUND_TYPES,
                    limit=20,  # 限制数量，用 categories 兜底不 enrich
                )
            except Exception:
                extra_around = []
            for ap in extra_around:
                p = _around_to_poi(
                    ap, intent.city, None
                )  # enriched=None, typecode→categories 兜底
                if p.openshopid not in existing_oids:
                    pois.append(p)
                    existing_oids.add(p.openshopid)
        # 不做走廊过滤，候选池保持丰富，waypoint 通过 must_consider 置顶

    # v1.9.3 required_slots category-targeted 搜索（仅在没有预取结果时执行）
    _target_tc = _slot_typecodes(getattr(intent, "required_slots", []))
    if (
        pre_fetched_pois is None
        and _target_tc
        and intent.anchor_lng is not None
        and intent.anchor_lat is not None
    ):
        from agents import anchor as _anchor_mod
        from agents.poi_cache import _around_to_poi

        try:
            _cat_around = await _anchor_mod.fetch_around(
                lng=intent.anchor_lng,
                lat=intent.anchor_lat,
                radius_m=int((intent.anchor_radius_km or 3.0) * 1000),
                types=_target_tc,
                limit=15,
            )
        except Exception:
            _cat_around = []
        existing_oids = {p.openshopid for p in pois}
        for ap in _cat_around:
            p = _around_to_poi(ap, intent.city, None)
            if p.openshopid not in existing_oids:
                pois.append(p)
                existing_oids.add(p.openshopid)

    # v1.10 keyword text_search: must_visit + required_slots[].categories 进 pool.
    # 关键词搜补足 fetch_around 的 typecode 兜不住的场景 (e.g. '南昌博物馆' / '南昌拌粉').
    # 命中的 POI 标记 must_consider=True, 豁免后续 candidate_pool 距离过滤.
    if pre_fetched_pois is None:
        from agents import anchor as _anchor_mod
        from agents.candidate_pool import _infer_role_from_categories
        from agents.poi_cache import _around_to_poi
        from dianping.schemas import EnrichedLabel

        _seen_oids_kw = {p.openshopid for p in pois}
        _keywords: list[str] = []
        for _kw in intent.must_visit or []:
            if _kw and _kw not in _keywords:
                _keywords.append(_kw)
        for _slot in intent.required_slots or []:
            for _cat in _slot.categories or []:
                if _cat and _cat not in _keywords:
                    _keywords.append(_cat)
        for _kw in _keywords:
            try:
                _kw_around = await _anchor_mod.text_search(
                    _kw, city=intent.city, limit=8
                )
            except Exception:
                _kw_around = []
            for ap in _kw_around:
                p = _around_to_poi(ap, intent.city, None)
                if p.openshopid in _seen_oids_kw:
                    continue
                _role = _infer_role_from_categories(p.categories)
                p.enriched = EnrichedLabel(
                    poi_role=_role if _role != "fallback" else "city_essential",
                    must_consider=True,
                    manual_priority=80,
                )
                pois.append(p)
                _seen_oids_kw.add(p.openshopid)

    template = make_instant_template(intent.time_window, intent.required_slots or [])
    flat_pois = flatten_candidate_pool(intent, variant, pois)
    flat_pois = prefer_pois_by_decision_signals(
        flat_pois, intent=intent, slot_name="候选池", variant=variant
    )
    if excluded_oids:
        flat_pois = [p for p in flat_pois if p.openshopid not in excluded_oids]

    # v1.9.4: geocoded waypoints 强制置顶 flat_pois（候选池距离过滤可能把远处 waypoint 踢出去）
    _gwps = getattr(intent, "geocoded_waypoints", [])
    if _gwps:
        _wp_oids = {f"waypoint_{wp.name[:8]}" for wp in _gwps}
        _in_flat = {p.openshopid for p in flat_pois}
        for p in pois:
            if p.openshopid in _wp_oids and p.openshopid not in _in_flat:
                flat_pois.insert(0, p)
                _in_flat.add(p.openshopid)
    # v1.8: 优先用 intent.anchor_lng/lat (来自高德 geocode); 兜底 POI[0]
    if intent.anchor_lng is not None and intent.anchor_lat is not None:
        anchor_name = (
            intent.anchor_resolved_name or intent.start_location_text or "锚点"
        )
        anchor_lat = intent.anchor_lat
        anchor_lng = intent.anchor_lng
    else:
        anchor_name = intent.start_location_text or (
            flat_pois[0].name if flat_pois else "市中心"
        )
        anchor_lat = flat_pois[0].latitude if flat_pois else 0.0
        anchor_lng = flat_pois[0].longitude if flat_pois else 0.0
    anchor = (anchor_name, anchor_lat, anchor_lng)

    # v1.9 meal anchor 距离过滤: 防止跨城吃饭. 老 anchor_explore 路径 (上面 if 块)
    # 已对全 pool 过滤; 这里覆盖 landmark_must / 无 anchor 路径.
    flat_pois = _filter_meal_by_anchor_distance(flat_pois, anchor_lat, anchor_lng)

    # 无 enriched 数据时（Amap POI），按 variant 重排候选以差异化 LLM 输入
    flat_pois = _reorder_for_variant(flat_pois, variant)

    try:
        _, day_plan, segments = await planner.compose_one_day(
            day_idx=0,
            intent=intent,
            template=template,
            anchor=anchor,
            day_cluster_pois=flat_pois,
            amap=amap,
            on_partial=on_partial,
            variant=variant,
        )
        return VariantPlan(
            variant=variant, day_plan=day_plan, transit_segments=segments
        )
    except PlannerLLMError as plerr:
        # Fallback: synth a route from top-ranked pool POIs without LLM
        day_list = _synthesize_fallback_route(
            [template],
            [anchor],
            [flat_pois],
            intent,
        )
        day_plan = (
            day_list[0]
            if day_list
            else DayPlan(day_index=0, anchor_district=anchor_name, stops=[])
        )
        day_plan.day_index = 0
        _, segments = await _compute_day_transits(day_plan, intent, amap)
        return VariantPlan(
            variant=variant,
            day_plan=day_plan,
            transit_segments=segments,
            error=str(plerr.original),
        )


async def plan_three_variants(
    *,
    intent: ParsedIntent,
    planner,
    amap,
    pois: Optional[list[POI]] = None,
    on_partial: Optional[Callable[[str, int, list[str]], Awaitable[None]]] = None,
) -> dict[Variant, VariantPlan]:
    """Run main → low_queue → interest_first sequentially.

    B 方案的 backend 部分: main 先出, branches 后. on_partial 信号会带 variant
    名传给 caller (routes.py 转 SSE).
    """
    if pois is None:
        pois = load_city_pois_from_mock(intent.city)
    out: dict[Variant, VariantPlan] = {}
    variants: list[Variant] = ["main", "low_queue", "interest_first"]
    for v in variants:

        async def _partial(day_idx: int, names: list[str], _v: Variant = v):
            if on_partial:
                await on_partial(_v, day_idx, names)

        vp = await plan_one_variant(
            intent=intent,
            variant=v,
            planner=planner,
            amap=amap,
            pois=pois,
            on_partial=_partial,
        )
        out[v] = vp
    return out
