"""Day-level transit computation — 4-mode (drive/walk/transit/cycle) routing per stop pair."""

from __future__ import annotations


async def compute_day_transits(day_plan, intent, amap):
    """Compute 4-mode transit for each consecutive stop pair in a day.

    Returns: (day_index, segments)
      segments = [{from_index, to_index, options: {mode: TransitInfo dict}, recommended}]
    """
    segments = []
    stops = day_plan.stops
    for i in range(len(stops) - 1):
        a = stops[i].poi
        b = stops[i + 1].poi
        options, recommended = await amap.get_transit_options(
            origin=(a.longitude, a.latitude),
            dest=(b.longitude, b.latitude),
            city=intent.city or "",
            traveler_type=intent.traveler_type,
        )
        segments.append(
            {
                "from_index": i,
                "to_index": i + 1,
                "options": {m: v.model_dump(mode="json") for m, v in options.items()},
                "recommended": recommended,
            }
        )
    return day_plan.day_index, segments
