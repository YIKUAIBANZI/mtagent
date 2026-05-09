"""Planner — deterministic orchestration + single LLM compose.

Pipeline:
  1. day_template by pace (default by traveler_type)
  2. anchor selection per day (city's well-known districts)
  3. parallel search by category × anchor → candidate ids
  4. batch_get_poi_details → full POI objects
  5. cluster by k=days (≤ 5km radius)
  6. filter by business hours per slot's middle time (using start_date)
  7. filter by intent constraints (avoid / budget / must_visit)
  8. rank by traveler_type
  9. single LLM call for narrative composition
  10. parse + validate RouteDraft (with fallback synthesis if LLM returns empty)
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Awaitable, Callable, Optional

from agents.context import TripContext
from agents.tools import (
    DayTemplate,
    batch_get_poi_details,
    check_business_hours,
    cluster_anchor_orbit,
    default_pace_for_traveler,
    filter_by_intent_constraints,
    generate_day_template,
    rank_by_traveler_type,
    search_pois,
)
from dianping.client import DianpingClient
from dianping.schemas import (
    DayPlan,
    ParsedIntent,
    POI,
    RouteDraft,
    Stop,
    TimeSlot,
)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "planner.md"


# Hand-curated anchors per city (centroid lat/lng for known business districts).
_CITY_ANCHORS: dict[str, list[tuple[str, float, float]]] = {
    "深圳": [
        ("福田CBD", 22.5429, 114.0596),
        ("华侨城", 22.5430, 113.9847),
        ("海岸城", 22.5187, 113.9415),
        ("万象天地", 22.5413, 113.9290),
        ("东门老街", 22.5483, 114.1183),
    ],
    "上海": [
        ("陆家嘴", 31.2397, 121.4990),
        ("南京路步行街", 31.2360, 121.4730),
        ("新天地", 31.2197, 121.4760),
        ("徐家汇", 31.1953, 121.4373),
        ("豫园", 31.2273, 121.4920),
    ],
    "西安": [
        ("钟楼", 34.2614, 108.9398),
        ("大雁塔", 34.2218, 108.9647),
        ("回民街", 34.2628, 108.9384),
        ("大唐不夜城", 34.2196, 108.9648),
        ("永宁门", 34.2543, 108.9380),
    ],
}


def _pick_anchors(
    city: str, days: int, must_visit: list[str]
) -> list[tuple[str, float, float]]:
    pool = _CITY_ANCHORS.get(city, [])
    if not pool:
        return [("市中心", 0.0, 0.0)] * days
    preferred = [a for a in pool if any(m in a[0] for m in must_visit)]
    rest = [a for a in pool if a not in preferred]
    chosen = (preferred + rest)[:days]
    while len(chosen) < days:
        chosen.append(pool[len(chosen) % len(pool)])
    return chosen


class Planner:
    def __init__(
        self,
        client: DianpingClient,
        llm_call: Optional[Callable[[str, str], Awaitable[str]]] = None,
    ):
        self.client = client
        self.llm_call = llm_call or _default_qwen_call
        self._system_prompt = (
            _PROMPT_PATH.read_text(encoding="utf-8") if _PROMPT_PATH.exists() else ""
        )

    async def run(self, ctx: TripContext) -> RouteDraft:
        intent = ctx.intent
        if intent is None:
            raise ValueError(
                "Planner requires ctx.intent to be set (run Profiler first)"
            )

        ctx.log_event("Planner", "start", {})

        # 1. Day templates
        pace = intent.pace or default_pace_for_traveler(intent.traveler_type)
        templates = generate_day_template(
            days=intent.days,
            traveler_type=intent.traveler_type,
            pace=pace,
        )

        # 2. Anchors
        anchors = _pick_anchors(intent.city, intent.days, intent.must_visit)

        # 3. Parallel search per anchor × distinct category
        all_categories = {
            c for tmpl in templates for slot in tmpl.slots for c in slot.category_pool
        }
        search_tasks = []
        for anchor_name, lat, lng in anchors:
            for cat in all_categories:
                search_tasks.append(
                    search_pois(
                        self.client,
                        city=intent.city,
                        latitude=lat,
                        longitude=lng,
                        radius=5000,
                        categories=cat,
                        limit=25,
                    )
                )
        results = await asyncio.gather(*search_tasks, return_exceptions=True)
        all_ids: set[str] = set()
        for r in results:
            if isinstance(r, Exception):
                continue
            all_ids.update(rec.openshopid for rec in r)

        # 4. Batch detail
        if not all_ids:
            ctx.log_event("Planner", "no_candidates", {})
            ctx.draft_route = RouteDraft(
                days=[
                    DayPlan(day_index=i, anchor_district=anchors[i][0], stops=[])
                    for i in range(intent.days)
                ]
            )
            ctx.save()
            return ctx.draft_route

        details = await batch_get_poi_details(self.client, list(all_ids))
        pois = list(details.values())

        # 5. Cluster (forces no-cross-district per day)
        clusters = cluster_anchor_orbit(pois, k=intent.days, max_radius_km=5.0)

        # 6+7. Filter per cluster (business_hour at slot midpoint, intent constraints)
        start_date = intent.start_date or datetime.now().date()
        filtered_clusters: list[list[POI]] = []
        for di, cluster in enumerate(clusters):
            day_date = start_date + timedelta(days=di)
            mid_time = datetime.combine(day_date, time(12, 30))
            kept = [p for p in cluster if check_business_hours(p, mid_time)]
            kept = filter_by_intent_constraints(kept, intent)
            filtered_clusters.append(kept)

        # 8. Rank
        ranked_clusters = [
            rank_by_traveler_type(c, intent.traveler_type) for c in filtered_clusters
        ]

        # Snapshot candidates into context (audit trail)
        ctx.candidate_pois = [p for c in ranked_clusters for p in c]

        # 9. LLM compose
        compose_payload = self._build_compose_payload(
            intent, templates, anchors, ranked_clusters
        )
        raw = await self.llm_call(self._system_prompt, compose_payload)
        try:
            llm_data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Planner LLM did not return valid JSON: {raw[:200]}"
            ) from exc

        # 10. Build RouteDraft from LLM output, attaching real POI objects
        days_out: list[DayPlan] = []
        poi_index = {p.openshopid: p for p in ctx.candidate_pois}

        for d, day_data in enumerate(llm_data.get("days", [])):
            stops: list[Stop] = []
            for s in day_data.get("stops", []) or []:
                pid = s.get("poi_openshopid")
                poi = poi_index.get(pid)
                if poi is None:
                    continue
                slot_name = s.get("slot_name", "上午景点")
                slot_def = next(
                    (slot for slot in templates[d].slots if slot.name == slot_name),
                    templates[d].slots[0],
                )
                stops.append(
                    Stop(
                        poi=poi,
                        slot=TimeSlot(
                            name=slot_name, start=slot_def.start, end=slot_def.end
                        ),
                        arrival_time=_parse_time(s.get("arrival_time"), slot_def.start),
                        leave_time=_parse_time(s.get("leave_time"), slot_def.end),
                        transport_to_next_minutes=int(
                            s.get("transport_to_next_minutes", 30)
                        ),
                    )
                )
            days_out.append(
                DayPlan(
                    day_index=day_data.get("day_index", d),
                    anchor_district=day_data.get(
                        "anchor_district", anchors[d][0] if d < len(anchors) else ""
                    ),
                    stops=stops,
                )
            )

        # If LLM gave no stops at all, synthesize a basic route
        if (not days_out or all(len(d.stops) == 0 for d in days_out)) and any(
            ranked_clusters
        ):
            days_out = _synthesize_fallback_route(
                templates, anchors, ranked_clusters, intent
            )

        route = RouteDraft(
            days=days_out,
            summary=llm_data.get("summary", ""),
        )
        ctx.draft_route = route
        ctx.log_event("Planner", "done", {"day_count": len(route.days)})
        ctx.save()
        return route

    def _build_compose_payload(
        self,
        intent: ParsedIntent,
        templates: list[DayTemplate],
        anchors: list[tuple[str, float, float]],
        ranked_clusters: list[list[POI]],
    ) -> str:
        """Format input payload for the Planner LLM call."""
        days_input = []
        for d, (tmpl, anchor, cluster) in enumerate(
            zip(templates, anchors, ranked_clusters)
        ):
            slots_input = [
                {
                    "name": s.name,
                    "start": s.start.strftime("%H:%M"),
                    "end": s.end.strftime("%H:%M"),
                    "category_pool": s.category_pool,
                    "is_meal": s.is_meal,
                    "min_stay_minutes": s.min_stay_minutes,
                    "max_stay_minutes": s.max_stay_minutes,
                }
                for s in tmpl.slots
            ]
            poi_brief = [
                {
                    "openshopid": p.openshopid,
                    "name": p.name,
                    "categories": p.categories,
                    "avgprice": p.avgprice,
                    "star": p.star,
                    "review_tags_top3": [
                        {"tag": rt.tag, "hit": rt.hit}
                        for rt in sorted(p.reviewTags, key=lambda x: -x.hit)[:3]
                    ],
                    "business_hour": p.business_hour,
                }
                for p in cluster[:30]
            ]
            days_input.append(
                {
                    "day_index": d,
                    "anchor_district": anchor[0],
                    "slots": slots_input,
                    "candidates": poi_brief,
                }
            )
        return json.dumps(
            {
                "intent": {
                    "city": intent.city,
                    "days": intent.days,
                    "traveler_type": intent.traveler_type,
                    "budget_level": intent.budget_level,
                    "preferences": intent.preferences,
                    "must_visit": intent.must_visit,
                    "avoid": intent.avoid,
                },
                "days_input": days_input,
            },
            ensure_ascii=False,
        )


def _parse_time(s: Optional[str], default: time) -> time:
    if not s:
        return default
    try:
        h, m = s.split(":")
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        return default


def _synthesize_fallback_route(
    templates,
    anchors,
    ranked_clusters,
    intent,
) -> list[DayPlan]:
    """When LLM returned empty (e.g., test stub), build a deterministic fallback.

    Pick the top-ranked candidate per slot from the day's cluster.
    """
    days_out: list[DayPlan] = []
    for d, (tmpl, anchor, cluster) in enumerate(
        zip(templates, anchors, ranked_clusters)
    ):
        used: set[str] = set()
        stops: list[Stop] = []
        for slot in tmpl.slots:
            if slot.optional:
                continue
            picked: Optional[POI] = None
            for p in cluster:
                if p.openshopid in used:
                    continue
                if any(c in slot.category_pool for c in p.categories):
                    picked = p
                    break
            if picked is None:
                continue
            used.add(picked.openshopid)
            stops.append(
                Stop(
                    poi=picked,
                    slot=TimeSlot(name=slot.name, start=slot.start, end=slot.end),
                    arrival_time=slot.start,
                    leave_time=slot.end,
                    transport_to_next_minutes=30,
                )
            )
        days_out.append(
            DayPlan(
                day_index=d,
                anchor_district=anchor[0],
                stops=stops,
            )
        )
    return days_out


async def _default_qwen_call(system: str, user: str) -> str:
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
        temperature=0.3,
        max_tokens=4000,
        extra_body={"enable_thinking": False},
    )
    return resp.choices[0].message.content or "{}"
