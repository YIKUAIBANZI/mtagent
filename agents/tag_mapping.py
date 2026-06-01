"""v1.9 Tag Mapping — 用户自然语言 ↔ planning_tags / risk_tags 数据化.

Spec §1.3 docs/superpowers/specs/2026-05-14-v19-data-recommend-profile-adjust.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from dianping.schemas import ParsedIntent

_TAG_MAPPING_PATH = Path("data/tag_mapping.json")


class TagMapping(BaseModel):
    user_interest_to_planning_tags: dict[str, list[str]] = Field(default_factory=dict)
    user_constraints_to_risk_tags: dict[str, list[str]] = Field(default_factory=dict)
    review_tag_to_planning_tags: dict[str, list[str]] = Field(default_factory=dict)
    review_tag_to_risk_tags: dict[str, list[str]] = Field(default_factory=dict)


_CACHED: Optional[TagMapping] = None


def load_tag_mapping(path: Optional[Path] = None) -> TagMapping:
    """读取 data/tag_mapping.json. 进程内缓存."""
    global _CACHED
    if _CACHED is not None and path is None:
        return _CACHED
    p = path or _TAG_MAPPING_PATH
    if not p.exists():
        return TagMapping()
    data = json.loads(p.read_text(encoding="utf-8"))
    m = TagMapping(**data)
    if path is None:
        _CACHED = m
    return m


def expand_user_signals(intent: ParsedIntent) -> tuple[set[str], set[str]]:
    """合并 intent.interests + intent.preferences + intent.constraints → (positive, negative).

    positive: planning_tags 集 (POI 命中应加分)
    negative: risk_tags 集 (POI 命中应扣分)
    """
    m = load_tag_mapping()
    positive: set[str] = set()
    negative: set[str] = set()
    for src in list(intent.interests or []) + list(intent.preferences or []):
        tags = m.user_interest_to_planning_tags.get(src, [])
        positive.update(tags)
    for cname, on in (intent.constraints or {}).items():
        if not on:
            continue
        tags = m.user_constraints_to_risk_tags.get(cname, [])
        negative.update(tags)
    return positive, negative
