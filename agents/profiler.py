"""Profiler — parse free-text user input into a structured ParsedIntent.

LLM-driven. Designed to be testable by injecting an `llm_call` async fn.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Awaitable, Callable, Optional

from agents.context import TripContext
from dianping.schemas import ParsedIntent, ProfilerOutput

_PROMPT_PATH = Path(__file__).parent / "prompts" / "profiler.md"


REQUIRED_FIELDS = ("city", "days", "traveler_type")


class Profiler:
    """Profiler agent. v0 minimal — single LLM call, no clarifying loop."""

    def __init__(self, llm_call: Optional[Callable[[str, str], Awaitable[str]]] = None):
        """`llm_call(system_prompt, user_message) -> json_text`."""
        self.llm_call = llm_call or _default_qwen_call
        self._system_prompt = (
            _PROMPT_PATH.read_text(encoding="utf-8") if _PROMPT_PATH.exists() else ""
        )

    async def run(self, ctx: TripContext) -> ProfilerOutput:
        ctx.log_event("Profiler", "start", {"input": ctx.user_input.free_text[:100]})
        raw = await self.llm_call(self._system_prompt, ctx.user_input.free_text)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Profiler LLM did not return valid JSON: {raw[:200]}"
            ) from exc

        # Build ParsedIntent — None values keep field optional/missing
        missing: list[str] = []
        for k in REQUIRED_FIELDS:
            v = data.get(k)
            if v in (None, "", 0):
                missing.append(k)

        if missing:
            understood = ParsedIntent(
                city=data.get("city") or "?",
                days=data.get("days") or 1,
                traveler_type=data.get("traveler_type") or "情侣",
                budget_level=data.get("budget_level"),
                pace=data.get("pace"),
                preferences=data.get("preferences") or [],
                must_visit=data.get("must_visit") or [],
                avoid=data.get("avoid") or [],
            )
            ready = False
        else:
            understood = ParsedIntent(
                city=data["city"],
                days=int(data["days"]),
                traveler_type=data["traveler_type"],
                budget_level=data.get("budget_level"),
                pace=data.get("pace"),
                preferences=data.get("preferences") or [],
                must_visit=data.get("must_visit") or [],
                avoid=data.get("avoid") or [],
            )
            ready = True

        ctx.intent = understood
        ctx.log_event(
            "Profiler",
            "done",
            {
                "ready_to_plan": ready,
                "missing_fields": missing,
            },
        )
        ctx.save()

        return ProfilerOutput(
            understood=understood,
            ready_to_plan=ready,
            missing_fields=missing,
        )


async def _default_qwen_call(system: str, user: str) -> str:
    """Default LLM caller using qwen-plus via OpenAI-compatible API."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
        base_url=os.environ.get(
            "QWEN_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
    )
    resp = await client.chat.completions.create(
        model=os.environ.get("QWEN_MODEL", "qwen-plus"),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
        extra_body={"enable_thinking": False},
    )
    return resp.choices[0].message.content or "{}"
