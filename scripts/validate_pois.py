"""Validate the five-city offline POI delivery bundle.

Run:
    PYTHONPATH=. python3 scripts/validate_pois.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from dianping.schemas import POI

DEFAULT_CITIES = ["深圳", "上海", "北京", "西安", "庐山"]
DEFAULT_MOCK_DIR = Path("data/mock_dianping")
DEFAULT_ENRICHED_PATH = Path("data/poi_enriched_labels.json")
DEFAULT_SIGNALS_PATH = Path("data/poi_decision_signals.json")
DEFAULT_REPORT_PATH = Path("data/validation_report.json")
LUSHAN_BOUNDS = (115.90, 116.10, 29.40, 29.70)
CITY_BOUNDS = {
    "深圳": (113.70, 114.70, 22.30, 22.90),
    "上海": (120.80, 122.10, 30.60, 31.90),
    "北京": (115.70, 117.10, 39.40, 40.80),
    "西安": (108.00, 109.70, 33.70, 34.90),
    "庐山": LUSHAN_BOUNDS,
}
_QUEUE_EVIDENCE = re.compile(r"排队|等位")
_VALUE_TAGS = {"便宜大碗", "性价比高"}
_REVIEW_TAG_EVIDENCE = re.compile(r"^UGC 摘要：reviewTag「(.+)」$")
_UGC_EVIDENCE = re.compile(r"^UGC 摘要：评论「(.+)」$")


def _load_json(path: Path) -> Any:
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


def _within_lushan(poi: dict[str, Any]) -> bool:
    min_lng, max_lng, min_lat, max_lat = LUSHAN_BOUNDS
    longitude = float(poi.get("longitude") or 0)
    latitude = float(poi.get("latitude") or 0)
    return min_lng <= longitude <= max_lng and min_lat <= latitude <= max_lat


def _within_city(city: str, poi: dict[str, Any]) -> bool:
    bounds = CITY_BOUNDS.get(city)
    if not bounds:
        return True
    min_lng, max_lng, min_lat, max_lat = bounds
    longitude = float(poi.get("longitude") or 0)
    latitude = float(poi.get("latitude") or 0)
    return min_lng <= longitude <= max_lng and min_lat <= latitude <= max_lat


def _traceable_evidence(poi: dict[str, Any], evidence: str) -> bool:
    review_match = _REVIEW_TAG_EVIDENCE.match(evidence)
    if review_match:
        return review_match.group(1) in {
            str(item.get("tag") or "")
            for item in poi.get("reviewTags") or []
            if isinstance(item, dict)
        }
    ugc_match = _UGC_EVIDENCE.match(evidence)
    if ugc_match:
        return ugc_match.group(1) in {
            str(item.get("content") or "")
            for item in poi.get("ugcs") or []
            if isinstance(item, dict)
        }
    return False


def validate_pois(
    *,
    mock_dir: Path = DEFAULT_MOCK_DIR,
    enriched_path: Path = DEFAULT_ENRICHED_PATH,
    signals_path: Path = DEFAULT_SIGNALS_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    cities: list[str] | None = None,
    min_lushan_pois: int = 200,
    max_lushan_pois: int = 400,
) -> dict[str, Any]:
    """Validate schema, indexes, label attachment and traceable decision evidence."""
    target_cities = cities or DEFAULT_CITIES
    errors: list[str] = []
    warnings: list[str] = []
    city_pois: dict[str, list[dict[str, Any]]] = {}
    city_reports: dict[str, dict[str, Any]] = {}
    all_ids: list[str] = []

    for city in target_cities:
        path = mock_dir / f"{city}.json"
        if not path.exists():
            errors.append(f"missing city data: {path}")
            city_pois[city] = []
            continue
        value = _load_json(path)
        if not isinstance(value, list):
            errors.append(f"{path} must contain a JSON list")
            city_pois[city] = []
            continue
        pois = [item for item in value if isinstance(item, dict)]
        if len(pois) != len(value):
            errors.append(f"{path} contains non-object POIs")
        city_pois[city] = pois
        schema_errors = 0
        for index, poi in enumerate(pois):
            openshopid = str(poi.get("openshopid") or "")
            all_ids.append(openshopid)
            if not openshopid:
                errors.append(f"{city}[{index}] missing openshopid")
            if poi.get("city") != city:
                errors.append(f"{city}[{index}] city mismatch: {poi.get('city')!r}")
            try:
                POI.model_validate(poi)
            except Exception as exc:
                schema_errors += 1
                errors.append(f"{city}[{index}] schema error: {str(exc)[:180]}")
            latitude = float(poi.get("latitude") or 0)
            longitude = float(poi.get("longitude") or 0)
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                errors.append(f"{city}[{index}] invalid coordinates")
            elif not _within_city(city, poi):
                errors.append(f"{city}[{index}] outside {city} bounds: {openshopid}")
            review_tags = {
                str(item.get("tag") or "")
                for item in poi.get("reviewTags") or []
                if isinstance(item, dict)
            }
            if int(poi.get("avgprice") or 0) >= 500 and review_tags & _VALUE_TAGS:
                errors.append(f"{city}[{index}] high price conflicts with value tag: {openshopid}")
            if city == "庐山":
                if not openshopid.startswith("amap_"):
                    errors.append(f"庐山[{index}] non-Amap openshopid: {openshopid}")
                if not _within_lushan(poi):
                    errors.append(f"庐山[{index}] outside Lushan bounds: {openshopid}")
        city_reports[city] = {
            "poi_count": len(pois),
            "schema_error_count": schema_errors,
        }

    duplicate_ids = sorted(
        openshopid for openshopid, count in Counter(all_ids).items() if openshopid and count > 1
    )
    if duplicate_ids:
        errors.append(f"duplicate openshopid across delivery cities: {duplicate_ids[:10]}")

    lushan_count = len(city_pois.get("庐山", []))
    if "庐山" in target_cities and not min_lushan_pois <= lushan_count <= max_lushan_pois:
        errors.append(
            f"庐山 POI count must be within {min_lushan_pois}..{max_lushan_pois}: {lushan_count}"
        )

    enriched_all = _load_json(enriched_path)
    if not isinstance(enriched_all, dict):
        errors.append(f"{enriched_path} must contain a JSON object")
        enriched_all = {}
    extra_label_cities = sorted(set(enriched_all) - set(target_cities))
    if extra_label_cities:
        errors.append(f"enriched contains non-delivery cities: {extra_label_cities}")
    for city, pois in city_pois.items():
        labels = enriched_all.get(city, {})
        if not isinstance(labels, dict):
            errors.append(f"enriched labels for {city} must be an object")
            labels = {}
        poi_ids = {str(poi.get("openshopid") or "") for poi in pois}
        label_ids = set(labels)
        missing = sorted(poi_ids - label_ids)
        orphans = sorted(label_ids - poi_ids)
        if missing:
            errors.append(f"{city} missing enriched labels: {missing[:10]}")
        if orphans:
            errors.append(f"{city} orphan enriched labels: {orphans[:10]}")
        for index, poi in enumerate(pois):
            openshopid = str(poi.get("openshopid") or "")
            label = labels.get(openshopid, {})
            review_tags = [
                str(item.get("tag") or "")
                for item in poi.get("reviewTags") or []
                if isinstance(item, dict)
            ]
            if any(_QUEUE_EVIDENCE.search(tag) for tag in review_tags) and "queue_heavy" not in set(
                label.get("risk_tags") or []
            ):
                errors.append(f"{city}[{index}] queue evidence without queue_heavy: {openshopid}")
        city_reports.setdefault(city, {})["attach_rate"] = (
            round(len(poi_ids & label_ids) / len(poi_ids), 4) if poi_ids else 1.0
        )

    expected_index = [poi for city in target_cities for poi in city_pois.get(city, [])]
    actual_index = _load_json(mock_dir / "index.json")
    if not isinstance(actual_index, list):
        errors.append("mock_dianping/index.json must contain a JSON list")
        actual_index = []
    expected_index_ids = [str(poi.get("openshopid") or "") for poi in expected_index]
    actual_index_ids = [
        str(poi.get("openshopid") or "") for poi in actual_index if isinstance(poi, dict)
    ]
    if Counter(actual_index_ids) != Counter(expected_index_ids):
        errors.append("mock_dianping/index.json does not match delivery city files")

    metadata = _load_json(mock_dir / "metadata.json")
    metadata_stats = metadata.get("city_stats", {}) if isinstance(metadata, dict) else {}
    if set(metadata_stats) != set(target_cities):
        errors.append("mock_dianping/metadata.json city_stats does not match delivery cities")
    if metadata.get("total_count") != len(expected_index):
        errors.append("mock_dianping/metadata.json total_count does not match delivery index")
    for city, pois in city_pois.items():
        if metadata_stats.get(city, {}).get("total") != len(pois):
            errors.append(f"mock_dianping/metadata.json total mismatch for {city}")

    by_id = {
        str(poi.get("openshopid") or ""): poi
        for pois in city_pois.values()
        for poi in pois
    }
    signals = _load_json(signals_path)
    if not isinstance(signals, dict):
        errors.append(f"{signals_path} must contain a JSON object")
        signals = {}
    traceable_count = 0
    for openshopid, signal in signals.items():
        poi = by_id.get(str(openshopid))
        if not poi:
            errors.append(f"decision signal POI not found: {openshopid}")
            continue
        evidence = signal.get("evidence") if isinstance(signal, dict) else None
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"decision signal missing evidence: {openshopid}")
            continue
        untraceable = [item for item in evidence if not _traceable_evidence(poi, str(item))]
        if untraceable:
            errors.append(f"untraceable evidence for {openshopid}: {untraceable[:3]}")
        else:
            traceable_count += 1
        for fallback_id in signal.get("fallback_poi_ids") or []:
            if str(fallback_id) not in by_id:
                errors.append(f"decision signal fallback POI not found: {fallback_id}")

    report = {
        "schema_version": "poi_validation:v1",
        "valid": not errors,
        "delivery_cities": target_cities,
        "total_poi_count": len(expected_index),
        "cities": city_reports,
        "decision_signals": {
            "signal_count": len(signals),
            "traceable_count": traceable_count,
        },
        "errors": errors,
        "warnings": warnings,
    }
    _write_json_atomic(report_path, report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock-dir", type=Path, default=DEFAULT_MOCK_DIR)
    parser.add_argument("--enriched", type=Path, default=DEFAULT_ENRICHED_PATH)
    parser.add_argument("--signals", type=Path, default=DEFAULT_SIGNALS_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--cities", nargs="+", default=DEFAULT_CITIES)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = validate_pois(
        mock_dir=args.mock_dir,
        enriched_path=args.enriched,
        signals_path=args.signals,
        report_path=args.report,
        cities=args.cities,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
