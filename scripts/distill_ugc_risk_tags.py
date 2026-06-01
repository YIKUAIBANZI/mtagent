"""Distill routing risk tags from each POI's own review tags and UGC.

Run:
    PYTHONPATH=. python3 scripts/distill_ugc_risk_tags.py --cities 上海
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

DEFAULT_MOCK_DIR = Path("data/mock_dianping")
DEFAULT_ENRICHED_PATH = Path("data/poi_enriched_labels.json")
DEFAULT_REPORT_PATH = Path("data/ugc_risk_coverage.json")
SOURCE = "agent:risk_from_ugc:v1"
RISK_ORDER = ("queue_heavy", "crowded_weekend", "walk_heavy")
RISK_PATTERNS = {
    "queue_heavy": re.compile(r"排队|等位|队伍.{0,4}长|翻台慢|上菜慢"),
    "crowded_weekend": re.compile(
        r"周末.{0,6}(人多|爆满|拥挤)|节假日.{0,6}(人多|爆满|拥挤)|人流较多|人稍微多"
    ),
    "walk_heavy": re.compile(r"暴走|爬山|爬坡|步行多|走路多|逛完.{0,6}累|地方.{0,4}大"),
}


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


def infer_ugc_risks(poi: dict[str, Any]) -> dict[str, list[str]]:
    """Return evidence-backed risk tags inferred only from this POI."""
    evidence: dict[str, list[str]] = {}
    sources = [
        (f"reviewTag:{item.get('tag', '')}", str(item.get("tag") or ""))
        for item in poi.get("reviewTags") or []
        if isinstance(item, dict) and item.get("tag")
    ]
    sources.extend(
        (f"ugc:{item.get('content', '')}", str(item.get("content") or ""))
        for item in poi.get("ugcs") or []
        if isinstance(item, dict) and item.get("content")
    )
    for source, text in sources:
        for risk_tag in RISK_ORDER:
            if RISK_PATTERNS[risk_tag].search(text):
                evidence.setdefault(risk_tag, []).append(source)
    return evidence


def _ordered_risks(values: set[str]) -> list[str]:
    known = [risk for risk in RISK_ORDER if risk in values]
    return [*known, *sorted(values - set(RISK_ORDER))]


def distill_ugc_risk_tags(
    *,
    mock_dir: Path = DEFAULT_MOCK_DIR,
    enriched_path: Path = DEFAULT_ENRICHED_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    cities: list[str] | None = None,
) -> dict[str, Any]:
    """Add evidence-backed risks to enriched labels and write an audit report."""
    target_cities = cities or ["上海"]
    enriched_all = json.loads(enriched_path.read_text(encoding="utf-8"))
    report_cities: dict[str, Any] = {}

    for city in target_cities:
        pois = json.loads((mock_dir / f"{city}.json").read_text(encoding="utf-8"))
        labels = enriched_all.get(city, {})
        changed_poi_count = 0
        evidence_samples: dict[str, list[dict[str, Any]]] = {
            risk: [] for risk in RISK_ORDER
        }
        for poi in pois:
            openshopid = str(poi.get("openshopid") or "")
            label = labels.get(openshopid)
            if not isinstance(label, dict):
                continue
            inferred = infer_ugc_risks(poi)
            existing = set(label.get("risk_tags") or [])
            added = set(inferred) - existing
            if added:
                label["risk_tags"] = _ordered_risks(existing | added)
                sources = set(label.get("label_sources") or [])
                sources.add(SOURCE)
                label["label_sources"] = sorted(sources)
                changed_poi_count += 1
            for risk_tag, risk_evidence in inferred.items():
                samples = evidence_samples[risk_tag]
                if len(samples) < 5:
                    samples.append(
                        {
                            "openshopid": openshopid,
                            "evidence": risk_evidence[:3],
                        }
                    )

        risk_counter = Counter(
            risk
            for label in labels.values()
            if isinstance(label, dict)
            for risk in label.get("risk_tags") or []
        )
        report_cities[city] = {
            "poi_count": len(pois),
            "changed_poi_count": changed_poi_count,
            "risk_tags": dict(sorted(risk_counter.items())),
            "evidence_samples": {
                risk: samples for risk, samples in evidence_samples.items() if samples
            },
        }

    report = {
        "schema_version": "ugc_risk_coverage:v1",
        "source": SOURCE,
        "cities": report_cities,
    }
    _write_json_atomic(enriched_path, enriched_all)
    _write_json_atomic(report_path, report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock-dir", type=Path, default=DEFAULT_MOCK_DIR)
    parser.add_argument("--enriched", type=Path, default=DEFAULT_ENRICHED_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--cities", nargs="+", default=["上海"])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = distill_ugc_risk_tags(
        mock_dir=args.mock_dir,
        enriched_path=args.enriched,
        report_path=args.report,
        cities=args.cities,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
