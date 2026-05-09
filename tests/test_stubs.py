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


@pytest.mark.asyncio
async def test_adjuster_stub_raises_not_implemented():
    from agents.adjuster import Adjuster
    from agents.context import TripContext
    from dianping.schemas import Feedback, UserInput

    adjuster = Adjuster()
    ctx = TripContext.create(user_input=UserInput(free_text="x"))
    feedback = Feedback(action="replace_stop", target_day=0, target_stop_idx=0)

    with pytest.raises(NotImplementedError):
        await adjuster.run(ctx, feedback)
