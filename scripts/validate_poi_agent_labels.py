"""Validate labels returned by the lower-level POI labeling agent.

This script is a guardrail only. It does not create or infer labels.

Expected input:
    data/poi_agent_labels.json

Run:
    PYTHONPATH=. python3 scripts/validate_poi_agent_labels.py
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

DATA_DIR = Path("data/mock_dianping")
LABELS_PATH = Path("data/poi_agent_labels.json")
SUMMARY_PATH = Path("data/poi_agent_label_summary.json")
CITIES = ("深圳", "上海", "西安")

TRAVELER_TYPES = {"情侣", "家庭亲子", "银发", "独行", "商务", "朋友团"}
MODIFIER_NAMES = {"轻量体力", "重文化", "重美食", "怕排队"}
POI_ROLES = {"city_essential", "persona_preferred", "meal", "connector", "fallback"}
UNIVERSAL_LEVELS = {"high", "medium", "low"}
PLANNING_TAGS = {
    "photo_friendly",
    "food_quality",
    "culture_friendly",
    "family_friendly",
    "couple_friendly",
    "group_friendly",
    "business_friendly",
    "senior_friendly",
    "solo_friendly",
    "quiet",
    "atmosphere",
    "good_value",
    "good_service",
    "fast_service",
    "transit_friendly",
    "rain_friendly",
    "night_friendly",
    "rest_friendly",
    "shopping_friendly",
    "first_visit_friendly",
    "landmark",
    "food",
    "private_room",
    "premium_food",
    "pet_friendly",
}
RISK_TAGS = {
    "queue_heavy",
    "slow_service",
    "pricey",
    "hard_to_find",
    "parking_hard",
    "facility_old",
    "smoky",
    "small_portion",
    "service_average",
    "portion_mismatch",
    "reservation_recommended",
    "walk_heavy",
    "crowded_weekend",
}
SUGGESTED_SLOTS = {"morning", "lunch", "afternoon", "afternoon_tea", "dinner", "evening"}

REQUIRED_FIELDS = {
    "traveler_types",
    "modifiers",
    "poi_role",
    "universal_level",
    "must_consider",
    "manual_priority",
    "planning_tags",
    "risk_tags",
    "district",
    "city_zone",
    "neighbor_zones",
    "suggested_slots",
    "min_stay_minutes",
    "max_stay_minutes",
    "confidence",
    "label_notes",
}


def load_source_ids(data_dir: Path) -> dict[str, set[str]]:
    ids: dict[str, set[str]] = {}
    for city in CITIES:
        path = data_dir / f"{city}.json"
        pois = json.loads(path.read_text(encoding="utf-8"))
        ids[city] = {str(poi.get("openshopid")) for poi in pois if poi.get("openshopid")}
    return ids


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def check_list_values(
    errors: list[str],
    *,
    city: str,
    shop_id: str,
    field: str,
    value: Any,
    allowed: set[str],
) -> None:
    if not isinstance(value, list):
        errors.append(f"{city}/{shop_id}: {field} must be list")
        return
    bad = sorted({str(item) for item in value if str(item) not in allowed})
    if bad:
        errors.append(f"{city}/{shop_id}: {field} has invalid values {bad}")


def validate_one(city: str, shop_id: str, label: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED_FIELDS - set(label))
    if missing:
        errors.append(f"{city}/{shop_id}: missing fields {missing}")

    check_list_values(
        errors,
        city=city,
        shop_id=shop_id,
        field="traveler_types",
        value=label.get("traveler_types"),
        allowed=TRAVELER_TYPES,
    )
    check_list_values(
        errors,
        city=city,
        shop_id=shop_id,
        field="planning_tags",
        value=label.get("planning_tags"),
        allowed=PLANNING_TAGS,
    )
    check_list_values(
        errors,
        city=city,
        shop_id=shop_id,
        field="risk_tags",
        value=label.get("risk_tags"),
        allowed=RISK_TAGS,
    )
    check_list_values(
        errors,
        city=city,
        shop_id=shop_id,
        field="suggested_slots",
        value=label.get("suggested_slots"),
        allowed=SUGGESTED_SLOTS,
    )

    modifiers = label.get("modifiers")
    if not isinstance(modifiers, dict):
        errors.append(f"{city}/{shop_id}: modifiers must be object")
    else:
        missing_modifiers = sorted(MODIFIER_NAMES - set(modifiers))
        if missing_modifiers:
            errors.append(f"{city}/{shop_id}: modifiers missing {missing_modifiers}")
        bad_modifiers = sorted(set(modifiers) - MODIFIER_NAMES)
        if bad_modifiers:
            errors.append(f"{city}/{shop_id}: modifiers invalid {bad_modifiers}")
        non_bool = sorted(k for k, v in modifiers.items() if not isinstance(v, bool))
        if non_bool:
            errors.append(f"{city}/{shop_id}: modifiers not boolean {non_bool}")

    if label.get("poi_role") not in POI_ROLES:
        errors.append(f"{city}/{shop_id}: invalid poi_role {label.get('poi_role')!r}")
    if label.get("universal_level") not in UNIVERSAL_LEVELS:
        errors.append(
            f"{city}/{shop_id}: invalid universal_level {label.get('universal_level')!r}"
        )
    if not isinstance(label.get("must_consider"), bool):
        errors.append(f"{city}/{shop_id}: must_consider must be boolean")

    priority = label.get("manual_priority")
    if not isinstance(priority, int) or not 0 <= priority <= 100:
        errors.append(f"{city}/{shop_id}: manual_priority must be integer 0-100")

    confidence = label.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        errors.append(f"{city}/{shop_id}: confidence must be number 0-1")

    min_stay = label.get("min_stay_minutes")
    max_stay = label.get("max_stay_minutes")
    if not isinstance(min_stay, int) or min_stay < 0:
        errors.append(f"{city}/{shop_id}: min_stay_minutes must be non-negative integer")
    if not isinstance(max_stay, int) or max_stay < 0:
        errors.append(f"{city}/{shop_id}: max_stay_minutes must be non-negative integer")
    if isinstance(min_stay, int) and isinstance(max_stay, int) and min_stay > max_stay:
        errors.append(f"{city}/{shop_id}: min_stay_minutes > max_stay_minutes")

    for field in ("district", "city_zone", "label_notes"):
        if not isinstance(label.get(field), str):
            errors.append(f"{city}/{shop_id}: {field} must be string")
    if not isinstance(label.get("neighbor_zones"), list):
        errors.append(f"{city}/{shop_id}: neighbor_zones must be list")

    return errors


def build_summary(labels: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for city, city_labels in labels.items():
        role_counter: Counter[str] = Counter()
        planning_counter: Counter[str] = Counter()
        risk_counter: Counter[str] = Counter()
        zone_counter: Counter[str] = Counter()
        for label in city_labels.values():
            role_counter[str(label.get("poi_role", "unknown"))] += 1
            planning_counter.update(as_list(label.get("planning_tags")))
            risk_counter.update(as_list(label.get("risk_tags")))
            zone_counter[str(label.get("city_zone", "unknown"))] += 1
        summary[city] = {
            "count": len(city_labels),
            "poi_roles": dict(role_counter.most_common()),
            "planning_tags": dict(planning_counter.most_common()),
            "risk_tags": dict(risk_counter.most_common()),
            "city_zones": dict(zone_counter.most_common()),
        }
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--labels", type=Path, default=LABELS_PATH)
    parser.add_argument("--summary-out", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--allow-partial", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.labels.exists():
        print(f"missing labels file: {args.labels}", file=sys.stderr)
        raise SystemExit(2)

    source_ids = load_source_ids(args.data_dir)
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    errors: list[str] = []

    if not isinstance(labels, dict):
        print("labels root must be object", file=sys.stderr)
        raise SystemExit(2)

    for city, city_labels in labels.items():
        if city not in source_ids:
            errors.append(f"unknown city: {city}")
            continue
        if not isinstance(city_labels, dict):
            errors.append(f"{city}: labels must be object keyed by openshopid")
            continue
        unknown_ids = sorted(set(city_labels) - source_ids[city])
        if unknown_ids:
            errors.append(f"{city}: unknown openshopid count={len(unknown_ids)} sample={unknown_ids[:5]}")
        missing_ids = sorted(source_ids[city] - set(city_labels))
        if missing_ids and not args.allow_partial:
            errors.append(f"{city}: missing labels count={len(missing_ids)} sample={missing_ids[:5]}")
        for shop_id, label in city_labels.items():
            if isinstance(label, dict):
                errors.extend(validate_one(city, shop_id, label))
            else:
                errors.append(f"{city}/{shop_id}: label must be object")

    summary = {
        "schema_version": "poi_agent_label_summary:v1",
        "label_file": str(args.labels),
        "allow_partial": bool(args.allow_partial),
        "error_count": len(errors),
        "errors_sample": errors[:50],
        "cities": build_summary(labels if isinstance(labels, dict) else {}),
    }
    args.summary_out.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("POI Agent 标签校验完成:")
    print(f"  labels: {args.labels}")
    print(f"  errors: {len(errors)}")
    print(f"  summary: {args.summary_out}")
    if errors:
        for error in errors[:20]:
            print(f"  - {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
