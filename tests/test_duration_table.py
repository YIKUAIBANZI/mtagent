"""Unit tests for agents.duration_table — categories → 基础时长 × traveler 倍率."""

from agents.duration_table import base_duration_for, duration_for


# --- base_duration_for: 关键词匹配优先级 ---


def test_base_scenic_named() -> None:
    """风景名胜命中 90."""
    assert base_duration_for(["风景名胜", "5A 景区"]) == 90


def test_base_museum_beats_generic_scenic() -> None:
    """博物馆条目在表里位于景点之前 → 命中 100 而非 90."""
    assert base_duration_for(["博物馆", "景点"]) == 100


def test_base_meal_hotpot() -> None:
    """火锅命中 90."""
    assert base_duration_for(["火锅店", "中餐厅"]) == 90


def test_base_cafe() -> None:
    """咖啡命中 40."""
    assert base_duration_for(["咖啡", "甜品"]) == 40


def test_base_fountain_landmark() -> None:
    """喷泉命中 20（打卡型）."""
    assert base_duration_for(["音乐喷泉", "标志建筑"]) == 20


def test_base_empty_fallback() -> None:
    """空 categories → DEFAULT 60."""
    assert base_duration_for([]) == 60


def test_base_unknown_fallback() -> None:
    """没命中任何关键词 → DEFAULT 60."""
    assert base_duration_for(["未知类别 X"]) == 60


def test_base_scenic_outranks_cafe() -> None:
    """风景名胜 + 咖啡 混合 categories → 命中风景名胜 90, 不是咖啡 40.

    一个公园里的咖啡馆首先是景点, 不是单纯咖啡馆.
    """
    assert base_duration_for(["风景名胜", "咖啡馆"]) == 90


# --- duration_for: traveler 倍率 + 向上取整到 5 ---


def test_duration_scenic_couple() -> None:
    """风景名胜 + 情侣: 90 × 1.2 = 108 → 110."""
    assert duration_for(["风景名胜"], "情侣") == 110


def test_duration_museum_business() -> None:
    """博物馆 + 商务: 100 × 0.7 = 70 → 70."""
    assert duration_for(["博物馆"], "商务") == 70


def test_duration_hotpot_family() -> None:
    """火锅 + 亲子: 90 × 1.4 = 126 → 130."""
    assert duration_for(["火锅"], "亲子") == 130


def test_duration_cafe_senior() -> None:
    """咖啡 + 银发: 40 × 1.3 = 52 → 55."""
    assert duration_for(["咖啡"], "银发") == 55


def test_duration_fountain_solo() -> None:
    """喷泉 + 独行: 20 × 1.0 = 20."""
    assert duration_for(["喷泉"], "独行") == 20


def test_duration_unknown_traveler_falls_back_to_1x() -> None:
    """未知 traveler → multiplier 1.0."""
    assert duration_for(["博物馆"], "外星人") == 100
