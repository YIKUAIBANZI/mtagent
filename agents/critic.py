"""Critic — async unobtrusive route validator.

v0 STATUS: stub. Returns empty patches list.
v2 design: ReAct loop, calling tools (check_business_hours, query reviewTags
negativity, validate cluster radius, etc.) to find issues; outputs Patch list.

Skeleton kept here so v2 just fills internals — no restructuring needed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from agents.context import TripContext
from dianping.schemas import Patch

_PROMPT_PATH = Path(__file__).parent / "prompts" / "critic.md"


class Critic:
    def __init__(self, llm_call: Optional[Callable] = None):
        self.llm_call = llm_call
        self._system_prompt = (
            _PROMPT_PATH.read_text(encoding="utf-8") if _PROMPT_PATH.exists() else ""
        )

    async def run(self, ctx: TripContext) -> list[Patch]:
        ctx.log_event(
            "Critic",
            "stub_skip",
            {
                "reason": "v0 stub — implementation in v2 spec",
            },
        )
        return []
