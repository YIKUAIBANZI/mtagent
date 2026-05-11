"""Offline pipeline: label POIs with traveler_types + modifiers from
structured fields (reviewTags / special / queueable / isBlackPearl).

Run:
    PYTHONPATH=. python scripts/label_pois.py
Outputs:
    data/poi_labels.json  (~360 KB)
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

CITIES = ("深圳", "上海", "西安")
DATA_DIR = Path("data/mock_dianping")
OUT_PATH = Path("data/poi_labels.json")


def label_traveler_types(poi: dict) -> list[str]:
    """Map structured fields to traveler_types list. '独行' as fallback."""
    tags = {t["tag"] for t in poi.get("reviewTags") or []}
    spec = set(poi.get("special") or [])
    types: list[str] = []
    if "适合约会" in tags:
        types.append("情侣")
    if "亲子友好" in tags or "提供婴儿椅" in spec:
        types.append("家庭亲子")
    if "无障碍" in spec:
        types.append("银发")
    if "适合聚会" in tags or "可包间" in spec:
        types.append("朋友团")
    if "包厢私密" in tags or "商务宴请" in tags:
        types.append("商务")
    if not types:
        types = ["独行"]
    return types


def label_modifiers(poi: dict) -> dict[str, bool]:
    """Map structured fields to 4 binary modifier flags."""
    tags = {t["tag"] for t in poi.get("reviewTags") or []}
    spec = set(poi.get("special") or [])
    return {
        "轻量体力": "提供婴儿椅" in spec or "无障碍" in spec or "亲子友好" in tags,
        "重文化": "老字号" in tags or "本地特色" in tags,
        "重美食": "菜品精致" in tags
        or "食材新鲜" in tags
        or poi.get("isBlackPearl") == 1,
        "怕排队": not poi.get("queueable", False) and "等位久" not in tags,
    }


def main() -> None:
    output: dict[str, dict[str, dict]] = {}
    summary: dict[str, Counter] = {}
    for city in CITIES:
        path = DATA_DIR / f"{city}.json"
        pois = json.loads(path.read_text(encoding="utf-8"))
        city_labels: dict[str, dict] = {}
        type_counter: Counter = Counter()
        for poi in pois:
            shop_id = poi.get("openshopid")
            if not shop_id:
                continue
            tt = label_traveler_types(poi)
            mods = label_modifiers(poi)
            city_labels[shop_id] = {"traveler_types": tt, "modifiers": mods}
            for t in tt:
                type_counter[t] += 1
        output[city] = city_labels
        summary[city] = type_counter
        print(f"\n[{city}] {len(city_labels)} POIs labeled")
        print("  traveler_type 分布:")
        for t, c in sorted(type_counter.items(), key=lambda x: -x[1]):
            pct = c / len(pois) * 100
            print(f"    {t:8s} {c:4d} ({pct:5.1f}%)")
            if pct < 5.0:
                print("      ⚠️  覆盖率 < 5%, 调规则补 (spec §10 risk)")
    OUT_PATH.write_text(
        json.dumps(output, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"\n✅ wrote {OUT_PATH} ({OUT_PATH.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
