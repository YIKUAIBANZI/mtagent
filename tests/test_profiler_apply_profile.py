from dianping.schemas import ParsedIntent, UserProfile
from agents.profiler import _apply_profile_to_intent


def test_apply_profile_surfaces_tags():
    intent = ParsedIntent(city="上海", days=1, traveler_type="情侣")
    prof = UserProfile(
        cookie_key="k",
        loved_tags=["photo_friendly"],
        rejected_tags=["queue_heavy"],
        avg_budget_per_day=200,
    )
    prof.user_marked.been_there = ["外滩"]
    _apply_profile_to_intent(intent, prof)
    assert intent.profile_loved_tags == ["photo_friendly"]
    assert intent.profile_rejected_tags == ["queue_heavy"]
    assert intent.profile_been_there == ["外滩"]
    assert intent.profile_budget == 200


def test_apply_profile_none_is_noop():
    intent = ParsedIntent(city="上海", days=1, traveler_type="情侣")
    _apply_profile_to_intent(intent, None)
    assert intent.profile_loved_tags == []
    assert intent.profile_budget == 0
