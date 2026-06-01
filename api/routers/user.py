"""User profile endpoints: GET/PUT /api/user/profile."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from api.routers._shared import cookie_key as _cookie_key

router = APIRouter(prefix="/api")


@router.get("/user/profile")
async def get_user_profile(request: Request):
    """Return current cookie's UserProfile, or null if first visit."""
    from agents.user_profile_store import get_profile

    cookie_key = _cookie_key(request)
    profile = get_profile(cookie_key)
    return profile.model_dump(mode="json") if profile else None


class _UpdateProfileBody(BaseModel):
    modifiers: Optional[dict[str, bool]] = None
    interests_text: Optional[str] = None


@router.put("/user/profile")
async def update_user_profile(body: _UpdateProfileBody, request: Request):
    from agents.user_profile_store import upsert_profile

    cookie_key = _cookie_key(request)
    if not cookie_key:
        raise HTTPException(400, "no cookie_key — middleware not active?")
    profile = upsert_profile(
        cookie_key,
        modifiers=body.modifiers,
        interests_text=body.interests_text,
    )
    return profile.model_dump(mode="json")


def _lookup_poi_best_effort(poi_id: str):
    """从 poi_cache 查 POI (best-effort)。查不到返 None → love/reject 静默跳过。
    带标签 POI 的主捕获走 adjust 钩子 (那里直接持有 POI 对象, 见 Task 7)。"""
    if not poi_id:
        return None
    try:
        from agents.adjuster import _load_cache
        from dianping.schemas import POI

        raw = _load_cache().get(poi_id)
        return POI.model_validate(raw) if isinstance(raw, dict) else None
    except Exception:
        return None


class _SignalBody(BaseModel):
    action: str  # love | reject | dislike | visited
    poi_id: Optional[str] = None
    poi_name: Optional[str] = None


@router.post("/user/signal")
async def post_signal(body: _SignalBody, request: Request):
    """统一行为信号入口: love/reject/dislike(需 poi) | visited(用 poi_name)。"""
    from agents.user_profile_store import apply_signal

    key = _cookie_key(request)
    poi = None
    if body.poi_id and body.action in ("love", "reject", "dislike"):
        poi = _lookup_poi_best_effort(body.poi_id)
    profile = apply_signal(key, body.action, poi=poi, poi_name=body.poi_name)
    return profile.model_dump(mode="json")
