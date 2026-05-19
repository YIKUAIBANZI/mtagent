"""Rationale generator — pure function templates explaining Planner decisions.

Produces dict events conforming to v1.5 SSE schema for `planner.rationale`.
No side effects, no LLM calls. Templates are stage 1 (skeleton); v1.5.1 will
add LLM polish on top.
"""

from __future__ import annotations

from typing import Optional

from dianping.schemas import DayPlan, EnrichedLabel, ParsedIntent, Stop


_MODE_CN = {
    "drive": "打车",
    "walk": "步行",
    "transit": "地铁",
    "bicycle": "骑行",
}


_TRAVELER_PHRASES = {
    "情侣": "考虑你们是情侣",
    "家庭亲子": "考虑你带孩子",
    "银发": "考虑你带长辈",
    "独行": "你一个人出行",
    "商务": "你出差行程紧",
    "朋友团": "考虑朋友团出行",
}

_TRAVELER_ANCHOR_EXPLAIN = {
    "情侣": "都是出片好地标 + 周边有氛围餐厅",
    "家庭亲子": "市中心地标 + 室内商场，避免郊区奔波",
    "银发": "节奏舒缓的人文地标",
    "独行": "灵活紧凑的城市核心区",
    "商务": "高铁/机场可达性强",
    "朋友团": "热闹氛围的核心商圈",
}

_PREFERENCE_KEYWORDS = {
    "拍照": "拍照",
    "打卡": "拍照",
    "出片": "拍照",
    "美食": "爱吃",
    "文化": "喜欢人文",
    "历史": "喜欢人文",
    "小众": "爱小众",
    "网红": "拍照",
}

_BUDGET_TAILS = {
    "性价比": "，控住人均预算",
    "精致": "，挑了品质感的去处",
}

_TRAVELER_DAY_TAIL = {
    "银发": "节奏舒缓，避免长途奔波。",
    "家庭亲子": "尽量室内 + 短间距，方便带娃。",
    "情侣": "拍照点和氛围餐厅都安排上了。",
    "独行": "节奏紧凑，单点深度体验。",
    "商务": "效率优先，集中在交通核心。",
    "朋友团": "主打热闹氛围。",
}


def _preference_phrase(preferences: list[str]) -> str:
    if not preferences:
        return ""
    seen: list[str] = []
    for p in preferences:
        mapped = _PREFERENCE_KEYWORDS.get(p)
        if mapped and mapped not in seen:
            seen.append(mapped)
    if not seen:
        return ""
    return "+" + "+".join(seen)


def build_rationale_for_anchors(
    intent: ParsedIntent,
    anchors: list[tuple[str, float, float]],
) -> dict:
    """Anchor-stage rationale dict per spec §5.1."""
    if not anchors:
        text = "我帮你看了城市核心区域。"
        return {
            "stage": "anchors",
            "day_index": None,
            "text": text,
            "key_factors": [f"city={intent.city or ''}"],
        }

    traveler_phrase = _TRAVELER_PHRASES.get(intent.traveler_type or "", "结合你的偏好")
    pref_phrase = _preference_phrase(intent.preferences or [])

    names = [a[0] for a in anchors]
    if len(names) > 3:
        anchor_names = " / ".join(names[:3]) + " 等"
    else:
        anchor_names = " / ".join(names)

    explain = _TRAVELER_ANCHOR_EXPLAIN.get(intent.traveler_type or "", "城市的核心商圈")
    budget_tail = _BUDGET_TAILS.get(intent.budget_level or "", "")

    text = f"{traveler_phrase}{pref_phrase}，我挑了 {anchor_names}——{explain}{budget_tail}。"

    factors = [
        f"traveler_type={intent.traveler_type or ''}",
        f"city={intent.city or ''}",
        f"anchors={','.join(names)}",
    ]
    if pref_phrase:
        factors.append(f"preferences={','.join(intent.preferences)}")
    if intent.budget_level:
        factors.append(f"budget_level={intent.budget_level}")

    return {
        "stage": "anchors",
        "day_index": None,
        "text": text,
        "key_factors": factors,
    }


def _rhythm_phrase(stops: list) -> str:
    """Compose a 'morning / noon / afternoon' line from stops."""
    if not stops:
        return "暂无可推荐节奏"

    if len(stops) >= 4:
        morning = next((s for s in stops if s.slot.name == "上午景点"), stops[0])
        noon_slot = next(
            (s for s in stops if s.slot.name in ("午饭", "下午茶")),
            None,
        )
        afternoon = next(
            (s for s in stops if s.slot.name in ("下午",)),
            None,
        )

        parts = [f"上午 {morning.slot.name}"]
        if noon_slot is not None:
            parts.append(f"中午就近 {noon_slot.slot.name}")
        if afternoon is not None:
            parts.append(f"下午 {afternoon.slot.name}")
        return "，".join(parts)

    return "早午晚就近串成一线"


def build_rationale_for_day(
    intent: ParsedIntent,
    day_index: int,
    day_plan: DayPlan,
    anchor_name: str,
    transit_summary: Optional[dict] = None,
) -> dict:
    """Compose-stage rationale per spec §5.1 (one per day).

    `transit_summary` (optional): {total_min, main_mode, saved_yuan?, estimated?}
    appends a tail like '（92 分钟通勤，地铁为主，比打车省 ¥80）' after the
    rhythm sentence. v2 — backward compatible, None preserves v1.5 wording.
    """
    if not day_plan.stops:
        return {
            "stage": "compose",
            "day_index": day_index,
            "text": f"Day {day_index + 1} 暂无可用编排。",
            "key_factors": [
                f"day_index={day_index}",
                "stops=0",
            ],
        }

    rhythm = _rhythm_phrase(day_plan.stops)
    tail = _TRAVELER_DAY_TAIL.get(intent.traveler_type or "", "")
    anchor = anchor_name or day_plan.anchor_district or "市中心"

    text = f"Day {day_index + 1} 集中在 {anchor} 附近，{rhythm}。"
    if tail:
        text += tail

    factors = [
        f"day_index={day_index}",
        f"anchor={anchor}",
        f"stops={len(day_plan.stops)}",
        f"traveler_type={intent.traveler_type or ''}",
    ]

    if transit_summary:
        estimated = bool(transit_summary.get("estimated"))
        prefix = "约 " if estimated else ""
        mode_cn = _MODE_CN.get(transit_summary.get("main_mode", ""), "")
        bits = [f"{prefix}{transit_summary['total_min']} 分钟通勤"]
        if mode_cn:
            bits.append(f"{mode_cn}为主")
        if transit_summary.get("saved_yuan"):
            bits.append(f"比打车省 ¥{transit_summary['saved_yuan']}")
        suffix = "，估算）" if estimated else "）"
        text += "（" + "，".join(bits) + suffix
        factors.append(
            f"transit={transit_summary.get('main_mode', '')},{transit_summary.get('total_min', '')}min"
        )

    return {
        "stage": "compose",
        "day_index": day_index,
        "text": text,
        "key_factors": factors,
    }


def build_rationale_for_stop(
    intent: ParsedIntent,
    stop: Stop,
    variant: str = "main",
) -> dict:
    """Stop 级 rationale dict。

    优先级（高 → 低）：
    1. must_visit 子串命中 → "因为你说想去 {user_keyword}"
    2. must_consider（amap inject） → "你点名的 {slot}"
    3. variant 偏置 → "low_queue 偏分店 / interest_first 偏文化"
    4. planning_tags 命中 traveler/preference → "适合 {traveler_type}+{tag}"
    5. fallback → "{slot} 就近顺路"
    """
    poi = stop.poi
    factors: list[str] = [f"variant={variant}", f"slot={stop.slot.name}"]

    user_keyword = _match_must_visit(
        poi.name, intent.must_visit or [], intent.city or ""
    )
    if user_keyword:
        text = f"因为你说想去「{user_keyword}」，我挑了「{poi.name}」对上。"
        factors.append("must_visit")
        return _wrap(stop, variant, text, factors)

    enriched = poi.enriched
    if enriched and enriched.must_consider:
        text = f"你点名要的{stop.slot.name}，我从地图实搜补了「{poi.name}」。"
        factors.append("amap_inject")
        return _wrap(stop, variant, text, factors)

    variant_text = _variant_phrase(variant, poi.name, enriched)
    if variant_text:
        text = variant_text
        factors.append(f"variant_bias={variant}")
        return _wrap(stop, variant, text, factors)

    if enriched and enriched.planning_tags:
        tags = "/".join(enriched.planning_tags[:2])
        traveler = intent.traveler_type or ""
        if traveler:
            text = f"{stop.slot.name}选「{poi.name}」——{tags}，适合{traveler}。"
        else:
            text = f"{stop.slot.name}选「{poi.name}」，主打{tags}。"
        factors.append(f"tags={tags}")
        return _wrap(stop, variant, text, factors)

    text = f"{stop.slot.name}就近顺路串「{poi.name}」。"
    factors.append("fallback")
    return _wrap(stop, variant, text, factors)


def _match_must_visit(poi_name: str, must_visit: list[str], city: str = "") -> str:
    """返回首个子串命中的用户原话；都没命中返 ''。"""
    for kw in must_visit:
        if not kw:
            continue
        if kw in poi_name or poi_name in kw:
            return kw
        # 去掉城市前缀再试
        if city and kw.startswith(city):
            core = kw[len(city) :]
            if core and (core in poi_name or poi_name in core):
                return kw
    return ""


def _variant_phrase(
    variant: str, poi_name: str, enriched: Optional[EnrichedLabel]
) -> str:
    if variant == "low_queue":
        if "分店" in poi_name or "新店" in poi_name:
            return f"备选「少排队」方案，挑了人少的分店「{poi_name}」。"
        return ""
    if variant == "interest_first":
        if enriched and any(
            t in ("文化", "历史", "人文", "小众") for t in enriched.planning_tags
        ):
            return f"备选「兴趣优先」方案，文化向「{poi_name}」。"
        return ""
    return ""


def _wrap(stop: Stop, variant: str, text: str, factors: list[str]) -> dict:
    return {
        "stage": "stop",
        "poi_name": stop.poi.name,
        "slot_name": stop.slot.name,
        "variant": variant,
        "text": text,
        "key_factors": factors,
    }
