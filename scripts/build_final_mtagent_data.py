"""Build the final mtagent data foundation from real source candidates.

This script converts the real evidence layer under data/real_sources into the
runtime-facing data shapes used by the current project. It replaces the local
mock server POI files with real-source POIs; it does not append legacy mock rows.

1. Dianping-compatible POI JSON files for the local mock server.
2. Structured route-planning labels for persona routing and future Planner work.

It does not call external APIs. The only POI identity used is the Amap id already
present in the source candidate; no synthetic POIs are created.

Run:
    PYTHONPATH=. python3 scripts/build_final_mtagent_data.py
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from scripts.label_pois import (
    LANDMARK_FALSE_POSITIVE_TERMS,
    LANDMARK_VALID_SUFFIXES,
    NEIGHBOR_ZONES,
    SLOT_ORDER,
    build_enriched_label,
    infer_city_zone,
    is_city_essential,
)

CITIES = ("深圳", "上海", "西安")
SOURCE_PATH = Path("data/real_sources/merged_real_poi_candidates.jsonl")
MOCK_DIR = Path("data/mock_dianping")
AGENT_LABELS_PATH = Path("data/poi_agent_labels.json")
ENRICHED_LABELS_PATH = Path("data/poi_enriched_labels.json")
LEGACY_LABELS_PATH = Path("data/poi_labels.json")
BUILD_SUMMARY_PATH = Path("data/final_data_build_summary.json")

TRAVELER_TYPES = ("情侣", "家庭亲子", "银发", "独行", "商务", "朋友团")
MODIFIER_NAMES = ("轻量体力", "重文化", "重美食", "怕排队")
POI_ROLES = {"city_essential", "persona_preferred", "meal", "connector", "fallback"}
UNIVERSAL_LEVELS = {"high", "medium", "low"}
PLANNING_TAGS = {
    "photo_friendly",
    "food_quality",
    "culture_friendly",
    "family_friendly",
    "couple_friendly",
    "group_friendly",
    "business_friendly",
    "senior_friendly",
    "solo_friendly",
    "quiet",
    "atmosphere",
    "good_value",
    "good_service",
    "fast_service",
    "transit_friendly",
    "rain_friendly",
    "night_friendly",
    "rest_friendly",
    "shopping_friendly",
    "first_visit_friendly",
    "landmark",
    "food",
    "private_room",
    "premium_food",
    "pet_friendly",
}
RISK_TAGS = {
    "queue_heavy",
    "slow_service",
    "pricey",
    "hard_to_find",
    "parking_hard",
    "facility_old",
    "smoky",
    "small_portion",
    "service_average",
    "portion_mismatch",
    "reservation_recommended",
    "walk_heavy",
    "crowded_weekend",
}

AMAP_CATEGORY_TO_DIANPING = {
    "餐饮服务": ["美食"],
    "购物服务": ["购物"],
    "风景名胜": ["休闲娱乐"],
    "体育休闲服务": ["休闲娱乐"],
    "科教文化服务": ["休闲娱乐"],
    "生活服务": ["休闲娱乐"],
    "地名地址信息": ["休闲娱乐"],
    "交通设施服务": ["休闲娱乐"],
    "商务住宅": ["酒店"],
    "公司企业": ["休闲娱乐"],
    "医疗保健服务": ["休闲娱乐"],
}

KEYWORD_CATEGORY_HINTS = {
    "亲子": "亲子",
    "儿童": "亲子",
    "乐园": "亲子",
    "书店": "购物",
    "商场": "购物",
    "购物": "购物",
    "咖啡": "美食",
    "茶": "美食",
    "餐厅": "美食",
    "小吃": "美食",
    "酒店": "酒店",
    "民宿": "酒店",
    "美容": "丽人",
    "美发": "丽人",
    "美甲": "丽人",
    "KTV": "K歌",
    "酒吧": "K歌",
}

POSITIVE_TERM_TO_REVIEW_TAG = {
    "出片": "出片漂亮",
    "拍照": "出片漂亮",
    "好拍": "出片漂亮",
    "日落": "出片漂亮",
    "看海": "出片漂亮",
    "夜景": "氛围佳",
    "浪漫": "适合约会",
    "氛围": "氛围佳",
    "美食": "本地特色",
    "好吃": "菜品精致",
    "小吃": "本地特色",
    "文化": "本地特色",
    "历史": "老字号",
    "亲子": "亲子友好",
    "轻松": "环境优雅",
    "舒服": "环境优雅",
    "惬意": "环境优雅",
    "免费": "性价比高",
    "地铁直达": "交通方便",
    "地标": "出片漂亮",
}

POSITIVE_TERM_TO_PLANNING_TAGS = {
    "出片": {"photo_friendly"},
    "拍照": {"photo_friendly"},
    "好拍": {"photo_friendly"},
    "日落": {"photo_friendly"},
    "看海": {"photo_friendly", "rest_friendly"},
    "海风": {"photo_friendly", "rest_friendly"},
    "夜景": {"night_friendly", "photo_friendly"},
    "美食": {"food", "food_quality"},
    "好吃": {"food", "food_quality"},
    "小吃": {"food", "good_value"},
    "文化": {"culture_friendly"},
    "历史": {"culture_friendly"},
    "亲子": {"family_friendly"},
    "轻松": {"rest_friendly"},
    "地铁直达": {"transit_friendly"},
    "免费": {"good_value"},
    "浪漫": {"couple_friendly", "atmosphere"},
    "氛围": {"atmosphere"},
    "慢逛": {"rest_friendly"},
    "地标": {"landmark", "first_visit_friendly"},
}

RISK_TERM_TO_REVIEW_TAG = {
    "排队": "等位久",
    "人多": "等位久",
    "拥挤": "等位久",
    "预约": "等位久",
    "提前": "等位久",
    "步行多": "位置难找",
    "2w步": "位置难找",
    "太累": "位置难找",
}

RISK_TERM_TO_RISK_TAGS = {
    "排队": {"queue_heavy"},
    "人多": {"crowded_weekend"},
    "拥挤": {"crowded_weekend"},
    "预约": {"reservation_recommended"},
    "提前": {"reservation_recommended"},
    "步行多": {"walk_heavy"},
    "2w步": {"walk_heavy"},
    "太累": {"walk_heavy"},
    "跑空": {"hard_to_find"},
    "闭园": {"reservation_recommended"},
    "防晒": {"walk_heavy"},
    "太阳": {"walk_heavy"},
}

LANDMARK_WALK_KEYWORDS = (
    "山",
    "公园",
    "城墙",
    "兵马俑",
    "大雁塔",
    "华山",
    "梧桐山",
    "大鹏所城",
    "海滨",
    "古镇",
    "迪士尼",
    "欢乐谷",
)

CONNECTOR_NAME_KEYWORDS = ("咖啡", "茶", "书店", "商场", "万象", "中心", "广场")
FALLBACK_CATEGORY_HINTS = {"公司企业", "医疗保健服务"}
FOOD_SEMANTIC_TERMS = {"美食", "好吃", "小吃"}
LANDMARK_CHILD_FACILITY_KEYWORDS = (
    "售票处",
    "售票厅",
    "入口",
    "出口",
    "停车场",
    "游客中心",
    "卫生间",
    "有限公司",
    "官方旗舰店",
    "旅游摄影",
    "暂停营业",
)

REAL_CITY_ESSENTIAL_KEYWORDS = {
    "深圳": (
        "梧桐山",
        "仙湖植物园",
        "深圳世界之窗",
        "世界之窗",
        "甘坑古镇",
        "深圳湾公园",
        "海上世界",
        "欢乐港湾",
        "大鹏所城",
        "大梅沙",
        "小梅沙",
        "华强北",
        "东门老街",
        "莲花山公园",
        "较场尾",
    ),
    "上海": (
        "外滩",
        "东方明珠",
        "陆家嘴",
        "上海豫园",
        "豫园",
        "上海城隍庙",
        "城隍庙",
        "南京路步行街",
        "南京东路",
        "武康路",
        "新天地",
        "上海博物馆",
        "静安寺",
        "迪士尼",
        "上海欢乐谷",
        "人民广场",
    ),
    "西安": (
        "秦始皇兵马俑",
        "兵马俑",
        "西安钟楼",
        "钟楼",
        "鼓楼",
        "大雁塔",
        "大唐不夜城",
        "大唐芙蓉园",
        "西安城墙",
        "永宁门",
        "回民街",
        "陕西历史博物馆",
        "华清宫",
        "华清池",
        "小寨",
    ),
}

REAL_ZONE_BY_DISTRICT = {
    "上海": {
        "宝山区": "north",
        "嘉定区": "northwest",
        "青浦区": "west",
        "松江区": "southwest",
        "金山区": "south",
        "奉贤区": "south",
        "崇明区": "far_north",
    },
    "西安": {
        "灞桥区": "east",
        "蓝田县": "east",
        "鄠邑区": "southwest",
        "周至县": "southwest",
        "阎良区": "north",
        "高陵区": "north",
    },
}

REAL_NEIGHBOR_ZONES = {
    "上海": {
        "northwest": ["west", "north"],
        "south": ["southwest"],
        "far_north": ["north"],
    },
    "西安": {
        "southwest": ["west", "south"],
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_no}: root must be an object")
            rows.append(row)
    return rows


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def compact_text(value: Any, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def ordered_slots(values: Iterable[str]) -> list[str]:
    allowed = {slot for slot in SLOT_ORDER}
    unique = {value for value in values if value in allowed}
    idx = {slot: i for i, slot in enumerate(SLOT_ORDER)}
    return sorted(unique, key=lambda slot: idx[slot])


def ordered_tags(values: Iterable[str], allowed: set[str]) -> list[str]:
    return sorted({value for value in values if value in allowed})


def candidate_text(candidate: dict[str, Any]) -> str:
    amap = candidate.get("amap_match") if isinstance(candidate.get("amap_match"), dict) else {}
    parts = [
        candidate.get("canonical_name"),
        candidate.get("category_hint"),
        amap.get("poi_type"),
        amap.get("address"),
        candidate.get("cleaning_notes"),
    ]
    raw_signals = candidate.get("raw_signals") if isinstance(candidate.get("raw_signals"), dict) else {}
    parts.extend(as_list(raw_signals.get("positive_terms")))
    parts.extend(as_list(raw_signals.get("risk_terms")))
    for evidence in as_list(candidate.get("source_evidence")):
        if not isinstance(evidence, dict):
            continue
        parts.extend(
            [
                evidence.get("title"),
                evidence.get("excerpt"),
                evidence.get("reason"),
                evidence.get("warnings"),
            ]
        )
    return "\n".join(compact_text(part, 300) for part in parts if part)


def identity_text(candidate: dict[str, Any]) -> str:
    """Text that describes POI identity, excluding noisy guide semantics."""
    amap = candidate.get("amap_match") if isinstance(candidate.get("amap_match"), dict) else {}
    parts = [
        candidate.get("canonical_name"),
        candidate.get("category_hint"),
        amap.get("amap_name"),
        amap.get("poi_type"),
        amap.get("address"),
    ]
    return "\n".join(compact_text(part, 220) for part in parts if part)


def source_platforms(candidate: dict[str, Any]) -> set[str]:
    platforms: set[str] = set()
    for evidence in as_list(candidate.get("source_evidence")):
        if isinstance(evidence, dict) and evidence.get("source_platform"):
            platforms.add(str(evidence["source_platform"]))
    return platforms


def mapped_categories(candidate: dict[str, Any]) -> list[str]:
    category_hint = str(candidate.get("category_hint") or "")
    categories = list(AMAP_CATEGORY_TO_DIANPING.get(category_hint, ["休闲娱乐"]))
    text = identity_text(candidate)
    for keyword, category in KEYWORD_CATEGORY_HINTS.items():
        if keyword in text:
            categories.append(category)
    return dedupe_preserve_order(categories)


def review_tags_from_candidate(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    text = candidate_text(candidate)
    raw_signals = candidate.get("raw_signals") if isinstance(candidate.get("raw_signals"), dict) else {}
    terms = [
        *[str(term) for term in as_list(raw_signals.get("positive_terms"))],
        *[str(term) for term in as_list(raw_signals.get("risk_terms"))],
    ]
    counter: Counter[str] = Counter()
    for term in terms:
        review_tag = POSITIVE_TERM_TO_REVIEW_TAG.get(term) or RISK_TERM_TO_REVIEW_TAG.get(term)
        if review_tag:
            counter[review_tag] += 3
    for term, review_tag in POSITIVE_TERM_TO_REVIEW_TAG.items():
        if term in text:
            counter[review_tag] += 1
    for term, review_tag in RISK_TERM_TO_REVIEW_TAG.items():
        if term in text:
            counter[review_tag] += 1

    category_hint = str(candidate.get("category_hint") or "")
    if category_hint == "餐饮服务":
        counter["菜品精致"] += 1
    if category_hint == "购物服务":
        counter["交通方便"] += 1
    if category_hint in {"风景名胜", "科教文化服务"}:
        counter["出片漂亮"] += 1

    return [
        {"tag": tag, "hit": min(99, max(1, hit))}
        for tag, hit in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def ugcs_from_candidate(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    ugcs: list[dict[str, Any]] = []
    for evidence in as_list(candidate.get("source_evidence")):
        if not isinstance(evidence, dict) or evidence.get("source_platform") != "xhs":
            continue
        content = compact_text(
            " ".join(
                part
                for part in [
                    str(evidence.get("excerpt") or ""),
                    str(evidence.get("reason") or ""),
                    str(evidence.get("warnings") or ""),
                ]
                if part
            ),
            360,
        )
        if not content:
            continue
        ugcs.append(
            {
                "nick": "xhs_guide",
                "userface": "",
                "ispithy": True,
                "score": 0,
                "star": 0,
                "content": content,
                "photos": [],
                "addtime": 0,
            }
        )
    return ugcs[:5]


def normalize_rating(value: Any) -> float:
    try:
        rating = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(5.0, rating))


def is_real_city_essential(poi: dict[str, Any]) -> bool:
    name = str(poi.get("name") or "")
    city = str(poi.get("city") or "")
    if any(keyword in name for keyword in LANDMARK_CHILD_FACILITY_KEYWORDS):
        return False
    if any(term in name for term in LANDMARK_FALSE_POSITIVE_TERMS):
        return False
    if is_city_essential(poi):
        return True
    stripped = name
    for prefix in (city, f"{city}市"):
        if prefix and stripped.startswith(prefix) and len(stripped) > len(prefix):
            stripped = stripped[len(prefix) :]
            break
    for keyword in REAL_CITY_ESSENTIAL_KEYWORDS.get(city, ()):
        if name == keyword or stripped == keyword:
            return True
        if name.startswith(keyword) and (
            len(name) == len(keyword)
            or name[len(keyword)] in "·-（("
            or any(name[len(keyword) :].startswith(suffix) for suffix in LANDMARK_VALID_SUFFIXES)
        ):
            return True
        if stripped.startswith(keyword) and (
            len(stripped) == len(keyword)
            or stripped[len(keyword)] in "·-（("
            or any(stripped[len(keyword) :].startswith(suffix) for suffix in LANDMARK_VALID_SUFFIXES)
        ):
            return True
    return False


def zone_for_city_district(city: str, district: str) -> str:
    zone = infer_city_zone(city, district)
    if zone != "unknown":
        return zone
    return REAL_ZONE_BY_DISTRICT.get(city, {}).get(district, "unknown")


def neighbor_zones_for(city: str, zone: str) -> list[str]:
    if zone in NEIGHBOR_ZONES.get(city, {}):
        return NEIGHBOR_ZONES[city][zone]
    return REAL_NEIGHBOR_ZONES.get(city, {}).get(zone, [])


def build_poi(candidate: dict[str, Any]) -> dict[str, Any]:
    amap = candidate.get("amap_match") if isinstance(candidate.get("amap_match"), dict) else {}
    amap_id = compact_text(amap.get("amap_id"), 80)
    if not amap_id:
        raise ValueError(f"candidate missing amap_id: {candidate.get('canonical_name')}")

    name = compact_text(candidate.get("canonical_name") or amap.get("amap_name"), 120)
    city = compact_text(candidate.get("city"), 20)
    categories = mapped_categories(candidate)
    rating = normalize_rating(amap.get("rating"))
    tel = compact_text(amap.get("tel"), 80)
    poi_type = compact_text(amap.get("poi_type"), 120)
    source_url = compact_text(amap.get("source_url"), 300)
    address = compact_text(amap.get("address") or amap.get("district") or name, 200)
    district = compact_text(amap.get("district"), 40)

    return {
        "openshopid": amap_id,
        "data_source": "real_sources",
        "source_platforms": sorted(source_platforms(candidate)),
        "real_source_schema_version": str(candidate.get("schema_version") or ""),
        "openstatus": 0 if "暂停营业" in name else 1,
        "highquality": 1 if rating >= 4.7 and "酒店" not in categories else 0,
        "name": name,
        "branch_name": "",
        "address": address,
        "district": district,
        "shopDesc": compact_text(
            "；".join(
                part
                for part in [
                    poi_type,
                    candidate.get("cleaning_notes"),
                    f"source={source_url}" if source_url else "",
                ]
                if part
            ),
            360,
        ),
        "city": city,
        "isOverseas": False,
        "latitude": float(amap.get("lat") or 0.0),
        "longitude": float(amap.get("lng") or 0.0),
        "telephone": tel,
        "business_hour": compact_text(amap.get("opentime"), 180),
        "categories": categories,
        "shopI18ns": [],
        "mShopInfoUrl": source_url,
        "appShopInfoUrl": source_url,
        "evtShopInfoUrl": "",
        "pcShopInfoUrl": source_url,
        "wxShopInfoUrl": "",
        "headPic": "",
        "headPicVisible": 0,
        "reviewCount": 0,
        "star": rating,
        "avgprice": 0,
        "reviewTags": review_tags_from_candidate(candidate),
        "mReviewAllUrl": "",
        "appReviewAllUrl": "",
        "ugcs": ugcs_from_candidate(candidate),
        "picCount": 0,
        "shopPics": [],
        "dishs": [],
        "mRecommendDishUrl": "",
        "appRecommendDishUrl": "",
        "special": [],
        "isBlackPearl": 0,
        "takeawayable": False,
        "takeawayinfo": None,
        "queueable": False,
        "appQueueUrl": "",
        "mQueueUrl": "",
        "bookable": bool(re.search(r"预约|提前", candidate_text(candidate))),
        "appBookURL": "",
        "mBookURL": "",
        "mallInfo": None,
        "dealInfo": [],
        "brandName": compact_text(candidate.get("category_hint"), 40),
    }


def role_for_real_candidate(poi: dict[str, Any], candidate: dict[str, Any], base_role: str) -> str:
    name = str(poi.get("name") or "")
    categories = set(poi.get("categories") or [])
    category_hint = str(candidate.get("category_hint") or "")

    if is_real_city_essential(poi):
        return "city_essential"
    if category_hint in FALLBACK_CATEGORY_HINTS:
        return "fallback"
    if "美食" in categories:
        return "meal"
    if "购物" in categories or any(keyword in name for keyword in CONNECTOR_NAME_KEYWORDS):
        return "connector"
    if "酒店" in categories:
        return "fallback"
    if category_hint == "生活服务" and not source_platforms(candidate).intersection({"xhs"}):
        return "fallback"
    if category_hint == "商务住宅":
        return "fallback"
    if base_role in POI_ROLES:
        return base_role
    return "persona_preferred"


def planning_tags_from_signals(candidate: dict[str, Any], poi: dict[str, Any]) -> set[str]:
    raw_signals = candidate.get("raw_signals") if isinstance(candidate.get("raw_signals"), dict) else {}
    tags: set[str] = set()
    category_hint = str(candidate.get("category_hint") or "")
    for term in as_list(raw_signals.get("positive_terms")):
        if str(term) in FOOD_SEMANTIC_TERMS and category_hint != "餐饮服务":
            continue
        tags.update(POSITIVE_TERM_TO_PLANNING_TAGS.get(str(term), set()))
    text = candidate_text(candidate)
    for term, mapped in POSITIVE_TERM_TO_PLANNING_TAGS.items():
        if term in FOOD_SEMANTIC_TERMS and category_hint != "餐饮服务":
            continue
        if term in text:
            tags.update(mapped)

    name = str(poi.get("name") or "")
    poi_type = str((candidate.get("amap_match") or {}).get("poi_type") or "")

    if category_hint == "餐饮服务":
        tags.update({"food", "food_quality"})
    if category_hint == "购物服务":
        tags.update({"shopping_friendly", "rain_friendly", "rest_friendly"})
    if category_hint in {"风景名胜", "科教文化服务"}:
        tags.add("photo_friendly")
    if "博物馆" in name or "博物馆" in poi_type or "纪念馆" in name:
        tags.update({"culture_friendly", "rain_friendly"})
    if re.search(r"海|湾|江|湖|塔|夜景|灯光", name + poi_type):
        tags.add("photo_friendly")
    if re.search(r"地铁|公交|车站|步行街", candidate_text(candidate)):
        tags.add("transit_friendly")
    if "儿童" in name or "亲子" in name or "乐园" in name:
        tags.add("family_friendly")
    return tags


def risk_tags_from_signals(candidate: dict[str, Any], poi: dict[str, Any], role: str) -> set[str]:
    raw_signals = candidate.get("raw_signals") if isinstance(candidate.get("raw_signals"), dict) else {}
    tags: set[str] = set()
    for term in as_list(raw_signals.get("risk_terms")):
        tags.update(RISK_TERM_TO_RISK_TAGS.get(str(term), set()))
    text = candidate_text(candidate)
    for term, mapped in RISK_TERM_TO_RISK_TAGS.items():
        if term in text:
            tags.update(mapped)

    name = str(poi.get("name") or "")
    if role == "city_essential" and source_platforms(candidate).intersection({"xhs"}):
        tags.add("crowded_weekend")
    if any(keyword in name for keyword in LANDMARK_WALK_KEYWORDS):
        tags.add("walk_heavy")
    return tags


def traveler_types_for_label(label: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    tags = set(label.get("planning_tags") or [])
    role = str(label.get("poi_role") or "")
    category_hint = str(candidate.get("category_hint") or "")
    out: list[str] = []

    if "couple_friendly" in tags or "photo_friendly" in tags or "night_friendly" in tags:
        out.append("情侣")
    if "family_friendly" in tags or "rain_friendly" in tags:
        out.append("家庭亲子")
    if "culture_friendly" in tags or "transit_friendly" in tags or "rest_friendly" in tags:
        out.append("银发")
    if "food" in tags or "shopping_friendly" in tags or "atmosphere" in tags:
        out.append("朋友团")
    if "business_friendly" in tags or category_hint in {"商务住宅", "购物服务"}:
        out.append("商务")
    if role in {"persona_preferred", "connector", "meal"}:
        out.append("独行")
    if role == "city_essential":
        out.extend(TRAVELER_TYPES)
    return dedupe_preserve_order(out) or ["独行"]


def modifiers_for_label(label: dict[str, Any]) -> dict[str, bool]:
    tags = set(label.get("planning_tags") or [])
    risks = set(label.get("risk_tags") or [])
    role = str(label.get("poi_role") or "")
    return {
        "轻量体力": "rest_friendly" in tags
        or "transit_friendly" in tags
        or role in {"meal", "connector"},
        "重文化": "culture_friendly" in tags or "landmark" in tags,
        "重美食": "food" in tags or "food_quality" in tags or "premium_food" in tags,
        "怕排队": "queue_heavy" not in risks
        and "crowded_weekend" not in risks
        and "reservation_recommended" not in risks,
    }


def priority_for_label(poi: dict[str, Any], candidate: dict[str, Any], label: dict[str, Any]) -> int:
    role = str(label.get("poi_role") or "")
    rating = float(poi.get("star") or 0.0)
    has_xhs = "xhs" in source_platforms(candidate)
    priority = int(label.get("manual_priority") or 0)

    if role == "city_essential":
        priority = max(priority, 92)
    elif role == "meal":
        priority = max(priority, 55 if rating >= 4.7 else 42)
    elif role == "persona_preferred":
        priority = max(priority, 62 if has_xhs else 45 if rating >= 4.7 else 35)
    elif role == "connector":
        priority = max(priority, 55 if has_xhs else 38)
    else:
        priority = min(priority, 25)

    if has_xhs:
        priority += 6
    if rating >= 4.8:
        priority += 4
    return max(0, min(100, priority))


def confidence_for_label(candidate: dict[str, Any], label: dict[str, Any]) -> float:
    role = str(label.get("poi_role") or "")
    platforms = source_platforms(candidate)
    confidence = 0.72
    if "amap" in platforms:
        confidence += 0.08
    if "xhs" in platforms:
        confidence += 0.08
    if role == "city_essential":
        confidence += 0.05
    if role == "fallback":
        confidence -= 0.08
    return round(max(0.55, min(0.95, confidence)), 2)


def notes_for_label(candidate: dict[str, Any], label: dict[str, Any]) -> str:
    platforms = source_platforms(candidate)
    evidence_bits = ["高德提供实体、坐标、评分和营业时间。"] if "amap" in platforms else []
    xhs_evidence = [
        evidence
        for evidence in as_list(candidate.get("source_evidence"))
        if isinstance(evidence, dict) and evidence.get("source_platform") == "xhs"
    ]
    if xhs_evidence:
        first = xhs_evidence[0]
        mention = compact_text(first.get("matched_mention") or first.get("title"), 30)
        evidence_bits.append(f"小红书攻略提到 {mention}，用于补充路线语义。")
    role = str(label.get("poi_role") or "")
    tags = ", ".join((label.get("planning_tags") or [])[:4])
    risks = ", ".join((label.get("risk_tags") or [])[:3])
    evidence_bits.append(f"标为 {role}；核心标签：{tags or '无'}。")
    if risks:
        evidence_bits.append(f"风险：{risks}。")
    return compact_text("".join(evidence_bits), 180)


def build_agent_label(poi: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    base = build_enriched_label(poi)
    label = dict(base)
    role = role_for_real_candidate(poi, candidate, str(base.get("poi_role") or ""))
    label["poi_role"] = role

    planning = set(base.get("planning_tags") or [])
    risks = set(base.get("risk_tags") or [])
    planning.update(planning_tags_from_signals(candidate, poi))
    risks.update(risk_tags_from_signals(candidate, poi, role))

    if role == "city_essential":
        planning.update({"landmark", "first_visit_friendly"})
        label["must_consider"] = True
        label["universal_level"] = "high"
    elif role in {"persona_preferred", "connector"} and (
        "xhs" in source_platforms(candidate) or float(poi.get("star") or 0.0) >= 4.7
    ):
        label["universal_level"] = "medium"
        label["must_consider"] = False
    elif role == "meal":
        label["universal_level"] = "medium" if float(poi.get("star") or 0.0) >= 4.7 else "low"
        label["must_consider"] = False
    else:
        label["universal_level"] = "low"
        label["must_consider"] = False

    if role == "meal":
        planning.add("food")
        slots = {"lunch", "dinner"}
        min_stay, max_stay = 60, 90
    elif role == "city_essential":
        slots = {"morning", "afternoon"}
        if "night_friendly" in planning:
            slots.add("evening")
        min_stay, max_stay = 90, 180
    elif role == "connector":
        slots = {"afternoon", "evening"}
        if "food" in planning:
            slots.update({"lunch", "dinner"})
        min_stay, max_stay = 30, 90
    elif role == "fallback":
        slots = {"afternoon"}
        min_stay, max_stay = 30, 60
    else:
        slots = set(base.get("suggested_slots") or ["morning", "afternoon"])
        min_stay, max_stay = 60, 120
    if "night_friendly" in planning:
        slots.add("evening")
    if re.search(r"咖啡|茶|书店", str(poi.get("name") or "")):
        slots.add("afternoon_tea")

    district = str(label.get("district") or poi.get("district") or "").strip()
    city = str(poi.get("city") or "")
    city_zone = zone_for_city_district(city, district)
    label["district"] = district
    label["city_zone"] = city_zone
    label["neighbor_zones"] = neighbor_zones_for(city, city_zone)
    label["planning_tags"] = ordered_tags(planning, PLANNING_TAGS)
    label["risk_tags"] = ordered_tags(risks, RISK_TAGS)
    label["suggested_slots"] = ordered_slots(slots)
    label["min_stay_minutes"] = min_stay
    label["max_stay_minutes"] = max_stay
    label["traveler_types"] = traveler_types_for_label(label, candidate)
    label["modifiers"] = modifiers_for_label(label)
    label["manual_priority"] = priority_for_label(poi, candidate, label)
    label["confidence"] = confidence_for_label(candidate, label)
    label["label_notes"] = notes_for_label(candidate, label)
    return label


def enriched_from_agent_label(label: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    enriched = {
        key: value
        for key, value in label.items()
        if key not in {"confidence", "label_notes"}
    }
    sources = {"agent:real_sources:v1"}
    if "amap" in source_platforms(candidate):
        sources.add("amap:poi")
    if "xhs" in source_platforms(candidate):
        sources.add("xhs:guide")
    enriched["label_sources"] = sorted(sources)
    return enriched


def legacy_from_agent_label(label: dict[str, Any]) -> dict[str, Any]:
    return {
        "traveler_types": label.get("traveler_types") or [],
        "modifiers": {
            name: bool((label.get("modifiers") or {}).get(name, False))
            for name in MODIFIER_NAMES
        },
    }


def build_index(city_pois: list[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    index: dict[str, dict[str, list[str]]] = {
        "by_category": defaultdict(list),
        "by_district": defaultdict(list),
        "by_mall": defaultdict(list),
        "by_keyword": defaultdict(list),
    }
    keyword_pool = [
        "火锅",
        "粤菜",
        "川菜",
        "湘菜",
        "日料",
        "西餐",
        "咖啡",
        "茶",
        "小吃",
        "景点",
        "公园",
        "博物馆",
        "展馆",
        "古迹",
        "历史",
        "购物",
        "商场",
        "书店",
        "酒店",
        "KTV",
        "酒吧",
        "亲子",
        "儿童",
        "乐园",
        "外滩",
        "陆家嘴",
        "东方明珠",
        "豫园",
        "南京路",
        "钟楼",
        "鼓楼",
        "大雁塔",
        "兵马俑",
        "城墙",
        "回民街",
        "深圳湾",
        "世界之窗",
        "华强北",
        "欢乐港湾",
        "海上世界",
    ]
    mall_keywords = ("广场", "中心", "天地", "万象", "大悦城", "万达", "SKP", "太古里", "IFC")

    for poi in city_pois:
        shop_id = str(poi.get("openshopid") or "")
        name = str(poi.get("name") or "")
        for category in poi.get("categories") or []:
            index["by_category"][str(category)].append(shop_id)
        district = str(poi.get("district") or "")
        if district:
            index["by_district"][district].append(shop_id)
        if any(keyword in name for keyword in mall_keywords):
            index["by_mall"][name].append(shop_id)
        for keyword in keyword_pool:
            if keyword in name:
                index["by_keyword"][keyword].append(shop_id)

    return {section: dict(values) for section, values in index.items()}


def metadata_for(by_city: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    city_stats: dict[str, Any] = {}
    for city, rows in by_city.items():
        categories = Counter(
            category for poi in rows for category in (poi.get("categories") or [])
        )
        districts = Counter(str(poi.get("district") or "") for poi in rows if poi.get("district"))
        city_stats[city] = {
            "total": len(rows),
            "by_category": dict(categories.most_common()),
            "by_district": dict(districts.most_common()),
            "avg_review": 0,
            "avg_price": 0,
            "food_count": sum(1 for poi in rows if "美食" in (poi.get("categories") or [])),
            "black_pearl_count": 0,
        }
    return {
        "generated_at": now_iso(),
        "total_count": sum(len(rows) for rows in by_city.values()),
        "version": "real_sources:v1",
        "source": "amap+xhs-real-sources",
        "city_stats": city_stats,
        "categories_used": sorted(
            {
                category
                for rows in by_city.values()
                for poi in rows
                for category in (poi.get("categories") or [])
            }
        ),
    }


def validate_no_duplicate_ids(pois: list[dict[str, Any]]) -> None:
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for poi in pois:
        shop_id = str(poi.get("openshopid") or "")
        city = str(poi.get("city") or "")
        if shop_id in seen:
            duplicates.append(f"{shop_id} ({seen[shop_id]} / {city})")
            continue
        seen[shop_id] = city
    if duplicates:
        raise ValueError(f"duplicate openshopid values: {duplicates[:10]}")


def validate_required_poi_fields(pois: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for poi in pois:
        shop_id = str(poi.get("openshopid") or "<missing>")
        for field in (
            "openshopid",
            "name",
            "city",
            "address",
            "latitude",
            "longitude",
            "categories",
            "star",
            "reviewCount",
        ):
            if poi.get(field) in (None, "", []):
                errors.append(f"{shop_id}: missing {field}")
    return errors


def build_outputs(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    pois: list[dict[str, Any]] = []
    candidates_by_id: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        poi = build_poi(candidate)
        pois.append(poi)
        candidates_by_id[poi["openshopid"]] = candidate
    validate_no_duplicate_ids(pois)

    by_city: dict[str, list[dict[str, Any]]] = {city: [] for city in CITIES}
    for poi in sorted(pois, key=lambda item: (str(item["city"]), str(item["name"]), str(item["openshopid"]))):
        by_city.setdefault(str(poi["city"]), []).append(poi)

    agent_labels: dict[str, dict[str, dict[str, Any]]] = {city: {} for city in CITIES}
    enriched_labels: dict[str, dict[str, dict[str, Any]]] = {city: {} for city in CITIES}
    legacy_labels: dict[str, dict[str, dict[str, Any]]] = {city: {} for city in CITIES}
    for city, city_pois in by_city.items():
        for poi in city_pois:
            shop_id = str(poi["openshopid"])
            candidate = candidates_by_id[shop_id]
            label = build_agent_label(poi, candidate)
            enriched = enriched_from_agent_label(label, candidate)
            agent_labels[city][shop_id] = label
            enriched_labels[city][shop_id] = enriched
            legacy_labels[city][shop_id] = legacy_from_agent_label(label)

    return {
        "by_city": by_city,
        "agent_labels": agent_labels,
        "enriched_labels": enriched_labels,
        "legacy_labels": legacy_labels,
    }


def build_summary(outputs: dict[str, Any], source_path: Path) -> dict[str, Any]:
    by_city = outputs["by_city"]
    enriched = outputs["enriched_labels"]
    required_errors = [
        error for pois in by_city.values() for error in validate_required_poi_fields(pois)
    ]
    city_summary: dict[str, Any] = {}
    for city, pois in by_city.items():
        role_counter = Counter(
            str(label.get("poi_role") or "unknown")
            for label in enriched.get(city, {}).values()
        )
        planning_counter: Counter[str] = Counter()
        risk_counter: Counter[str] = Counter()
        zone_counter = Counter(
            str(label.get("city_zone") or "unknown")
            for label in enriched.get(city, {}).values()
        )
        source_counter: Counter[str] = Counter()
        data_source_counter = Counter(str(poi.get("data_source") or "unknown") for poi in pois)
        for label in enriched.get(city, {}).values():
            planning_counter.update(label.get("planning_tags") or [])
            risk_counter.update(label.get("risk_tags") or [])
            source_counter.update(label.get("label_sources") or [])
        city_summary[city] = {
            "poi_count": len(pois),
            "data_sources": dict(data_source_counter.most_common()),
            "poi_roles": dict(role_counter.most_common()),
            "city_zones": dict(zone_counter.most_common()),
            "planning_tags": dict(planning_counter.most_common(12)),
            "risk_tags": dict(risk_counter.most_common(12)),
            "label_sources": dict(source_counter.most_common()),
        }

    return {
        "schema_version": "final_data_build_summary:v1",
        "generated_at": now_iso(),
        "source": str(source_path),
        "outputs": {
            "mock_dir": str(MOCK_DIR),
            "agent_labels": str(AGENT_LABELS_PATH),
            "legacy_labels": str(LEGACY_LABELS_PATH),
            "enriched_labels": str(ENRICHED_LABELS_PATH),
        },
        "error_count": len(required_errors),
        "errors_sample": required_errors[:50],
        "cities": city_summary,
    }


def write_outputs(outputs: dict[str, Any], source_path: Path) -> dict[str, Any]:
    by_city = outputs["by_city"]
    MOCK_DIR.mkdir(parents=True, exist_ok=True)
    for city in CITIES:
        write_json(MOCK_DIR / f"{city}.json", by_city.get(city, []))
    write_json(
        MOCK_DIR / "index.json",
        {city: build_index(by_city.get(city, [])) for city in CITIES},
    )
    write_json(MOCK_DIR / "metadata.json", metadata_for(by_city))
    write_json(AGENT_LABELS_PATH, outputs["agent_labels"])
    write_json(ENRICHED_LABELS_PATH, outputs["enriched_labels"])
    write_json(LEGACY_LABELS_PATH, outputs["legacy_labels"])

    summary = build_summary(outputs, source_path)
    write_json(BUILD_SUMMARY_PATH, summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    candidates = read_jsonl(args.source)
    outputs = build_outputs(candidates)
    summary = write_outputs(outputs, args.source)

    print("mtagent 最终数据已生成:")
    print(f"  source_candidates: {len(candidates)}")
    print(f"  mock_dir: {MOCK_DIR}")
    print(f"  agent_labels: {AGENT_LABELS_PATH}")
    print(f"  legacy_labels: {LEGACY_LABELS_PATH}")
    print(f"  enriched_labels: {ENRICHED_LABELS_PATH}")
    print(f"  build_summary: {BUILD_SUMMARY_PATH}")
    for city, data in summary["cities"].items():
        print(
            f"  - {city}: {data['poi_count']} POIs, "
            f"roles={data['poi_roles']}, zones={data['city_zones']}"
        )
    if summary["error_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
