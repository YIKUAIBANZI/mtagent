"""Tests for Profiler modifier extraction (LLM + rule fallback)."""

from agents.profiler import _apply_modifier_defaults
from dianping.schemas import ParsedIntent


def _intent(traveler_type: str = "情侣", **mods) -> ParsedIntent:
    return ParsedIntent(
        city="西安", days=3, traveler_type=traveler_type, modifiers=mods
    )


def test_apply_default_elderly_implies_light_stamina():
    """traveler_type=银发 → 轻量体力 默认 True."""
    intent = _intent(traveler_type="银发")
    _apply_modifier_defaults(intent, "")
    assert intent.modifiers["轻量体力"] is True


def test_apply_default_family_implies_light_stamina():
    """traveler_type=家庭亲子 → 轻量体力 默认 True."""
    intent = _intent(traveler_type="家庭亲子")
    _apply_modifier_defaults(intent, "")
    assert intent.modifiers["轻量体力"] is True


def test_apply_keyword_culture():
    """User text mentions '博物馆' → 重文化 = True."""
    intent = _intent()
    _apply_modifier_defaults(intent, "想去博物馆看历史")
    assert intent.modifiers["重文化"] is True


def test_apply_keyword_food_and_no_queue():
    """User text mentions '美食' + '不想排队' → 重美食 + 怕排队 both True."""
    intent = _intent()
    _apply_modifier_defaults(intent, "美食打卡，但不想排队")
    assert intent.modifiers["重美食"] is True
    assert intent.modifiers["怕排队"] is True


def test_apply_unfilled_modifiers_default_false():
    """All 4 modifiers always end up with explicit bool (no missing keys)."""
    intent = _intent(traveler_type="独行")
    _apply_modifier_defaults(intent, "")
    for m in ("轻量体力", "重文化", "重美食", "怕排队"):
        assert m in intent.modifiers
        assert intent.modifiers[m] is False  # 独行无任何关键词触发
