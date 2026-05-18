"""Usage: python scripts/validate_trip.py data/trips/trip_xxx.json

打印每个 variant × day 的 7 规则通过表. 调试用.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from agents.context import TripContext
from agents.route_validator import validate_day
from dianping.schemas import RouteDraft


def main(path: str) -> int:
    ctx_path = Path(path)
    if not ctx_path.exists():
        print(f"FILE NOT FOUND: {path}", file=sys.stderr)
        return 2

    data = json.loads(ctx_path.read_text(encoding="utf-8"))
    ctx = TripContext.model_validate(data)
    if not ctx.intent:
        print("trip has no intent, can't validate", file=sys.stderr)
        return 2

    variants: dict[str, RouteDraft] = ctx.variants or {}
    if not variants and ctx.draft_route:
        variants = {"main": ctx.draft_route}
    if not variants:
        print("trip has no variants nor draft_route", file=sys.stderr)
        return 2

    print(
        f"\nTrip: {ctx.trip_id}  city={ctx.intent.city}  "
        f"traveler={ctx.intent.traveler_type}  pace={ctx.intent.pace}"
    )
    print("=" * 100)

    for vname, route in variants.items():
        for day in route.days:
            report = validate_day(day, ctx.intent)
            mark = "PASS" if report.score == 1.0 else "FAIL"
            print(
                f"\n[{mark}] variant={vname}  day={day.day_index}  "
                f"stops={len(day.stops)}  score={report.passed_count}/{report.total}"
            )
            for c in report.checks:
                glyph = "OK " if c.passed else "X  "
                print(f"  {glyph} {c.name:20s} {c.detail}")

    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python scripts/validate_trip.py <trip.json>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
