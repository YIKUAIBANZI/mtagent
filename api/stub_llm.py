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
_CN_NUM = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
_DAYS_PAT_CN = re.compile(r"([一二两三四五六七八九十])\s*天")
_TRAVELER_PATS = [
    (re.compile(r"(情侣|男朋友|女朋友|对象)"), "情侣"),
    (re.compile(r"(家庭|带孩子|带小孩|带娃|亲子|一家人|全家)"), "家庭亲子"),
    (re.compile(r"(爸妈|长辈|银发|爷爷|奶奶|外公|外婆)"), "银发"),
    (re.compile(r"(独行|一个人|独自)"), "独行"),
    (re.compile(r"(出差|商务)"), "商务"),
    (re.compile(r"(朋友|闺蜜|一群)"), "朋友团"),
]
_BUDGET_PATS = [
    (re.compile(r"(穷游|性价比|不贵|便宜)"), "性价比"),
    (re.compile(r"(精致|高端|不在乎钱|奢华)"), "精致"),
]
_PREFERENCE_TOKENS = ["拍照", "打卡", "美食", "文化", "历史", "出片", "小众", "网红"]

# v1.7 即时出发关键词
_TIME_WINDOW_PATS = [
    (re.compile(r"(夜里|晚上|夜场|夜间)"), "半日_夜间"),
    (re.compile(r"(下午)"), "半日_下午"),
    (re.compile(r"(上午|早上)"), "半日_上午"),
    (re.compile(r"(一整天|一天|一日|整天)"), "一日"),
]
_HALF_DAY_FALLBACK = re.compile(r"(半天|半日)")
_START_LOC_PAT = re.compile(
    r"我?现在在([^,，。.！!？?\s]+?)(附近|这|这里|这边)?(?=[,，。.！!？?\s]|$)"
)
# v1.8 通用锚点抽取 (动词约束 + 非贪婪 取最近 2-15 字)
_ANCHOR_PATS = [
    re.compile(
        r"(?:想?去|想?到|在|从)([一-龥A-Za-z]{2,15}?)(?:附近|周边|这边|这里|一带)"
    ),
    re.compile(r"(?:在|从)([一-龥A-Za-z]{2,15}?(?:站|机场|客运站))"),
]
_HOURS_PAT = re.compile(r"(\d+)\s*(?:个)?小时")
_INTEREST_TOKENS = ["拍照", "美食", "文化", "购物", "展览", "自然", "夜景"]

# v1.9.2: must_visit 抽取 — 必去/一定要去/不可错过/想去 后接 2-15 字中文/英文
_MUST_VISIT_PATS = [
    re.compile(
        r"(?:必去|一定要去|不可错过|不能错过|要去)([一-龥A-Za-z]{2,15}?)(?=[,，。\s!！?？]|$|必去|一定要去)"
    ),
    re.compile(r"([一-龥A-Za-z]{2,15}?)(?:是必去|是一定要去|不可错过)"),
]


async def stub_profiler_llm(system: str, user: str) -> str:
    """Pattern-match the user text into a ParsedIntent JSON.

    Best-effort heuristic — fallback when no real LLM available.
    """
    city_match = _CITY_PAT.search(user)
    city = city_match.group(1) if city_match else None

    days_match = _DAYS_PAT.search(user)
    if days_match:
        days = int(days_match.group(1))
    else:
        cn_match = _DAYS_PAT_CN.search(user)
        days = _CN_NUM[cn_match.group(1)] if cn_match else None

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

    # v1.7 即时出发字段抽取
    time_window = None
    for pat, label in _TIME_WINDOW_PATS:
        if pat.search(user):
            time_window = label
            break
    if time_window is None and _HALF_DAY_FALLBACK.search(user):
        # "半天" 没指明 → 默认下午
        time_window = "半日_下午"
    # 如果用户写多日 (days > 1) 而上面 time_window=半日/一日, 以 days 为准
    if (
        time_window in ("半日_上午", "半日_下午", "半日_夜间", "一日")
        and (days or 0) > 1
    ):
        time_window = "多日"

    # v1.7 简化: 用户没说几天 + 没说半天/上午/下午 → 默认一日 (full day, 含两顿饭)
    if time_window is None and (days is None or days == 0):
        time_window = "一日"

    # v1.7: traveler_type 兜底 — 没说默认情侣 (demo 最常见场景)
    if traveler_type is None:
        traveler_type = "情侣"

    interests = [t for t in _INTEREST_TOKENS if t in user]

    # v1.8 锚点抽取: 三正则按优先级试, 命中即停
    start_location_text = None
    loc_match = _START_LOC_PAT.search(user)
    if loc_match:
        start_location_text = loc_match.group(1)
    else:
        for pat in _ANCHOR_PATS:
            m = pat.search(user)
            if m:
                cand = m.group(1).strip()
                # 过滤短噪音 (≤ 1 字 / 含数字)
                if len(cand) >= 2 and not any(c.isdigit() for c in cand):
                    start_location_text = cand
                    break

    # 半日 / 一日 时长估算
    estimated_hours = None
    if time_window == "一日":
        estimated_hours = 8
    elif time_window and time_window.startswith("半日_"):
        estimated_hours = 4

    # v1.8: "X 小时" 显式抽 (覆盖 time_window 估算)
    hours_match = _HOURS_PAT.search(user)
    if hours_match:
        estimated_hours = int(hours_match.group(1))

    # v1.9.2: must_visit 抽取 (多个匹配都收)
    must_visit: list[str] = []
    for pat in _MUST_VISIT_PATS:
        for m in pat.finditer(user):
            cand = m.group(1).strip()
            if len(cand) >= 2 and cand not in must_visit:
                must_visit.append(cand)

    out = {
        "city": city,
        "days": days,
        "traveler_type": traveler_type,
        "budget_level": budget_level,
        "pace": None,
        "preferences": preferences,
        "must_visit": must_visit,
        "avoid": [],
        "start_date": None,
        # v1.7 字段 (Profiler 还会做 server-time 注入 + constraint defaults)
        "time_window": time_window,
        "interests": interests,
        "constraints": {},
        "start_location_text": start_location_text,
        "estimated_hours": estimated_hours,
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


async def stub_planner_llm_stream(system: str, user: str):
    """Stream variant of stub_planner_llm — yields one chunk with empty stops.

    compose_one_day's empty-stops detection raises PlannerLLMError → routes.py
    fallback path takes over (_synthesize_fallback_route + transit compute).
    """
    yield json.dumps({"stops": []}, ensure_ascii=False)


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


def resolve_planner_llm_stream():
    """Return real qwen stream if DASHSCOPE_API_KEY is set, else stub stream."""
    if os.environ.get("DASHSCOPE_API_KEY"):
        from agents.planner import _default_qwen_stream

        return _default_qwen_stream
    return stub_planner_llm_stream


def resolve_questioner_llm() -> Callable[[str, str], Awaitable[str]]:
    """QuestionGenerator LLM resolver.

    优先用 QUESTIONER_API_KEY（DeepSeek/Kimi），回退到 Qwen，无 key 时返回 stub（空问题）。
    """
    if os.environ.get("QUESTIONER_API_KEY") or os.environ.get("DASHSCOPE_API_KEY"):
        from agents.questioner import _default_llm_call

        return _default_llm_call

    async def _stub(system: str, user: str) -> str:
        return '{"questions": []}'

    return _stub
