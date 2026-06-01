"""Build traceable UGC-derived decision signals for Shanghai demo POIs.

Run:
    PYTHONPATH=. python3 scripts/build_decision_signals.py --city 上海
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from scripts.distill_ugc_risk_tags import infer_ugc_risks

DEFAULT_MOCK_DIR = Path("data/mock_dianping")
DEFAULT_ENRICHED_PATH = Path("data/poi_enriched_labels.json")
DEFAULT_SIGNALS_PATH = Path("data/poi_decision_signals.json")
DEFAULT_REPORT_PATH = Path("data/decision_signal_coverage.json")


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def _evidence_lines(poi: dict[str, Any]) -> list[str]:
    inferred = infer_ugc_risks(poi)
    lines: list[str] = []
    for risk_tag in ("queue_heavy", "crowded_weekend", "walk_heavy"):
        for source in inferred.get(risk_tag, []):
            kind, text = source.split(":", 1)
            line = (
                f"UGC 摘要：reviewTag「{text}」"
                if kind == "reviewTag"
                else f"UGC 摘要：评论「{text}」"
            )
            if line not in lines:
                lines.append(line)
    return lines[:3]


def _queue_risk(poi: dict[str, Any], label: dict[str, Any]) -> dict[str, Any]:
    risks = set(label.get("risk_tags") or [])
    name = str(poi.get("name") or "")
    if "queue_heavy" in risks:
        return {
            "level": "high",
            "label": "饭点等位风险高",
            "when": ["11:45-13:15", "18:00-19:30", "周末"],
            "advice": "建议错峰到店；等待过长时切换到附近低排队备选。",
        }
    if "crowded_weekend" in risks:
        return {
            "level": "medium",
            "label": "日落和节假日人流高"
            if "外滩" in name
            else "周末和节假日人流较高",
            "when": ["周末", "节假日"],
            "advice": "建议提前到达或避开客流高峰，保留附近替代点。",
        }
    return {
        "level": "low",
        "label": "排队压力相对低",
        "when": [],
        "advice": "按当前路线安排即可。",
    }


def _best_time(label: dict[str, Any]) -> dict[str, Any]:
    risks = set(label.get("risk_tags") or [])
    if "queue_heavy" in risks:
        return {
            "label": "正餐提前场或错峰时段更稳",
            "slots": ["11:00-11:30", "17:30-18:00", "14:00 后"],
            "reason": "UGC 聚合标签显示高峰期有排队风险。",
        }
    if "crowded_weekend" in risks:
        return {
            "label": "工作日或上午更从容",
            "slots": ["09:00-11:00", "工作日"],
            "reason": "UGC 聚合标签显示周末和节假日人流更集中。",
        }
    return {
        "label": "按路线顺路安排",
        "slots": [],
        "reason": "未发现明显高峰风险。",
    }


def _reservation(poi: dict[str, Any], label: dict[str, Any]) -> dict[str, str]:
    risks = set(label.get("risk_tags") or [])
    if poi.get("bookable") or "reservation_recommended" in risks:
        return {"level": "recommended", "label": "建议提前确认预约或购票"}
    return {"level": "none", "label": "通常无需预约"}


def build_signal(
    poi: dict[str, Any],
    *,
    label: dict[str, Any],
    fallback_poi_ids: list[str],
) -> dict[str, Any]:
    """Build one decision signal using only traceable POI-local evidence."""
    role = str(label.get("poi_role") or "fallback")
    advice = (
        "正餐点建议主动错峰；若等待过长，切换附近低排队备选。"
        if role == "meal"
        else "景点建议结合时段和人流安排；拥挤时切换附近备选。"
    )
    return {
        "queue_risk": _queue_risk(poi, label),
        "best_time": _best_time(label),
        "reservation": _reservation(poi, label),
        "agent_advice": advice,
        "evidence": _evidence_lines(poi),
        "fallback_poi_ids": fallback_poi_ids,
    }


def rebuild_decision_signals(
    *,
    mock_dir: Path = DEFAULT_MOCK_DIR,
    enriched_path: Path = DEFAULT_ENRICHED_PATH,
    signals_path: Path = DEFAULT_SIGNALS_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    city: str = "上海",
) -> dict[str, Any]:
    """Replace stale manual signals with deterministic, traceable entries."""
    pois = json.loads((mock_dir / f"{city}.json").read_text(encoding="utf-8"))
    enriched_all = json.loads(enriched_path.read_text(encoding="utf-8"))
    labels = enriched_all.get(city, {})
    by_id = {str(poi.get("openshopid") or ""): poi for poi in pois}
    ordered_pois = sorted(
        pois,
        key=lambda poi: (-int(poi.get("reviewCount") or 0), str(poi.get("openshopid") or "")),
    )

    targets = [
        poi
        for poi in ordered_pois
        if infer_ugc_risks(poi)
        and isinstance(labels.get(str(poi.get("openshopid") or "")), dict)
    ]
    signals: dict[str, dict[str, Any]] = {}
    for poi in targets:
        openshopid = str(poi["openshopid"])
        label = labels[openshopid]
        role = str(label.get("poi_role") or "fallback")
        alternatives = [
            str(candidate["openshopid"])
            for candidate in ordered_pois
            if candidate.get("openshopid") != openshopid
            and isinstance(labels.get(str(candidate.get("openshopid") or "")), dict)
            and str(labels[str(candidate["openshopid"])].get("poi_role") or "fallback") == role
            and "queue_heavy"
            not in set(labels[str(candidate["openshopid"])].get("risk_tags") or [])
        ][:3]
        signal = build_signal(poi, label=label, fallback_poi_ids=alternatives)
        if signal["evidence"]:
            signals[openshopid] = signal

    report = {
        "schema_version": "decision_signal_coverage:v1",
        "cities": {
            city: {
                "mock_poi_count": len(pois),
                "signal_count": len(signals),
                "traceable_evidence_count": sum(
                    bool(signal.get("evidence")) for signal in signals.values()
                ),
                "sample_openshopids": list(signals)[:10],
            }
        },
    }
    _write_json_atomic(signals_path, signals)
    _write_json_atomic(report_path, report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock-dir", type=Path, default=DEFAULT_MOCK_DIR)
    parser.add_argument("--enriched", type=Path, default=DEFAULT_ENRICHED_PATH)
    parser.add_argument("--signals", type=Path, default=DEFAULT_SIGNALS_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--city", default="上海")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = rebuild_decision_signals(
        mock_dir=args.mock_dir,
        enriched_path=args.enriched,
        signals_path=args.signals,
        report_path=args.report,
        city=args.city,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
