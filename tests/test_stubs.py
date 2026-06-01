"""Test Critic and Adjuster stubs return expected v0 placeholder behaviors."""

import pytest


@pytest.mark.asyncio
async def test_critic_stub_returns_empty_patches():
    from agents.context import TripContext
    from agents.critic import Critic
    from dianping.schemas import UserInput

    critic = Critic()
    ctx = TripContext.create(user_input=UserInput(free_text="x"))
    patches = await critic.run(ctx)

    assert patches == []


# v1.9 Stage 3: Adjuster v0 stub removed.
# v1 contract uses replace_stop / remove_stop / regenerate_day / switch_variant
# named methods — see tests/test_adjuster_v1.py for the new coverage.
