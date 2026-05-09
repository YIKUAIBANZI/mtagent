"""Rationale generator — pure function templates explaining Planner decisions.

Produces dict events conforming to v1.5 SSE schema for `planner.rationale`.
No side effects, no LLM calls. Templates are stage 1 (skeleton); v1.5.1 will
add LLM polish on top.
"""

from __future__ import annotations

from dianping.schemas import DayPlan, ParsedIntent


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
) -> dict:
    """Compose-stage rationale per spec §5.1 (one per day)."""
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
    return {
        "stage": "compose",
        "day_index": day_index,
        "text": text,
        "key_factors": factors,
    }
