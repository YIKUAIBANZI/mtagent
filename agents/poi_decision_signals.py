"""UGC-derived POI decision signals.

This module is intentionally read-only and cheap: route generation can attach
these precomputed signals without waiting on live review mining.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from dianping.schemas import POI, ParsedIntent, Stop

_SIGNALS_PATH = Path("data/poi_decision_signals.json")


@lru_cache(maxsize=1)
def load_decision_signals(path: str | None = None) -> dict[str, dict[str, Any]]:
    """Load decision signals keyed by openshopid.

    Missing or malformed files degrade to an empty mapping so the planner can
    still return candidates within the 10s budget.
    """
    p = Path(path) if path else _SIGNALS_PATH
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}

    signals: dict[str, dict[str, Any]] = {}
    for openshopid, value in raw.items():
        if isinstance(openshopid, str) and isinstance(value, dict):
            signals[openshopid] = value
    return signals


def get_decision_signals(openshopid: str | None) -> dict[str, Any]:
    """Return UGC decision signals for one POI, or an empty dict."""
    if not openshopid:
        return {}
    signals = load_decision_signals().get(openshopid)
    return dict(signals) if isinstance(signals, dict) else {}


def intent_avoids_queue(intent: ParsedIntent | None) -> bool:
    """Whether the user explicitly cares about queue avoidance."""
    if intent is None:
        return False
    constraints = getattr(intent, "constraints", {}) or {}
    modifiers = getattr(intent, "modifiers", {}) or {}
    avoid = " ".join(getattr(intent, "avoid", []) or [])
    return bool(
        constraints.get("avoid_queue")
        or modifiers.get("怕排队")
        or "排队" in avoid
        or "等位" in avoid
    )


def queue_risk_rank(poi: POI) -> int:
    """Return 0-3 queue risk from UGC decision signals."""
    signals = get_decision_signals(poi.openshopid)
    level = str((signals.get("queue_risk") or {}).get("level") or "").lower()
    return {"low": 1, "medium": 2, "high": 3}.get(level, 0)


def prefer_pois_by_decision_signals(
    pois: list[POI],
    *,
    intent: ParsedIntent | None,
    slot_name: str,
    variant: str = "main",
) -> list[POI]:
    """Stable-sort matching candidates when queue avoidance matters."""
    wants_low_queue = intent_avoids_queue(intent) or variant == "low_queue"
    if not wants_low_queue:
        return pois

    def _sort_risk(poi: POI) -> int:
        signals = get_decision_signals(poi.openshopid)
        if not signals:
            return 1
        level = str((signals.get("queue_risk") or {}).get("level") or "").lower()
        return {"low": 0, "medium": 2, "high": 3}.get(level, 1)

    def _key(item: tuple[int, POI]) -> tuple[int, int]:
        idx, poi = item
        risk = _sort_risk(poi)
        if slot_name in ("午饭", "晚饭", "下午茶"):
            return (risk, idx)
        return (min(risk, 2), idx)

    return [poi for _, poi in sorted(enumerate(pois), key=_key)]


def build_decision_notes(
    poi: POI,
    *,
    slot_name: str,
    intent: ParsedIntent | None,
) -> tuple[dict[str, Any], list[str]]:
    """Build compact, user-facing notes from UGC decision signals."""
    signals = get_decision_signals(poi.openshopid)
    if not signals:
        return {}, []

    notes: list[str] = []
    queue = signals.get("queue_risk") or {}
    best_time = signals.get("best_time") or {}
    reservation = signals.get("reservation") or {}

    queue_label = queue.get("label")
    if queue_label:
        if intent_avoids_queue(intent):
            notes.append(f"UGC 提醒：{queue_label}，已按少排队偏好处理。")
        else:
            notes.append(f"UGC 提醒：{queue_label}。")

    best_label = best_time.get("label")
    if best_label:
        notes.append(f"建议时段：{best_label}。")

    if reservation.get("level") in ("recommended", "required"):
        notes.append(f"预约建议：{reservation.get('label') or '建议提前预约/购票'}。")

    advice = signals.get("agent_advice")
    if advice and len(notes) < 3:
        notes.append(str(advice))

    return signals, notes[:3]


def with_stop_decision_signals(stop: Stop, intent: ParsedIntent | None) -> Stop:
    """Attach UGC-derived decision signals to a Stop."""
    signals, notes = build_decision_notes(
        stop.poi,
        slot_name=stop.slot.name,
        intent=intent,
    )
    return stop.model_copy(
        update={
            "decision_signals": signals,
            "decision_notes": notes,
        }
    )
