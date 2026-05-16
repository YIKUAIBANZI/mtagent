"""v1.9 Refine: Refiner 把自由文本路由成 RefineAction (4 场景)."""

from __future__ import annotations

import json

import pytest

from agents.refiner import Refiner, RefineAction
from dianping.schemas import UserProfile


def _make_llm(response_json: dict):
    """Build a stub llm_call that returns the given JSON dict as str."""

    async def _llm(system: str, user: str) -> str:
        return json.dumps(response_json, ensure_ascii=False)

    return _llm


SUMMARY = (
    "西安·1天, 朋友团\n"
    "day 0 stops: [上午景点] 大雁塔 | [午饭] 长安大牌档 | [下午] 长安十二时辰\n"
    "variants: main / low_queue / interest_first"
)


@pytest.mark.asyncio
async def test_pure_profile_update():
    """A 类: 纯偏好 → profile_update 非 None, adjust None."""
    llm = _make_llm(
        {
            "reasoning": "记下博物馆偏好",
            "profile_update": {
                "interests_text_append": "博物馆",
                "modifiers_set": {"重文化": True},
            },
            "adjust": None,
            "chat_reply": None,
        }
    )
    refiner = Refiner(llm_call=llm)
    action = await refiner.run(
        user_text="他喜欢博物馆什么的",
        trip_summary=SUMMARY,
        current_profile=None,
    )

    assert isinstance(action, RefineAction)
    assert action.profile_update is not None
    assert action.profile_update.interests_text_append == "博物馆"
    assert action.profile_update.modifiers_set == {"重文化": True}
    assert action.adjust is None
    assert action.chat_reply is None
    assert "博物馆" in action.reasoning


@pytest.mark.asyncio
async def test_pure_adjust_replace_stop():
    """B 类: 纯调整 → adjust 非 None, profile_update None."""
    llm = _make_llm(
        {
            "reasoning": "好, 换个近的午饭",
            "profile_update": None,
            "adjust": {
                "operation": "replace_stop",
                "day_index": 0,
                "slot_name": "午饭",
                "variant": "",
                "user_hint": "近一点",
            },
            "chat_reply": None,
        }
    )
    refiner = Refiner(llm_call=llm)
    action = await refiner.run(
        user_text="把午饭换近的",
        trip_summary=SUMMARY,
        current_profile=None,
    )

    assert action.profile_update is None
    assert action.adjust is not None
    assert action.adjust.operation == "replace_stop"
    assert action.adjust.slot_name == "午饭"
    assert action.adjust.user_hint == "近一点"
    assert action.chat_reply is None


@pytest.mark.asyncio
async def test_combined_profile_and_adjust():
    """C 类: 同句两件事 → profile_update + adjust 都非 None."""
    llm = _make_llm(
        {
            "reasoning": "记下博物馆偏好, 同时换下午",
            "profile_update": {
                "interests_text_append": "博物馆",
                "modifiers_set": {"重文化": True},
            },
            "adjust": {
                "operation": "replace_stop",
                "day_index": 0,
                "slot_name": "下午",
                "variant": "",
                "user_hint": "博物馆",
            },
            "chat_reply": None,
        }
    )
    refiner = Refiner(llm_call=llm)
    action = await refiner.run(
        user_text="他喜欢博物馆, 把下午换成博物馆",
        trip_summary=SUMMARY,
        current_profile=None,
    )

    assert action.profile_update is not None
    assert action.adjust is not None
    assert action.adjust.slot_name == "下午"
    assert action.profile_update.modifiers_set.get("重文化") is True


@pytest.mark.asyncio
async def test_chat_reply_fallback():
    """D 类: 无法路由 → chat_reply 兜底, profile_update + adjust 均 None."""
    llm = _make_llm(
        {
            "reasoning": "新增站点暂时不支持",
            "profile_update": None,
            "adjust": None,
            "chat_reply": "暂时还不能加新站, 我可以帮你换或者重生成下午",
        }
    )
    refiner = Refiner(llm_call=llm)
    action = await refiner.run(
        user_text="再加一个夜景",
        trip_summary=SUMMARY,
        current_profile=None,
    )

    assert action.profile_update is None
    assert action.adjust is None
    assert action.chat_reply is not None
    assert "新站" in action.chat_reply or "不支持" in action.chat_reply


@pytest.mark.asyncio
async def test_switch_variant():
    """B 子场景: switch_variant 路由."""
    llm = _make_llm(
        {
            "reasoning": "好, 切到少排队方案",
            "profile_update": None,
            "adjust": {
                "operation": "switch_variant",
                "day_index": 0,
                "slot_name": "",
                "variant": "low_queue",
                "user_hint": "",
            },
            "chat_reply": None,
        }
    )
    refiner = Refiner(llm_call=llm)
    action = await refiner.run(
        user_text="切到少排队那版",
        trip_summary=SUMMARY,
        current_profile=None,
    )

    assert action.adjust is not None
    assert action.adjust.operation == "switch_variant"
    assert action.adjust.variant == "low_queue"


@pytest.mark.asyncio
async def test_llm_returns_invalid_json_falls_back():
    """LLM 返非 JSON → 不 raise, 返 chat_reply 兜底."""

    async def _bad_llm(system: str, user: str) -> str:
        return "this is not json at all"

    refiner = Refiner(llm_call=_bad_llm)
    action = await refiner.run(
        user_text="任何文本",
        trip_summary=SUMMARY,
        current_profile=None,
    )

    assert action.profile_update is None
    assert action.adjust is None
    assert action.chat_reply is not None


@pytest.mark.asyncio
async def test_invalid_operation_rejected():
    """LLM 返了不存在的 operation → adjust 应被丢弃."""
    llm = _make_llm(
        {
            "reasoning": "...",
            "profile_update": None,
            "adjust": {
                "operation": "add_stop",  # 非法
                "day_index": 0,
                "slot_name": "下午",
                "variant": "",
                "user_hint": "",
            },
            "chat_reply": "兜底",
        }
    )
    refiner = Refiner(llm_call=llm)
    action = await refiner.run(
        user_text="加一个",
        trip_summary=SUMMARY,
        current_profile=None,
    )

    assert action.adjust is None
    assert action.chat_reply is not None


@pytest.mark.asyncio
async def test_empty_response_gets_fallback_reply():
    """三个 action 都 None + 无 chat_reply → 自动兜底."""
    llm = _make_llm(
        {
            "reasoning": "",
            "profile_update": None,
            "adjust": None,
            "chat_reply": None,
        }
    )
    refiner = Refiner(llm_call=llm)
    action = await refiner.run(
        user_text="嗯",
        trip_summary=SUMMARY,
        current_profile=None,
    )

    assert action.profile_update is None
    assert action.adjust is None
    assert action.chat_reply  # 自动兜底


@pytest.mark.asyncio
async def test_profile_in_summary():
    """current_profile 非 None 时, 传给 LLM 的 user_msg 应包含 profile 段."""
    captured = {}

    async def _capturing_llm(system: str, user: str) -> str:
        captured["user"] = user
        return json.dumps(
            {
                "reasoning": "ok",
                "profile_update": None,
                "adjust": None,
                "chat_reply": "ok",
            }
        )

    refiner = Refiner(llm_call=_capturing_llm)
    profile = UserProfile(
        cookie_key="cookie_X",
        modifiers={"重美食": True},
        interests_text="咖啡馆",
    )
    await refiner.run(
        user_text="test",
        trip_summary=SUMMARY,
        current_profile=profile,
    )

    assert "重美食" in captured["user"]
    assert "咖啡馆" in captured["user"]
