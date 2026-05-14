"""v1.9 EnrichedLabel 脏点扫描.

跑全量 mock_dianping POI, 根据规则标红, 输出 data/generated/enriched_audit_report.json.
配合 scripts/refix_enriched.py 用 LLM 重打.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path


class AuditFlag(str, Enum):
    LANDMARK_WITH_FOOD = "landmark_with_food"
    HOTEL_AS_POI = "hotel_as_poi"
    MEAL_ROLE_NO_FOOD_CATEGORY = "meal_role_no_food_category"
    CITY_ESSENTIAL_LOW_PRIORITY = "city_essential_low_priority"
    MISSING_CITY_ZONE = "missing_city_zone"
    TOO_FEW_PLANNING_TAGS = "too_few_planning_tags"


_LANDMARK_KEYWORDS = ("城墙", "古城", "塔", "寺", "博物馆", "宫", "陵", "园")
_HOTEL_KEYWORDS = ("酒店", "宾馆", "公寓", "客栈")


def _has_any(s: str, words: tuple[str, ...]) -> bool:
    return any(w in s for w in words)


def audit_poi(poi: dict) -> list[AuditFlag]:
    """Audit 一个 POI dict, 返回标红 flags 列表."""
    flags: list[AuditFlag] = []
    name = poi.get("name", "")
    categories = poi.get("categories") or []
    cats_str = " ".join(categories)
    enriched = poi.get("enriched") or {}

    if _has_any(name, _LANDMARK_KEYWORDS) and "美食" in cats_str:
        flags.append(AuditFlag.LANDMARK_WITH_FOOD)

    if _has_any(name, _HOTEL_KEYWORDS):
        flags.append(AuditFlag.HOTEL_AS_POI)

    if enriched.get("poi_role") == "meal" and "美食" not in cats_str:
        flags.append(AuditFlag.MEAL_ROLE_NO_FOOD_CATEGORY)

    if (
        enriched.get("poi_role") == "city_essential"
        and (enriched.get("manual_priority") or 0) < 70
    ):
        flags.append(AuditFlag.CITY_ESSENTIAL_LOW_PRIORITY)

    if not (enriched.get("city_zone") or ""):
        flags.append(AuditFlag.MISSING_CITY_ZONE)

    if len(enriched.get("planning_tags") or []) < 2:
        flags.append(AuditFlag.TOO_FEW_PLANNING_TAGS)

    return flags


def audit_city(city: str) -> dict:
    """Audit 一城所有 POI. 返回 {flagged_count, total, report}."""
    poi_path = Path(f"data/mock_dianping/{city}.json")
    enriched_path = Path("data/poi_enriched_labels.json")
    if not poi_path.exists():
        return {"error": f"missing {poi_path}", "city": city}

    pois = json.loads(poi_path.read_text(encoding="utf-8"))
    enriched_all = (
        json.loads(enriched_path.read_text(encoding="utf-8"))
        if enriched_path.exists()
        else {}
    )
    enriched_map = enriched_all.get(city, {})

    report = []
    for p in pois:
        en = enriched_map.get(p.get("openshopid"))
        flagged = audit_poi({**p, "enriched": en})
        if flagged:
            report.append(
                {
                    "openshopid": p.get("openshopid"),
                    "name": p.get("name"),
                    "categories": p.get("categories"),
                    "flags": [f.value for f in flagged],
                }
            )
    return {
        "city": city,
        "total": len(pois),
        "flagged_count": len(report),
        "flagged_rate": round(len(report) / max(len(pois), 1), 3),
        "report": report,
    }


def main() -> None:
    output = Path("data/generated/enriched_audit_report.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    all_results = {}
    for city in ("深圳", "上海", "西安"):
        r = audit_city(city)
        all_results[city] = r
        if "error" not in r:
            print(
                f"{city}: {r['flagged_count']}/{r['total']} 标红 "
                f"({r['flagged_rate'] * 100:.1f}%)"
            )
        else:
            print(f"{city}: {r['error']}")
    output.write_text(
        json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nReport written to {output}")


if __name__ == "__main__":
    main()
