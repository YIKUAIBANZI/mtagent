"""v1.9 tag_mapping: 用户兴趣/约束 → planning_tags / risk_tags 映射."""

from agents.tag_mapping import TagMapping, expand_user_signals, load_tag_mapping
from dianping.schemas import ParsedIntent


def _intent(**kw):
    d = dict(city="深圳", days=1, traveler_type="情侣")
    d.update(kw)
    return ParsedIntent(**d)


def test_load_tag_mapping_returns_pydantic_model():
    m = load_tag_mapping()
    assert isinstance(m, TagMapping)
    assert "拍照" in m.user_interest_to_planning_tags
    assert "photo_friendly" in m.user_interest_to_planning_tags["拍照"]


def test_expand_user_signals_with_photo_interest():
    intent = _intent(interests=["拍照"])
    pos, neg = expand_user_signals(intent)
    assert "photo_friendly" in pos
    assert neg == set()


def test_expand_user_signals_with_avoid_queue_constraint():
    intent = _intent(constraints={"avoid_queue": True})
    pos, neg = expand_user_signals(intent)
    assert "queue_heavy" in neg


def test_expand_user_signals_combines_legacy_preferences():
    """v1.6 老字段 preferences 也要映射."""
    intent = _intent(preferences=["美食"])
    pos, neg = expand_user_signals(intent)
    assert "food_quality" in pos or "local_food" in pos


def test_expand_user_signals_returns_empty_when_no_signals():
    intent = _intent()
    pos, neg = expand_user_signals(intent)
    assert pos == set()
    assert neg == set()
