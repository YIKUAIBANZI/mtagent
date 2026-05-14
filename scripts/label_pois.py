"""Offline pipeline for route-planning POI labels.

Stage 1 uses deterministic rules to label POIs from structured fields
(reviewTags / special / categories / address / queueable / isBlackPearl).
Stage 2 can merge AI-produced UGC labels from data/poi_ai_labels.json when that
file exists. Manual corrections from data/poi_manual_labels.json are also
merged when present.

Run:
    PYTHONPATH=. python scripts/label_pois.py
Outputs:
    data/poi_labels.json             Legacy persona labels used by current code
    data/poi_enriched_labels.json    Route-planning labels for future Planner
    data/poi_ai_label_tasks.jsonl    AI-label tasks for high-value POIs
    data/poi_label_summary.json      Label distribution summary
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

CITIES = ("深圳", "上海", "西安")
DATA_DIR = Path("data/mock_dianping")
OUT_PATH = Path("data/poi_labels.json")
ENRICHED_OUT_PATH = Path("data/poi_enriched_labels.json")
AI_TASKS_OUT_PATH = Path("data/poi_ai_label_tasks.jsonl")
SUMMARY_OUT_PATH = Path("data/poi_label_summary.json")
AI_LABELS_PATH = Path("data/poi_ai_labels.json")
MANUAL_LABELS_PATH = Path("data/poi_manual_labels.json")

AI_TASK_LIMIT_PER_CITY = 160

LIST_MERGE_FIELDS = {
    "traveler_types",
    "planning_tags",
    "risk_tags",
    "suggested_slots",
    "neighbor_zones",
}

SCALAR_OVERRIDE_FIELDS = {
    "poi_role",
    "universal_level",
    "must_consider",
    "district",
    "city_zone",
    "manual_priority",
    "min_stay_minutes",
    "max_stay_minutes",
}

TAG_TO_PLANNING = {
    "出片漂亮": "photo_friendly",
    "菜品精致": "food_quality",
    "食材新鲜": "food_quality",
    "老字号": "culture_friendly",
    "本地特色": "culture_friendly",
    "亲子友好": "family_friendly",
    "适合约会": "couple_friendly",
    "适合聚会": "group_friendly",
    "包厢私密": "business_friendly",
    "商务宴请": "business_friendly",
    "环境优雅": "quiet",
    "氛围佳": "atmosphere",
    "交通方便": "transit_friendly",
    "性价比高": "good_value",
    "服务好": "good_service",
    "上菜快": "fast_service",
}

TAG_TO_RISK = {
    "等位久": "queue_heavy",
    "上菜慢": "slow_service",
    "价格偏贵": "pricey",
    "位置难找": "hard_to_find",
    "停车难": "parking_hard",
    "厕所老旧": "facility_old",
    "油烟大": "smoky",
    "分量小": "small_portion",
    "服务一般": "service_average",
    "菜量虚标": "portion_mismatch",
}

CITY_ESSENTIAL_KEYWORDS = {
    "深圳": [
        "深圳湾公园",
        "深圳世界之窗",
        "世界之窗",
        "欢乐海岸",
        "莲花山公园",
        "华强北",
        "东门老街",
        "海上世界",
        "大梅沙",
        "小梅沙",
        "大鹏所城",
        "较场尾",
        "甘坑古镇",
        "大芬油画村",
        "欢乐港湾",
    ],
    "上海": [
        "东方明珠",
        "外滩",
        "陆家嘴",
        "豫园",
        "南京东路",
        "人民广场",
        "上海博物馆",
        "武康路",
        "新天地",
        "田子坊",
        "城隍庙",
        "静安寺",
        "北外滩",
    ],
    "西安": [
        "钟楼",
        "大雁塔",
        "回民街",
        "永宁门",
        "城墙",
        "大唐不夜城",
        "大唐芙蓉园",
        "兵马俑",
        "秦始皇兵马俑",
        "华清池",
        "华清宫",
        "陕西历史博物馆",
        "鼓楼",
        "碑林博物馆",
        "小寨",
        "小寨赛格",
        "华山",
    ],
}

LANDMARK_FALSE_POSITIVE_TERMS = (
    "酒店",
    "民宿",
    "餐厅",
    "菜馆",
    "家宴",
    "茶餐厅",
    "火锅店",
    "烧烤摊",
    "小吃店",
    "日料店",
    "美容院",
    "美发店",
    "美甲店",
    "母婴店",
    "早教中心",
    "水果店",
    "超市",
    "便利店",
    "儿童乐园",
    "电影院",
    "书店",
    "乐园",
    "服装店",
    "网吧",
    "健身房",
    "游泳池",
    "棋牌室",
    "KTV",
    "湘菜",
    "川菜",
    "粤菜",
)

DISTRICT_ALIASES = {
    "深圳": {
        "南山区": ["南山区", "深圳湾", "世界之窗", "欢乐海岸", "海上世界", "南头", "万象天地"],
        "福田区": ["福田区", "华强北", "莲花山", "市民中心"],
        "罗湖区": ["罗湖区", "东门老街", "东门"],
        "宝安区": ["宝安区", "欢乐港湾", "宝安"],
        "盐田区": ["盐田区", "大梅沙", "小梅沙", "海滨栈道"],
        "龙岗区": ["龙岗区", "甘坑", "大芬", "龙岗"],
        "大鹏新区": ["大鹏", "较场尾", "杨梅坑", "桔钓沙", "天文台"],
        "龙华区": ["龙华区", "龙华"],
        "光明区": ["光明区", "光明"],
        "坪山区": ["坪山区", "坪山"],
    },
    "上海": {
        "黄浦区": ["黄浦区", "外滩", "豫园", "南京东路", "人民广场", "城隍庙", "田子坊"],
        "浦东新区": ["浦东新区", "陆家嘴", "世纪大道"],
        "静安区": ["静安区", "南京西路", "静安寺", "新天地"],
        "徐汇区": ["徐汇区", "武康路", "徐家汇"],
        "虹口区": ["虹口区", "北外滩", "甜爱路", "鲁迅公园", "多伦路"],
        "普陀区": ["普陀区", "M50"],
        "长宁区": ["长宁区"],
        "闵行区": ["闵行区"],
    },
    "西安": {
        "碑林区": ["碑林区", "钟楼", "永宁门", "南大街", "城墙"],
        "莲湖区": ["莲湖区", "回民街", "北院门", "青年路"],
        "雁塔区": ["雁塔区", "大雁塔", "小寨", "曲江"],
        "新城区": ["新城区", "西安站"],
        "未央区": ["未央区", "凤城"],
        "长安区": ["长安区", "子午大道"],
        "临潼区": ["临潼区", "兵马俑", "华清池"],
        "高新区": ["高新区", "科技路", "科技二路"],
    },
}

ZONE_BY_DISTRICT = {
    "深圳": {
        "南山区": "west",
        "宝安区": "west",
        "福田区": "center",
        "罗湖区": "center",
        "龙华区": "north",
        "光明区": "north",
        "盐田区": "east",
        "龙岗区": "east",
        "坪山区": "east",
        "大鹏新区": "far_east",
    },
    "上海": {
        "黄浦区": "center",
        "静安区": "center",
        "徐汇区": "center",
        "浦东新区": "east",
        "虹口区": "north_center",
        "杨浦区": "north",
        "普陀区": "west",
        "长宁区": "west",
        "闵行区": "southwest",
    },
    "西安": {
        "碑林区": "center",
        "莲湖区": "center",
        "新城区": "center",
        "雁塔区": "south",
        "高新区": "west",
        "长安区": "south",
        "未央区": "north",
        "临潼区": "east",
    },
}

NEIGHBOR_ZONES = {
    "深圳": {
        "west": ["center", "north"],
        "center": ["west", "north", "east"],
        "north": ["west", "center"],
        "east": ["center", "far_east"],
        "far_east": ["east"],
        "unknown": [],
    },
    "上海": {
        "center": ["east", "north_center", "west", "north"],
        "east": ["center"],
        "north_center": ["center", "west", "north"],
        "north": ["center", "north_center"],
        "west": ["center", "north_center", "southwest"],
        "southwest": ["west"],
        "unknown": [],
    },
    "西安": {
        "center": ["south", "west", "north"],
        "south": ["center", "west"],
        "west": ["center", "south"],
        "north": ["center"],
        "east": ["center"],
        "unknown": [],
    },
}

SLOT_ORDER = ["morning", "lunch", "afternoon", "afternoon_tea", "dinner", "evening"]


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


def _tag_hits(poi: dict) -> dict[str, int]:
    return {
        str(t.get("tag")): int(t.get("hit") or 0)
        for t in poi.get("reviewTags") or []
        if t.get("tag")
    }


def _desc_blob(poi: dict) -> str:
    """只取 name + address + shopDesc，不含 UGC（避免 UGC 噪声）。"""
    parts = [
        str(poi.get("name") or ""),
        str(poi.get("address") or ""),
        str(poi.get("shopDesc") or ""),
    ]
    return "\n".join(parts)


def _text_blob(poi: dict) -> str:
    parts = [
        str(poi.get("name") or ""),
        str(poi.get("address") or ""),
        str(poi.get("shopDesc") or ""),
    ]
    for ugc in poi.get("ugcs") or []:
        parts.append(str(ugc.get("content") or ""))
    return "\n".join(parts)


def _ordered(values: set[str], order: list[str] | None = None) -> list[str]:
    if order is None:
        return sorted(values)
    idx = {v: i for i, v in enumerate(order)}
    return sorted(values, key=lambda v: (idx.get(v, len(idx)), v))


def infer_district(poi: dict) -> str:
    city = str(poi.get("city") or "")
    # 优先使用 POI 原始 district 字段（数据 100% 覆盖）
    raw_district = str(poi.get("district") or "").strip()
    if raw_district:
        # 精确匹配 DISTRICT_ALIASES 的 key
        if raw_district in DISTRICT_ALIASES.get(city, {}):
            return raw_district
        # 原始字段可能是别名（如"宝安"→"宝安区"），做反向查找
        for district, keys in DISTRICT_ALIASES.get(city, {}).items():
            if raw_district in keys or raw_district == district:
                return district
        # 仍未匹配，用原始值作为 district（后续 infer_city_zone 仍可能命中）
        return raw_district
    # 回退到地址文本匹配
    blob = _text_blob(poi)
    for district, keys in DISTRICT_ALIASES.get(city, {}).items():
        if any(k in blob for k in keys):
            return district
    return ""


def infer_city_zone(city: str, district: str) -> str:
    if not district:
        return "unknown"
    return ZONE_BY_DISTRICT.get(city, {}).get(district, "unknown")


# 合理的地标后缀——关键词 + 这些后缀仍可视为地标
LANDMARK_VALID_SUFFIXES = (
    "景区", "公园", "博物馆", "纪念馆", "广场", "步行街", "古街",
    "古镇", "老街", "乐园", "世界", "乐园", "海岸", "塔", "楼",
    "寺", "宫", "庙", "陵", "园", "遗址", "石窟", "故居",
)

# 需要完整匹配的关键词（不能只包含就判定）
LANDMARK_EXACT_ONLY = {"小寨", "小寨赛格"}


def is_city_essential(poi: dict) -> bool:
    city = str(poi.get("city") or "")
    name = str(poi.get("name") or "")
    for kw in CITY_ESSENTIAL_KEYWORDS.get(city, []):
        if kw not in name:
            continue
        # 完全匹配或带分隔符的匹配（如"世界之窗-xxx"）
        if name == kw or name.startswith(f"{kw}-") or name.startswith(f"{kw}·"):
            # 仍需排除 false positive
            if any(term in name for term in LANDMARK_FALSE_POSITIVE_TERMS):
                continue
            return True
        # 关键词在 name 中，但 name 不是精确匹配 → 检查后缀
        # 先排除 false positive
        if any(term in name for term in LANDMARK_FALSE_POSITIVE_TERMS):
            continue
        # 检查是否是 "关键词+合理后缀" 的模式（如"大雁塔景区"）
        suffix_part = name[len(kw):]
        if suffix_part and any(suffix_part.startswith(s) for s in LANDMARK_VALID_SUFFIXES):
            return True
        # 特殊处理：名称完全以关键词开头且剩余部分是数字或空
        if name.startswith(kw) and (not suffix_part or suffix_part.isdigit()):
            return True
        # LANDMARK_EXACT_ONLY 类关键词不模糊匹配
        if kw in LANDMARK_EXACT_ONLY and name != kw:
            continue
        # 其他情况：关键词在 name 中且不含 false positive → 保留
        # 但要求关键词在 name 的开头（避免 "xxx钟楼" 误判）
        if name.startswith(kw):
            return True
    return False


def label_poi_role(poi: dict) -> str:
    categories = set(poi.get("categories") or [])
    tags = _tag_hits(poi)
    name = str(poi.get("name") or "")

    if is_city_essential(poi):
        return "city_essential"
    if "美食" in categories:
        return "meal"
    if "购物" in categories:
        return "connector"
    if "酒店" in categories:
        return "fallback"
    if "亲子" in categories or "亲子友好" in tags:
        return "persona_preferred"
    if "丽人" in categories:
        return "connector"
    if any(k in name for k in ("咖啡", "茶", "书店", "商场", "万象城")):
        return "connector"
    return "persona_preferred"


def label_planning_tags(poi: dict, poi_role: str) -> list[str]:
    tags = _tag_hits(poi)
    categories = set(poi.get("categories") or [])
    special = set(poi.get("special") or [])
    blob = _text_blob(poi)
    out: set[str] = set()

    for tag, mapped in TAG_TO_PLANNING.items():
        if tag in tags:
            out.add(mapped)

    if "美食" in categories:
        out.add("food")
    if "购物" in categories:
        out.add("shopping_friendly")
        out.add("rain_friendly")
    if "亲子" in categories or "提供婴儿椅" in special:
        out.add("family_friendly")
    if "无障碍" in special:
        out.add("senior_friendly")
    if "可包间" in special:
        out.add("private_room")
    if "免费 WiFi" in special:
        out.add("rest_friendly")
    if "宠物友好" in special:
        out.add("pet_friendly")
    if poi.get("isBlackPearl") == 1:
        out.add("premium_food")
        out.add("food_quality")
    if poi_role == "city_essential":
        out.add("first_visit_friendly")
        out.add("landmark")
    if re.search(r"夜景|灯会|KTV|酒吧|Live|夜市|晚上|夜晚", blob, re.I):
        out.add("night_friendly")
    if re.search(r"拍照|出片|江景|海景|日落|日出", blob):
        out.add("photo_friendly")
    if re.search(r"安静|坐一坐", blob):
        out.add("quiet")
        out.add("rest_friendly")
    if re.search(r"室内|商场|电影院|书店|KTV|网吧|美术馆|博物馆", blob):
        out.add("rain_friendly")
    # transit_friendly: 只从 address（非 UGC）匹配"地铁"，或 reviewTags "交通方便"
    addr_blob = _desc_blob(poi)
    if re.search(r"地铁|公交", addr_blob) or "交通方便" in tags:
        out.add("transit_friendly")

    return _ordered(out)


def label_risk_tags(poi: dict, poi_role: str) -> list[str]:
    tags = _tag_hits(poi)
    name = str(poi.get("name") or "")
    blob = _text_blob(poi)
    out: set[str] = set()

    for tag, mapped in TAG_TO_RISK.items():
        if tag in tags:
            out.add(mapped)

    if "等位久" in tags or re.search(
        r"等位久|排队排到|排队.*崩溃|队伍.*长",
        blob,
    ):
        out.add("queue_heavy")
    if poi.get("bookable", False):
        out.add("reservation_recommended")
    if poi_role == "city_essential" and int(poi.get("reviewCount") or 0) >= 1000:
        out.add("crowded_weekend")
    if any(k in name for k in ("公园", "世界之窗", "城墙", "兵马俑", "大雁塔", "大鹏所城")):
        out.add("walk_heavy")
    if re.search(r"走路|逛完.*累|地方.*大|爬坡", blob):
        out.add("walk_heavy")

    return _ordered(out)


def label_suggested_slots(poi: dict, poi_role: str, planning_tags: list[str]) -> list[str]:
    name = str(poi.get("name") or "")
    slots: set[str] = set()

    if poi_role == "meal":
        slots.update({"lunch", "dinner"})
    elif poi_role == "city_essential":
        slots.update({"morning", "afternoon"})
    elif poi_role == "connector":
        slots.update({"afternoon", "evening"})
    elif poi_role == "fallback":
        slots.update({"afternoon"})
    else:
        slots.update({"morning", "afternoon"})

    if "night_friendly" in planning_tags or any(k in name for k in ("KTV", "灯会", "夜")):
        slots.add("evening")
    if any(k in name for k in ("咖啡", "茶", "书店")):
        slots.add("afternoon_tea")
    if "food" in planning_tags:
        slots.update({"lunch", "dinner"})

    return _ordered(slots, SLOT_ORDER)


def stay_minutes_for_role(poi_role: str) -> tuple[int, int]:
    if poi_role == "city_essential":
        return 90, 180
    if poi_role == "meal":
        return 60, 90
    if poi_role == "connector":
        return 30, 90
    if poi_role == "fallback":
        return 30, 60
    return 60, 120


def universal_level_for(poi: dict, poi_role: str) -> str:
    review_count = int(poi.get("reviewCount") or 0)
    if poi_role == "city_essential":
        return "high"
    if review_count >= 600 and poi_role in {"persona_preferred", "connector"}:
        return "medium"
    return "low"


def manual_priority_for(poi: dict, poi_role: str) -> int:
    review_count = int(poi.get("reviewCount") or 0)
    star = float(poi.get("star") or 0.0)
    if poi_role == "city_essential":
        return 90 + min(review_count // 1000, 9)
    if review_count >= 1000 and star >= 4.5:
        return 70
    if review_count >= 300:
        return 50
    return 20


def build_enriched_label(poi: dict) -> dict[str, Any]:
    city = str(poi.get("city") or "")
    district = infer_district(poi)
    city_zone = infer_city_zone(city, district)
    poi_role = label_poi_role(poi)
    planning_tags = label_planning_tags(poi, poi_role)
    risk_tags = label_risk_tags(poi, poi_role)
    min_stay, max_stay = stay_minutes_for_role(poi_role)

    return {
        "traveler_types": label_traveler_types(poi),
        "modifiers": label_modifiers(poi),
        "poi_role": poi_role,
        "universal_level": universal_level_for(poi, poi_role),
        "must_consider": poi_role == "city_essential",
        "manual_priority": manual_priority_for(poi, poi_role),
        "planning_tags": planning_tags,
        "risk_tags": risk_tags,
        "district": district,
        "city_zone": city_zone,
        "neighbor_zones": NEIGHBOR_ZONES.get(city, {}).get(city_zone, []),
        "suggested_slots": label_suggested_slots(poi, poi_role, planning_tags),
        "min_stay_minutes": min_stay,
        "max_stay_minutes": max_stay,
        "label_sources": ["rules:v1"],
    }


def load_optional_label_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def get_override(overrides: dict[str, Any], city: str, shop_id: str) -> dict[str, Any]:
    if not overrides:
        return {}
    if city in overrides and isinstance(overrides[city], dict):
        item = overrides[city].get(shop_id, {})
        return item if isinstance(item, dict) else {}
    item = overrides.get(shop_id, {})
    return item if isinstance(item, dict) else {}


def merge_override(label: dict[str, Any], override: dict[str, Any], source: str) -> dict[str, Any]:
    if not override:
        return label

    merged = dict(label)
    for field in LIST_MERGE_FIELDS:
        if field in override:
            existing = set(merged.get(field) or [])
            incoming = set(override.get(field) or [])
            order = SLOT_ORDER if field == "suggested_slots" else None
            merged[field] = _ordered(existing | incoming, order)

    if "risk_tags_remove" in override:
        remove = set(override.get("risk_tags_remove") or [])
        merged["risk_tags"] = [t for t in merged.get("risk_tags", []) if t not in remove]
    if "planning_tags_remove" in override:
        remove = set(override.get("planning_tags_remove") or [])
        merged["planning_tags"] = [
            t for t in merged.get("planning_tags", []) if t not in remove
        ]

    for field in SCALAR_OVERRIDE_FIELDS:
        if field in override and override[field] is not None:
            merged[field] = override[field]

    if "modifiers" in override and isinstance(override["modifiers"], dict):
        mods = dict(merged.get("modifiers") or {})
        mods.update(override["modifiers"])
        merged["modifiers"] = mods

    if "ai_notes" in override:
        merged["ai_notes"] = override["ai_notes"]
    if "confidence" in override:
        merged["confidence"] = override["confidence"]

    sources = list(merged.get("label_sources") or [])
    sources.append(source)
    merged["label_sources"] = _ordered(set(sources))
    return merged


def compact_ugc(ugcs: list[dict], max_items: int = 3, max_chars: int = 220) -> list[str]:
    out: list[str] = []
    for ugc in ugcs[:max_items]:
        content = re.sub(r"\s+", " ", str(ugc.get("content") or "")).strip()
        if not content:
            continue
        out.append(content[:max_chars])
    return out


def ai_task_score(poi: dict, label: dict[str, Any]) -> float:
    score = float(label.get("manual_priority") or 0)
    score += float(poi.get("star") or 0) * 8
    score += min(int(poi.get("reviewCount") or 0), 3000) / 80
    if label.get("poi_role") == "city_essential":
        score += 80
    if label.get("poi_role") in {"meal", "persona_preferred"}:
        score += 20
    if poi.get("ugcs"):
        score += 15
    return score


def build_ai_task(poi: dict, label: dict[str, Any]) -> dict[str, Any]:
    return {
        "openshopid": poi.get("openshopid"),
        "city": poi.get("city"),
        "name": poi.get("name"),
        "address": poi.get("address"),
        "categories": poi.get("categories") or [],
        "star": poi.get("star", 0),
        "reviewCount": poi.get("reviewCount", 0),
        "avgprice": poi.get("avgprice", 0),
        "reviewTags": poi.get("reviewTags") or [],
        "special": poi.get("special") or [],
        "rule_label": label,
        "ugc_excerpt": compact_ugc(poi.get("ugcs") or []),
        "expected_output_fields": [
            "planning_tags",
            "risk_tags",
            "poi_role",
            "suggested_slots",
            "min_stay_minutes",
            "max_stay_minutes",
            "confidence",
            "ai_notes",
        ],
    }


def write_ai_tasks(tasks: list[dict[str, Any]]) -> None:
    AI_TASKS_OUT_PATH.write_text(
        "\n".join(json.dumps(t, ensure_ascii=False, separators=(",", ":")) for t in tasks)
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    legacy_output: dict[str, dict[str, dict]] = {}
    enriched_output: dict[str, dict[str, dict]] = {}
    summary: dict[str, dict[str, dict[str, int]]] = {}
    ai_tasks: list[dict[str, Any]] = []
    ai_overrides = load_optional_label_file(AI_LABELS_PATH)
    manual_overrides = load_optional_label_file(MANUAL_LABELS_PATH)

    for city in CITIES:
        path = DATA_DIR / f"{city}.json"
        pois = json.loads(path.read_text(encoding="utf-8"))
        city_legacy_labels: dict[str, dict] = {}
        city_enriched_labels: dict[str, dict] = {}
        type_counter: Counter = Counter()
        role_counter: Counter = Counter()
        zone_counter: Counter = Counter()
        planning_counter: Counter = Counter()
        risk_counter: Counter = Counter()
        city_task_candidates: list[tuple[float, dict[str, Any]]] = []

        for poi in pois:
            shop_id = poi.get("openshopid")
            if not shop_id:
                continue

            base_label = build_enriched_label(poi)
            # AI tasks must be generated from the rule-only label. If we use the
            # already merged label, rerunning the pipeline turns Stage 2 into a
            # no-op and can overwrite data/poi_ai_labels.json with empty output.
            city_task_candidates.append(
                (ai_task_score(poi, base_label), build_ai_task(poi, base_label))
            )

            label = base_label
            label = merge_override(
                label,
                get_override(ai_overrides, city, shop_id),
                "ai:ugc",
            )
            label = merge_override(
                label,
                get_override(manual_overrides, city, shop_id),
                "manual",
            )

            tt = label["traveler_types"]
            mods = label["modifiers"]
            city_legacy_labels[shop_id] = {"traveler_types": tt, "modifiers": mods}
            city_enriched_labels[shop_id] = label

            for t in label.get("traveler_types", []):
                type_counter[t] += 1
            role_counter[label.get("poi_role", "unknown")] += 1
            zone_counter[label.get("city_zone", "unknown")] += 1
            planning_counter.update(label.get("planning_tags") or [])
            risk_counter.update(label.get("risk_tags") or [])

        legacy_output[city] = city_legacy_labels
        enriched_output[city] = city_enriched_labels
        summary[city] = {
            "traveler_types": dict(type_counter),
            "poi_roles": dict(role_counter),
            "city_zones": dict(zone_counter),
            "planning_tags": dict(planning_counter.most_common()),
            "risk_tags": dict(risk_counter.most_common()),
        }
        ai_tasks.extend(
            task
            for _, task in sorted(city_task_candidates, key=lambda x: x[0], reverse=True)[
                :AI_TASK_LIMIT_PER_CITY
            ]
        )

        print(f"\n[{city}] {len(city_legacy_labels)} POIs labeled")
        print("  traveler_type 分布:")
        for t, c in sorted(type_counter.items(), key=lambda x: -x[1]):
            pct = c / len(pois) * 100
            print(f"    {t:8s} {c:4d} ({pct:5.1f}%)")
            if pct < 5.0:
                print("      ⚠️  覆盖率 < 5%, 调规则补 (spec §10 risk)")
        print("  poi_role 分布:")
        for t, c in sorted(role_counter.items(), key=lambda x: -x[1]):
            print(f"    {t:18s} {c:4d}")

    OUT_PATH.write_text(
        json.dumps(legacy_output, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    ENRICHED_OUT_PATH.write_text(
        json.dumps(enriched_output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_ai_tasks(ai_tasks)
    SUMMARY_OUT_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\n✅ wrote {OUT_PATH} ({OUT_PATH.stat().st_size / 1024:.1f} KB)")
    print(
        f"✅ wrote {ENRICHED_OUT_PATH} "
        f"({ENRICHED_OUT_PATH.stat().st_size / 1024:.1f} KB)"
    )
    print(
        f"✅ wrote {AI_TASKS_OUT_PATH} "
        f"({AI_TASKS_OUT_PATH.stat().st_size / 1024:.1f} KB, {len(ai_tasks)} tasks)"
    )
    print(f"✅ wrote {SUMMARY_OUT_PATH} ({SUMMARY_OUT_PATH.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
