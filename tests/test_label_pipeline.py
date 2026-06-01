"""Tests for offline label pipeline rules."""

from scripts.label_pois import (
    build_enriched_label,
    label_modifiers,
    label_planning_tags,
    label_poi_role,
    label_traveler_types,
)


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


def test_label_poi_role_accepts_amap_food_categories():
    poi = _poi()
    poi["categories"] = ["餐饮服务", "中餐厅"]

    assert label_poi_role(poi) == "meal"
    assert "food" in label_planning_tags(poi, "meal")


def test_label_poi_role_accepts_amap_shopping_categories():
    poi = _poi()
    poi["categories"] = ["购物服务", "商场"]

    assert label_poi_role(poi) == "connector"
    assert "shopping_friendly" in label_planning_tags(poi, "connector")


def test_beijing_landmark_is_city_essential():
    poi = _poi()
    poi.update({"city": "北京", "name": "故宫博物院", "categories": ["风景名胜"]})

    assert build_enriched_label(poi)["poi_role"] == "city_essential"


def test_lushan_landmark_gets_mountain_route_tags():
    poi = _poi(review_tags=["风景绝美"])
    poi.update(
        {
            "city": "庐山",
            "district": "庐山市",
            "name": "三叠泉",
            "categories": ["风景名胜"],
            "ugcs": [{"content": "台阶很多，爬坡比较费体力。"}],
        }
    )

    label = build_enriched_label(poi)

    assert label["poi_role"] == "city_essential"
    assert label["city_zone"] == "mountain"
    assert "walk_heavy" in label["risk_tags"]
