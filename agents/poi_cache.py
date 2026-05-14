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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from agents.anchor import _norm_name

_CACHE_PATH = Path("data/poi_cache.json")
CACHE_VERSION = "v1.9.1"


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
