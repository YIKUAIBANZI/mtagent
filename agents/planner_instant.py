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
        category_pool=["休闲娱乐", "亲子"],
        is_meal=False,
        min_stay_minutes=60,
        max_stay_minutes=180,
    ),
    "午饭": dict(
        start=time(12, 0),
        end=time(13, 30),
        category_pool=["美食"],
        is_meal=True,
        min_stay_minutes=60,
        max_stay_minutes=90,
    ),
    "下午": dict(
        start=time(13, 30),
        end=time(17, 0),
        category_pool=["购物", "休闲娱乐"],
        is_meal=False,
        min_stay_minutes=90,
        max_stay_minutes=180,
    ),
    "下午茶": dict(
        start=time(15, 30),
        end=time(16, 30),
        category_pool=["美食"],
        is_meal=False,
        optional=True,
        min_stay_minutes=30,
        max_stay_minutes=60,
    ),
    "晚饭": dict(
        start=time(18, 0),
        end=time(20, 0),
        category_pool=["美食"],
        is_meal=True,
        min_stay_minutes=60,
        max_stay_minutes=120,
    ),
    "夜场": dict(
        start=time(20, 0),
        end=time(22, 0),
        category_pool=["休闲娱乐"],
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


def make_instant_template(time_window: Optional[str]) -> DayTemplate:
    """Build a single-day template fitting the time_window.

    Fallback (unknown / None): 全天 4 slot 跟旧 'pace=适中' 一致.
    """
    names = _INSTANT_SLOT_NAMES.get(time_window) or ["上午景点", "午饭", "下午", "晚饭"]
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
        d = _haversine_km((anchor_lng, anchor_lat), (p.longitude, p.latitude))
        if d <= radius_km:
            kept.append(p)
    return kept


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
) -> VariantPlan:
    """Run one variant end-to-end: pool → compose_one_day → DayPlan + segments.

    On compose_one_day failure (PlannerLLMError) → fallback synth using top-N pool POIs.

    v1.9 Stage 3: `excluded_oids` 用于 regenerate_day — flatten 后过滤掉这批 POI,
    避免新一天又出现旧 stops 的 POI. 默认 None / 空 = 兼容老调用.
    """
    from agents.planner import PlannerLLMError, _synthesize_fallback_route
    from api.routes import _compute_day_transits

    # v1.9 / v1.9.1: anchor 模式下拉高德周边 POI → cache 层 → 合进本地池 (扩 pool)
    if (
        intent.anchor_lng is not None
        and intent.anchor_lat is not None
        and intent.trip_mode in ("anchor_explore", "layover_eat", "layover_explore")
    ):
        from agents import anchor as _anchor_mod
        from agents import poi_cache as _poi_cache
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
            # v1.9.1: cache 层 — 高德 POI 进 cache 命中复用 / miss 并发 enrich + 写回
            try:
                amap_enriched = await _poi_cache.lookup_and_enrich(
                    around, city=intent.city
                )
            except Exception:
                amap_enriched = []

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

    template = make_instant_template(intent.time_window)
    flat_pois = flatten_candidate_pool(intent, variant, pois)
    if excluded_oids:
        flat_pois = [p for p in flat_pois if p.openshopid not in excluded_oids]
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

    try:
        _, day_plan, segments = await planner.compose_one_day(
            day_idx=0,
            intent=intent,
            template=template,
            anchor=anchor,
            day_cluster_pois=flat_pois,
            amap=amap,
            on_partial=on_partial,
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
