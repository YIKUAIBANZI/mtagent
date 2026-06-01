"""Tests for PersonaLabels schema + POI/ParsedIntent backward compat."""

from dianping.schemas import (
    POI,
    ParsedIntent,
    PersonaLabels,
)


def test_persona_labels_round_trip():
    """PersonaLabels serializes and deserializes cleanly."""
    labels = PersonaLabels(
        traveler_types=["情侣", "家庭亲子"],
        modifiers={"轻量体力": True, "重文化": False, "重美食": True, "怕排队": False},
    )
    data = labels.model_dump()
    restored = PersonaLabels(**data)
    assert restored == labels


def test_poi_persona_labels_optional():
    """POI without persona_labels stays valid (backward compat)."""
    poi = POI(openshopid="abc", name="x", city="西安", latitude=34.0, longitude=108.0)
    assert poi.persona_labels is None  # default


def test_parsed_intent_modifiers_default_empty():
    """ParsedIntent without modifiers defaults to empty dict."""
    intent = ParsedIntent(city="西安", days=3, traveler_type="情侣")
    assert intent.modifiers == {}
