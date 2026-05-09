"""Stub LLM fallback when DASHSCOPE_API_KEY is missing.

Lets the demo run end-to-end without API costs. The Planner's fallback
synthesis (in agents/planner.py) takes over when the stub returns empty days,
producing a deterministic real route from real mock POIs.
"""

from __future__ import annotations

import json
import os
import re
from typing import Awaitable, Callable

_CITY_PAT = re.compile(r"(深圳|上海|西安)")
_DAYS_PAT = re.compile(r"(\d+)\s*天")
_TRAVELER_PATS = [
    (re.compile(r"(情侣|男朋友|女朋友|对象)"), "情侣"),
    (re.compile(r"(家庭|带孩子|亲子|一家人)"), "家庭亲子"),
    (re.compile(r"(爸妈|长辈|银发)"), "银发"),
    (re.compile(r"(独行|一个人|独自)"), "独行"),
    (re.compile(r"(出差|商务)"), "商务"),
    (re.compile(r"(朋友|闺蜜|一群)"), "朋友团"),
]
_BUDGET_PATS = [
    (re.compile(r"(穷游|性价比|不贵|便宜)"), "性价比"),
    (re.compile(r"(精致|高端|不在乎钱|奢华)"), "精致"),
]
_PREFERENCE_TOKENS = ["拍照", "打卡", "美食", "文化", "历史", "出片", "小众", "网红"]


async def stub_profiler_llm(system: str, user: str) -> str:
    """Pattern-match the user text into a ParsedIntent JSON.

    Best-effort heuristic — fallback when no real LLM available.
    """
    city_match = _CITY_PAT.search(user)
    city = city_match.group(1) if city_match else None

    days_match = _DAYS_PAT.search(user)
    days = int(days_match.group(1)) if days_match else None

    traveler_type = None
    for pat, label in _TRAVELER_PATS:
        if pat.search(user):
            traveler_type = label
            break

    budget_level = None
    for pat, label in _BUDGET_PATS:
        if pat.search(user):
            budget_level = label
            break
    if budget_level is None and re.search(r"预算\s*(\d+)", user):
        amt = int(re.search(r"预算\s*(\d+)", user).group(1))
        per_day_per_person = amt / max(days or 1, 1) / 2
        if per_day_per_person < 100:
            budget_level = "性价比"
        elif per_day_per_person < 300:
            budget_level = "适中"
        else:
            budget_level = "精致"

    preferences = [t for t in _PREFERENCE_TOKENS if t in user]

    out = {
        "city": city,
        "days": days,
        "traveler_type": traveler_type,
        "budget_level": budget_level,
        "pace": None,
        "preferences": preferences,
        "must_visit": [],
        "avoid": [],
        "start_date": None,
    }
    return json.dumps(out, ensure_ascii=False)


async def stub_planner_llm(system: str, user: str) -> str:
    """Returns empty days — triggers Planner.fallback synthesis."""
    return json.dumps(
        {
            "summary": "为你打造的行程——基于真实候选 POI 的智能编排（stub LLM 模式）。",
            "days": [],
        },
        ensure_ascii=False,
    )


def resolve_profiler_llm() -> Callable[[str, str], Awaitable[str]]:
    """Return real qwen call if DASHSCOPE_API_KEY is set, else stub."""
    if os.environ.get("DASHSCOPE_API_KEY"):
        from agents.profiler import _default_qwen_call

        return _default_qwen_call
    return stub_profiler_llm


def resolve_planner_llm() -> Callable[[str, str], Awaitable[str]]:
    """Return real qwen call if DASHSCOPE_API_KEY is set, else stub."""
    if os.environ.get("DASHSCOPE_API_KEY"):
        from agents.planner import _default_qwen_call

        return _default_qwen_call
    return stub_planner_llm
