"""Align runtime enriched labels with mock POI ids and write coverage.

The runtime already joins ``mock_dianping/<city>.json`` with
``poi_enriched_labels.json`` by ``openshopid``. This script keeps that contract
and repairs missing labels with the existing deterministic rule pipeline.

Run:
    PYTHONPATH=. python3 scripts/build_canonical_pois.py
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from scripts.label_pois import build_enriched_label

DEFAULT_MOCK_DIR = Path("data/mock_dianping")
DEFAULT_ENRICHED_PATH = Path("data/poi_enriched_labels.json")
DEFAULT_REPORT_PATH = Path("data/canonical_coverage.json")
_IGNORED_MOCK_FILES = {"index.json", "metadata.json"}


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


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


def _city_files(mock_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in mock_dir.glob("*.json")
        if path.name not in _IGNORED_MOCK_FILES
    )


def _mock_pois(path: Path) -> list[dict[str, Any]]:
    value = _load_json(path, [])
    if not isinstance(value, list):
        raise ValueError(f"{path} must contain a JSON list")
    pois = [item for item in value if isinstance(item, dict)]
    ids = [str(poi.get("openshopid") or "") for poi in pois]
    if any(not openshopid for openshopid in ids):
        raise ValueError(f"{path} contains POI without openshopid")
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path} contains duplicate openshopid")
    return pois


def build_canonical_pois(
    *,
    mock_dir: Path = DEFAULT_MOCK_DIR,
    enriched_path: Path = DEFAULT_ENRICHED_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    rebuild: bool = False,
) -> dict[str, Any]:
    """Repair enriched labels so every runtime mock POI has one attachable label."""
    enriched_all = _load_json(enriched_path, {})
    if not isinstance(enriched_all, dict):
        raise ValueError(f"{enriched_path} must contain a JSON object")

    repaired: dict[str, dict[str, dict[str, Any]]] = {}
    city_reports: dict[str, dict[str, Any]] = {}
    for city_path in _city_files(mock_dir):
        city = city_path.stem
        pois = _mock_pois(city_path)
        previous = enriched_all.get(city, {})
        if not isinstance(previous, dict):
            raise ValueError(f"{enriched_path}: {city} labels must be an object")

        mock_ids = {str(poi["openshopid"]) for poi in pois}
        previous_ids = set(previous)
        attached_before = previous_ids & mock_ids
        city_labels: dict[str, dict[str, Any]] = {}
        generated_missing = 0
        rebuilt_labels = 0
        for poi in pois:
            openshopid = str(poi["openshopid"])
            existing = previous.get(openshopid)
            if isinstance(existing, dict) and not rebuild:
                city_labels[openshopid] = existing
            else:
                city_labels[openshopid] = build_enriched_label(poi)
                if isinstance(existing, dict):
                    rebuilt_labels += 1
                else:
                    generated_missing += 1

        repaired[city] = city_labels
        attached_after = len(city_labels)
        city_reports[city] = {
            "mock_poi_count": len(pois),
            "label_count_before": len(previous),
            "attached_before": len(attached_before),
            "attach_rate_before": round(len(attached_before) / len(pois), 4)
            if pois
            else 1.0,
            "generated_missing": generated_missing,
            "rebuilt_labels": rebuilt_labels,
            "dropped_orphans": len(previous_ids - mock_ids),
            "attached_after": attached_after,
            "attach_rate_after": round(attached_after / len(pois), 4)
            if pois
            else 1.0,
        }

    report = {
        "schema_version": "canonical_coverage:v1",
        "runtime_contract": (
            "mock_dianping/<city>.json + poi_enriched_labels.json[city][openshopid]"
        ),
        "cities": city_reports,
    }
    _write_json_atomic(enriched_path, repaired)
    _write_json_atomic(report_path, report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock-dir", type=Path, default=DEFAULT_MOCK_DIR)
    parser.add_argument("--enriched", type=Path, default=DEFAULT_ENRICHED_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--rebuild", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_canonical_pois(
        mock_dir=args.mock_dir,
        enriched_path=args.enriched,
        report_path=args.report,
        rebuild=args.rebuild,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
