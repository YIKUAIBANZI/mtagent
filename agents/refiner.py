"""Refiner — 把用户在三方案出来后追加的自由文本路由成结构化操作.

输入: user_text + 当前 trip 摘要 + 当前 UserProfile (可空)
输出: RefineAction (profile_update + adjust + chat_reply 任意组合, 配 reasoning)

LLM-driven. 用 (system, user) -> json_text 签名, response_format=json_object.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Awaitable, Callable, Optional

from pydantic import BaseModel, Field

from agents.context import TripContext
from dianping.schemas import (
    AdjustRequest,
    ModifierName,
    UserProfile,
)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "refiner.md"


class ProfileUpdate(BaseModel):
    """偏好更新部分."""

    interests_text_append: Optional[str] = None
    modifiers_set: dict[ModifierName, bool] = Field(default_factory=dict)


class RefineAction(BaseModel):
    """Refiner 输出 — A 偏好 / B 调整 / C 同句 / D 兜底回复."""

    reasoning: str = ""
    profile_update: Optional[ProfileUpdate] = None
    adjust: Optional[AdjustRequest] = None
    chat_reply: Optional[str] = None


def build_trip_summary(ctx: TripContext) -> str:
    """从 ctx 拼一段给 LLM 看的简短摘要 (城市/天数/每天 stops/variants)."""
    if ctx.intent is None or ctx.draft_route is None:
        return "(trip not ready)"
    intent = ctx.intent
    lines = [f"{intent.city}·{intent.days}天, {intent.traveler_type or '不限同伴'}"]
    for di, day in enumerate(ctx.draft_route.days):
        parts = []
        for s in day.stops:
            parts.append(f"[{s.slot.name}] {s.poi.name}")
        lines.append(f"day {di} stops: " + " | ".join(parts))
    if ctx.variants:
        lines.append("variants: " + " / ".join(ctx.variants.keys()))
    return "\n".join(lines)


def build_profile_summary(profile: Optional[UserProfile]) -> str:
    """UserProfile 摘要 (null → '无')."""
    if profile is None:
        return "(无 UserProfile, 首次访问)"
    mods = {k: v for k, v in (profile.modifiers or {}).items() if v}
    return (
        f"modifiers: {json.dumps(mods, ensure_ascii=False)}\n"
        f"interests_text: {profile.interests_text or '(空)'}"
    )


class Refiner:
    """Refiner agent. LLM 单调用, 输出结构化 action."""

    def __init__(self, llm_call: Optional[Callable[[str, str], Awaitable[str]]] = None):
        self.llm_call = llm_call or _default_qwen_call
        self._system_prompt = (
            _PROMPT_PATH.read_text(encoding="utf-8") if _PROMPT_PATH.exists() else ""
        )

    async def run(
        self,
        *,
        user_text: str,
        trip_summary: str,
        current_profile: Optional[UserProfile],
    ) -> RefineAction:
        """单 LLM 调用 → 解析 → 返回 RefineAction.

        失败兜底: 返回 chat_reply 让前端知道"理解失败", 不 raise.
        """
        user_msg = (
            f"### 用户原话\n{user_text}\n\n"
            f"### 当前 trip 摘要\n{trip_summary}\n\n"
            f"### 当前 UserProfile\n{build_profile_summary(current_profile)}"
        )
        try:
            raw = await self.llm_call(self._system_prompt, user_msg)
            data = json.loads(raw)
        except (json.JSONDecodeError, Exception) as e:
            return RefineAction(
                reasoning="解析失败",
                chat_reply=f"没读懂这句话, 可以换个说法吗?(err: {type(e).__name__})",
            )

        # Build action — 容错: 字段不全也能用
        profile_update = None
        if isinstance(data.get("profile_update"), dict):
            try:
                profile_update = ProfileUpdate.model_validate(data["profile_update"])
            except Exception:
                profile_update = None

        adjust = None
        if isinstance(data.get("adjust"), dict):
            try:
                adjust = AdjustRequest.model_validate(data["adjust"])
                # validate operation enum
                if adjust.operation not in (
                    "replace_stop",
                    "remove_stop",
                    "regenerate_day",
                    "switch_variant",
                ):
                    adjust = None
            except Exception:
                adjust = None

        chat_reply = (
            data.get("chat_reply") if isinstance(data.get("chat_reply"), str) else None
        )
        reasoning = (
            data.get("reasoning") if isinstance(data.get("reasoning"), str) else ""
        )

        # 兜底: 如果三个 action 都为 None, 也没 chat_reply, 给一个 fallback reply
        if profile_update is None and adjust is None and not chat_reply:
            chat_reply = "嗯嗯, 有要调整的告诉我就行 😊"

        return RefineAction(
            reasoning=reasoning,
            profile_update=profile_update,
            adjust=adjust,
            chat_reply=chat_reply,
        )


async def _default_qwen_call(system: str, user: str) -> str:
    """Default LLM caller, qwen-plus via OpenAI-compatible API. JSON response."""
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
