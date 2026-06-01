"""Build a reproducible Lushan mock dataset from real Amap POI records.

POI names, addresses and coordinates come from Amap. Review tags and UGC are
deterministic mock content for the hackathon dataset.

Fetch and build:
    set -a; source .env; set +a
    PYTHONPATH=. python3 scripts/build_lushan_mock.py --fetch-amap

Rebuild from the saved Amap snapshot:
    PYTHONPATH=. python3 scripts/build_lushan_mock.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import tempfile
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

AMAP_TEXT_URL = "https://restapi.amap.com/v3/place/text"
DEFAULT_MOCK_DIR = Path("data/mock_dianping")
DEFAULT_RAW_PATH = Path("data/build/lushan_amap_raw.json")
DEFAULT_REPORT_PATH = Path("data/lushan_build_report.json")
TARGET_CITIES = ("深圳", "上海", "北京", "西安", "庐山")
MAX_LUSHAN_POIS = 360
LUSHAN_BOUNDS = (115.90, 116.10, 29.40, 29.70)
SEARCH_TERMS = (
    "庐山",
    "庐山景区",
    "庐山景点",
    "庐山索道",
    "庐山牯岭",
    "庐山观景台",
    "庐山瀑布",
    "庐山徒步",
    "庐山民宿",
    "庐山餐厅",
    "庐山茶馆",
    "庐山农家乐",
)

_SCENIC_TERMS = ("风景", "景点", "公园", "山", "泉", "湖", "峰", "洞", "瀑布", "台")
_CLIMB_TERMS = ("山", "泉", "峰", "洞", "瀑布", "台", "徒步", "索道")
_REST_TERMS = ("民宿", "酒店", "饭店", "餐厅", "茶", "咖啡", "农家乐")
_ROUTE_SERVICE_TERMS = ("索道", "售票", "停车", "游客中心", "观景", "换乘", "车站")
_EXCLUDED_CATEGORY_TERMS = ("学校", "政府", "住宅", "充电站", "公司", "工厂")


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


def _stable_random(value: str) -> random.Random:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _string(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value if item)
    return str(value or "")


def _coordinates(value: Any) -> tuple[float, float] | None:
    try:
        longitude, latitude = str(value).split(",", maxsplit=1)
        return float(longitude), float(latitude)
    except (TypeError, ValueError):
        return None


def _within_lushan(longitude: float, latitude: float) -> bool:
    min_lng, max_lng, min_lat, max_lat = LUSHAN_BOUNDS
    return min_lng <= longitude <= max_lng and min_lat <= latitude <= max_lat


def _is_lushan_poi(raw: dict[str, Any]) -> bool:
    coordinates = _coordinates(raw.get("location"))
    if not coordinates or not _within_lushan(*coordinates):
        return False
    text = " ".join(
        [_string(raw.get("name")), _string(raw.get("address")), _string(raw.get("adname"))]
    )
    return "庐山" in text or _string(raw.get("adname")) == "庐山市"


def _is_route_relevant(raw: dict[str, Any]) -> bool:
    name = _string(raw.get("name"))
    categories = _string(raw.get("type"))
    if any(term in categories for term in _EXCLUDED_CATEGORY_TERMS):
        return False
    return any(
        term in categories
        for term in ("风景名胜", "住宿服务", "餐饮服务", "博物馆", "纪念馆", "休闲场所")
    ) or any(term in name for term in _ROUTE_SERVICE_TERMS)


def _route_priority(raw: dict[str, Any]) -> tuple[int, str, str]:
    name = _string(raw.get("name"))
    categories = _string(raw.get("type"))
    score = 0
    if any(term in categories for term in ("风景名胜", "博物馆", "纪念馆")):
        score += 100
    if any(term in name for term in _CLIMB_TERMS):
        score += 50
    if any(term in name for term in _ROUTE_SERVICE_TERMS):
        score += 35
    if "住宿服务" in categories:
        score += 25
    if "餐饮服务" in categories:
        score += 20
    if "庐山" in name:
        score += 10
    return -score, name, _string(raw.get("id"))


def _mock_reviews(name: str, categories: list[str], seed: str) -> tuple[list[dict], list[dict]]:
    rng = _stable_random(seed)
    blob = " ".join([name, *categories])
    scenic = any(term in blob for term in _SCENIC_TERMS)
    climb = any(term in blob for term in _CLIMB_TERMS)
    rest = any(term in blob for term in _REST_TERMS)

    tags: list[str] = []
    ugc = ["位置来自高德 POI，点评内容为路线规划演示用 mock。"]
    if scenic:
        tags.extend(["风景绝美", "出片漂亮"])
        ugc.append("景色很开阔，适合拍照，天气好时值得慢慢走。")
    if climb:
        tags.append("爬坡较多")
        ugc.append("台阶和爬坡路段不少，建议预留体力并穿舒适的鞋。")
    if rest:
        tags.append("适合休息")
        ugc.append("适合作为山上休息点，行程中可以在这里缓一缓。")
    if "索道" in blob or rng.random() < 0.18:
        tags.append("排队较长")
        ugc.append("周末高峰可能排队，建议错峰到达。")
    elif scenic and rng.random() < 0.35:
        tags.append("周末人多")
        ugc.append("节假日人流较多，早点到体验更从容。")

    review_tags = [
        {"tag": tag, "hit": rng.randint(18, 880)}
        for tag in dict.fromkeys(tags)
    ]
    ugcs = [
        {
            "nick": f"庐山路线体验官{rng.randint(100, 999)}",
            "userface": "",
            "ispithy": index == 1,
            "score": round(rng.uniform(4.1, 4.9), 1),
            "star": 5,
            "content": content,
            "photos": [],
            "addtime": 1746057600000 + rng.randint(0, 2_592_000_000),
        }
        for index, content in enumerate(ugc)
    ]
    return review_tags, ugcs


def transform_amap_poi(raw: dict[str, Any], *, ordinal: int) -> dict[str, Any]:
    """Convert one accepted Amap record into the mock Dianping contract."""
    coordinates = _coordinates(raw.get("location"))
    if coordinates is None:
        raise ValueError("Amap POI location must be '<longitude>,<latitude>'")
    longitude, latitude = coordinates
    amap_id = _string(raw.get("id")).strip()
    if not amap_id:
        raise ValueError("Amap POI id is required")
    name = _string(raw.get("name")).strip()
    categories = [part for part in _string(raw.get("type")).split(";") if part]
    review_tags, ugcs = _mock_reviews(name, categories, amap_id)
    rng = _stable_random(amap_id)
    is_food = any(term in " ".join(categories) for term in ("餐饮", "中餐", "小吃", "咖啡", "茶"))
    biz_ext = raw.get("biz_ext") if isinstance(raw.get("biz_ext"), dict) else {}

    return {
        "openshopid": f"amap_{amap_id}",
        "openstatus": 1,
        "highquality": 1 if ordinal < 80 else 0,
        "name": name,
        "branch_name": "",
        "address": _string(raw.get("address")),
        "shopDesc": "真实高德地点；点评和体验标签为赛题 mock。",
        "city": "庐山",
        "district": _string(raw.get("adname")) or "庐山市",
        "isOverseas": False,
        "latitude": latitude,
        "longitude": longitude,
        "telephone": _string(raw.get("tel")),
        "business_hour": _string(biz_ext.get("opentime")) or "08:00-18:00",
        "categories": categories or ["风景名胜"],
        "reviewCount": rng.randint(36, 2800),
        "star": round(rng.uniform(4.1, 5.0), 1),
        "avgprice": rng.randint(35, 180) if is_food else rng.randint(0, 120),
        "reviewTags": review_tags,
        "ugcs": ugcs,
        "picCount": rng.randint(8, 680),
        "shopPics": [],
        "dishs": [],
        "special": ["免费 WiFi"] if any(term in name for term in _REST_TERMS) else [],
        "isBlackPearl": 0,
        "takeawayable": is_food,
        "queueable": any(tag["tag"] == "排队较长" for tag in review_tags),
        "bookable": "索道" in name or any(term in name for term in ("民宿", "酒店")),
        "mallInfo": None,
        "dealInfo": [],
        "brandName": "",
    }


def _city_metadata(pois: list[dict[str, Any]]) -> dict[str, Any]:
    categories = Counter(
        category for poi in pois for category in poi.get("categories") or []
    )
    prices = [int(poi.get("avgprice") or 0) for poi in pois if poi.get("avgprice")]
    return {
        "total": len(pois),
        "food_count": sum(
            1
            for poi in pois
            if any("餐饮" in category for category in poi.get("categories") or [])
        ),
        "avg_price": round(sum(prices) / len(prices)) if prices else 0,
        "by_category": dict(categories),
    }


def build_lushan_mock(
    *,
    raw_pois: list[dict[str, Any]],
    mock_dir: Path = DEFAULT_MOCK_DIR,
    metadata_path: Path | None = None,
    index_path: Path | None = None,
    report_path: Path | None = None,
) -> dict[str, Any]:
    """Write Lushan data and rebuild the delivery index with five target cities."""
    metadata_path = metadata_path or mock_dir / "metadata.json"
    index_path = index_path or mock_dir / "index.json"
    report_path = report_path or DEFAULT_REPORT_PATH

    eligible: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    duplicate_count = 0
    rejected_count = 0
    for raw in raw_pois:
        amap_id = _string(raw.get("id")).strip()
        if not amap_id or not _is_lushan_poi(raw) or not _is_route_relevant(raw):
            rejected_count += 1
            continue
        if amap_id in seen_ids:
            duplicate_count += 1
            continue
        seen_ids.add(amap_id)
        eligible.append(raw)

    eligible.sort(key=_route_priority)
    capped_count = max(0, len(eligible) - MAX_LUSHAN_POIS)
    accepted = [
        transform_amap_poi(raw, ordinal=ordinal)
        for ordinal, raw in enumerate(eligible[:MAX_LUSHAN_POIS])
    ]
    accepted.sort(key=lambda poi: (poi["name"], poi["openshopid"]))
    _write_json_atomic(mock_dir / "庐山.json", accepted)

    by_city: dict[str, list[dict[str, Any]]] = {}
    for city in TARGET_CITIES:
        path = mock_dir / f"{city}.json"
        if not path.exists():
            raise FileNotFoundError(f"missing city mock data: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise ValueError(f"{path} must contain a JSON list")
        by_city[city] = value

    index = [poi for city in TARGET_CITIES for poi in by_city[city]]
    metadata = {
        "version": "dt_v3_lushan",
        "generated_at": datetime.now(UTC).date().isoformat(),
        "total_count": len(index),
        "city_stats": {city: _city_metadata(pois) for city, pois in by_city.items()},
    }
    report = {
        "schema_version": "lushan_mock_build:v1",
        "source": "Amap POI snapshot for locations; deterministic mock reviews",
        "raw_poi_count": len(raw_pois),
        "eligible_poi_count": len(eligible),
        "accepted_poi_count": len(accepted),
        "rejected_poi_count": rejected_count,
        "duplicate_poi_count": duplicate_count,
        "capped_poi_count": capped_count,
        "delivery_cities": list(TARGET_CITIES),
        "index_poi_count": len(index),
    }
    _write_json_atomic(index_path, index)
    _write_json_atomic(metadata_path, metadata)
    _write_json_atomic(report_path, report)
    return report


def fetch_amap_pois(*, key: str, pages: int = 4) -> list[dict[str, Any]]:
    """Fetch a raw snapshot from Amap without logging the API key."""
    output: list[dict[str, Any]] = []
    for keyword in SEARCH_TERMS:
        for page in range(1, pages + 1):
            query = urllib.parse.urlencode(
                {
                    "keywords": keyword,
                    "city": "九江",
                    "offset": 25,
                    "page": page,
                    "extensions": "base",
                    "key": key,
                }
            )
            with urllib.request.urlopen(f"{AMAP_TEXT_URL}?{query}", timeout=15) as response:
                body = json.load(response)
            if body.get("status") != "1":
                raise RuntimeError(f"Amap request failed: {body.get('info') or 'unknown error'}")
            pois = body.get("pois") or []
            output.extend(item for item in pois if isinstance(item, dict))
            if len(pois) < 25:
                break
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock-dir", type=Path, default=DEFAULT_MOCK_DIR)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--fetch-amap", action="store_true")
    parser.add_argument("--pages", type=int, default=4)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.fetch_amap:
        key = os.environ.get("AMAP_KEY", "").strip()
        if not key:
            raise SystemExit("AMAP_KEY is required with --fetch-amap")
        raw_pois = fetch_amap_pois(key=key, pages=args.pages)
        _write_json_atomic(args.raw, {"source": "Amap text API", "pois": raw_pois})
    else:
        snapshot = json.loads(args.raw.read_text(encoding="utf-8"))
        raw_pois = snapshot.get("pois") if isinstance(snapshot, dict) else snapshot
        if not isinstance(raw_pois, list):
            raise SystemExit(f"{args.raw} must contain a POI list")
    report = build_lushan_mock(
        raw_pois=raw_pois,
        mock_dir=args.mock_dir,
        report_path=args.report,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
