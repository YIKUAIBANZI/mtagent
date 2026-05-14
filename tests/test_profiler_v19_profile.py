"""v1.9 Stage 2: Profiler 用 user_profile 覆盖 modifiers + 拼 interests."""

from __future__ import annotations

import pytest

from agents.context import TripContext
from agents.profiler import Profiler
from dianping.schemas import UserInput, UserProfile


async def _fake_llm(system: str, user: str) -> str:
    """假装 LLM 返了一个解析结果. 关键是: modifiers 不动 — 看 profile 是否覆盖."""
    return '{"city": "深圳", "days": 1, "traveler_type": "情侣", "modifiers": {"轻量体力": false, "重美食": false, "怕排队": false, "重文化": true}, "interests": ["拍照"]}'


@pytest.mark.asyncio
async def test_profile_overrides_modifiers():
    """profile.modifiers 显式偏好覆盖 LLM 解析."""
    ctx = TripContext.create(user_input=UserInput(free_text="深圳 1天 情侣 重文化"))
    ctx.profile = UserProfile(
        cookie_key="cookie_A",
        modifiers={"重美食": True, "怕排队": True},
    )

    profiler = Profiler(llm_call=_fake_llm)
    await profiler.run(ctx)

    assert ctx.intent is not None
    # profile 写了 True 的, intent 应也是 True (覆盖 LLM 的 false)
    assert ctx.intent.modifiers.get("重美食") is True
    assert ctx.intent.modifiers.get("怕排队") is True
    # profile 没写 "重文化", 应保留 LLM 的 True
    assert ctx.intent.modifiers.get("重文化") is True


@pytest.mark.asyncio
async def test_profile_interests_appended():
    """profile.interests_text 拼到 intent.interests, 去重."""
    ctx = TripContext.create(user_input=UserInput(free_text="深圳"))
    ctx.profile = UserProfile(
        cookie_key="cookie_B",
        interests_text="美食，小众景点",
    )

    profiler = Profiler(llm_call=_fake_llm)
    await profiler.run(ctx)

    assert ctx.intent is not None
    assert "美食" in ctx.intent.interests
    assert "小众景点" in ctx.intent.interests
    assert "拍照" in ctx.intent.interests  # LLM 解析的也保留


@pytest.mark.asyncio
async def test_no_profile_falls_back_to_keyword_scan():
    """无 profile → modifiers 走 _apply_modifier_defaults 关键词扫描."""
    ctx = TripContext.create(user_input=UserInput(free_text="深圳, 重美食 不想排队"))
    ctx.profile = None

    profiler = Profiler(llm_call=_fake_llm)
    await profiler.run(ctx)

    assert ctx.intent is not None
    assert ctx.intent.modifiers.get("重美食") is True
    assert ctx.intent.modifiers.get("怕排队") is True
    assert ctx.intent.modifiers.get("重文化") is False  # 没关键词
