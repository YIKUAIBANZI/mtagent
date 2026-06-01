"""Build normalized user preference profiles from trip contexts and events.

Inputs:
    data/trips/*.json              TripContext snapshots saved by agents/context.py
    data/user_events.jsonl         Optional raw user behavior / feedback events

Outputs:
    data/user_profiles/{key}.json  One normalized profile per cookie_key
    data/user_profile_summary.json Aggregate summary for inspection

Run:
    PYTHONPATH=. python3 scripts/clean_user_profiles.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_TRIPS_DIR = Path("data/trips")
DEFAULT_EVENTS_PATH = Path("data/user_events.jsonl")
DEFAULT_OUT_DIR = Path("data/user_profiles")
DEFAULT_SUMMARY_PATH = Path("data/user_profile_summary.json")
DEFAULT_COOKIE_KEY = "anonymous_demo"

SUPPORTED_CITIES = {"深圳", "上海", "西安"}
TRAVELER_TYPES = {"情侣", "家庭亲子", "银发", "独行", "商务", "朋友团"}
BUDGET_LEVELS = {"性价比", "适中", "精致"}
PACE_LEVELS = {"暴走", "适中", "佛系"}
MODIFIER_NAMES = ("轻量体力", "重文化", "重美食", "怕排队")

PREFERENCE_PATTERNS: dict[str, tuple[str, ...]] = {
    "photo_friendly": ("拍照", "出片", "打卡", "好看", "景观", "景色"),
    "food_quality": ("美食", "吃", "餐厅", "小吃", "好吃", "菜品", "本地特色"),
    "culture_friendly": ("文化", "历史", "博物馆", "古迹", "老字号", "展览"),
    "family_friendly": ("亲子", "带娃", "带孩子", "小朋友", "家庭"),
    "night_friendly": ("夜景", "夜游", "晚上", "夜市", "灯光"),
    "shopping_friendly": ("购物", "商场", "买东西", "逛街"),
    "good_value": ("性价比", "便宜", "不贵", "划算"),
    "low_queue": (
        "少排队",
        "不排队",
        "不想排队",
        "别排队",
        "怕排队",
        "不想等",
        "省时间",
    ),
    "low_walk": (
        "少走路",
        "不累",
        "轻松",
        "佛系",
        "别太累",
        "不要太累",
        "不想太累",
    ),
}

MODIFIER_TO_PREFERENCE = {
    "轻量体力": "low_walk",
    "重文化": "culture_friendly",
    "重美食": "food_quality",
    "怕排队": "low_queue",
}

LIST_FIELDS = (
    "must_visit",
    "avoid_keywords",
    "loved_pois",
    "rejected_pois",
    "been_there_pois",
    "rejected_categories",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


def compact_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_cookie_key(value: Any) -> str:
    text = compact_text(value)
    return text or DEFAULT_COOKIE_KEY


def filename_for_cookie(cookie_key: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", cookie_key):
        return f"{cookie_key}.json"
    digest = hashlib.sha1(cookie_key.encode("utf-8")).hexdigest()[:12]
    return f"user_{digest}.json"


def unique_sorted(values: Iterable[Any]) -> list[str]:
    out = {compact_text(v) for v in values if compact_text(v)}
    return sorted(out)


def detect_preference_tags(*values: Any) -> set[str]:
    text = " ".join(compact_text(v) for v in values if v is not None)
    detected: set[str] = set()
    for tag, keywords in PREFERENCE_PATTERNS.items():
        if any(keyword in text for keyword in keywords):
            detected.add(tag)
    return detected


def empty_profile(cookie_key: str) -> dict[str, Any]:
    return {
        "schema_version": "user_profile:v1",
        "cookie_key": cookie_key,
        "updated_at": now_iso(),
        "preference_weights": {tag: 0 for tag in PREFERENCE_PATTERNS},
        "traveler_type_weights": {},
        "city_weights": {},
        "budget_level_weights": {},
        "pace_weights": {},
        "modifiers": {name: False for name in MODIFIER_NAMES},
        "must_visit": [],
        "avoid_keywords": [],
        "loved_pois": [],
        "rejected_pois": [],
        "been_there_pois": [],
        "rejected_categories": [],
        "raw_preference_terms": {},
        "evidence": [],
    }


def iter_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    if not path.exists():
        return
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            print(
                f"skip invalid jsonl line {path}:{line_no}: {exc}",
                file=sys.stderr,
            )
            continue
        if isinstance(data, dict):
            yield line_no, data


def event_from_raw(raw: dict[str, Any], source: str) -> dict[str, Any]:
    event = dict(raw)
    event["source"] = source
    event["cookie_key"] = normalize_cookie_key(raw.get("cookie_key"))
    event["event_type"] = compact_text(raw.get("event_type") or "raw_event")
    return event


def iter_raw_events(path: Path) -> Iterable[dict[str, Any]]:
    for line_no, raw in iter_jsonl(path) or []:
        yield event_from_raw(raw, f"{path}:{line_no}")


def event_from_trip(path: Path, raw: dict[str, Any]) -> dict[str, Any]:
    user_input = raw.get("user_input") or {}
    intent = raw.get("intent") or {}
    return {
        "source": f"{path}:trip_context",
        "event_type": "trip_context",
        "trip_id": raw.get("trip_id"),
        "timestamp": raw.get("updated_at") or raw.get("created_at"),
        "cookie_key": normalize_cookie_key(user_input.get("cookie_key")),
        "free_text": user_input.get("free_text", ""),
        "city": intent.get("city"),
        "days": intent.get("days"),
        "traveler_type": intent.get("traveler_type"),
        "budget_level": intent.get("budget_level"),
        "pace": intent.get("pace"),
        "preferences": intent.get("preferences") or [],
        "must_visit": intent.get("must_visit") or [],
        "avoid": intent.get("avoid") or [],
        "modifiers": intent.get("modifiers") or {},
    }


def events_from_feedback(path: Path, raw: dict[str, Any]) -> Iterable[dict[str, Any]]:
    user_input = raw.get("user_input") or {}
    cookie_key = normalize_cookie_key(user_input.get("cookie_key"))
    for idx, feedback in enumerate(raw.get("user_feedback") or []):
        if not isinstance(feedback, dict):
            continue
        yield {
            "source": f"{path}:user_feedback:{idx}",
            "event_type": "feedback",
            "trip_id": raw.get("trip_id"),
            "timestamp": raw.get("updated_at") or raw.get("created_at"),
            "cookie_key": cookie_key,
            "action": feedback.get("action"),
            "reason": feedback.get("reason", ""),
            "target_day": feedback.get("target_day"),
            "target_stop_idx": feedback.get("target_stop_idx"),
        }


def iter_trip_events(trips_dir: Path) -> Iterable[dict[str, Any]]:
    if not trips_dir.exists():
        return
    for path in sorted(trips_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"skip invalid trip file {path}: {exc}", file=sys.stderr)
            continue
        if not isinstance(raw, dict):
            continue
        yield event_from_trip(path, raw)
        yield from events_from_feedback(path, raw)


def bump(counter_dict: dict[str, int], key: Any, allowed: set[str] | None = None) -> None:
    text = compact_text(key)
    if not text:
        return
    if allowed is not None and text not in allowed:
        return
    counter_dict[text] = int(counter_dict.get(text, 0)) + 1


def add_evidence(profile: dict[str, Any], event: dict[str, Any], signals: list[str]) -> None:
    if not signals:
        return
    evidence = profile["evidence"]
    if len(evidence) >= 80:
        return
    evidence.append(
        {
            "source": event.get("source", ""),
            "event_type": event.get("event_type", ""),
            "trip_id": event.get("trip_id"),
            "timestamp": event.get("timestamp"),
            "signals": signals,
        }
    )


def merge_event(profile: dict[str, Any], event: dict[str, Any]) -> None:
    signals: list[str] = []

    city = compact_text(event.get("city"))
    if city in SUPPORTED_CITIES:
        bump(profile["city_weights"], city)
        signals.append(f"city={city}")

    traveler_type = compact_text(event.get("traveler_type"))
    if traveler_type in TRAVELER_TYPES:
        bump(profile["traveler_type_weights"], traveler_type)
        signals.append(f"traveler_type={traveler_type}")

    budget_level = compact_text(event.get("budget_level"))
    if budget_level in BUDGET_LEVELS:
        bump(profile["budget_level_weights"], budget_level)
        signals.append(f"budget_level={budget_level}")

    pace = compact_text(event.get("pace"))
    if pace in PACE_LEVELS:
        bump(profile["pace_weights"], pace)
        signals.append(f"pace={pace}")

    preference_terms = [compact_text(v) for v in as_list(event.get("preferences"))]
    for term in preference_terms:
        if not term:
            continue
        profile["raw_preference_terms"][term] = (
            int(profile["raw_preference_terms"].get(term, 0)) + 1
        )

    text_values = [
        event.get("free_text"),
        event.get("reason"),
        " ".join(preference_terms),
        " ".join(compact_text(v) for v in as_list(event.get("avoid"))),
    ]
    for tag in detect_preference_tags(*text_values):
        profile["preference_weights"][tag] += 1
        signals.append(f"preference={tag}")

    modifiers = event.get("modifiers") or {}
    if isinstance(modifiers, dict):
        for name, enabled in modifiers.items():
            if name not in MODIFIER_NAMES or not bool(enabled):
                continue
            profile["modifiers"][name] = True
            mapped = MODIFIER_TO_PREFERENCE.get(name)
            if mapped:
                profile["preference_weights"][mapped] += 1
                signals.append(f"modifier={name}")

    list_updates = {
        "must_visit": event.get("must_visit"),
        "avoid_keywords": event.get("avoid") or event.get("avoid_keywords"),
        "loved_pois": event.get("loved_pois"),
        "rejected_pois": event.get("rejected_pois"),
        "been_there_pois": event.get("been_there_pois"),
        "rejected_categories": event.get("rejected_categories"),
    }
    for field, value in list_updates.items():
        merged = set(profile[field])
        incoming = unique_sorted(as_list(value))
        if incoming:
            merged.update(incoming)
            profile[field] = sorted(merged)
            signals.append(f"{field}+={len(incoming)}")

    action = compact_text(event.get("action"))
    if action in {"replace_stop", "redo_day", "mark_disliked", "mark_been_there"}:
        signals.append(f"feedback={action}")

    add_evidence(profile, event, signals)


def build_profiles(events: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for event in events:
        cookie_key = normalize_cookie_key(event.get("cookie_key"))
        profile = profiles.setdefault(cookie_key, empty_profile(cookie_key))
        merge_event(profile, event)
        profile["updated_at"] = now_iso()
    return profiles


def sort_profile(profile: dict[str, Any]) -> dict[str, Any]:
    sorted_profile = dict(profile)
    for key in (
        "preference_weights",
        "traveler_type_weights",
        "city_weights",
        "budget_level_weights",
        "pace_weights",
        "raw_preference_terms",
    ):
        items = sorted(
            profile.get(key, {}).items(),
            key=lambda item: (-int(item[1]), item[0]),
        )
        sorted_profile[key] = {k: v for k, v in items}
    for field in LIST_FIELDS:
        sorted_profile[field] = sorted(set(profile.get(field) or []))
    return sorted_profile


def write_profiles(
    profiles: dict[str, dict[str, Any]],
    out_dir: Path,
    summary_path: Path,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)

    profile_summaries = {}
    aggregate_preferences: Counter[str] = Counter()
    for cookie_key, profile in sorted(profiles.items()):
        sorted_data = sort_profile(profile)
        path = out_dir / filename_for_cookie(cookie_key)
        path.write_text(
            json.dumps(sorted_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        non_zero_preferences = {
            k: v
            for k, v in sorted_data["preference_weights"].items()
            if int(v) > 0
        }
        aggregate_preferences.update(non_zero_preferences)
        profile_summaries[cookie_key] = {
            "path": str(path),
            "evidence_count": len(sorted_data.get("evidence") or []),
            "top_preferences": dict(list(non_zero_preferences.items())[:5]),
            "top_cities": dict(list(sorted_data["city_weights"].items())[:5]),
            "top_traveler_types": dict(
                list(sorted_data["traveler_type_weights"].items())[:5]
            ),
        }

    summary = {
        "schema_version": "user_profile_summary:v1",
        "updated_at": now_iso(),
        "profile_count": len(profiles),
        "aggregate_preferences": dict(aggregate_preferences.most_common()),
        "profiles": profile_summaries,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trips-dir", type=Path, default=DEFAULT_TRIPS_DIR)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS_PATH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--summary-out", type=Path, default=DEFAULT_SUMMARY_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    events = [*iter_trip_events(args.trips_dir), *iter_raw_events(args.events)]
    profiles = build_profiles(events)
    summary = write_profiles(profiles, args.out_dir, args.summary_out)

    print("用户画像清洗完成:")
    print(f"  trip dir: {args.trips_dir}")
    print(f"  raw events: {args.events} ({'exists' if args.events.exists() else 'missing'})")
    print(f"  events loaded: {len(events)}")
    print(f"  profiles: {summary['profile_count']}")
    print(f"  wrote: {args.out_dir}")
    print(f"  wrote: {args.summary_out}")


if __name__ == "__main__":
    main()
