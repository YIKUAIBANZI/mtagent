"""v1.9 Stage 1.5: POI Enrichment Cache.

Spec: docs/superpowers/specs/2026-05-14-v19-stage1-5-poi-enrichment-cache.md

骨架职责:
- cache_key(name, lng, lat) — 跨源去重 key (norm_name + 4 位精度坐标 ~11m)
- load_cache / save_cache — JSON 持久化 (data/poi_cache.json)
- upsert_entry — 新写入或刷 last_seen + seen_count++

并发 enrich / RAG 检索属于后续 Task 2-4 范围.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Optional

from agents.anchor import AroundPOI, _norm_name, _typecode_to_categories
from dianping.schemas import POI, EnrichedLabel

_CACHE_PATH = Path("data/poi_cache.json")
CACHE_VERSION = "v1.9.1"

# A 线判别 (Phase B 用; Phase A 不区分但提前实现规则)
_A_LINE_KEYWORDS = (
    "城墙",
    "古城",
    "塔",
    "寺",
    "博物馆",
    "宫",
    "陵",
    "园",
    "故居",
    "老字号",
    "百年",
    "世界之窗",
)
_A_LINE_TYPECODE_PREFIX = ("11", "15")  # 11 景点 / 15 交通设施

# 词表 (跟 scripts/refix_enriched.py 同源, Phase C 抽到 data/tag_mapping.json reverse)
_PLANNING_TAGS_VOCAB = [
    "food_quality",
    "local_food",
    "snack_friendly",
    "coffee_friendly",
    "photo_friendly",
    "culture_friendly",
    "museum_friendly",
    "history_friendly",
    "shopping_friendly",
    "night_friendly",
    "family_friendly",
    "couple_friendly",
    "elderly_friendly",
    "solo_friendly",
    "business_friendly",
    "rest_friendly",
    "citywalk_friendly",
    "rainy_day_friendly",
    "transit_friendly",
    "low_budget_friendly",
    "premium_friendly",
    "landmark",
    "first_visit_friendly",
    "atmosphere",
    "lunch_friendly",
    "dinner_friendly",
    "rain_friendly",
]
_RISK_TAGS_VOCAB = [
    "queue_heavy",
    "crowded_weekend",
    "walk_heavy",
    "far_from_anchor",
    "hard_to_find",
    "pricey",
    "reservation_needed",
    "unstable_opening",
    "weather_sensitive",
]
_POI_ROLES = ["city_essential", "persona_preferred", "meal", "connector", "fallback"]


def cache_key(name: str, lng: float, lat: float) -> str:
    """跨源去重 key. norm_name + 4 位坐标 (~11m) 视为同 POI."""
    return f"{_norm_name(name)}|{round(lng, 4)}|{round(lat, 4)}"


def load_cache(path: Optional[Path] = None) -> dict[str, dict[str, Any]]:
    """读 cache. 文件不存在返空 dict."""
    p = path or _CACHE_PATH
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def save_cache(cache: dict[str, dict[str, Any]], path: Optional[Path] = None) -> None:
    """写 cache. 覆盖整文件."""
    p = path or _CACHE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def upsert_entry(
    cache: dict[str, dict[str, Any]],
    key: str,
    *,
    name: str,
    lng: float,
    lat: float,
    city: str,
    typecode: str,
    categories: list[str],
    enriched: dict[str, Any],
    source: str,
) -> None:
    """新 entry 写入或老 entry 刷 last_seen + seen_count++.

    基础结构稳定字段 (name/lng/lat/typecode/categories) 不覆盖.
    enriched / source 老 entry 时仅在 caller 明确传新值时覆盖 (这里直接覆盖, 由 caller 控制).
    """
    now = datetime.now(UTC).isoformat()
    existing = cache.get(key)
    if existing is None:
        cache[key] = {
            "name": name,
            "lng": lng,
            "lat": lat,
            "city": city,
            "typecode": typecode,
            "categories": categories,
            "enriched": enriched,
            "source": source,
            "version": CACHE_VERSION,
            "created_at": now,
            "last_seen": now,
            "seen_count": 1,
        }
        return
    existing["last_seen"] = now
    existing["seen_count"] = int(existing.get("seen_count", 0)) + 1
    existing["enriched"] = enriched
    existing["source"] = source


def classify_line(name: str, typecode: str) -> Literal["A", "B"]:
    """A 线 (固定 POI) vs B 线 (动态 POI). Phase B 决定 enrich model 强度."""
    if any(kw in name for kw in _A_LINE_KEYWORDS):
        return "A"
    if typecode[:2] in _A_LINE_TYPECODE_PREFIX:
        return "A"
    return "B"


def build_enrich_prompt(poi: dict) -> str:
    """单个新 POI 的 enrich prompt. 输入只有 name + city + typecode + categories."""
    return f"""你是本地路线规划数据校对专家. 给定一个高德新拉到的 POI, 生成 EnrichedLabel 用于路线规划.

## POI 信息
- 名字: {poi.get("name")}
- 城市: {poi.get("city")}
- 高德 typecode: {poi.get("typecode")}
- categories: {poi.get("categories")}

## 任务
1. 选合适的 poi_role: {", ".join(_POI_ROLES)}
   - 餐饮 → meal; 景点/历史 → city_essential; 购物/休闲 → connector;
     传统型景点 + 用户兴趣强 → persona_preferred
2. 从词表选 planning_tags (≥ 2 个, 不能自造):
   {", ".join(_PLANNING_TAGS_VOCAB)}
3. 从词表选 risk_tags (可空):
   {", ".join(_RISK_TAGS_VOCAB)}
4. 推断 city_zone (区域名, 例 "万象天地 / 科技园" / "钟楼-鼓楼")
5. manual_priority 0-100, city_essential 通常 80+
6. min_stay_minutes / max_stay_minutes (景点 60-180, 餐饮 45-90, 购物 60-150)

## 输出严格 JSON
{{
  "poi_role": "city_essential",
  "planning_tags": ["landmark", "history_friendly", "photo_friendly"],
  "risk_tags": ["crowded_weekend"],
  "city_zone": "罗湖钟楼街",
  "manual_priority": 90,
  "min_stay_minutes": 60,
  "max_stay_minutes": 120
}}
"""


async def _enrich_via_qwen(poi: dict) -> dict:
    """调 qwen-plus 给单个 POI 打 EnrichedLabel.

    Caller 责任: 失败处理 (try/except)、并发限流.
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
        base_url=os.environ.get(
            "QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
    )
    prompt = build_enrich_prompt(poi)
    resp = await client.chat.completions.create(
        model=os.environ.get("QWEN_MODEL", "qwen-plus"),
        messages=[
            {
                "role": "system",
                "content": "你是路线规划数据校对专家. 严格按 JSON schema 输出.",
            },
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
        extra_body={"enable_thinking": False},
    )
    return json.loads(resp.choices[0].message.content or "{}")


async def _batch_enrich_via_qwen(pois: list[dict]) -> dict[str, dict]:
    """单次 LLM 调用批量 enrich 一组 POI（替代逐个调用）.

    输入 poi dict 含 name/lng/lat/city/typecode/categories.
    返回 dict[cache_key, enriched_dict].
    LLM 失败或漏项 → 对应 key 不进结果 (caller 走 enriched=None 兜底).
    """
    if not pois:
        return {}

    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
        base_url=os.environ.get(
            "QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
    )
    poi_list_json = json.dumps(
        [
            {
                "id": i,
                "name": p["name"],
                "city": p["city"],
                "typecode": p.get("typecode", ""),
                "categories": p.get("categories", []),
            }
            for i, p in enumerate(pois)
        ],
        ensure_ascii=False,
    )
    prompt = (
        f"批量给以下 {len(pois)} 个 POI 生成路线规划标签。\n\n"
        f"POI列表：{poi_list_json}\n\n"
        "规则：\n"
        "- poi_role: 餐饮/美食→meal, 著名景点/历史/文化→city_essential, "
        "购物/公园/休闲→connector, 特色小众→persona_preferred, 其他→fallback\n"
        f"- planning_tags 从以下选2-4个: {', '.join(_PLANNING_TAGS_VOCAB)}\n"
        f"- risk_tags 可空: {', '.join(_RISK_TAGS_VOCAB)}\n"
        "- manual_priority: city_essential→80-95, connector→50-70, meal→40-60, 其他→20-40\n"
        "- min_stay_minutes/max_stay_minutes: 景点60-180, 餐厅45-90, 购物60-150\n\n"
        "输出JSON对象，items数组与输入id一一对应:\n"
        '{"items":[{"id":0,"poi_role":"city_essential","planning_tags":["landmark"],'
        '"risk_tags":[],"city_zone":"外滩","manual_priority":90,'
        '"min_stay_minutes":60,"max_stay_minutes":120}]}'
    )
    try:
        resp = await client.chat.completions.create(
            model=os.environ.get("QWEN_MODEL", "qwen-plus"),
            messages=[
                {
                    "role": "system",
                    "content": "你是路线规划数据专家，严格按JSON格式输出。",
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            extra_body={"enable_thinking": False},
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        items = data.get("items") or []
    except Exception:
        return {}

    result: dict[str, dict] = {}
    for item in items:
        idx = item.get("id")
        if idx is None or not isinstance(idx, int) or idx >= len(pois):
            continue
        poi = pois[idx]
        key = cache_key(poi["name"], poi["lng"], poi["lat"])
        result[key] = item
    return result


async def batch_enrich(
    pois: list[dict],
    *,
    sem_limit: int = 5,  # 保留参数兼容旧调用, 不再使用
) -> dict[str, dict]:
    """批量 enrich 一批新 POI. 单次 LLM 调用返回全部结果 (替代原逐个并发).

    分块处理 (每块 ≤ 30) 避免超 token 限制.
    输入 poi dict 必须含 name/lng/lat/city/typecode/categories.
    """
    if not pois:
        return {}

    CHUNK = 30
    result: dict[str, dict] = {}
    for i in range(0, len(pois), CHUNK):
        try:
            chunk_result = await _batch_enrich_via_qwen(pois[i : i + CHUNK])
            result.update(chunk_result)
        except Exception:
            pass  # 单块失败不阻断其他块
    return result


def _around_to_poi(ap: AroundPOI, city: str, enriched_dict: Optional[dict]) -> POI:
    """高德 AroundPOI → 项目 POI; 可选 attach EnrichedLabel."""
    poi = POI(
        openshopid=f"amap_{ap.typecode}_{round(ap.lng, 4)}_{round(ap.lat, 4)}",
        name=ap.name,
        city=city,
        latitude=ap.lat,
        longitude=ap.lng,
        categories=_typecode_to_categories(ap.typecode),
        address=ap.address,
        avgprice=0,
        star=0,
        business_hour="",
    )
    if enriched_dict:
        poi.enriched = EnrichedLabel(**enriched_dict)
    return poi


async def lookup_and_enrich(
    around_pois: list[AroundPOI],
    city: str,
    *,
    cache_path: Optional[Path] = None,
) -> list[POI]:
    """高德 around POI → cache lookup → miss 并发 enrich → 写回 cache → 返回 list[POI].

    每个返回的 POI:
    - cache hit: enriched attach + cache seen_count++
    - cache miss + LLM 成功: enriched attach + cache 新写入
    - cache miss + LLM 失败: enriched=None (caller 的 _bucket_of 走 categories 兜底)
    """
    cache = load_cache(path=cache_path)

    hits: list[tuple[AroundPOI, str, dict]] = []
    miss_around: list[tuple[AroundPOI, str]] = []
    for ap in around_pois:
        key = cache_key(ap.name, ap.lng, ap.lat)
        entry = cache.get(key)
        if entry is not None and entry.get("enriched"):
            hits.append((ap, key, entry["enriched"]))
        else:
            miss_around.append((ap, key))

    enriched_results: dict[str, dict] = {}
    if miss_around:
        miss_payloads = [
            {
                "name": ap.name,
                "lng": ap.lng,
                "lat": ap.lat,
                "city": city,
                "typecode": ap.typecode,
                "categories": _typecode_to_categories(ap.typecode),
            }
            for ap, _ in miss_around
        ]
        enriched_results = await batch_enrich(miss_payloads)

    out: list[POI] = []
    for ap, key, enr_dict in hits:
        upsert_entry(
            cache,
            key,
            name=ap.name,
            lng=ap.lng,
            lat=ap.lat,
            city=city,
            typecode=ap.typecode,
            categories=_typecode_to_categories(ap.typecode),
            enriched=enr_dict,
            source="amap_around",
        )
        out.append(_around_to_poi(ap, city, enr_dict))

    for ap, key in miss_around:
        enr_dict = enriched_results.get(key)
        if enr_dict is None:
            out.append(_around_to_poi(ap, city, None))
            continue
        upsert_entry(
            cache,
            key,
            name=ap.name,
            lng=ap.lng,
            lat=ap.lat,
            city=city,
            typecode=ap.typecode,
            categories=_typecode_to_categories(ap.typecode),
            enriched=enr_dict,
            source="amap_around",
        )
        out.append(_around_to_poi(ap, city, enr_dict))

    save_cache(cache, path=cache_path)
    return out
