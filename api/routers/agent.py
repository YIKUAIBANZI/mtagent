"""Agent v2 POI-first endpoints."""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from agents.amap_pool import prefetch_amap_pois
from agents.candidate_pool import build_candidate_pool
from agents.context import TripContext
from agents.planner_instant import load_city_pois_from_mock
from agents.poi_decision_signals import get_decision_signals
from agents.profiler import Profiler
from api.routers._shared import cookie_key as _cookie_key
from api.stub_llm import resolve_profiler_llm
from dianping.schemas import POI, UserInput

router = APIRouter(prefix="/api/agent")


class PoiCandidatesRequest(BaseModel):
    free_text: str
    traveler_type: Optional[str] = None
    pace: Optional[str] = None
    interests: list[str] = []


def _poi_payload(poi: POI) -> dict:
    en = poi.enriched
    role = en.poi_role if en else ""
    tags = list(en.planning_tags[:4]) if en else []
    decision_signals = get_decision_signals(poi.openshopid)
    return {
        "openshopid": poi.openshopid,
        "name": poi.name,
        "desc": poi.shopDesc or poi.address or "本地路线候选 POI",
        "city": poi.city,
        "categories": poi.categories,
        "role": role,
        "tags": tags,
        "star": poi.star,
        "avgprice": poi.avgprice,
        "latitude": poi.latitude,
        "longitude": poi.longitude,
        "address": poi.address,
        "headPic": poi.headPic,
        "decision_signals": decision_signals,
    }


def _unique_top(pois: list[POI], limit: int) -> list[POI]:
    seen: set[str] = set()
    out: list[POI] = []
    for poi in pois:
        if poi.openshopid in seen:
            continue
        seen.add(poi.openshopid)
        out.append(poi)
        if len(out) >= limit:
            break
    return out


@router.post("/poi-candidates")
async def poi_candidates(body: PoiCandidatesRequest, request: Request):
    """Return grouped POI candidates for the standalone mtagentv2 Agent page.

    This endpoint intentionally stops before route generation. It creates a
    TripContext, parses the user's one-line intent, prepares the same local/Amap
    POI pool used by the instant planner, and returns grouped cards for the UI.
    """
    from agents.user_profile_store import get_profile

    cookie_key = _cookie_key(request)
    profile = get_profile(cookie_key) if cookie_key else None

    ctx = TripContext.create(user_input=UserInput(free_text=body.free_text))
    ctx.profile = profile

    profiler = Profiler(llm_call=resolve_profiler_llm())
    out = await profiler.run(ctx)
    intent = out.understood

    # Homepage chips are explicit UI choices. They should override profiler
    # defaults, while free-text still contributes city, POI names, slots, etc.
    if body.traveler_type:
        intent.traveler_type = body.traveler_type  # type: ignore[assignment]
    if body.pace:
        intent.pace = body.pace  # type: ignore[assignment]
    for interest in body.interests or []:
        if interest and interest not in intent.interests:
            intent.interests.append(interest)
        if interest and interest not in intent.preferences:
            intent.preferences.append(interest)
    ctx.intent = intent

    base_pois = load_city_pois_from_mock(intent.city)
    try:
        pois = await asyncio.wait_for(prefetch_amap_pois(intent, base_pois), timeout=8)
    except Exception:
        pois = base_pois
    if not pois:
        pois = base_pois
    ctx.pre_fetched_pois = pois or []

    pool = build_candidate_pool(pois=ctx.pre_fetched_pois, intent=intent, variant="main")
    attractions = _unique_top(pool.city_essential + pool.persona_preferred, 8)
    food = _unique_top(pool.meal, 8)
    entertainment = _unique_top(pool.connector, 8)

    ctx.candidate_pois = _unique_top(attractions + food + entertainment, 40)
    ctx.save()

    return {
        "trip_id": ctx.trip_id,
        "ready_to_plan": out.ready_to_plan,
        "missing_fields": out.missing_fields,
        "intent": intent.model_dump(mode="json"),
        "groups": {
            "attractions": [_poi_payload(p) for p in attractions],
            "food": [_poi_payload(p) for p in food],
            "entertainment": [_poi_payload(p) for p in entertainment],
        },
    }
