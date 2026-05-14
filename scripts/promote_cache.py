"""v1.9.1 Phase B: 把 poi_cache.json 中 seen_count >= N 的 entry 晋升进本地 POI 库.

- data/poi_cache.json 中 entry.seen_count >= min_seen_count AND not entry.promoted → 晋升
- 生成稳定 openshopid = CACHE_<md5(cache_key)[:10]>
- 追加进 data/mock_dianping/{city}.json (按 openshopid 去重)
- 追加进 data/poi_enriched_labels.json[city][openshopid]
- cache entry 标记 promoted=true (幂等)

CLI:
    venv/bin/python scripts/promote_cache.py --dry-run
    venv/bin/python scripts/promote_cache.py --limit 5
    venv/bin/python scripts/promote_cache.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Optional


CACHE_PATH_DEFAULT = Path("data/poi_cache.json")
MOCK_DIR_DEFAULT = Path("data/mock_dianping")
ENRICHED_PATH_DEFAULT = Path("data/poi_enriched_labels.json")


def _gen_openshopid(cache_key: str) -> str:
    """稳定 ID: cache_key 同 → openshopid 同, 跨城跨重跑不变."""
    return "CACHE_" + hashlib.md5(cache_key.encode("utf-8")).hexdigest()[:10].upper()


def _cache_entry_to_mock_poi(cache_key: str, entry: dict) -> dict:
    """cache entry → mock_dianping POI dict (满足 POI pydantic schema 必填字段).

    POI 必填: openshopid / name / city / latitude / longitude.
    其他字段全有默认, 给合理零值即可. data_source 标 'cache_promoted'.
    """
    oid = _gen_openshopid(cache_key)
    return {
        "openshopid": oid,
        "name": entry["name"],
        "city": entry["city"],
        "longitude": entry["lng"],
        "latitude": entry["lat"],
        "categories": entry.get("categories", []),
        "highquality": 0,
        "openstatus": 1,
        "branch_name": "",
        "address": "",
        "data_source": "cache_promoted",
        "avgprice": 0,
        "business_hour": "",
        "telephone": "",
        "reviewCount": 0,
        "star": 0.0,
    }


def _cache_entry_to_enriched(entry: dict) -> Optional[dict]:
    """cache entry.enriched → poi_enriched_labels schema. None if cache 无 enriched."""
    en = entry.get("enriched")
    if not en:
        return None
    return {
        "poi_role": en.get("poi_role", "fallback"),
        "manual_priority": en.get("manual_priority", 50),
        "planning_tags": en.get("planning_tags", []),
        "risk_tags": en.get("risk_tags", []),
        "city_zone": en.get("city_zone", ""),
        "min_stay_minutes": en.get("min_stay_minutes", 45),
        "max_stay_minutes": en.get("max_stay_minutes", 90),
        "label_sources": ["cache_promoted:v1.9.1"],
    }


def promote_cache(
    *,
    min_seen_count: int = 5,
    cities: Optional[list[str]] = None,
    limit: Optional[int] = None,
    dry_run: bool = False,
    cache_path: Path = CACHE_PATH_DEFAULT,
    mock_dir: Path = MOCK_DIR_DEFAULT,
    enriched_path: Path = ENRICHED_PATH_DEFAULT,
) -> dict:
    """晋升 cache → 本地 POI 库. 返回 per-city summary.

    summary[city] = {
        "promoted": int,
        "skipped_below_threshold": int,  # seen 不够
        "skipped_already_promoted": int,  # cache 里已 promoted=true
        "skipped_no_enriched": int,       # 没 enriched 跳过 (保守, 不污染本地)
        "skipped_dup_in_mock": int,       # mock_dianping 已有同 openshopid
    }
    """
    cache = (
        json.loads(cache_path.read_text(encoding="utf-8"))
        if cache_path.exists()
        else {}
    )

    summary: dict[str, dict] = {}
    # group keys by city for batch write
    by_city: dict[str, list[tuple[str, dict]]] = {}
    for k, v in cache.items():
        c = v.get("city", "")
        if not c:
            continue
        if cities and c not in cities:
            continue
        by_city.setdefault(c, []).append((k, v))

    total_promoted = 0

    for city, items in by_city.items():
        stats = {
            "promoted": 0,
            "skipped_below_threshold": 0,
            "skipped_already_promoted": 0,
            "skipped_no_enriched": 0,
            "skipped_dup_in_mock": 0,
        }
        mock_file = mock_dir / f"{city}.json"
        mock_list: list[dict] = (
            json.loads(mock_file.read_text(encoding="utf-8"))
            if mock_file.exists()
            else []
        )
        existing_oids = {p.get("openshopid") for p in mock_list if isinstance(p, dict)}

        enriched_all: dict = (
            json.loads(enriched_path.read_text(encoding="utf-8"))
            if enriched_path.exists()
            else {}
        )
        enriched_city = enriched_all.get(city, {})

        new_pois: list[dict] = []
        new_enriched: dict[str, dict] = {}
        cache_updates: list[str] = []  # keys to mark promoted=true

        for key, entry in items:
            if entry.get("promoted") is True:
                stats["skipped_already_promoted"] += 1
                continue
            if entry.get("seen_count", 0) < min_seen_count:
                stats["skipped_below_threshold"] += 1
                continue
            enriched_dict = _cache_entry_to_enriched(entry)
            if enriched_dict is None:
                stats["skipped_no_enriched"] += 1
                continue

            poi_dict = _cache_entry_to_mock_poi(key, entry)
            oid = poi_dict["openshopid"]
            if oid in existing_oids:
                stats["skipped_dup_in_mock"] += 1
                cache_updates.append(key)  # 即使已存在也标 promoted, 下次不再考虑
                continue

            new_pois.append(poi_dict)
            new_enriched[oid] = enriched_dict
            cache_updates.append(key)
            existing_oids.add(oid)
            stats["promoted"] += 1

            if limit is not None and total_promoted + stats["promoted"] >= limit:
                break

        total_promoted += stats["promoted"]
        summary[city] = stats

        if dry_run:
            continue

        # 写 mock_dianping/{city}.json
        if new_pois:
            mock_list.extend(new_pois)
            mock_file.write_text(
                json.dumps(mock_list, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        # 写 poi_enriched_labels.json[city]
        if new_enriched:
            enriched_city.update(new_enriched)
            enriched_all[city] = enriched_city
            enriched_path.write_text(
                json.dumps(enriched_all, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        # cache entry 标 promoted=true (含 dup_in_mock 那部分, 防止下次再算)
        for key in cache_updates:
            cache[key]["promoted"] = True

        if limit is not None and total_promoted >= limit:
            break

    if not dry_run:
        cache_path.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return summary


def _print_summary(summary: dict, dry_run: bool) -> None:
    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"{prefix}Promote summary:")
    grand = {"promoted": 0}
    for city, st in summary.items():
        print(f"  {city}: {st}")
        grand["promoted"] += st.get("promoted", 0)
    print(f"  TOTAL promoted: {grand['promoted']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--min-seen", type=int, default=5)
    ap.add_argument("--cities", nargs="*", default=None)
    args = ap.parse_args()

    summary = promote_cache(
        min_seen_count=args.min_seen,
        cities=args.cities,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    _print_summary(summary, args.dry_run)


if __name__ == "__main__":
    main()
