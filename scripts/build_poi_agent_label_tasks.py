"""Build POI labeling tasks for a lower-level labeling agent.

This script does not decide labels. It only slices raw POI data into stable
JSONL tasks, provides the allowed schema, and creates optional batch files.

Run:
    PYTHONPATH=. python3 scripts/build_poi_agent_label_tasks.py
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

CITIES = ("深圳", "上海", "西安")
DATA_DIR = Path("data/mock_dianping")
OUT_PATH = Path("data/poi_agent_label_tasks.jsonl")
BATCH_DIR = Path("data/poi_agent_label_batches")

TRAVELER_TYPES = ["情侣", "家庭亲子", "银发", "独行", "商务", "朋友团"]
MODIFIER_NAMES = ["轻量体力", "重文化", "重美食", "怕排队"]
POI_ROLES = ["city_essential", "persona_preferred", "meal", "connector", "fallback"]
UNIVERSAL_LEVELS = ["high", "medium", "low"]
PLANNING_TAGS = [
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
]
RISK_TAGS = [
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
]
SUGGESTED_SLOTS = ["morning", "lunch", "afternoon", "afternoon_tea", "dinner", "evening"]

LABELING_RULES = [
    "只根据给定 POI 字段标注，不创造 openshopid、POI、地址或真实世界事实。",
    "city_essential 只给真正城市地标或首次到访强相关地点，不给地标附近餐厅/KTV/酒店。",
    "餐饮 POI 优先标 meal；咖啡、商场、书店、轻量休息点优先标 connector。",
    "planning_tags 必须有明确字段、reviewTags、UGC 或名称/地址证据。",
    "risk_tags 必须保守；queue_heavy 只表示明确排队/等位风险，slow_service 不等于 queue_heavy。",
    "suggested_slots 要服务路线节奏：meal 用 lunch/dinner，夜景用 evening，地标常用 morning/afternoon。",
    "confidence < 0.6 时仍可输出，但 label_notes 必须说明不确定原因。",
]


def compact_text(value: Any, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:max_chars]


def compact_ugc(ugcs: list[dict[str, Any]], max_items: int, max_chars: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for ugc in ugcs[:max_items]:
        content = compact_text(ugc.get("content"), max_chars)
        if not content:
            continue
        items.append(
            {
                "score": ugc.get("score", 0),
                "star": ugc.get("star", 0),
                "content": content,
            }
        )
    return items


def build_task(
    poi: dict[str, Any],
    *,
    ugc_items: int,
    ugc_chars: int,
) -> dict[str, Any]:
    city = str(poi.get("city") or "")
    shop_id = str(poi.get("openshopid") or "")
    return {
        "schema_version": "poi_agent_label_task:v1",
        "task_id": f"{city}:{shop_id}",
        "city": city,
        "openshopid": shop_id,
        "input": {
            "name": poi.get("name", ""),
            "branch_name": poi.get("branch_name", ""),
            "address": poi.get("address", ""),
            "district": poi.get("district", ""),
            "latitude": poi.get("latitude"),
            "longitude": poi.get("longitude"),
            "categories": poi.get("categories") or [],
            "star": poi.get("star", 0),
            "reviewCount": poi.get("reviewCount", 0),
            "avgprice": poi.get("avgprice", 0),
            "business_hour": poi.get("business_hour", ""),
            "reviewTags": poi.get("reviewTags") or [],
            "special": poi.get("special") or [],
            "queueable": poi.get("queueable", False),
            "bookable": poi.get("bookable", False),
            "isBlackPearl": poi.get("isBlackPearl", 0),
            "dishs": poi.get("dishs") or [],
            "ugc_excerpt": compact_ugc(poi.get("ugcs") or [], ugc_items, ugc_chars),
        },
        "allowed_values": {
            "traveler_types": TRAVELER_TYPES,
            "modifiers": MODIFIER_NAMES,
            "poi_role": POI_ROLES,
            "universal_level": UNIVERSAL_LEVELS,
            "planning_tags": PLANNING_TAGS,
            "risk_tags": RISK_TAGS,
            "suggested_slots": SUGGESTED_SLOTS,
        },
        "required_output": {
            "traveler_types": ["array of allowed traveler_types"],
            "modifiers": {name: "boolean" for name in MODIFIER_NAMES},
            "poi_role": "one allowed poi_role",
            "universal_level": "high|medium|low",
            "must_consider": "boolean",
            "manual_priority": "integer 0-100",
            "planning_tags": ["array of allowed planning_tags"],
            "risk_tags": ["array of allowed risk_tags"],
            "district": "string; prefer input.district when reliable",
            "city_zone": "string such as west|center|east|south|north|unknown",
            "neighbor_zones": ["array of neighboring zone strings"],
            "suggested_slots": ["array of allowed suggested_slots"],
            "min_stay_minutes": "integer",
            "max_stay_minutes": "integer",
            "confidence": "number 0-1",
            "label_notes": "short evidence-based Chinese note",
        },
        "labeling_rules": LABELING_RULES,
    }


def load_pois(data_dir: Path, cities: tuple[str, ...]) -> list[dict[str, Any]]:
    pois: list[dict[str, Any]] = []
    for city in cities:
        path = data_dir / f"{city}.json"
        city_pois = json.loads(path.read_text(encoding="utf-8"))
        pois.extend(city_pois)
    return pois


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows)
        + "\n",
        encoding="utf-8",
    )


def write_batches(batch_dir: Path, tasks: list[dict[str, Any]], batch_size: int) -> int:
    batch_dir.mkdir(parents=True, exist_ok=True)
    for old in batch_dir.glob("*.jsonl"):
        old.unlink()

    batch_count = 0
    by_city: dict[str, list[dict[str, Any]]] = {city: [] for city in CITIES}
    for task in tasks:
        by_city.setdefault(task["city"], []).append(task)

    for city, city_tasks in by_city.items():
        for start in range(0, len(city_tasks), batch_size):
            batch = city_tasks[start : start + batch_size]
            if not batch:
                continue
            batch_count += 1
            idx = start // batch_size + 1
            write_jsonl(batch_dir / f"{city}_{idx:03d}.jsonl", batch)
    return batch_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    parser.add_argument("--batch-dir", type=Path, default=BATCH_DIR)
    parser.add_argument("--batch-size", type=int, default=80)
    parser.add_argument("--limit-per-city", type=int, default=0)
    parser.add_argument("--ugc-items", type=int, default=3)
    parser.add_argument("--ugc-chars", type=int, default=220)
    parser.add_argument("--no-batches", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw_pois = load_pois(args.data_dir, CITIES)
    if args.limit_per_city > 0:
        limited: list[dict[str, Any]] = []
        counts: dict[str, int] = {city: 0 for city in CITIES}
        for poi in raw_pois:
            city = str(poi.get("city") or "")
            if counts.get(city, 0) >= args.limit_per_city:
                continue
            limited.append(poi)
            counts[city] = counts.get(city, 0) + 1
        raw_pois = limited

    tasks = [
        build_task(poi, ugc_items=args.ugc_items, ugc_chars=args.ugc_chars)
        for poi in raw_pois
        if poi.get("openshopid")
    ]
    write_jsonl(args.out, tasks)

    batch_count = 0
    if not args.no_batches:
        batch_count = write_batches(args.batch_dir, tasks, args.batch_size)

    city_counts: dict[str, int] = {}
    for task in tasks:
        city_counts[task["city"]] = city_counts.get(task["city"], 0) + 1

    print("POI Agent 标注任务已生成:")
    print(f"  tasks: {len(tasks)}")
    print(f"  city_counts: {city_counts}")
    print(f"  wrote: {args.out}")
    if not args.no_batches:
        print(f"  batches: {batch_count}")
        print(f"  batch_dir: {args.batch_dir}")


if __name__ == "__main__":
    main()
