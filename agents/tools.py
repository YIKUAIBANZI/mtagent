"""Agent tool layer.

Pure-function wrappers around DianpingClient + planning intelligence helpers.
Agents call these; agents do NOT import client/mock_server directly.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import datetime, time
from typing import Optional

from pydantic import BaseModel, Field

from dianping.client import DianpingClient
from dianping.schemas import (
    POI,
    PaceLevel,
    ParsedIntent,
    SearchRecord,
    SlotName,
    TravelerType,
)


# =================================================================
# Day template
# =================================================================


class DaySlotSpec(BaseModel):
    """One slot spec in a day template."""

    name: SlotName
    start: time
    end: time
    category_pool: list[str] = Field(default_factory=list)
    is_meal: bool = False
    optional: bool = False
    min_stay_minutes: int = 60
    max_stay_minutes: int = 120


class DayTemplate(BaseModel):
    day_index: int
    slots: list[DaySlotSpec] = Field(default_factory=list)


_DEFAULT_PACE: dict[str, PaceLevel] = {
    "情侣": "适中",
    "家庭亲子": "佛系",
    "银发": "佛系",
    "独行": "适中",
    "商务": "暴走",
    "朋友团": "暴走",
}


def default_pace_for_traveler(traveler_type: TravelerType) -> PaceLevel:
    """Map traveler_type to default pace."""
    return _DEFAULT_PACE.get(traveler_type, "适中")


# Slot specs by name (start/end immutable; category/min_stay configurable per pace)
_SLOT_DEFS: dict[str, dict] = {
    "上午景点": {
        "start": time(9, 0),
        "end": time(12, 0),
        "category_pool": ["休闲娱乐", "亲子"],
        "is_meal": False,
        "optional": False,
        "min_stay_minutes": 60,
        "max_stay_minutes": 180,
    },
    "午饭": {
        "start": time(12, 0),
        "end": time(13, 30),
        "category_pool": ["美食"],
        "is_meal": True,
        "optional": False,
        "min_stay_minutes": 60,
        "max_stay_minutes": 90,
    },
    "下午": {
        "start": time(13, 30),
        "end": time(17, 0),
        "category_pool": ["购物", "休闲娱乐", "丽人"],
        "is_meal": False,
        "optional": False,
        "min_stay_minutes": 90,
        "max_stay_minutes": 180,
    },
    "下午茶": {
        "start": time(15, 30),
        "end": time(16, 30),
        "category_pool": ["美食"],
        "is_meal": False,
        "optional": True,
        "min_stay_minutes": 30,
        "max_stay_minutes": 60,
    },
    "晚饭": {
        "start": time(18, 0),
        "end": time(20, 0),
        "category_pool": ["美食"],
        "is_meal": True,
        "optional": False,
        "min_stay_minutes": 60,
        "max_stay_minutes": 120,
    },
    "夜场": {
        "start": time(20, 0),
        "end": time(22, 0),
        "category_pool": ["休闲娱乐", "K歌"],
        "is_meal": False,
        "optional": True,
        "min_stay_minutes": 60,
        "max_stay_minutes": 120,
    },
}

_PACE_SLOTS: dict[PaceLevel, list[str]] = {
    "暴走": ["上午景点", "午饭", "下午", "下午茶", "晚饭", "夜场"],
    "适中": ["上午景点", "午饭", "下午", "晚饭"],
    "佛系": ["上午景点", "午饭", "下午", "晚饭"],
}


def generate_day_template(
    *,
    days: int,
    traveler_type: TravelerType,
    pace: Optional[PaceLevel] = None,
) -> list[DayTemplate]:
    """Build deterministic day templates for the trip duration."""
    pace_resolved = pace or default_pace_for_traveler(traveler_type)
    slot_names = _PACE_SLOTS[pace_resolved]
    templates: list[DayTemplate] = []
    for d in range(days):
        slots = [DaySlotSpec(name=n, **_SLOT_DEFS[n]) for n in slot_names]
        templates.append(DayTemplate(day_index=d, slots=slots))
    return templates


# =================================================================
# Client wrappers (thin)
# =================================================================


async def search_pois(
    client: DianpingClient,
    **params,
) -> list[SearchRecord]:
    """Wrap client.search; pure delegation in v0."""
    return await client.search(**params)


async def batch_get_poi_details(
    client: DianpingClient,
    ids: list[str],
) -> dict[str, POI]:
    """Wrap client.batch_get_poi; chunks > 100 ids."""
    if len(ids) <= 100:
        return await client.batch_get_poi(ids)
    out: dict[str, POI] = {}
    for i in range(0, len(ids), 100):
        out.update(await client.batch_get_poi(ids[i : i + 100]))
    return out


# =================================================================
# Cluster (anchor & orbit)
# =================================================================


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def cluster_anchor_orbit(
    pois: list[POI],
    k: int,
    max_radius_km: float = 5.0,
) -> list[list[POI]]:
    """Lightweight K-means on lat/lng to enforce 'no cross-district' rule.

    Returns k clusters of POIs. POIs more than max_radius_km from any centroid
    are dropped (rare).
    """
    if not pois or k <= 0:
        return []
    if k >= len(pois):
        return [[p] for p in pois]

    # K-means++ style init: pick first POI, then iteratively pick the POI
    # FARTHEST from any existing centroid. This ensures clusters span the data
    # geography rather than collapsing into one neighborhood.
    centroids: list[tuple[float, float]] = [(pois[0].latitude, pois[0].longitude)]
    for _ in range(k - 1):
        best_idx = 0
        best_min_d = -1.0
        for i, p in enumerate(pois):
            min_d = min(
                _haversine_km(p.latitude, p.longitude, c[0], c[1]) for c in centroids
            )
            if min_d > best_min_d:
                best_min_d = min_d
                best_idx = i
        centroids.append((pois[best_idx].latitude, pois[best_idx].longitude))

    # K-means iterations — assign EVERY POI to nearest centroid (no drops here);
    # max_radius_km is enforced as a post-process tightness filter so distant
    # POIs don't poison cluster centroids but still get rejected from the final
    # day plan (preserving the 'no cross-district per day' rule).
    groups: dict[int, list[POI]] = defaultdict(list)
    for _ in range(20):
        groups = defaultdict(list)
        for p in pois:
            best, best_d = 0, float("inf")
            for i, (clat, clng) in enumerate(centroids):
                d = _haversine_km(p.latitude, p.longitude, clat, clng)
                if d < best_d:
                    best_d = d
                    best = i
            groups[best].append(p)
        new_centroids: list[tuple[float, float]] = []
        for i in range(k):
            members = groups.get(i, [])
            if members:
                new_centroids.append(
                    (
                        sum(m.latitude for m in members) / len(members),
                        sum(m.longitude for m in members) / len(members),
                    )
                )
            else:
                new_centroids.append(centroids[i])
        if new_centroids == centroids:
            break
        centroids = new_centroids

    # Tightness filter: keep only POIs within max_radius_km of THEIR centroid.
    final: list[list[POI]] = []
    for i in range(k):
        members = groups.get(i, [])
        clat, clng = centroids[i]
        tight = [
            p
            for p in members
            if _haversine_km(p.latitude, p.longitude, clat, clng) <= max_radius_km
        ]
        final.append(tight)
    return final


# =================================================================
# Business hours
# =================================================================

_HOUR_RE = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")


def check_business_hours(poi: POI, visit_time: datetime) -> bool:
    """True if poi.business_hour contains visit_time. Empty hour string = always open."""
    if not poi.business_hour:
        return True  # tolerate missing data
    visit_minutes = visit_time.hour * 60 + visit_time.minute
    for m in _HOUR_RE.finditer(poi.business_hour):
        start = int(m.group(1)) * 60 + int(m.group(2))
        end = int(m.group(3)) * 60 + int(m.group(4))
        if start <= visit_minutes <= end:
            return True
    return False


# =================================================================
# Intent-based filtering
# =================================================================

_BUDGET_BANDS: dict[str, tuple[int, int]] = {
    "性价比": (0, 100),
    "适中": (100, 300),
    "精致": (300, 100000),
}


def filter_by_intent_constraints(pois: list[POI], intent: ParsedIntent) -> list[POI]:
    """Drop POIs that violate intent.avoid / budget mismatch.

    must_visit POIs are always kept regardless.
    """
    must = list(intent.must_visit or [])
    avoid = list(intent.avoid or [])
    budget = intent.budget_level

    out: list[POI] = []
    for p in pois:
        # must_visit override (by name match)
        if any(m and m in p.name for m in must):
            out.append(p)
            continue
        # avoid (name OR category contains)
        if any(
            (a and (a in p.name or any(a in c for c in p.categories))) for a in avoid
        ):
            continue
        # budget (only for food categories)
        if budget and "美食" in p.categories and p.avgprice > 0:
            lo, hi = _BUDGET_BANDS[budget]
            if not (lo <= p.avgprice <= hi):
                continue
        out.append(p)
    return out


# =================================================================
# Ranker (basic by traveler_type)
# =================================================================

_TRAVELER_TAG_BIAS: dict[str, list[str]] = {
    "情侣": ["适合约会", "氛围佳", "出片漂亮", "环境优雅"],
    "家庭亲子": ["亲子友好", "干净卫生", "包厢私密"],
    "银发": ["老字号", "环境优雅", "干净卫生"],
    "独行": ["性价比高", "出片漂亮", "本地特色"],
    "商务": ["包厢私密", "服务好", "环境优雅"],
    "朋友团": ["适合聚会", "氛围佳", "出片漂亮"],
}


def rank_by_traveler_type(pois: list[POI], traveler_type: str) -> list[POI]:
    """Rank by hit-weight on tags relevant to traveler_type, then star descending."""
    bias_tags = _TRAVELER_TAG_BIAS.get(traveler_type, [])

    def score(p: POI) -> float:
        tag_score = sum(rt.hit for rt in p.reviewTags if rt.tag in bias_tags)
        return tag_score + p.star * 50

    return sorted(pois, key=score, reverse=True)
