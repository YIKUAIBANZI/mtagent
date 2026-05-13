"""Profiler — parse free-text user input into a structured ParsedIntent.

LLM-driven. Designed to be testable by injecting an `llm_call` async fn.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, Optional

try:
    from zoneinfo import ZoneInfo  # py3.9+
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

from agents.anchor import resolve_anchor as _resolve_anchor
from agents.context import TripContext
from agents.trip_router import (
    DEFAULT_ANCHOR_RADIUS_KM,
    compute_safety_margin,
    infer_hub_type,
    route_trip_mode,
)
from dianping.schemas import ConstraintName, ModifierName, ParsedIntent, ProfilerOutput

_PROMPT_PATH = Path(__file__).parent / "prompts" / "profiler.md"


REQUIRED_FIELDS = ("city", "days", "traveler_type")


KEYWORD_RULES: dict[ModifierName, tuple[str, ...]] = {
    "重文化": ("博物馆", "历史", "文化", "古迹", "陕博", "碑林"),
    "重美食": ("美食", "吃", "小吃", "网红店", "陕菜", "凉皮", "肉夹馍"),
    "怕排队": ("不想排队", "省时间", "怕等", "工作日"),
}

ALL_MODIFIERS: tuple[ModifierName, ...] = ("轻量体力", "重文化", "重美食", "怕排队")
ALL_CONSTRAINTS: tuple[ConstraintName, ...] = (
    "avoid_queue",
    "avoid_walking",
    "avoid_cross_district",
    "need_meal",
)


def _apply_modifier_defaults(intent: ParsedIntent, user_text: str) -> None:
    """Fill intent.modifiers from traveler_type defaults + keyword scan.

    Mutates intent in place. Always populates all 4 modifier keys with bools.
    """
    text = (user_text or "").lower()
    # Default by traveler_type (only generates 轻量体力 default)
    if intent.traveler_type in ("银发", "家庭亲子"):
        intent.modifiers.setdefault("轻量体力", True)
    # Keyword scan (any-of)
    for mod, keywords in KEYWORD_RULES.items():
        if any(w.lower() in text for w in keywords):
            intent.modifiers[mod] = True
    # Backfill missing modifiers with False (explicit, never missing)
    for m in ALL_MODIFIERS:
        intent.modifiers.setdefault(m, False)


def _apply_constraint_defaults(intent: ParsedIntent) -> None:
    """Backfill v1.7 constraints with deterministic defaults.

    LLM may omit constraints; ensure all 4 keys present as bool.
    """
    if intent.traveler_type in ("银发", "家庭亲子"):
        intent.constraints.setdefault("avoid_walking", True)
    for c in ALL_CONSTRAINTS:
        intent.constraints.setdefault(c, False)


def _server_now_iso() -> str:
    """Current server time in Asia/Shanghai ISO 8601 (China hackathon target)."""
    if ZoneInfo is not None:
        return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    return datetime.now().astimezone().isoformat(timespec="seconds")


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
        # v1.7: inject server time into user message for "current departure" inference
        now_iso = _server_now_iso()
        user_msg = f"当前服务器时间: {now_iso}\n\n{ctx.user_input.free_text}"
        raw = await self.llm_call(self._system_prompt, user_msg)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Profiler LLM did not return valid JSON: {raw[:200]}"
            ) from exc

        # v1.7: time_window 非 None 时, days 缺失自动当 1 (半日/一日 = 单日规划)
        if data.get("time_window") in (
            "半日_上午",
            "半日_下午",
            "半日_夜间",
            "一日",
        ) and not data.get("days"):
            data["days"] = 1

        # v1.7.3 简化默认: 真 LLM 可能不返 traveler_type (stub 已 backfill).
        # 单字段 backfill 让 ready_to_plan 不再因 traveler_type 缺失被拒.
        # city 仍需用户/LLM 给出, 没说才走 clarifying.
        if not data.get("traveler_type"):
            data["traveler_type"] = "情侣"

        # Build ParsedIntent — None values keep field optional/missing
        missing: list[str] = []
        for k in REQUIRED_FIELDS:
            v = data.get(k)
            if v in (None, "", 0):
                missing.append(k)

        # v1.7 即时出发字段 (全部 optional, LLM 没返回也安全)
        v17_extra = dict(
            time_window=data.get("time_window"),
            interests=data.get("interests") or [],
            constraints=data.get("constraints") or {},
            start_location_text=data.get("start_location_text"),
            start_with_meal=bool(data.get("start_with_meal") or False),
            estimated_hours=data.get("estimated_hours"),
            current_time=data.get("current_time") or now_iso,
        )

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
                **v17_extra,
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
                **v17_extra,
            )
            ready = True

        _apply_modifier_defaults(understood, ctx.user_input.free_text)
        _apply_constraint_defaults(understood)

        # v1.7.2: 天气感知 (best-effort, 失败不阻塞 profiler)
        if understood.city:
            try:
                from agents.weather import fetch_weather as _fetch_weather

                wx = await _fetch_weather(understood.city)
                understood.weather_hint = wx["hint"]
                understood.weather_raw = wx["raw"]
                understood.weather_temp_c = wx["temp_c"]
            except Exception as wxerr:
                understood.weather_hint = "unknown"
                ctx.log_event("Profiler", "weather_failed", {"error": str(wxerr)})

        # v1.8 trip_mode 路由 + anchor 解析

        # 1) Resolve anchor (best-effort, 失败不阻塞)
        if understood.start_location_text and understood.city:
            try:
                anchor = await _resolve_anchor(
                    understood.start_location_text, understood.city
                )
            except Exception as aerr:
                anchor = None
                ctx.log_event("Profiler", "anchor_failed", {"error": str(aerr)})
            if anchor is not None:
                understood.anchor_lng = anchor.lng
                understood.anchor_lat = anchor.lat
                understood.anchor_resolved_name = anchor.name

        # 2) Route trip_mode (规则路由, LLM 已抽 trip_mode 则尊重)
        if not understood.trip_mode:
            understood.trip_mode = route_trip_mode(understood, ctx.user_input.free_text)

        # 3) Layover: 推 hub_type + safety_margin
        if understood.trip_mode in ("layover_eat", "layover_explore"):
            if not understood.hub_type:
                understood.hub_type = infer_hub_type(understood.start_location_text)
            if understood.safety_margin_min is None:
                understood.safety_margin_min = compute_safety_margin(
                    understood.hub_type
                )

        # 4) Anchor_explore: 默认半径
        if (
            understood.trip_mode == "anchor_explore"
            and understood.anchor_radius_km is None
        ):
            understood.anchor_radius_km = DEFAULT_ANCHOR_RADIUS_KM

        # 5) 锚点解析失败 + 用户提了锚点 → 降级 landmark_must
        if (
            understood.start_location_text
            and understood.anchor_lng is None
            and understood.trip_mode
            in ("anchor_explore", "layover_eat", "layover_explore")
        ):
            understood.trip_mode = "landmark_must"

        ctx.intent = understood
        ctx.log_event(
            "Profiler",
            "done",
            {
                "ready_to_plan": ready,
                "missing_fields": missing,
                "time_window": understood.time_window,
                "start_with_meal": understood.start_with_meal,
                "estimated_hours": understood.estimated_hours,
                "weather_hint": understood.weather_hint,
                "weather_raw": understood.weather_raw,
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
