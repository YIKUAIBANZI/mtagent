"""Tests for user profile cleaning helpers."""

import json

from scripts.clean_user_profiles import (
    build_profiles,
    event_from_trip,
    iter_trip_events,
)


def test_build_profiles_merges_intent_and_feedback_signals():
    profiles = build_profiles(
        [
            {
                "source": "unit",
                "event_type": "raw_event",
                "cookie_key": "u1",
                "city": "深圳",
                "traveler_type": "情侣",
                "budget_level": "适中",
                "pace": "佛系",
                "preferences": ["拍照", "美食"],
                "avoid": ["不想排队", "不要太累"],
                "modifiers": {"轻量体力": True, "重美食": True, "怕排队": True},
                "must_visit": ["深圳湾公园"],
            }
        ]
    )

    profile = profiles["u1"]
    assert profile["city_weights"] == {"深圳": 1}
    assert profile["traveler_type_weights"] == {"情侣": 1}
    assert profile["budget_level_weights"] == {"适中": 1}
    assert profile["pace_weights"] == {"佛系": 1}
    assert profile["preference_weights"]["photo_friendly"] >= 1
    assert profile["preference_weights"]["food_quality"] >= 1
    assert profile["preference_weights"]["low_queue"] >= 1
    assert profile["preference_weights"]["low_walk"] >= 1
    assert profile["modifiers"]["轻量体力"] is True
    assert profile["modifiers"]["重美食"] is True
    assert profile["modifiers"]["怕排队"] is True
    assert profile["must_visit"] == ["深圳湾公园"]
    assert profile["avoid_keywords"] == ["不要太累", "不想排队"]
    assert profile["evidence"]


def test_event_from_trip_uses_trip_context_schema(tmp_path):
    path = tmp_path / "trip_1.json"
    raw = {
        "trip_id": "trip_1",
        "created_at": "2026-05-12T10:00:00",
        "updated_at": "2026-05-12T10:10:00",
        "user_input": {"free_text": "深圳 情侣 拍照 美食 不想排队", "cookie_key": "u2"},
        "intent": {
            "city": "深圳",
            "days": 1,
            "traveler_type": "情侣",
            "budget_level": "适中",
            "pace": "佛系",
            "preferences": ["拍照", "美食"],
            "must_visit": [],
            "avoid": ["排队"],
            "modifiers": {"怕排队": True},
        },
        "user_feedback": [
            {
                "action": "replace_stop",
                "target_day": 0,
                "target_stop_idx": 1,
                "reason": "这个点太远，换近一点",
            }
        ],
    }
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    event = event_from_trip(path, raw)
    assert event["cookie_key"] == "u2"
    assert event["city"] == "深圳"
    assert event["preferences"] == ["拍照", "美食"]

    loaded = list(iter_trip_events(tmp_path))
    assert [item["event_type"] for item in loaded] == ["trip_context", "feedback"]
    assert loaded[1]["action"] == "replace_stop"
