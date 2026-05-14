"""v1.7 即时出发: 三层候选池构建 + 规则评分.

读取 POI 的 EnrichedLabel (来自 data/poi_enriched_labels.json), 按 poi_role 分桶,
按规则评分排序, top N 喂给 Planner LLM. LLM 不再从全量 POI 里盲选.

设计原则:
- city_essential 不被 traveler_type / persona 过滤掉 (是城市骨架, 进候选池保权重)
- 评分不依赖 reviewCount/avgprice (amap 数据来源限制, 这两字段全 0)
- 三个 variant (main / low_queue / interest_first) 共享 city_essential, 其它桶 variant-tuned (B4)
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from dianping.schemas import POI, ParsedIntent

Variant = Literal["main", "low_queue", "interest_first"]

# 候选池容量上限 (GPT spec)
DEFAULT_POOL_CAPS = {
    "city_essential": 10,
    "persona_preferred": 16,
    "meal": 12,
    "connector": 12,
}

# 兴趣关键词 → planning_tag 映射
INTEREST_TO_TAG = {
    "拍照": "photo_friendly",
    "出片": "photo_friendly",
    "美食": "food_quality",
    "吃": "food_quality",
    "文化": "culture_friendly",
    "历史": "culture_friendly",
    "购物": "shopping_friendly",
    "展览": "culture_friendly",
    "自然": "rest_friendly",
    "夜景": "night_friendly",
    "亲子": "family_friendly",
    "约会": "couple_friendly",
}


class CandidatePool(BaseModel):
    """4 桶候选池. 每桶是按 score 排好序的 POI 列表."""

    city_essential: list[POI] = Field(default_factory=list)
    persona_preferred: list[POI] = Field(default_factory=list)
    meal: list[POI] = Field(default_factory=list)
    connector: list[POI] = Field(default_factory=list)

    def total_size(self) -> int:
        return (
            len(self.city_essential)
            + len(self.persona_preferred)
            + len(self.meal)
            + len(self.connector)
        )


def _interest_tags(intent: ParsedIntent) -> set[str]:
    """Map intent.interests + intent.preferences (legacy) to planning_tag set."""
    tags: set[str] = set()
    for it in list(intent.interests) + list(intent.preferences):
        tag = INTEREST_TO_TAG.get(it)
        if tag:
            tags.add(tag)
    return tags


def score_poi(poi: POI, intent: ParsedIntent, variant: Variant = "main") -> float:
    """Rule-based weighted score. 不依赖 reviewCount/avgprice (amap 数据局限).

    Components:
    - manual_priority (0-100, 主权重)
    - traveler_type match (+20)
    - interest match (+10/命中标签)
    - star * 4 (0-20)
    - planning_tag bonus (光是有 photo/landmark 等好标签 +5/个)
    - risk penalty 受 variant + constraints 双重影响
    """
    enriched = poi.enriched
    if enriched is None:
        # 无 enriched: 兜底用 star + 旧 persona_labels
        return float(poi.star or 0) * 5.0

    score = float(enriched.manual_priority)

    # traveler_type match
    if intent.traveler_type in enriched.traveler_types:
        score += 20.0

    # interest match
    want_tags = _interest_tags(intent)
    for t in enriched.planning_tags:
        if t in want_tags:
            score += 10.0

    # planning_tag bonus (有 landmark / photo_friendly 等 +5 (不命中也加))
    POSITIVE_TAGS = {"landmark", "photo_friendly", "first_visit_friendly", "atmosphere"}
    for t in enriched.planning_tags:
        if t in POSITIVE_TAGS:
            score += 5.0

    # star
    score += float(poi.star or 0) * 4.0

    # risk penalty
    avoid_queue = intent.constraints.get("avoid_queue", False)
    avoid_walking = intent.constraints.get("avoid_walking", False)
    queue_heavy = "queue_heavy" in enriched.risk_tags
    walk_heavy = "walk_heavy" in enriched.risk_tags
    crowded = "crowded_weekend" in enriched.risk_tags

    # variant-specific penalty (B4 起作用)
    if variant == "low_queue":
        # low_queue 强惩罚 queue_heavy + walk_heavy + crowded
        if queue_heavy:
            score -= 50.0
        if walk_heavy:
            score -= 30.0
        if crowded:
            score -= 20.0
    else:
        # main / interest_first 用用户 constraint 加正常惩罚
        if avoid_queue and queue_heavy:
            score -= 30.0
        if avoid_walking and walk_heavy:
            score -= 20.0

    # interest_first variant: 用户兴趣命中再加权
    if variant == "interest_first":
        for t in enriched.planning_tags:
            if t in want_tags:
                score += 15.0  # 再叠加

    # v1.7.2 天气感知: 雨/雪/极端温度 → 户外类 walk_heavy 惩罚, rain_friendly 加分
    hint = intent.weather_hint or "normal"
    if hint in ("rainy", "stormy", "snowy", "hot", "cold"):
        from agents.weather import WEATHER_PENALTY_RULES

        rules = WEATHER_PENALTY_RULES.get(hint, {})
        if "rain_friendly" in enriched.planning_tags:
            score += rules.get("rain_friendly_bonus", 0)
        if walk_heavy:
            score += rules.get("walk_heavy_penalty", 0)
        # landmark + 户外 (无 rain_friendly 标签) 视为户外景点, 惩罚 outdoor
        is_outdoor_landmark = (
            "landmark" in enriched.planning_tags
            and "rain_friendly" not in enriched.planning_tags
        )
        if is_outdoor_landmark:
            score += rules.get("landmark_outdoor_penalty", 0)

    # v1.8 anchor distance_penalty (Spec §4.1)
    if intent.anchor_lng is not None and intent.anchor_lat is not None:
        from agents.anchor import _haversine_km

        d_km = _haversine_km(
            (intent.anchor_lng, intent.anchor_lat),
            (poi.longitude, poi.latitude),
        )
        radius = intent.anchor_radius_km or 3.0
        if d_km <= radius / 2:
            pass  # 半径一半内不扣
        elif d_km <= radius:
            score -= (d_km - radius / 2) * 10  # 线性扣
        else:
            score -= 50 + (d_km - radius) * 20  # 超出硬扣

    return score


def _infer_role_from_categories(categories: Optional[list[str]]) -> str:
    """v1.9: 给无 enriched 的 POI 按 categories 兜底 poi_role.

    用于高德 fetch_around 返回的 POI (没经过 mock_dianping enriched 流程).
    """
    if not categories:
        return "fallback"
    cats = " ".join(categories)
    if "美食" in cats:
        return "meal"
    if "景点" in cats or "历史文化" in cats:
        return "city_essential"
    if "购物" in cats or "休闲娱乐" in cats:
        return "connector"
    return "fallback"


def _bucket_of(poi: POI) -> Optional[str]:
    """Return poi_role bucket name, or None if no enriched + categories 也推不出.

    v1.9: 无 enriched 时按 categories 兜底 (高德 around POI 用).
    """
    if poi.enriched is not None:
        return poi.enriched.poi_role
    role = _infer_role_from_categories(poi.categories)
    return role if role != "fallback" else None


def build_candidate_pool(
    *,
    pois: list[POI],
    intent: ParsedIntent,
    variant: Variant = "main",
    pool_caps: Optional[dict[str, int]] = None,
) -> CandidatePool:
    """Build 4-bucket candidate pool from city-filtered POIs.

    Pre-conditions: pois are already filtered to intent.city (caller's job).

    Behavior:
    - city_essential: 不被 traveler_type 过滤 (城市骨架)
    - persona_preferred: 优先匹配 intent.traveler_type, 不匹配的 score 仍计算但末位
    - meal: 按 score 取 top
    - connector: 按 score 取 top
    - fallback: 不进任何桶 (除非 N 不够时由 caller 决定)
    """
    caps = {**DEFAULT_POOL_CAPS, **(pool_caps or {})}
    buckets: dict[str, list[tuple[float, POI]]] = {
        "city_essential": [],
        "persona_preferred": [],
        "meal": [],
        "connector": [],
    }
    for poi in pois:
        if poi.city != intent.city:
            continue
        # v1.8: 有 anchor 时硬过滤掉超出 radius 2x 的 POI
        if intent.anchor_lng is not None and intent.anchor_lat is not None:
            from agents.anchor import _haversine_km

            d = _haversine_km(
                (intent.anchor_lng, intent.anchor_lat),
                (poi.longitude, poi.latitude),
            )
            if d > (intent.anchor_radius_km or 3.0) * 2:
                continue
        bucket = _bucket_of(poi)
        if bucket not in buckets:
            continue  # fallback or no-enriched 跳过
        s = score_poi(poi, intent, variant=variant)
        buckets[bucket].append((s, poi))

    # sort desc by score, take top N
    def _top(bucket: str) -> list[POI]:
        items = sorted(buckets[bucket], key=lambda x: x[0], reverse=True)
        return [p for _, p in items[: caps[bucket]]]

    return CandidatePool(
        city_essential=_top("city_essential"),
        persona_preferred=_top("persona_preferred"),
        meal=_top("meal"),
        connector=_top("connector"),
    )
