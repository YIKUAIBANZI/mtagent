"""v1.9 Stage 3: Adjuster v1.

4 个 operation 调整已生成的 RouteDraft:
- replace_stop: 单 stop 替换 (cache 优先, miss 落 candidate_pool)
- remove_stop: 删 + transit 重排
- regenerate_day: 整天换一组 POI (excluded_oids 排除旧 stops)
- switch_variant: ctx.draft_route = ctx.variants[variant]

Cache 联动 (v1.9.1 Phase B 复用): replace 时优先从 data/poi_cache.json 同
city_zone + poi_role + seen desc 拿替代品, miss 才落 candidate_pool 次高分.

LLM 调用边界: replace_stop 在 user_hint 非空时调一次轻量 LLM 二选; 其余零 LLM.
(regenerate_day 复用 plan_one_variant 链路, 那本来就调 LLM.)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from dianping.schemas import DayPlan, POI, RouteDraft, Stop
from agents.context import TripContext


def _cache_path() -> Path:
    return Path(os.environ.get("MTAGENT_POI_CACHE_PATH", "data/poi_cache.json"))


def _load_cache() -> dict:
    p = _cache_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _target_role(stop: Stop) -> str:
    """当前 stop 推 poi_role: enriched 优先, 否则 categories 兜底."""
    if stop.poi.enriched and stop.poi.enriched.poi_role:
        return stop.poi.enriched.poi_role
    from agents.candidate_pool import _infer_role_from_categories

    return _infer_role_from_categories(stop.poi.categories) or "fallback"


def _target_zone(stop: Stop, day_plan: DayPlan) -> str:
    """当前 stop 推 city_zone: enriched 优先, 否则 anchor_district 兜底."""
    if stop.poi.enriched and stop.poi.enriched.city_zone:
        return stop.poi.enriched.city_zone
    return day_plan.anchor_district or ""


def _cache_entry_to_poi(entry: dict, key: str) -> POI:
    """cache entry → POI (复用 promote_cache._cache_entry_to_mock_poi 的字段映射)."""
    from scripts.promote_cache import _cache_entry_to_mock_poi

    poi_dict = _cache_entry_to_mock_poi(key, entry)
    poi = POI(**poi_dict)
    en = entry.get("enriched")
    if en:
        from dianping.schemas import EnrichedLabel

        poi.enriched = EnrichedLabel.model_validate(en)
    return poi


def _pick_cache_candidates(
    ctx: TripContext,
    *,
    target_zone: str,
    target_role: str,
    excluded_oids: set[str],
    top_k: int = 3,
) -> list[POI]:
    """cache 同 zone + role + 排除 used 的 top_k 候选, seen desc + manual_priority desc."""
    cache = _load_cache()
    city = ctx.intent.city if ctx.intent else ""
    matches: list[tuple[float, POI]] = []
    for key, entry in cache.items():
        if entry.get("city") != city:
            continue
        en = entry.get("enriched") or {}
        if target_zone and en.get("city_zone") != target_zone:
            continue
        if en.get("poi_role") != target_role:
            continue
        try:
            poi = _cache_entry_to_poi(entry, key)
        except Exception:
            continue
        if poi.openshopid in excluded_oids:
            continue
        score = float(entry.get("seen_count", 0)) * 100.0 + float(
            en.get("manual_priority", 0)
        )
        matches.append((score, poi))
    matches.sort(key=lambda x: -x[0])
    return [p for _, p in matches[:top_k]]


def _pick_pool_candidate(
    ctx: TripContext,
    *,
    target_role: str,
    excluded_oids: set[str],
) -> Optional[POI]:
    """candidate_pois 同 bucket 次高分 (manual_priority desc), 排除 used."""
    from agents.candidate_pool import _bucket_of

    cands = [p for p in ctx.candidate_pois if p.openshopid not in excluded_oids]
    cands_in_bucket = [p for p in cands if _bucket_of(p) == target_role]
    cands_in_bucket.sort(
        key=lambda p: -(p.enriched.manual_priority if p.enriched else 0)
    )
    return cands_in_bucket[0] if cands_in_bucket else None


def _pick_pool_candidate_relaxed(
    ctx: TripContext,
    *,
    target_role: str,
    excluded_oids: set[str],
) -> Optional[POI]:
    """降级版: enriched.poi_role 精确匹配失败时，按宽泛类别（美食/景点）兜底."""
    from agents.candidate_pool import _infer_role_from_categories

    FOOD_ROLES = {"meal", "lunch_main", "dinner_main", "snack", "cafe", "breakfast"}
    SIGHTSEEING_ROLES = {"city_essential", "hidden_gem", "connector"}

    if target_role in FOOD_ROLES:
        broad = "food"
    elif target_role in SIGHTSEEING_ROLES:
        broad = "sight"
    else:
        broad = None

    def _broad_match(p: POI) -> bool:
        role = (
            p.enriched.poi_role
            if p.enriched
            else _infer_role_from_categories(p.categories)
        )
        if broad == "food":
            return (
                role in FOOD_ROLES
                or "meal" in (role or "")
                or (_infer_role_from_categories(p.categories) == "meal")
            )
        if broad == "sight":
            return role in SIGHTSEEING_ROLES or (
                _infer_role_from_categories(p.categories) == "city_essential"
            )
        return True

    cands = [
        p
        for p in ctx.candidate_pois
        if p.openshopid not in excluded_oids and _broad_match(p)
    ]
    cands.sort(key=lambda p: -(p.enriched.manual_priority if p.enriched else 0))
    return cands[0] if cands else None


def _all_used_oids(route: RouteDraft) -> set[str]:
    return {s.poi.openshopid for d in route.days for s in d.stops}


def _find_target_poi(ctx: TripContext, target_poi_id: str) -> Optional[POI]:
    """Find an exact POI by openshopid for user-picked replacement."""
    oid = (target_poi_id or "").strip()
    if not oid:
        return None

    buckets: list[POI] = []
    buckets.extend(ctx.candidate_pois or [])
    buckets.extend(ctx.pre_fetched_pois or [])
    if ctx.draft_route is not None:
        for day in ctx.draft_route.days:
            buckets.extend(stop.poi for stop in day.stops)
    for variant in (ctx.variants or {}).values():
        if variant is None:
            continue
        for day in variant.days:
            buckets.extend(stop.poi for stop in day.stops)

    for poi in buckets:
        if poi.openshopid == oid:
            return poi

    city = getattr(ctx.intent, "city", "")
    if city:
        try:
            from agents.planner_instant import load_city_pois_from_mock

            for poi in load_city_pois_from_mock(city):
                if poi.openshopid == oid:
                    return poi
        except Exception:
            return None
    return None


class AdjusterError(Exception):
    pass


class Adjuster:
    """v1: replace_stop / remove_stop / regenerate_day / switch_variant."""

    def __init__(self, llm_call=None):
        self.llm_call = llm_call

    # ------------------------------------------------------------------ replace
    async def replace_stop(
        self,
        ctx: TripContext,
        *,
        day_index: int,
        slot_name: str,
        user_hint: str = "",
        target_poi_id: str = "",
    ) -> dict:
        """Returns {old_oid, new_stop, source: 'target'|'cache'|'pool'|'amap'}."""
        if ctx.draft_route is None:
            raise AdjusterError("ctx.draft_route is None")
        if day_index >= len(ctx.draft_route.days):
            raise AdjusterError(f"day_index {day_index} out of range")
        day_plan = ctx.draft_route.days[day_index]
        stop_idx = next(
            (i for i, s in enumerate(day_plan.stops) if s.slot.name == slot_name),
            -1,
        )
        if stop_idx < 0:
            raise AdjusterError(f"slot_name '{slot_name}' not found in day {day_index}")
        old_stop = day_plan.stops[stop_idx]

        used = _all_used_oids(ctx.draft_route)
        target_role = _target_role(old_stop)
        target_zone = _target_zone(old_stop, day_plan)

        chosen: Optional[POI] = _find_target_poi(ctx, target_poi_id)
        source = "target" if chosen is not None else ""

        if chosen is None:
            cache_cands = _pick_cache_candidates(
                ctx,
                target_zone=target_zone,
                target_role=target_role,
                excluded_oids=used,
            )
            # 降级1: zone 过滤太严时放宽
            if not cache_cands and target_zone:
                cache_cands = _pick_cache_candidates(
                    ctx,
                    target_zone="",
                    target_role=target_role,
                    excluded_oids=used,
                )

            if cache_cands:
                chosen = await self._llm_pick_or_first(cache_cands, user_hint)
                source = "cache"
            else:
                pool_pick = _pick_pool_candidate(
                    ctx,
                    target_role=target_role,
                    excluded_oids=used,
                )
                # 降级2: enriched.poi_role 精确匹配失败时，按宽泛类别兜底
                if pool_pick is None:
                    pool_pick = _pick_pool_candidate_relaxed(
                        ctx,
                        target_role=target_role,
                        excluded_oids=used,
                    )
                if pool_pick is not None:
                    chosen = pool_pick
                    source = "pool"

        # v1.10 P0.3: cache + pool 都失败时, 用 user_hint 调 amap text_search 兜底.
        # 解决 "用户说去南昌之星但本地池没这个 POI" 的现实场景.
        if chosen is None and user_hint and len(user_hint.strip()) >= 2:
            from agents.anchor import text_search
            from agents.candidate_pool import _infer_role_from_categories
            from agents.poi_cache import _around_to_poi
            from dianping.schemas import EnrichedLabel

            try:
                amap_results = await text_search(
                    user_hint.strip(),
                    city=ctx.intent.city,
                    limit=5,
                )
            except Exception:
                amap_results = []
            for ap in amap_results:
                new_poi = _around_to_poi(ap, ctx.intent.city, None)
                if new_poi.openshopid in used:
                    continue
                role = _infer_role_from_categories(new_poi.categories)
                new_poi.enriched = EnrichedLabel(
                    poi_role=role if role != "fallback" else target_role,
                    must_consider=True,
                    manual_priority=80,
                )
                chosen = new_poi
                source = "amap"
                break

        if chosen is None:
            raise AdjusterError(
                f"no replacement candidate for day {day_index} slot {slot_name}"
            )

        new_stop = Stop(
            poi=chosen,
            slot=old_stop.slot,
            arrival_time=old_stop.arrival_time,
            leave_time=old_stop.leave_time,
            transport_to_next_minutes=old_stop.transport_to_next_minutes,
            transport_options=old_stop.transport_options,
        )
        day_plan.stops[stop_idx] = new_stop

        # v1.10 P0.3: 同步 variants 里同名 slot 的 stop, 否则前端地图 markers (从
        # variants 拿) 显示老 POI. 与 remove_stop 同步逻辑配对.
        for vp in (ctx.variants or {}).values():
            if vp is None or day_index >= len(vp.days):
                continue
            v_day = vp.days[day_index]
            v_idx = next(
                (i for i, s in enumerate(v_day.stops) if s.slot.name == slot_name),
                -1,
            )
            if v_idx >= 0:
                v_day.stops[v_idx] = Stop(
                    poi=chosen,
                    slot=v_day.stops[v_idx].slot,
                    arrival_time=v_day.stops[v_idx].arrival_time,
                    leave_time=v_day.stops[v_idx].leave_time,
                    transport_to_next_minutes=v_day.stops[
                        v_idx
                    ].transport_to_next_minutes,
                    transport_options=v_day.stops[v_idx].transport_options,
                )
        ctx.log_event(
            "Adjuster",
            "stop_replaced",
            {
                "day_index": day_index,
                "slot_name": slot_name,
                "old_oid": old_stop.poi.openshopid,
                "new_oid": chosen.openshopid,
                "source": source,
            },
        )
        return {
            "old_oid": old_stop.poi.openshopid,
            "new_stop": new_stop,
            "source": source,
        }

    async def _llm_pick_or_first(self, candidates: list[POI], user_hint: str) -> POI:
        """user_hint 非空且 candidates >= 2 → 调 LLM 二选; 否则取 top 1."""
        if not user_hint or len(candidates) < 2 or self.llm_call is None:
            return candidates[0]
        try:
            prompt = self._build_pick_prompt(candidates, user_hint)
            raw = await self.llm_call(prompt)
            picked = (raw or "").strip()
            for c in candidates:
                if c.openshopid == picked or c.name in picked:
                    return c
        except Exception:
            pass
        return candidates[0]

    @staticmethod
    def _build_pick_prompt(candidates: list[POI], user_hint: str) -> str:
        lines = [
            "你是替换 POI 的助手. 用户对当前 stop 不满意, 给出了 hint.",
            f"用户 hint: {user_hint}",
            "候选 POI:",
        ]
        for c in candidates:
            tags = list(c.enriched.planning_tags) if c.enriched else []
            lines.append(f"- {c.openshopid} | {c.name} | tags={tags}")
        lines.append("请只输出最匹配 hint 的 openshopid, 不要解释.")
        return "\n".join(lines)

    # ------------------------------------------------------------------ remove
    async def remove_stop(
        self,
        ctx: TripContext,
        *,
        day_index: int,
        slot_name: str,
    ) -> DayPlan:
        if ctx.draft_route is None:
            raise AdjusterError("ctx.draft_route is None")
        day_plan = ctx.draft_route.days[day_index]
        stop_idx = next(
            (i for i, s in enumerate(day_plan.stops) if s.slot.name == slot_name),
            -1,
        )
        if stop_idx < 0:
            raise AdjusterError(f"slot_name '{slot_name}' not found in day {day_index}")
        removed_oid = day_plan.stops[stop_idx].poi.openshopid
        del day_plan.stops[stop_idx]
        day_plan.transit_segments = self._reflow_transit_segments(day_plan)

        # v1.10 P0.3: 同步删 variants 里同名 slot, 否则前端地图 markers (从 variants
        # 拿) 不同步, 残留被删 stop 的 pin. 用户痛点: 截图里地图还显示老 stop.
        for vp in (ctx.variants or {}).values():
            if vp is None or day_index >= len(vp.days):
                continue
            v_day = vp.days[day_index]
            v_idx = next(
                (i for i, s in enumerate(v_day.stops) if s.slot.name == slot_name),
                -1,
            )
            if v_idx >= 0:
                del v_day.stops[v_idx]
                v_day.transit_segments = self._reflow_transit_segments(v_day)

        ctx.log_event(
            "Adjuster",
            "stop_removed",
            {
                "day_index": day_index,
                "slot_name": slot_name,
                "removed_oid": removed_oid,
            },
        )
        return day_plan

    @staticmethod
    def _reflow_transit_segments(day_plan: DayPlan) -> list[dict]:
        """删后 placeholder segments — 真 amap 调用在 routes.py 那层做."""
        segs: list[dict] = []
        for i in range(len(day_plan.stops) - 1):
            segs.append(
                {
                    "from_index": i,
                    "to_index": i + 1,
                    "options": {},
                    "recommended": "transit",
                }
            )
        return segs

    # ----------------------------------------------------------- regenerate_day
    async def regenerate_day(
        self,
        ctx: TripContext,
        *,
        day_index: int,
        planner,
        amap,
        user_hint: str = "",
    ) -> DayPlan:
        """复用 plan_one_variant, 排除当天旧 stops 的 POI."""
        from agents.planner_instant import plan_one_variant

        if ctx.draft_route is None or ctx.intent is None:
            raise AdjusterError("ctx.draft_route or intent is None")
        if day_index >= len(ctx.draft_route.days):
            raise AdjusterError(f"day_index {day_index} out of range")

        old_oids = {s.poi.openshopid for s in ctx.draft_route.days[day_index].stops}
        variant = self._infer_current_variant(ctx)

        vp = await plan_one_variant(
            intent=ctx.intent,
            variant=variant,
            planner=planner,
            amap=amap,
            pois=ctx.candidate_pois,
            excluded_oids=old_oids,
        )
        new_day = vp.day_plan
        new_day.day_index = day_index
        new_day.transit_segments = vp.transit_segments
        ctx.draft_route.days[day_index] = new_day
        ctx.log_event(
            "Adjuster",
            "day_regenerated",
            {
                "day_index": day_index,
                "excluded_oids": list(old_oids),
                "new_stops": [s.poi.openshopid for s in new_day.stops],
            },
        )
        return new_day

    @staticmethod
    def _infer_current_variant(ctx: TripContext) -> str:
        if not ctx.variants:
            return "main"
        for name, route in ctx.variants.items():
            if route is ctx.draft_route:
                return name
        return "main"

    # ------------------------------------------------------------- switch_variant
    async def switch_variant(self, ctx: TripContext, *, variant: str) -> None:
        if not ctx.variants:
            raise AdjusterError("ctx.variants empty (instant flow 未跑过)")
        if variant not in ctx.variants:
            raise AdjusterError(f"variant '{variant}' not in ctx.variants")
        ctx.draft_route = ctx.variants[variant]
        ctx.log_event(
            "Adjuster",
            "variant_switched",
            {"variant": variant},
        )
