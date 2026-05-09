"""Adjuster — handles user real-time route adjustments + feedback loop writeback.

v0 STATUS: stub. Raises NotImplementedError.
v3 design: replace_stop (nearby same-category swap) / redo_day (per-day Anchor & Orbit
re-roll) / writes user_marked.disliked / been_there back to user_profile.

Skeleton kept here so v3 just fills internals.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from agents.context import TripContext
from dianping.schemas import Feedback, RouteDraft

_PROMPT_PATH = Path(__file__).parent / "prompts" / "adjuster.md"


class Adjuster:
    def __init__(self, llm_call: Optional[Callable] = None):
        self.llm_call = llm_call
        self._system_prompt = (
            _PROMPT_PATH.read_text(encoding="utf-8") if _PROMPT_PATH.exists() else ""
        )

    async def run(self, ctx: TripContext, feedback: Feedback) -> RouteDraft:
        ctx.log_event("Adjuster", "stub_invoked", {"action": feedback.action})
        raise NotImplementedError(
            "Adjuster.run is v0 stub. v3 spec implements replace_stop / redo_day."
        )
