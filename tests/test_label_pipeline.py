"""Tests for offline label pipeline rules."""

from scripts.label_pois import label_modifiers, label_traveler_types


def _poi(*, review_tags=None, special=None, queueable=False, isBlackPearl=0):
    return {
        "reviewTags": [{"tag": t, "hit": 5} for t in (review_tags or [])],
        "special": special or [],
        "queueable": queueable,
        "isBlackPearl": isBlackPearl,
    }


def test_label_traveler_types_couple():
    """'适合约会' tag → 情侣."""
    poi = _poi(review_tags=["适合约会"])
    assert "情侣" in label_traveler_types(poi)


def test_label_traveler_types_family():
    """'亲子友好' tag OR '提供婴儿椅' special → 家庭亲子."""
    assert "家庭亲子" in label_traveler_types(_poi(review_tags=["亲子友好"]))
    assert "家庭亲子" in label_traveler_types(_poi(special=["提供婴儿椅"]))


def test_label_traveler_types_fallback_solo():
    """No matched signal → ['独行'] fallback."""
    assert label_traveler_types(_poi()) == ["独行"]


def test_label_modifiers_full():
    """All 4 modifiers correctly mapped from structured fields."""
    poi = _poi(
        review_tags=["亲子友好", "老字号", "菜品精致", "等位久"],
        special=["提供婴儿椅"],
        queueable=True,
        isBlackPearl=0,
    )
    mods = label_modifiers(poi)
    assert mods["轻量体力"] is True
    assert mods["重文化"] is True
    assert mods["重美食"] is True
    assert mods["怕排队"] is False  # queueable=True AND 等位久 → 不怕排队=False
