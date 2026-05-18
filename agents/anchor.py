"""v1.8 锚点解析 — 高德 geocode + place around + merge 本地 POI.

Spec §3. AMAP_KEY 已在 .env (沿用 weather.py 的 key).
"""

from __future__ import annotations

import math
import os
import re
from typing import Literal, Optional

import httpx
from pydantic import BaseModel

from dianping.schemas import POI

_AMAP_BASE = "https://restapi.amap.com"
_TIMEOUT = 5.0

# 高德 typecode: 餐饮/购物/休闲/景点/科教文化(含博物馆) (Spec §3.2)
DEFAULT_AROUND_TYPES = "050000|060000|080000|110000|140000"


class AnchorResolution(BaseModel):
    text: str
    name: str
    lng: float
    lat: float
    adcode: str
    formatted_address: str
    confidence: Literal["high", "medium", "low"]


class AroundPOI(BaseModel):
    name: str
    lng: float
    lat: float
    typecode: str
    distance_m: int
    address: str


async def _amap_get(path: str, params: dict) -> dict:
    """高德 GET 调用. 内置 timeout, 抛 httpx.HTTPError 由 caller 处理."""
    key = os.environ.get("AMAP_KEY", "")
    params = {**params, "key": key}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(f"{_AMAP_BASE}{path}", params=params)
        resp.raise_for_status()
        return resp.json()


async def resolve_anchor(text: str, city: str) -> Optional[AnchorResolution]:
    """高德 geocode 文本 → 坐标. Spec §3.3.

    失败 (status != 1 / geocodes 空) 返 None, caller 走 landmark_must.
    """
    try:
        data = await _amap_get("/v3/geocode/geo", {"address": text, "city": city})
    except Exception:
        return None
    if data.get("status") != "1":
        return None
    geocodes = data.get("geocodes") or []
    if not geocodes:
        return None
    g = geocodes[0]
    location = g.get("location", "")
    try:
        lng_str, lat_str = location.split(",")
        lng, lat = float(lng_str), float(lat_str)
    except (ValueError, AttributeError):
        return None
    level = g.get("level", "")
    confidence: Literal["high", "medium", "low"]
    if level in ("兴趣点", "门牌号", "兴趣点群"):
        confidence = "high"
    elif level in ("道路", "地铁站", "公交站台"):
        confidence = "medium"
    else:
        confidence = "low"
    return AnchorResolution(
        text=text,
        name=g.get("formatted_address", text),
        lng=lng,
        lat=lat,
        adcode=g.get("adcode", ""),
        formatted_address=g.get("formatted_address", ""),
        confidence=confidence,
    )


async def fetch_around(
    lng: float,
    lat: float,
    radius_m: int,
    types: str = DEFAULT_AROUND_TYPES,
    limit: int = 50,
) -> list[AroundPOI]:
    """高德周边搜索. Spec §3.2.

    limit ≤ 50 (高德 page_size 上限).
    """
    try:
        data = await _amap_get(
            "/v3/place/around",
            {
                "location": f"{lng:.6f},{lat:.6f}",
                "radius": min(radius_m, 50000),
                "types": types,
                "offset": min(limit, 50),
                "page": 1,
                "extensions": "base",
            },
        )
    except Exception:
        return []
    if data.get("status") != "1":
        return []
    out: list[AroundPOI] = []
    for raw in data.get("pois", []):
        loc = raw.get("location", "")
        try:
            lng_s, lat_s = loc.split(",")
            p_lng, p_lat = float(lng_s), float(lat_s)
        except (ValueError, AttributeError):
            continue
        out.append(
            AroundPOI(
                name=raw.get("name", ""),
                lng=p_lng,
                lat=p_lat,
                typecode=raw.get("typecode", ""),
                distance_m=int(raw.get("distance") or 0),
                address=raw.get("address", "")
                if isinstance(raw.get("address"), str)
                else "",
            )
        )
    return out


async def text_search(
    keyword: str,
    city: str,
    limit: int = 10,
) -> list[AroundPOI]:
    """高德关键词文本搜 POI. /v3/place/text.

    用于 must_visit (e.g. '南昌博物馆') 和 required_slots categories (e.g. '南昌拌粉')
    进入 candidate pool — 周边搜的 typecode 兜不住具体关键词的场景由此补齐.
    失败兜底返 [] (与 fetch_around 对齐, 不让 caller 崩).
    """
    try:
        data = await _amap_get(
            "/v3/place/text",
            {
                "keywords": keyword,
                "city": city,
                "citylimit": "true",
                "offset": min(limit, 25),
                "page": 1,
                "extensions": "base",
            },
        )
    except Exception:
        return []
    if data.get("status") != "1":
        return []
    out: list[AroundPOI] = []
    for raw in data.get("pois", []):
        loc = raw.get("location", "")
        try:
            lng_s, lat_s = loc.split(",")
            p_lng, p_lat = float(lng_s), float(lat_s)
        except (ValueError, AttributeError):
            continue
        out.append(
            AroundPOI(
                name=raw.get("name", ""),
                lng=p_lng,
                lat=p_lat,
                typecode=raw.get("typecode", ""),
                distance_m=int(raw.get("distance") or 0),
                address=raw.get("address", "")
                if isinstance(raw.get("address"), str)
                else "",
            )
        )
    return out


_PAREN_PAT = re.compile(r"[(（].*?[)）]|总店|分店")


def _norm_name(name: str) -> str:
    """归一化店名 — 去括号注释 + 总店/分店 后缀."""
    return _PAREN_PAT.sub("", name).strip()


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """great-circle distance in km. Input: (lng, lat) tuples."""
    lng1, lat1 = math.radians(a[0]), math.radians(a[1])
    lng2, lat2 = math.radians(b[0]), math.radians(b[1])
    dl = lng2 - lng1
    dp = lat2 - lat1
    h = math.sin(dp / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def _within_100m(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return _haversine_km(a, b) < 0.1


def _typecode_to_categories(typecode: str) -> list[str]:
    """高德 typecode → 我们的 categories. 5 位粗分."""
    if not typecode:
        return ["其它"]
    prefix = typecode[:2]
    return {
        "05": ["美食"],
        "06": ["购物"],
        "07": ["生活服务"],
        "08": ["休闲娱乐"],
        "11": ["景点"],
    }.get(prefix, ["其它"])


def merge_with_local_pool(
    amap_pois: list[AroundPOI],
    local_pois: list[POI],
    anchor: AnchorResolution,
    radius_m: int,
) -> list[POI]:
    """合并本地 + 高德 POI. Spec §3.4.

    规则:
    1. 本地 POI 在半径内: 保留 (有 enriched 标签, 优先)
    2. 高德 POI 在半径内 + 本地没有: 转 POI 对象 (无 enriched, 兜底)
    3. 去重 key: (norm_name, < 100m 坐标)
    4. 排序: 内置 enriched.manual_priority desc → 距 anchor 距离 asc
    """
    anchor_pt = (anchor.lng, anchor.lat)
    radius_km = radius_m / 1000.0

    kept_local: list[POI] = []
    local_keys: set[tuple[str, int, int]] = set()
    for p in local_pois:
        d = _haversine_km(anchor_pt, (p.longitude, p.latitude))
        if d > radius_km:
            continue
        key = (_norm_name(p.name), round(p.latitude, 3), round(p.longitude, 3))
        if key in local_keys:
            continue
        local_keys.add(key)
        kept_local.append(p)

    kept_amap: list[POI] = []
    for ap in amap_pois:
        d = _haversine_km(anchor_pt, (ap.lng, ap.lat))
        if d > radius_km:
            continue
        norm = _norm_name(ap.name)
        dup = False
        for lp in kept_local:
            if _norm_name(lp.name) == norm and _within_100m(
                (ap.lng, ap.lat), (lp.longitude, lp.latitude)
            ):
                dup = True
                break
        if dup:
            continue
        synthetic_id = f"amap_{ap.typecode}_{round(ap.lng, 4)}_{round(ap.lat, 4)}"
        categories = _typecode_to_categories(ap.typecode)
        kept_amap.append(
            POI(
                openshopid=synthetic_id,
                name=ap.name,
                city=local_pois[0].city if local_pois else "",
                latitude=ap.lat,
                longitude=ap.lng,
                categories=categories,
                address=ap.address,
                avgprice=0,
                star=0,
                business_hour="",
            )
        )

    kept_local.sort(
        key=lambda p: (
            -(p.enriched.manual_priority if p.enriched else 0),
            _haversine_km(anchor_pt, (p.longitude, p.latitude)),
        )
    )
    kept_amap.sort(key=lambda p: _haversine_km(anchor_pt, (p.longitude, p.latitude)))
    return kept_local + kept_amap
