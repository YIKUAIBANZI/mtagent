"""按 traveler_type 自动扩 text_search 类目关键词.

哈尔滨 demo 暴露: 用户 must_visit 只填地标 (中央大街/哈工大),
required_slots 又是 []. _apply_text_search_keywords 只搜地标 →
餐饮候选池窄, 三 variant 没东西可分流.

修法: 加 TRAVELER_CATEGORY_HINTS 字典, 按 traveler_type 自动注入
2-3 个高 ROI 类目词 (情侣→咖啡/西餐; 亲子→冰激凌; 银发→老字号/茶馆).
"""

from agents.text_search_keywords import (
    TRAVELER_CATEGORY_HINTS,
    expand_keywords_for_traveler,
)


def test_all_six_traveler_types_covered():
    """6 个 TravelerType 都要有 hints (即使是空 list)."""
    expected = {"情侣", "家庭亲子", "银发", "独行", "商务", "朋友团"}
    assert set(TRAVELER_CATEGORY_HINTS.keys()) == expected


def test_couple_gets_cafe_and_western():
    hints = TRAVELER_CATEGORY_HINTS["情侣"]
    assert "咖啡" in hints
    assert "西餐" in hints


def test_family_gets_kid_friendly():
    hints = TRAVELER_CATEGORY_HINTS["家庭亲子"]
    assert any("亲子" in h or "冰" in h for h in hints), (
        f"family hints should include kid-friendly: {hints}"
    )


def test_silver_gets_traditional():
    hints = TRAVELER_CATEGORY_HINTS["银发"]
    assert any("老字号" in h or "茶" in h for h in hints), (
        f"silver hints should include traditional venues: {hints}"
    )


def test_expand_keywords_dedupes_against_existing():
    """expand_keywords_for_traveler 应去重: 已有的 keyword 不重复注入."""
    existing = ["咖啡", "中央大街"]
    expanded = expand_keywords_for_traveler("情侣", existing)
    # 已有的 "咖啡" 不该重复
    assert expanded.count("咖啡") == 1
    # 应该至少新增 "西餐"
    assert "西餐" in expanded


def test_expand_empty_traveler_returns_existing():
    """traveler_type 不在字典时, 返回原 list 不变."""
    existing = ["x"]
    expanded = expand_keywords_for_traveler("", existing)
    assert expanded == existing
