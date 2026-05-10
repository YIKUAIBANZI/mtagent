"""Tests for two-stage persona routing in tools.py."""

from agents.tools import (
    NEIGHBOR_TYPES,
    RELAX_ORDER,
    _filter_by_traveler_type,
    _progressive_relax,
    _rank_by_modifiers,
    _score,
    route_by_persona,
)
from dianping.schemas import POI, ParsedIntent, PersonaLabels


def _poi(shop_id: str, traveler_types: list[str], **mods) -> POI:
    full_mods = {
        "轻量体力": False,
        "重文化": False,
        "重美食": False,
        "怕排队": False,
        **mods,
    }
    return POI(
        openshopid=shop_id,
        name=shop_id,
        city="西安",
        latitude=34.0,
        longitude=108.0,
        persona_labels=PersonaLabels(
            traveler_types=traveler_types, modifiers=full_mods
        ),
    )


def _intent(traveler_type: str = "情侣", **mods) -> ParsedIntent:
    full_mods = {
        "轻量体力": False,
        "重文化": False,
        "重美食": False,
        "怕排队": False,
        **mods,
    }
    return ParsedIntent(
        city="西安", days=3, traveler_type=traveler_type, modifiers=full_mods
    )


def test_filter_by_traveler_type_keeps_only_matching():
    pool = [
        _poi("a", ["情侣"]),
        _poi("b", ["家庭亲子"]),
        _poi("c", ["情侣", "朋友团"]),
    ]
    out = _filter_by_traveler_type(pool, "情侣")
    assert {p.openshopid for p in out} == {"a", "c"}


def test_filter_drops_pois_without_persona_labels():
    """POI without persona_labels (legacy v2) is dropped from filter."""
    legacy = POI(
        openshopid="legacy", name="x", city="西安", latitude=34.0, longitude=108.0
    )
    pool = [_poi("a", ["情侣"]), legacy]
    out = _filter_by_traveler_type(pool, "情侣")
    assert {p.openshopid for p in out} == {"a"}


def test_score_match_plus_two_mismatch_minus_one():
    """want=True+poi=True → +2; want=True+poi=False → -1; want=False → 0."""
    intent_mods = {"重文化": True, "重美食": True, "轻量体力": False, "怕排队": False}
    poi = _poi("p", ["情侣"], 重文化=True, 重美食=False, 轻量体力=True, 怕排队=False)
    # 重文化 want=T poi=T → +2
    # 重美食 want=T poi=F → -1
    # 轻量体力 want=F → 0 (regardless of poi)
    # 怕排队 want=F → 0
    assert _score(poi, intent_mods) == 1


def test_rank_orders_by_score_desc():
    intent_mods = {
        "重文化": True,
        "轻量体力": False,
        "重美食": False,
        "怕排队": False,
    }
    pool = [
        _poi("low", ["情侣"], 重文化=False),  # score = -1
        _poi("hi", ["情侣"], 重文化=True),  # score = +2
        _poi("mid", ["情侣"]),  # score = -1 (重文化 want=T poi=F)
    ]
    out = _rank_by_modifiers(pool, intent_mods)
    assert out[0].openshopid == "hi"


def test_progressive_relax_drops_modifier_first():
    """When filter+rank yields too few, drop modifiers per RELAX_ORDER."""
    pool = [_poi(f"id{i}", ["情侣"]) for i in range(2)]
    pool += [_poi(f"alt{i}", ["朋友团"]) for i in range(10)]
    intent = _intent(traveler_type="情侣", 重文化=True, 重美食=True)
    out = _progressive_relax(pool, intent, min_size=8, top_n=20)
    assert len(out) >= 8
    # Stage 1 fully exhausts modifiers but 情侣 still has only 2 → Stage 2 → 朋友团
    assert all(p.openshopid.startswith("alt") for p in out)


def test_progressive_relax_falls_back_to_full_pool():
    """If no neighbors satisfy min_size, return pool[:top_n]."""
    pool = [_poi(f"x{i}", ["商务"]) for i in range(3)]
    intent = _intent(traveler_type="独行")
    out = _progressive_relax(pool, intent, min_size=8, top_n=20)
    # 独行 → neighbor=朋友团 (also empty) → Stage 3 fallback to pool[:top_n]
    assert len(out) == 3
    assert {p.openshopid for p in out} == {"x0", "x1", "x2"}


def test_route_by_persona_full_pipeline_happy_path():
    """Plenty of matching POIs → returns top-20 from Stage 1+2 only."""
    pool = [_poi(f"id{i}", ["家庭亲子"], 轻量体力=True) for i in range(50)]
    pool += [_poi(f"other{i}", ["独行"]) for i in range(10)]
    intent = _intent(traveler_type="家庭亲子", 轻量体力=True)
    out = route_by_persona(pool, intent, min_size=8, top_n=20)
    assert len(out) == 20
    assert all(p.openshopid.startswith("id") for p in out)


def test_relax_order_constant_present():
    """RELAX_ORDER is well-defined with all 4 modifiers."""
    assert set(RELAX_ORDER) == {"重美食", "重文化", "怕排队", "轻量体力"}
    assert RELAX_ORDER[0] == "重美食"  # 美食最先松
    assert RELAX_ORDER[-1] == "轻量体力"  # 体力最后松（生理约束）


def test_neighbor_types_constant_present():
    """NEIGHBOR_TYPES is well-defined for all traveler_types."""
    assert "家庭亲子" in NEIGHBOR_TYPES["银发"]
    assert "朋友团" in NEIGHBOR_TYPES["独行"]
