"""Merge real Amap POI entities with Xiaohongshu guide evidence.

This script treats Amap as the identity/coordinate layer and XHS notes as the
route/semantic evidence layer. It does not call external APIs.

Run:
    PYTHONPATH=. python3 scripts/merge_real_poi_sources.py
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

CITIES = ("深圳", "上海", "西安")
DEFAULT_AMAP_DIR = Path("/Users/yikuaibanz1/Desktop/xhsoutdata2/data/real_sources")
DEFAULT_XHS_NOTES = Path("/Users/yikuaibanz1/Desktop/xhsoutdata/xhs_notes.jsonl")
DEFAULT_OUT_DIR = Path("data/real_sources")

POSITIVE_TERMS = [
    "出片",
    "拍照",
    "好拍",
    "夜景",
    "日落",
    "看海",
    "海风",
    "好逛",
    "美食",
    "好吃",
    "小吃",
    "文化",
    "历史",
    "亲子",
    "轻松",
    "地铁直达",
    "免费",
    "浪漫",
    "舒服",
    "惬意",
    "氛围",
    "慢逛",
    "地标",
]

RISK_TERMS = [
    "排队",
    "人多",
    "拥挤",
    "预约",
    "提前",
    "防晒",
    "太阳",
    "步行多",
    "2w步",
    "太累",
    "涨价",
    "跑空",
    "闭园",
    "避开车流",
    "占道",
]

STOP_MENTIONS = {
    "返程",
    "住宿",
    "交通",
    "市内",
    "抵达",
    "景点攻略",
    "景点介绍",
    "注意事项",
    "避坑提醒",
    "美食",
    "吃什么",
    "路线安排",
    "一日游路线",
    "三日游路线",
    "必打卡",
    "推荐吃",
    "核心建议",
    "猜你想搜",
}

GENERIC_MATCHES = {
    "公园",
    "景区",
    "小镇",
    "古镇",
    "广场",
    "博物馆",
    "步行街",
    "商场",
    "餐厅",
    "酒店",
    "地铁站",
    "游客中心",
}

SPECIAL_SHORT_NAMES = {"外滩", "豫园", "钟楼", "鼓楼", "陆家嘴"}
ARROW_RE = re.compile(r"\s*(?:➡️|➡|→|->|—|–)\s*")
LEADING_MARK_RE = re.compile(r"^[^\u4e00-\u9fffA-Za-z0-9]+")
DAY_PREFIX_RE = re.compile(
    r"^(?:DAY|Day|day|第[一二三四五六七八九十\d]+天|[0-9]+[.、]|[①②③④⑤⑥⑦⑧⑨⑩])\s*[:：]?"
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


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows
    )
    path.write_text(text + ("\n" if rows else ""), encoding="utf-8")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def compact_text(value: Any, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def strip_city_prefix(value: str, city: str) -> str:
    result = value
    prefixes = {city, f"{city}市"}
    if city == "深圳":
        prefixes.update({"广东深圳", "广东省深圳市", "广东省深圳"})
    if city == "上海":
        prefixes.update({"上海市"})
    if city == "西安":
        prefixes.update({"西安市", "陕西西安", "陕西省西安市", "陕西省西安"})

    for prefix in sorted(prefixes, key=len, reverse=True):
        if result.startswith(prefix) and len(result) > len(prefix) + 1:
            result = result[len(prefix) :]
            break
    return result


def normalize_name(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\u00a0", "")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[#｜|,，。!！?？;；]+", "", text)
    return text.strip()


def has_chinese(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", value))


def clean_mention(value: str, city: str) -> str:
    text = value.strip()
    text = LEADING_MARK_RE.sub("", text)
    text = DAY_PREFIX_RE.sub("", text).strip()
    text = re.sub(r"^[路线安排]+[:：]?", "", text).strip()
    if "：" in text:
        left, _ = text.split("：", 1)
        if 2 <= len(normalize_name(left)) <= 14:
            text = left
    text = re.sub(r"（.*?）|\(.*?\)", "", text).strip()
    text = normalize_name(text)
    return text


def is_good_mention(value: str, city: str) -> bool:
    if not value or not has_chinese(value):
        return False
    if value in STOP_MENTIONS or value in GENERIC_MATCHES:
        return False
    if value in {city, f"{city}市"}:
        return False
    if value.endswith("区") and len(value) <= 4:
        return False
    if value.endswith("旅游") or value.endswith("攻略"):
        return False
    if len(value) < 2 or len(value) > 24:
        return False
    if any(bad in value for bad in ("住宿", "交通", "注意", "事项", "搜索", "路线")):
        return False
    return True


def split_route_payload(line: str) -> str:
    if "：" in line:
        left, right = line.split("：", 1)
        if re.search(r"(DAY|Day|day|路线|安排|第[一二三四五六七八九十\d]+天)", left):
            return right
    if ":" in line:
        left, right = line.split(":", 1)
        if re.search(r"(DAY|Day|day|route|路线|安排)", left):
            return right
    return line


def extract_mentions_from_note(note: dict[str, Any], city: str) -> list[dict[str, Any]]:
    body = str(note.get("body") or "")
    mentions: list[dict[str, Any]] = []
    seen: set[str] = set()
    route_order = 0

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if ARROW_RE.search(line):
            payload = split_route_payload(line)
            for segment in ARROW_RE.split(payload):
                mention = clean_mention(segment, city)
                if not is_good_mention(mention, city):
                    continue
                route_order += 1
                if mention not in seen:
                    mentions.append(
                        {"mention": mention, "route_order": route_order, "line": line}
                    )
                    seen.add(mention)
            continue

        if "：" in line:
            prefix, detail = line.split("：", 1)
            mention = clean_mention(prefix, city)
            if is_good_mention(mention, city) and mention not in seen:
                route_order += 1
                mentions.append(
                    {
                        "mention": mention,
                        "route_order": route_order,
                        "line": line,
                        "detail": compact_text(detail, 160),
                    }
                )
                seen.add(mention)
            continue

        bullet = clean_mention(line, city)
        if line.startswith(("*", "-", "•")) and is_good_mention(bullet, city):
            route_order += 1
            if bullet not in seen:
                mentions.append(
                    {"mention": bullet, "route_order": route_order, "line": line}
                )
                seen.add(bullet)

    return mentions


def extract_warning_lines(body: str) -> list[str]:
    warnings: list[str] = []
    in_warning_block = False
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if any(marker in line for marker in ("注意事项", "避坑", "提醒")):
            in_warning_block = True
            continue
        if in_warning_block and re.match(r"^[✅📸🍱🏠🚗🗺️]", line):
            in_warning_block = False
        if in_warning_block or any(term in line for term in RISK_TERMS):
            warnings.append(compact_text(line, 180))
    return warnings[:12]


def term_hits(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if term in text]


def build_xhs_guides(notes: list[dict[str, Any]], cities: tuple[str, ...]) -> list[dict[str, Any]]:
    city_set = set(cities)
    guides: list[dict[str, Any]] = []
    for note in notes:
        city = str(note.get("city") or "").replace("市", "")
        if city not in city_set or note.get("status") != "ok":
            continue
        body = str(note.get("body") or "")
        mentions = extract_mentions_from_note(note, city)
        guides.append(
            {
                "schema_version": "xhs_city_guide:v1",
                "city": city,
                "query": note.get("query", ""),
                "title": note.get("title", ""),
                "source_url": note.get("source_url", ""),
                "author": note.get("author", ""),
                "likes": note.get("likes", ""),
                "created_at": note.get("created_at", ""),
                "scraped_at": note.get("scraped_at", ""),
                "body": body,
                "candidate_mentions": mentions,
                "warning_lines": extract_warning_lines(body),
                "positive_terms": term_hits(body, POSITIVE_TERMS),
                "risk_terms": term_hits(body, RISK_TERMS),
            }
        )
    return guides


def add_variant(variants: set[str], value: Any, city: str) -> None:
    name = normalize_name(value)
    if not name:
        return
    candidates = {name, strip_city_prefix(name, city)}
    suffixes = [
        "风景名胜区",
        "文化旅游区",
        "文化休闲景区",
        "海滨公园",
        "海滨浴场",
        "旅游区",
        "景区",
        "公园",
        "步行街",
        "博物馆",
        "广场",
        "小镇",
        "古镇",
        "广播电视塔",
    ]
    for candidate in list(candidates):
        for suffix in suffixes:
            if candidate.endswith(suffix) and len(candidate) > len(suffix) + 1:
                candidates.add(candidate[: -len(suffix)])
    for candidate in candidates:
        if (
            candidate
            and candidate not in GENERIC_MATCHES
            and (len(candidate) >= 3 or candidate in SPECIAL_SHORT_NAMES)
        ):
            variants.add(candidate)


def poi_name_variants(poi: dict[str, Any], city: str) -> list[str]:
    variants: set[str] = set()
    add_variant(variants, poi.get("canonical_name"), city)
    for alias in poi.get("aliases") or []:
        add_variant(variants, alias, city)
    amap_match = poi.get("amap_match") or {}
    if isinstance(amap_match, dict):
        add_variant(variants, amap_match.get("amap_name"), city)
    return sorted(variants, key=len, reverse=True)


def is_name_match(mention: str, variants: list[str]) -> tuple[bool, float, str]:
    normalized_mention = normalize_name(mention)
    if not normalized_mention:
        return False, 0.0, ""

    for variant in variants:
        if normalized_mention == variant:
            return True, 1.0, variant
        if len(normalized_mention) >= 3 and normalized_mention in variant:
            return True, 0.92, variant
        if len(variant) >= 3 and variant in normalized_mention:
            return True, 0.9, variant

    best_score = 0.0
    best_variant = ""
    for variant in variants:
        if len(normalized_mention) < 3 or len(variant) < 3:
            continue
        score = SequenceMatcher(None, normalized_mention, variant).ratio()
        shared_chars = len(set(normalized_mention) & set(variant))
        if score > best_score and shared_chars >= 3:
            best_score = score
            best_variant = variant
    return best_score >= 0.88, best_score, best_variant


def find_line_containing(body: str, needle: str) -> str:
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if needle and needle in normalize_name(line):
            return line
    return ""


def context_around(body: str, needle: str, limit: int = 180) -> str:
    compact_body = re.sub(r"\s+", " ", body).strip()
    if not needle:
        return compact_text(compact_body, limit)
    idx = compact_body.find(needle)
    if idx < 0:
        return compact_text(compact_body, limit)
    start = max(0, idx - 55)
    end = min(len(compact_body), idx + len(needle) + 95)
    return compact_text(compact_body[start:end], limit)


def reason_from_line(line: str, matched_name: str) -> str:
    if "：" in line:
        left, right = line.split("：", 1)
        if matched_name in normalize_name(left) or matched_name in normalize_name(line):
            return compact_text(right, 140)
    return ""


def matched_warning_lines(warning_lines: list[str], variants: list[str], mention: str) -> str:
    matches: list[str] = []
    needles = [mention, *variants]
    for line in warning_lines:
        normalized_line = normalize_name(line)
        if any(needle and needle in normalized_line for needle in needles):
            matches.append(line)
    return "；".join(matches[:2])


def build_xhs_evidence(
    poi: dict[str, Any],
    guide: dict[str, Any],
    city: str,
) -> tuple[dict[str, Any] | None, dict[str, list[str]]]:
    variants = poi_name_variants(poi, city)
    if not variants:
        return None, {"route_mentions": [], "positive_terms": [], "risk_terms": []}

    body = str(guide.get("body") or "")
    best: dict[str, Any] | None = None
    best_score = 0.0
    matched_variant = ""

    normalized_body = normalize_name(body)
    for variant in variants:
        if variant in normalized_body:
            score = 0.97 + min(len(variant), 20) / 1000
            if score > best_score:
                line = find_line_containing(body, variant)
                best = {
                    "mention": variant,
                    "route_order": None,
                    "line": line,
                    "detail": "",
                    "match_method": "body_exact",
                }
                best_score = score
                matched_variant = variant

    for mention in guide.get("candidate_mentions") or []:
        if not isinstance(mention, dict):
            continue
        matched, score, variant = is_name_match(str(mention.get("mention") or ""), variants)
        if matched and score > best_score:
            best = {
                "mention": mention.get("mention", ""),
                "route_order": mention.get("route_order"),
                "line": mention.get("line", ""),
                "detail": mention.get("detail", ""),
                "match_method": "mention_match",
            }
            best_score = score
            matched_variant = variant

    if not best:
        return None, {"route_mentions": [], "positive_terms": [], "risk_terms": []}

    line = str(best.get("line") or "")
    mention = str(best.get("mention") or matched_variant)
    canonical = normalize_name(poi.get("canonical_name"))
    category = str(poi.get("category_hint") or "")
    raw_name = str(poi.get("canonical_name") or "")
    amap_match = poi.get("amap_match") if isinstance(poi.get("amap_match"), dict) else {}
    if category == "地名地址信息" and str(amap_match.get("poi_typecode") or "") == "190105":
        return None, {"route_mentions": [], "positive_terms": [], "risk_terms": []}
    is_branch_location = (
        mention
        and mention in canonical
        and not canonical.startswith(mention)
        and ("(" in raw_name or "（" in raw_name or raw_name.endswith("店"))
        and category in {"餐饮服务", "体育休闲服务", "生活服务"}
    )
    if is_branch_location:
        return None, {"route_mentions": [], "positive_terms": [], "risk_terms": []}

    excerpt = compact_text(line, 180) if line else context_around(body, mention)
    reason = str(best.get("detail") or "") or reason_from_line(line, matched_variant or mention)
    warning_text = matched_warning_lines(
        list(guide.get("warning_lines") or []), variants, mention
    )
    signal_text = " ".join([excerpt, reason, warning_text])

    evidence = {
        "source_platform": "xhs",
        "source_url": guide.get("source_url", ""),
        "title": guide.get("title", ""),
        "excerpt": excerpt,
        "reason": compact_text(reason, 140),
        "warnings": compact_text(warning_text, 180),
        "route_order": best.get("route_order"),
        "match_method": best.get("match_method", ""),
        "matched_mention": mention,
        "match_confidence": round(min(0.98, max(0.72, best_score)), 2),
    }
    signals = {
        "route_mentions": [line] if line and ARROW_RE.search(line) else [],
        "positive_terms": term_hits(signal_text, POSITIVE_TERMS),
        "risk_terms": term_hits(signal_text, RISK_TERMS),
    }
    return evidence, signals


def merge_unique_list(*values: Any) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        items = value if isinstance(value, list) else []
        for item in items:
            key = json.dumps(item, ensure_ascii=False, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
    return result


def normalize_amap_candidate(poi: dict[str, Any], city: str) -> dict[str, Any]:
    candidate = dict(poi)
    candidate["schema_version"] = "real_poi_candidate:v1"
    candidate["city"] = city
    candidate.setdefault("aliases", [])
    candidate.setdefault("category_hint", "")
    candidate.setdefault("source_evidence", [])
    candidate.setdefault("raw_signals", {})
    candidate.setdefault("cleaning_status", "ready_for_labeling")
    return candidate


def source_key(evidence: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(evidence.get("source_platform") or ""),
        str(evidence.get("source_url") or ""),
        str(evidence.get("matched_mention") or evidence.get("title") or ""),
    )


def dedupe_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        key = source_key(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def rank_poi_for_mention(poi: dict[str, Any], evidence: dict[str, Any], city: str) -> float:
    """Prefer the canonical city POI over shops or child facilities in the same place."""
    mention = normalize_name(evidence.get("matched_mention"))
    canonical = normalize_name(poi.get("canonical_name"))
    stripped = strip_city_prefix(canonical, city)
    category = str(poi.get("category_hint") or "")
    amap_match = poi.get("amap_match") if isinstance(poi.get("amap_match"), dict) else {}
    rating = amap_match.get("rating") if isinstance(amap_match, dict) else 0

    score = float(evidence.get("match_confidence") or 0) * 10
    if mention in {canonical, stripped}:
        score += 100
    if canonical.startswith(mention) or stripped.startswith(mention):
        score += 30
    if mention and mention in canonical:
        score += 8

    if category == "风景名胜":
        score += 20
    elif category in {"地名地址信息", "购物服务"}:
        score += 10
    elif category in {"生活服务", "科教文化服务"}:
        score += 2

    if category == "餐饮服务" and not (canonical.startswith(mention) or stripped.startswith(mention)):
        score -= 45
    if category == "体育休闲服务" and not (
        canonical.startswith(mention) or stripped.startswith(mention)
    ):
        score -= 25
    if any(token in canonical for token in ("游客中心", "售票", "停车场", "卫生间", "出入口")):
        score -= 35
    if any(token in canonical for token in ("暂停营业", "公司", "有限公司")):
        score -= 20
    if "国家级景点" in str(amap_match.get("poi_type") or ""):
        score += 8
    if str(amap_match.get("poi_typecode") or "") == "110202":
        score += 5

    try:
        score += float(rating)
    except (TypeError, ValueError):
        pass
    score -= min(len(canonical), 80) / 100
    return score


def select_best_xhs_matches(
    potentials: list[tuple[int, dict[str, Any], dict[str, list[str]]]],
    merged: list[dict[str, Any]],
    city: str,
) -> list[tuple[int, dict[str, Any], dict[str, list[str]]]]:
    grouped: dict[str, list[tuple[int, dict[str, Any], dict[str, list[str]]]]] = defaultdict(list)
    for item in potentials:
        _, evidence, _ = item
        key = str(evidence.get("matched_mention") or evidence.get("title") or "")
        grouped[key].append(item)

    selected: list[tuple[int, dict[str, Any], dict[str, list[str]]]] = []
    for items in grouped.values():
        selected.append(
            max(
                items,
                key=lambda item: rank_poi_for_mention(merged[item[0]], item[1], city),
            )
        )
    return selected


def merge_city(amap_rows: list[dict[str, Any]], guides: list[dict[str, Any]], city: str) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = [
        normalize_amap_candidate(raw_poi, city) for raw_poi in amap_rows
    ]

    pending_evidence: dict[int, list[dict[str, Any]]] = defaultdict(list)
    pending_signals: dict[int, dict[str, list[str]]] = defaultdict(
        lambda: {"route_mentions": [], "positive_terms": [], "risk_terms": []}
    )

    for guide in guides:
        potentials: list[tuple[int, dict[str, Any], dict[str, list[str]]]] = []
        for idx, poi in enumerate(merged):
            evidence, signals = build_xhs_evidence(poi, guide, city)
            if evidence:
                potentials.append((idx, evidence, signals))
        for idx, evidence, signals in select_best_xhs_matches(potentials, merged, city):
            pending_evidence[idx].append(evidence)
            existing_signals = pending_signals[idx]
            existing_signals["route_mentions"] = merge_unique_list(
                existing_signals["route_mentions"], signals.get("route_mentions")
            )
            existing_signals["positive_terms"] = merge_unique_list(
                existing_signals["positive_terms"], signals.get("positive_terms")
            )
            existing_signals["risk_terms"] = merge_unique_list(
                existing_signals["risk_terms"], signals.get("risk_terms")
    )

    for idx, poi in enumerate(merged):
        evidences = list(poi.get("source_evidence") or [])
        raw_signals = poi.get("raw_signals") if isinstance(poi.get("raw_signals"), dict) else {}

        route_mentions = list(raw_signals.get("route_mentions") or [])
        positive_terms = list(raw_signals.get("positive_terms") or [])
        risk_terms = list(raw_signals.get("risk_terms") or [])

        evidences.extend(pending_evidence.get(idx, []))
        signals = pending_signals.get(idx, {})
        route_mentions = merge_unique_list(route_mentions, signals.get("route_mentions"))
        positive_terms = merge_unique_list(positive_terms, signals.get("positive_terms"))
        risk_terms = merge_unique_list(risk_terms, signals.get("risk_terms"))

        poi["source_evidence"] = dedupe_evidence(evidences)
        poi["raw_signals"] = {
            "route_mentions": route_mentions,
            "positive_terms": positive_terms,
            "risk_terms": risk_terms,
        }
        has_xhs = any(e.get("source_platform") == "xhs" for e in poi["source_evidence"])
        poi["cleaning_notes"] = (
            "高德实体坐标 + 小红书攻略证据，适合优先交给标注 Agent。"
            if has_xhs
            else "高德实体坐标已确认；暂未匹配到小红书攻略语义证据。"
        )
    return merged


def load_amap_city_rows(amap_dir: Path, city: str) -> list[dict[str, Any]]:
    path = amap_dir / f"amap_poi_{city}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"missing Amap source file: {path}")
    return read_jsonl(path)


def build_unmatched_mentions(
    guides: list[dict[str, Any]],
    merged: list[dict[str, Any]],
) -> dict[str, list[str]]:
    matched_mentions_by_city: dict[str, set[str]] = defaultdict(set)
    for poi in merged:
        city = str(poi.get("city") or "")
        for evidence in poi.get("source_evidence") or []:
            if evidence.get("source_platform") == "xhs" and evidence.get("matched_mention"):
                matched_mentions_by_city[city].add(str(evidence["matched_mention"]))

    unmatched: dict[str, list[str]] = {}
    for guide in guides:
        city = str(guide.get("city") or "")
        mentions = {
            str(item.get("mention"))
            for item in guide.get("candidate_mentions") or []
            if isinstance(item, dict) and item.get("mention")
        }
        unmatched[city] = sorted(mentions - matched_mentions_by_city.get(city, set()))
    return unmatched


def build_summary(
    merged: list[dict[str, Any]],
    xhs_guides: list[dict[str, Any]],
    unmatched_mentions: dict[str, list[str]],
) -> dict[str, Any]:
    by_city: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for poi in merged:
        by_city[str(poi.get("city") or "")].append(poi)

    guide_counts = Counter(str(guide.get("city") or "") for guide in xhs_guides)
    summary: dict[str, Any] = {
        "schema_version": "real_poi_merge_summary:v1",
        "source_notes": {
            "amap": "Amap POI files from xhsoutdata2/data/real_sources",
            "xhs": "Xiaohongshu note bodies from xhsoutdata/xhs_notes.jsonl",
        },
        "cities": {},
        "outputs": {
            "amap_city_files": [f"amap_poi_{city}.jsonl" for city in CITIES],
            "xhs_guides": "xhs_city_guides.jsonl",
            "merged_all": "merged_real_poi_candidates.jsonl",
            "merged_xhs_only": "merged_real_poi_candidates_xhs_only.jsonl",
            "unmatched_mentions": "unmatched_xhs_mentions.json",
        },
    }
    for city in CITIES:
        rows = by_city.get(city, [])
        category_counter = Counter(str(row.get("category_hint") or "unknown") for row in rows)
        matched = [
            row
            for row in rows
            if any(e.get("source_platform") == "xhs" for e in row.get("source_evidence") or [])
        ]
        with_rating = sum(1 for row in rows if (row.get("amap_match") or {}).get("rating") not in (None, ""))
        summary["cities"][city] = {
            "amap_candidates": len(rows),
            "xhs_guides": guide_counts.get(city, 0),
            "xhs_matched_candidates": len(matched),
            "with_amap_rating": with_rating,
            "category_counts": dict(category_counter.most_common()),
            "matched_names": [row.get("canonical_name") for row in matched[:40]],
            "unmatched_xhs_mentions": unmatched_mentions.get(city, []),
        }
    summary["total_candidates"] = len(merged)
    summary["total_xhs_matched_candidates"] = sum(
        1
        for row in merged
        if any(e.get("source_platform") == "xhs" for e in row.get("source_evidence") or [])
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amap-dir", type=Path, default=DEFAULT_AMAP_DIR)
    parser.add_argument("--xhs-notes", type=Path, default=DEFAULT_XHS_NOTES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--cities", nargs="+", default=list(CITIES))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cities = tuple(args.cities)
    xhs_notes = read_jsonl(args.xhs_notes)
    xhs_guides = build_xhs_guides(xhs_notes, cities)
    guides_by_city: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for guide in xhs_guides:
        guides_by_city[str(guide.get("city") or "")].append(guide)

    merged: list[dict[str, Any]] = []
    for city in cities:
        amap_rows = load_amap_city_rows(args.amap_dir, city)
        normalized_amap = [normalize_amap_candidate(row, city) for row in amap_rows]
        write_jsonl(args.out_dir / f"amap_poi_{city}.jsonl", normalized_amap)
        merged.extend(merge_city(amap_rows, guides_by_city.get(city, []), city))

    xhs_only = [
        row
        for row in merged
        if any(e.get("source_platform") == "xhs" for e in row.get("source_evidence") or [])
    ]
    unmatched_mentions = build_unmatched_mentions(xhs_guides, merged)
    summary = build_summary(merged, xhs_guides, unmatched_mentions)

    write_jsonl(args.out_dir / "xhs_city_guides.jsonl", xhs_guides)
    write_jsonl(args.out_dir / "merged_real_poi_candidates.jsonl", merged)
    write_jsonl(args.out_dir / "merged_real_poi_candidates_xhs_only.jsonl", xhs_only)
    write_json(args.out_dir / "unmatched_xhs_mentions.json", unmatched_mentions)
    write_json(args.out_dir / "real_poi_merge_summary.json", summary)

    print(f"wrote {len(merged)} merged candidates to {args.out_dir}")
    print(f"xhs matched candidates: {len(xhs_only)}")
    for city, city_summary in summary["cities"].items():
        print(
            f"- {city}: {city_summary['amap_candidates']} amap, "
            f"{city_summary['xhs_matched_candidates']} xhs-matched, "
            f"{len(city_summary['unmatched_xhs_mentions'])} unmatched XHS mentions"
        )


if __name__ == "__main__":
    main()
