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
