"""Trip 后续交互: GET /plan/{id}, POST /plan/{id}/answer, .../adjust, .../refine."""

from __future__ import annotations

import os
from typing import AsyncIterator, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.context import TripContext
from api.routers._shared import cookie_key as _cookie_key
from api.services.adjust import stream_adjust_events
from api.services.variants import run_variants
from api.sse import format_event
from api.stub_llm import (
    resolve_planner_llm,
    resolve_planner_llm_stream,
    resolve_profiler_llm,
)

router = APIRouter(prefix="/api")


@router.get("/plan/{trip_id}")
async def get_trip(trip_id: str):
    """Retrieve a saved TripContext by trip_id."""
    try:
        ctx = TripContext.load(trip_id)
        return ctx.model_dump(mode="json")
    except FileNotFoundError:
        raise HTTPException(404, f"trip not found: {trip_id}")


class ClarifyAnswerRequest(BaseModel):
    idx: int
    choice: Optional[str] = None
    skipped: bool = False


@router.post("/plan/{trip_id}/answer")
async def submit_clarify_answer(
    trip_id: str,
    body: ClarifyAnswerRequest,
):
    """接收一条澄清回答。还有问题则返回下一条；全答完则触发 variant 生成。"""
    from agents.amap import AmapClient as _AmapClient
    from agents.planner import Planner as _Planner
    from dianping.schemas import ClarifyAnswer

    try:
        ctx = TripContext.load(trip_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="trip not found")

    ctx.clarify_answers.append(
        ClarifyAnswer(idx=body.idx, choice=body.choice, skipped=body.skipped)
    )

    answered = len(ctx.clarify_answers)
    total = len(ctx.clarify_questions)

    async def event_stream() -> AsyncIterator[str]:
        if answered < total:
            next_q = ctx.clarify_questions[answered]
            ctx.save()
            yield format_event(
                "clarify.question",
                {"idx": next_q.idx, "text": next_q.text, "options": next_q.options},
            )
            return

        yield format_event("clarify.done", {})

        intent = ctx.intent
        if ctx.clarify_answers:
            notes = []
            for ans in ctx.clarify_answers:
                if not ans.skipped and ans.choice:
                    q_text = (
                        ctx.clarify_questions[ans.idx].text
                        if ans.idx < len(ctx.clarify_questions)
                        else ""
                    )
                    notes.append(f"{q_text}→{ans.choice}")
            if notes:
                extra = "【用户补充偏好】" + "；".join(notes)
                intent = intent.model_copy(update={"extra_clarify_context": extra})

        amap = _AmapClient(key=os.environ.get("AMAP_KEY", ""))
        planner = _Planner(
            client=None,
            llm_call=resolve_planner_llm(),
            llm_call_stream=resolve_planner_llm_stream(),
        )
        ctx.save()

        # 若无 Amap 预取结果（landmark_must 模式），从 mock 加载本地 POI
        from agents.planner_instant import load_city_pois_from_mock as _load_mock

        base_pois = ctx.pre_fetched_pois or _load_mock(intent.city) or []

        try:
            async for chunk in run_variants(ctx, intent, base_pois, amap, planner):
                yield chunk
        except Exception as exc:
            yield format_event("error", {"phase": "variants", "message": str(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/plan/{trip_id}/adjust")
async def adjust_trip(trip_id: str, body: dict, request: Request):
    """Adjust an existing trip: replace_stop / remove_stop / regenerate_day / switch_variant.

    Stream SSE: adjust.thinking → adjust.<op>_xxx → adjust.done.
    """
    from dianping.schemas import AdjustRequest

    try:
        req = AdjustRequest.model_validate(body)
    except Exception as e:
        raise HTTPException(400, f"invalid adjust request: {e}")

    try:
        ctx = TripContext.load(trip_id)
    except FileNotFoundError:
        raise HTTPException(404, f"trip not found: {trip_id}")

    cookie_key = _cookie_key(request)

    async def _gen():
        yield format_event(
            "adjust.thinking",
            {"operation": req.operation, "day_index": req.day_index},
        )
        async for ev in stream_adjust_events(ctx, req, cookie_key=cookie_key):
            yield ev
        yield format_event("adjust.done", {"trip_id": ctx.trip_id})

    return StreamingResponse(_gen(), media_type="text/event-stream")


class _RefineBody(BaseModel):
    user_text: str


@router.post("/plan/{trip_id}/refine")
async def refine_trip(trip_id: str, body: _RefineBody, request: Request):
    """自由文本 → A 偏好/B 调整/C 同句 路由.

    Stream SSE:
      refine.thinking → refine.routed
        → [refine.profile_updated]
        → [adjust.* 复用]
        → [refine.chat_reply]
      → refine.done
    """
    from agents.refiner import Refiner, build_trip_summary
    from agents.user_profile_store import get_profile, upsert_profile

    try:
        ctx = TripContext.load(trip_id)
    except FileNotFoundError:
        raise HTTPException(404, f"trip not found: {trip_id}")

    cookie_key = _cookie_key(request)
    user_text = (body.user_text or "").strip()
    if not user_text:
        raise HTTPException(400, "user_text empty")

    async def _gen():
        yield format_event("refine.thinking", {"phase": "解析中..."})

        # Read current profile (best-effort)
        current_profile = get_profile(cookie_key) if cookie_key else None
        trip_summary = build_trip_summary(ctx)

        refiner = Refiner(llm_call=resolve_profiler_llm())
        try:
            action = await refiner.run(
                user_text=user_text,
                trip_summary=trip_summary,
                current_profile=current_profile,
            )
        except Exception as e:
            yield format_event("refine.error", {"reason": f"refiner failed: {e}"})
            yield format_event("refine.done", {"trip_id": ctx.trip_id})
            return

        yield format_event("refine.thinking", {"reasoning": action.reasoning})

        routed = []
        if action.profile_update is not None:
            routed.append("profile")
        if action.adjust is not None:
            routed.append("adjust")
        if action.chat_reply and not routed:
            routed.append("chat")
        yield format_event(
            "refine.routed",
            {"actions": routed, "summary": action.reasoning},
        )

        # 1) profile update
        if action.profile_update is not None and cookie_key:
            mods = action.profile_update.modifiers_set or {}
            new_interest = action.profile_update.interests_text_append or ""
            # 拼到现有 interests_text 后 (去重)
            existing_text = (
                current_profile.interests_text
                if current_profile and current_profile.interests_text
                else ""
            )
            merged_text = _merge_interest_text(existing_text, new_interest)
            # 合并 modifiers (true 覆盖, false 也保留)
            merged_mods = dict(
                (current_profile.modifiers if current_profile else {}) or {}
            )
            merged_mods.update(mods)

            profile = upsert_profile(
                cookie_key,
                modifiers=merged_mods,
                interests_text=merged_text,
            )
            yield format_event(
                "refine.profile_updated",
                {
                    "modifiers": dict(profile.modifiers),
                    "interests_text": profile.interests_text,
                },
            )

        # 2) adjust path (复用 adjust.* 事件)
        if action.adjust is not None:
            async for ev in stream_adjust_events(
                ctx, action.adjust, cookie_key=cookie_key
            ):
                yield ev

        # 3) chat reply 兜底
        if action.chat_reply:
            yield format_event("refine.chat_reply", {"text": action.chat_reply})

        yield format_event("refine.done", {"trip_id": ctx.trip_id})

    return StreamingResponse(_gen(), media_type="text/event-stream")


def _merge_interest_text(existing: str, addition: str) -> str:
    """合并 interests_text — 用中文逗号分隔, 去重."""
    if not addition:
        return existing
    tokens: list[str] = []
    for chunk in (existing + "，" + addition).replace(",", "，").split("，"):
        t = chunk.strip()
        if t and t not in tokens:
            tokens.append(t)
    return "，".join(tokens)
