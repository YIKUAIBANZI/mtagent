"""Amap POI pool augmentation — text_search keyword expansion + around-fetch prefetch.

提供两个函数:
- apply_text_search_keywords(intent, pois) — 关键词搜补足 pool
- prefetch_amap_pois(intent, base_pois) — 完整预取 (anchor 周边 + 关键词)

Moved from api.routes (was _apply_text_search_keywords / _prefetch_amap_pois)
to remove the agents → api reverse dependency.
"""

from __future__ import annotations


async def apply_text_search_keywords(intent, pois: list) -> list:
    """v1.10: 用 /v3/place/text 关键词搜补足 pool, 不依赖 anchor 坐标.

    对每个 intent.must_visit 和 required_slots[].categories 关键词调 amap text_search,
    命中 POI 标记 must_consider=True 豁免后续距离过滤. 对 must_visit 关键词命中的
    第一个具体 POI name 也 append 进 intent.must_visit (mutate), 让 candidate_pool
    的子串匹配能精确命中 — 解决 '南昌博物馆' (口语) vs '江西省博物馆' (amap 真名)
    字面对不上, LLM 找不到博物馆 POI 的根因.
    """
    must_visit_kws = [kw for kw in (intent.must_visit or []) if kw]
    slot_kws: list[str] = []
    for slot in intent.required_slots or []:
        for cat in slot.categories or []:
            if cat and cat not in slot_kws:
                slot_kws.append(cat)
    keywords: list[str] = []
    for kw in must_visit_kws + slot_kws:
        if kw not in keywords:
            keywords.append(kw)
    # P2: 按 traveler_type 自动扩 2-3 个类目词, 扩 variant 分流候选池.
    # 局部 import 防 autoflake (同 build_rationale_for_stop 的教训)
    from agents.text_search_keywords import expand_keywords_for_traveler

    keywords = expand_keywords_for_traveler(intent.traveler_type or "", keywords)
    if not keywords:
        return pois

    import asyncio as _asyncio

    from agents.anchor import text_search as _text_search
    from agents.candidate_pool import (
        _infer_role_from_categories as _infer_role,
    )
    from agents.poi_cache import _around_to_poi as _around_to_poi_kw
    from dianping.schemas import EnrichedLabel

    async def _ts(kw: str):
        try:
            r = await _text_search(kw, city=intent.city, limit=8)
            return (kw, r)
        except Exception:
            return (kw, [])

    kw_results = await _asyncio.gather(*(_ts(kw) for kw in keywords))
    existing_oids = {p.openshopid for p in pois}
    injected_names: list[str] = []
    for kw, ap_list in kw_results:
        is_must_kw = kw in must_visit_kws
        for idx, ap in enumerate(ap_list):
            p = _around_to_poi_kw(ap, intent.city, None)
            if p.openshopid in existing_oids:
                continue
            role = _infer_role(p.categories)
            p.enriched = EnrichedLabel(
                poi_role=role if role != "fallback" else "city_essential",
                must_consider=True,
                manual_priority=80,
            )
            pois.append(p)
            existing_oids.add(p.openshopid)
            if is_must_kw and idx == 0 and ap.name:
                injected_names.append(ap.name)
    # mutate intent.must_visit so candidate_pool 的子串匹配能精确命中
    # 必须 mutate (不能 model_copy/重新绑定), 否则 caller 的 ctx.intent 看不到
    if injected_names:
        current = list(intent.must_visit or [])
        for name in injected_names:
            if name not in current:
                current.append(name)
        intent.must_visit = current

    return pois


async def prefetch_amap_pois(intent, base_pois: list) -> list | None:
    """执行 intent 对应的所有 Amap fetch_around + text_search, 返回合并 pois 列表.

    - anchor 模式 (anchor_explore/layover_*): 完整走 fetch_around (周边搜) + text_search (关键词搜)
    - 非 anchor 模式 (landmark_must 等): 只走 text_search 关键词搜 (不需要 anchor 坐标)
    - 无 anchor 也无 must_visit/required_slots 关键词: 返 None, caller 自处理
    """
    from agents.planner_instant import (
        _slot_typecodes,
    )
    from agents.anchor import (
        _haversine_km,
        _norm_name,
        fetch_around,
        DEFAULT_AROUND_TYPES,
    )
    from agents.poi_cache import _around_to_poi

    has_anchor = (
        intent.anchor_lng is not None
        and intent.anchor_lat is not None
        and intent.trip_mode in ("anchor_explore", "layover_eat", "layover_explore")
    )
    has_keywords = bool(intent.must_visit) or any(
        slot.categories for slot in (intent.required_slots or [])
    )
    if not has_anchor and not has_keywords:
        return None

    pois = list(base_pois)

    if not has_anchor:
        # 非 anchor 模式: 只能跑 text_search 关键词搜
        return await apply_text_search_keywords(intent, pois)
    anchor_pt = (intent.anchor_lng, intent.anchor_lat)
    radius_m = int((intent.anchor_radius_km or 3.0) * 1000)
    radius_km = radius_m / 1000.0
    types = (
        "050000" if intent.trip_mode == "layover_eat" else "050000|060000|080000|110000"
    )

    seen_keys: set = set()

    def _key(p):
        return (_norm_name(p.name), round(p.latitude, 3), round(p.longitude, 3))

    # 主 anchor fetch
    try:
        around = await fetch_around(
            lng=intent.anchor_lng,
            lat=intent.anchor_lat,
            radius_m=radius_m,
            types=types,
            limit=50,
        )
    except Exception:
        around = []
    amap_enriched = [_around_to_poi(ap, intent.city, None) for ap in around]

    kept_local = [
        p
        for p in pois
        if _haversine_km(anchor_pt, (p.longitude, p.latitude)) <= radius_km
    ]
    for p in kept_local:
        seen_keys.add(_key(p))
    kept_amap = [
        ap
        for ap in amap_enriched
        if _haversine_km(anchor_pt, (ap.longitude, ap.latitude)) <= radius_km
        and _key(ap) not in seen_keys
    ]
    for ap in kept_amap:
        seen_keys.add(_key(ap))
    pois = kept_local + kept_amap

    # 额外 waypoint fetch + 强制注入 waypoint 本身为高优先级 POI
    extra_wps = getattr(intent, "geocoded_waypoints", [])
    if len(extra_wps) >= 2:
        existing_oids = {p.openshopid for p in pois}

        # 把所有 waypoint 合成 city_essential POI 强制进候选池（无论 mock 有没有）
        for wp in extra_wps:
            wp_oid = f"waypoint_{wp.name[:8]}"
            if wp_oid not in existing_oids:
                from dianping.schemas import EnrichedLabel, POI as _POI

                wp_poi = _POI(
                    openshopid=wp_oid,
                    name=wp.name,
                    city=intent.city,
                    latitude=wp.lat,
                    longitude=wp.lng,
                    categories=["旅游景点"],
                    star=4.8,
                    avgprice=0,
                    business_hour="09:00-18:00",
                )
                wp_poi.enriched = EnrichedLabel(
                    poi_role="city_essential",
                    universal_level="high",
                    must_consider=True,
                    manual_priority=99,  # 最高优先级，保证进 top-30
                    planning_tags=["landmark"],
                    min_stay_minutes=90,
                    max_stay_minutes=180,
                )
                pois.insert(0, wp_poi)  # 顶部插入
                existing_oids.add(wp_oid)

        for wp in extra_wps[1:]:
            try:
                extra = await fetch_around(
                    lng=wp.lng,
                    lat=wp.lat,
                    radius_m=int((intent.anchor_radius_km or 2.0) * 1000),
                    types=DEFAULT_AROUND_TYPES,
                    limit=20,
                )
            except Exception:
                extra = []
            for ap in extra:
                p = _around_to_poi(ap, intent.city, None)
                if p.openshopid not in existing_oids:
                    pois.append(p)
                    existing_oids.add(p.openshopid)
        # 扩展 anchor_radius_km 覆盖最远 waypoint，避免 planner 的 anchor 半径硬约束排除远处地点
        max_wp_dist = max(
            _haversine_km((extra_wps[0].lng, extra_wps[0].lat), (wp.lng, wp.lat))
            for wp in extra_wps[1:]
        )
        if max_wp_dist > (intent.anchor_radius_km or 3.0):
            # v1.10: mutate 而非 model_copy, 否则后续 inject 改的是副本, caller 看不到
            intent.anchor_radius_km = max_wp_dist + 5.0

    # category-targeted fetch
    target_tc = _slot_typecodes(getattr(intent, "required_slots", []))
    if target_tc:
        try:
            cat_around = await fetch_around(
                lng=intent.anchor_lng,
                lat=intent.anchor_lat,
                radius_m=radius_m,
                types=target_tc,
                limit=15,
            )
        except Exception:
            cat_around = []
        existing_oids = {p.openshopid for p in pois}
        for ap in cat_around:
            p = _around_to_poi(ap, intent.city, None)
            if p.openshopid not in existing_oids:
                pois.append(p)
                existing_oids.add(p.openshopid)

    pois = await apply_text_search_keywords(intent, pois)
    return pois
