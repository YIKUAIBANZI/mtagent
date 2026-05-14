"""v1.9 Stage 3: Adjuster v1 单测.

覆盖 spec 第 5 节:
- replace_stop hits cache → source="cache", LLM 不调
- replace_stop falls to pool → source="pool"
- replace_stop excludes used+self
- replace_stop user_hint 非空 + 多候选 → 调 LLM 一次
- remove_stop stops -1 + transit_segments 重排
- regenerate_day excluded_oids 真排除
- switch_variant ctx.draft_route 切对
- switch_variant invalid → AdjusterError
"""

from __future__ import annotations

import json
from datetime import time
from pathlib import Path

import pytest

from agents.adjuster import Adjuster, AdjusterError
from agents.context import TripContext
from dianping.schemas import (
    DayPlan,
    EnrichedLabel,
    ParsedIntent,
    POI,
    RouteDraft,
    Stop,
    TimeSlot,
    UserInput,
)


def _mk_poi(
    oid: str,
    name: str,
    *,
    city: str = "深圳",
    lng: float = 113.95,
    lat: float = 22.54,
    role: str = "meal",
    zone: str = "南山万象天地",
    priority: int = 50,
    categories=None,
) -> POI:
    poi = POI(
        openshopid=oid,
        name=name,
        city=city,
        longitude=lng,
        latitude=lat,
        categories=categories or ["美食"],
    )
    poi.enriched = EnrichedLabel(
        poi_role=role,
        city_zone=zone,
        manual_priority=priority,
        planning_tags=["food_quality"] if role == "meal" else [],
    )
    return poi


def _mk_slot(name: str, h_start: int, h_end: int) -> TimeSlot:
    return TimeSlot(name=name, start=time(h_start, 0), end=time(h_end, 0))


def _mk_stop(
    poi: POI, slot_name: str = "午饭", h_start: int = 12, h_end: int = 13
) -> Stop:
    return Stop(
        poi=poi,
        slot=_mk_slot(slot_name, h_start, h_end),
        arrival_time=time(h_start, 0),
        leave_time=time(h_end, 0),
    )


def _mk_ctx(
    *, stops: list[Stop], candidate_pois: list[POI] = None, variants: dict = None
) -> TripContext:
    ctx = TripContext.create(user_input=UserInput(free_text="test"))
    ctx.intent = ParsedIntent(city="深圳", days=1, traveler_type="情侣")
    ctx.draft_route = RouteDraft(
        days=[DayPlan(day_index=0, anchor_district="南山万象天地", stops=stops)]
    )
    ctx.candidate_pois = candidate_pois or []
    if variants is not None:
        ctx.variants = variants
    return ctx


@pytest.fixture
def cache_path(tmp_path, monkeypatch) -> Path:
    p = tmp_path / "poi_cache.json"
    monkeypatch.setenv("MTAGENT_POI_CACHE_PATH", str(p))
    return p


def _write_cache(p: Path, entries: dict) -> None:
    p.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")


def _cache_entry(
    name: str,
    *,
    city: str = "深圳",
    lng: float = 113.95,
    lat: float = 22.54,
    role: str = "meal",
    zone: str = "南山万象天地",
    seen: int = 6,
    priority: int = 75,
) -> dict:
    return {
        "name": name,
        "lng": lng,
        "lat": lat,
        "city": city,
        "typecode": "050000",
        "categories": ["美食"],
        "enriched": {
            "poi_role": role,
            "city_zone": zone,
            "planning_tags": ["food_quality"],
            "manual_priority": priority,
        },
        "seen_count": seen,
    }


# ============================================================ replace_stop


@pytest.mark.asyncio
async def test_replace_stop_hits_cache(cache_path):
    """cache 同 zone+role 有候选 → source='cache', LLM 不调."""
    old = _mk_poi("OID_OLD", "旧店", role="meal", zone="南山万象天地")
    other_pois = [_mk_poi("OID_X", "X", role="meal")]
    ctx = _mk_ctx(stops=[_mk_stop(old, "午饭")], candidate_pois=other_pois)

    _write_cache(
        cache_path,
        {
            "热门|113.96|22.55": _cache_entry(
                "热门替代",
                lng=113.96,
                lat=22.55,
                role="meal",
                zone="南山万象天地",
                seen=10,
            )
        },
    )

    llm_calls = []

    async def _llm(prompt):
        llm_calls.append(prompt)
        return ""

    adj = Adjuster(llm_call=_llm)
    result = await adj.replace_stop(ctx, day_index=0, slot_name="午饭", user_hint="")
    assert result["source"] == "cache"
    assert result["new_stop"].poi.name == "热门替代"
    assert llm_calls == []  # user_hint 空 → 不调


@pytest.mark.asyncio
async def test_replace_stop_falls_to_pool(cache_path):
    """cache 没匹配 → 落 candidate_pool 次高分."""
    old = _mk_poi("OID_OLD", "旧店", role="meal")
    pool = [
        _mk_poi("OID_OLD", "旧店", role="meal"),  # used
        _mk_poi("OID_FALLBACK", "Pool 替代", role="meal", priority=70),
    ]
    ctx = _mk_ctx(stops=[_mk_stop(old, "午饭")], candidate_pois=pool)
    # cache 空文件
    _write_cache(cache_path, {})

    adj = Adjuster()
    result = await adj.replace_stop(ctx, day_index=0, slot_name="午饭")
    assert result["source"] == "pool"
    assert result["new_stop"].poi.openshopid == "OID_FALLBACK"


@pytest.mark.asyncio
async def test_replace_stop_excludes_used_and_self(cache_path):
    """当天 used / 同 oid / 同 zone+role 的 used 不被选."""
    old = _mk_poi("OID_OLD", "旧店", role="meal", zone="A")
    other_meal_used = _mk_poi("OID_MEAL2", "另一家美食", role="meal", zone="A")
    ctx = _mk_ctx(
        stops=[
            _mk_stop(old, "午饭", 12, 13),
            _mk_stop(other_meal_used, "晚饭", 18, 20),
        ],
        candidate_pois=[other_meal_used],  # 唯一可选但已 used
    )
    _write_cache(cache_path, {})  # cache 空

    adj = Adjuster()
    with pytest.raises(AdjusterError):
        await adj.replace_stop(ctx, day_index=0, slot_name="午饭")


@pytest.mark.asyncio
async def test_replace_stop_with_user_hint_invokes_llm(cache_path):
    """user_hint 非空 + cache 多候选 → 调 LLM 一次, 拿 hint 选."""
    old = _mk_poi("OID_OLD", "旧店", role="meal")
    ctx = _mk_ctx(stops=[_mk_stop(old, "午饭")])

    _write_cache(
        cache_path,
        {
            "辣|113.96|22.55": _cache_entry(
                "辣味店", role="meal", zone="南山万象天地", seen=10, priority=70
            ),
            "清淡|113.97|22.56": _cache_entry(
                "清淡店",
                lng=113.97,
                lat=22.56,
                role="meal",
                zone="南山万象天地",
                seen=8,
                priority=80,
            ),
        },
    )

    async def _llm(prompt):
        assert "想要辣" in prompt
        # 返回 hint 想要的 (按 cache_key 转出来的 oid)
        from scripts.promote_cache import _gen_openshopid

        return _gen_openshopid("辣|113.96|22.55")

    adj = Adjuster(llm_call=_llm)
    result = await adj.replace_stop(
        ctx, day_index=0, slot_name="午饭", user_hint="想要辣一点"
    )
    assert result["source"] == "cache"
    assert result["new_stop"].poi.name == "辣味店"


@pytest.mark.asyncio
async def test_replace_stop_no_candidate_raises(cache_path):
    old = _mk_poi("OID_OLD", "旧店", role="meal")
    ctx = _mk_ctx(stops=[_mk_stop(old, "午饭")], candidate_pois=[])
    _write_cache(cache_path, {})
    adj = Adjuster()
    with pytest.raises(AdjusterError):
        await adj.replace_stop(ctx, day_index=0, slot_name="午饭")


@pytest.mark.asyncio
async def test_replace_stop_invalid_slot_raises(cache_path):
    old = _mk_poi("OID_OLD", "旧店", role="meal")
    ctx = _mk_ctx(stops=[_mk_stop(old, "午饭")])
    adj = Adjuster()
    with pytest.raises(AdjusterError):
        await adj.replace_stop(ctx, day_index=0, slot_name="夜场")


# ============================================================ remove_stop


@pytest.mark.asyncio
async def test_remove_stop_reduces_and_reflows():
    a = _mk_poi("A", "A", role="city_essential")
    b = _mk_poi("B", "B", role="meal")
    c = _mk_poi("C", "C", role="connector")
    ctx = _mk_ctx(
        stops=[
            _mk_stop(a, "上午景点", 9, 11),
            _mk_stop(b, "午饭", 12, 13),
            _mk_stop(c, "下午", 14, 17),
        ],
    )
    # 模拟原有 transit_segments (3 stops → 2 段)
    ctx.draft_route.days[0].transit_segments = [
        {"from_index": 0, "to_index": 1, "options": {}, "recommended": "transit"},
        {"from_index": 1, "to_index": 2, "options": {}, "recommended": "transit"},
    ]
    adj = Adjuster()
    day_plan = await adj.remove_stop(ctx, day_index=0, slot_name="午饭")
    assert len(day_plan.stops) == 2
    assert day_plan.stops[0].poi.openshopid == "A"
    assert day_plan.stops[1].poi.openshopid == "C"
    assert len(day_plan.transit_segments) == 1


@pytest.mark.asyncio
async def test_remove_stop_invalid_slot_raises():
    a = _mk_poi("A", "A")
    ctx = _mk_ctx(stops=[_mk_stop(a, "上午景点", 9, 11)])
    adj = Adjuster()
    with pytest.raises(AdjusterError):
        await adj.remove_stop(ctx, day_index=0, slot_name="不存在")


# ============================================================ regenerate_day


@pytest.mark.asyncio
async def test_regenerate_day_excludes_old_oids(monkeypatch):
    """plan_one_variant 被调时, excluded_oids 含旧 oids."""
    old_a = _mk_poi("OLD_A", "A", role="city_essential")
    old_b = _mk_poi("OLD_B", "B", role="meal")
    ctx = _mk_ctx(
        stops=[_mk_stop(old_a, "上午景点", 9, 11), _mk_stop(old_b, "午饭", 12, 13)]
    )

    captured_excluded: dict = {}

    async def _fake_plan_one_variant(
        *, intent, variant, planner, amap, pois, excluded_oids=None, **kw
    ):
        captured_excluded["v"] = set(excluded_oids or set())
        from agents.planner_instant import VariantPlan

        new_poi = _mk_poi("NEW_X", "新景点", role="city_essential")
        return VariantPlan(
            variant=variant,
            day_plan=DayPlan(
                day_index=0,
                anchor_district="南山万象天地",
                stops=[_mk_stop(new_poi, "上午景点", 9, 11)],
            ),
            transit_segments=[],
        )

    monkeypatch.setattr(
        "agents.planner_instant.plan_one_variant", _fake_plan_one_variant
    )

    adj = Adjuster()
    new_day = await adj.regenerate_day(ctx, day_index=0, planner=None, amap=None)
    assert captured_excluded["v"] == {"OLD_A", "OLD_B"}
    assert new_day.stops[0].poi.openshopid == "NEW_X"
    assert ctx.draft_route.days[0].stops[0].poi.openshopid == "NEW_X"


# ============================================================ switch_variant


@pytest.mark.asyncio
async def test_switch_variant_updates_draft_route():
    a = _mk_poi("A", "A", role="city_essential")
    b = _mk_poi("B", "B", role="city_essential")
    route_main = RouteDraft(
        days=[DayPlan(day_index=0, stops=[_mk_stop(a, "上午景点", 9, 11)])]
    )
    route_lq = RouteDraft(
        days=[DayPlan(day_index=0, stops=[_mk_stop(b, "上午景点", 9, 11)])]
    )
    ctx = _mk_ctx(stops=[_mk_stop(a, "上午景点", 9, 11)])
    ctx.variants = {"main": route_main, "low_queue": route_lq}
    ctx.draft_route = route_main

    adj = Adjuster()
    await adj.switch_variant(ctx, variant="low_queue")
    assert ctx.draft_route is route_lq


@pytest.mark.asyncio
async def test_switch_variant_invalid_raises():
    a = _mk_poi("A", "A")
    ctx = _mk_ctx(stops=[_mk_stop(a)])
    ctx.variants = {"main": ctx.draft_route}
    adj = Adjuster()
    with pytest.raises(AdjusterError):
        await adj.switch_variant(ctx, variant="not_a_variant")


@pytest.mark.asyncio
async def test_switch_variant_empty_variants_raises():
    a = _mk_poi("A", "A")
    ctx = _mk_ctx(stops=[_mk_stop(a)])
    # variants 未设置 (老多日路径)
    adj = Adjuster()
    with pytest.raises(AdjusterError):
        await adj.switch_variant(ctx, variant="main")
