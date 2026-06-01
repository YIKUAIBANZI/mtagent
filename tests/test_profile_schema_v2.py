from dianping.schemas import UserProfile, ParsedIntent


def test_userprofile_v2_fields_default():
    p = UserProfile(cookie_key="k")
    assert p.loved_tags == []
    assert p.rejected_tags == []
    assert p.persona_label == ""
    assert p.taste_summary == ""


def test_userprofile_ignores_legacy_categories_keys():
    # 旧 json 用 loved_categories（已弃用）；Pydantic v2 默认 extra=ignore，不报错
    old = {"cookie_key": "k", "loved_categories": ["x"], "rejected_categories": ["y"]}
    p = UserProfile.model_validate(old)
    assert p.cookie_key == "k"
    assert p.loved_tags == []  # 旧数据本就为空，无需迁移


def test_parsedintent_profile_fields_default():
    intent = ParsedIntent(city="上海", days=1, traveler_type="情侣")
    assert intent.profile_loved_tags == []
    assert intent.profile_rejected_tags == []
    assert intent.profile_been_there == []
    assert intent.profile_budget == 0
