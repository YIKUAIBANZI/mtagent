"""v1.9 _infer_role_from_categories: 给无 enriched POI 兜底 poi_role."""

from agents.candidate_pool import _infer_role_from_categories


def test_meal_for_food_categories():
    assert _infer_role_from_categories(["美食"]) == "meal"
    assert _infer_role_from_categories(["美食", "本帮菜"]) == "meal"


def test_city_essential_for_landmark():
    assert _infer_role_from_categories(["景点"]) == "city_essential"
    assert _infer_role_from_categories(["历史文化", "景点"]) == "city_essential"


def test_connector_for_shopping_and_leisure():
    assert _infer_role_from_categories(["购物"]) == "connector"
    assert _infer_role_from_categories(["休闲娱乐"]) == "connector"


def test_fallback_when_empty_or_unknown():
    assert _infer_role_from_categories([]) == "fallback"
    assert _infer_role_from_categories(["不存在分类"]) == "fallback"
    assert _infer_role_from_categories(None) == "fallback"  # type: ignore
