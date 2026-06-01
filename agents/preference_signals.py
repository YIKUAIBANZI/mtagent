"""把用户行为蒸馏成 profile 标签信号。纯函数，无 IO / 无 LLM。

走标签层（planning_tags / risk_tags），不碰高德粗类目。
被 user_profile_store.apply_signal / adjust 捕获接入点共用。
"""

from __future__ import annotations

from dianping.schemas import UserProfile, POI

_MAX_HISTORY = 20


def _planning_tags(poi: POI) -> list[str]:
    enr = getattr(poi, "enriched", None)
    return list(enr.planning_tags) if enr else []


def _risk_tags(poi: POI) -> list[str]:
    enr = getattr(poi, "enriched", None)
    return list(enr.risk_tags) if enr else []


def record_rejection(p: UserProfile, poi: POI) -> UserProfile:
    """删/换掉一个 POI = 对它的「雷区标签」负反馈。

    只记 risk_tags（queue_heavy 等），不记通用 planning_tags，
    避免把 photo_friendly 这种中性标签也打成雷区。
    """
    for t in _risk_tags(poi):
        if t and t not in p.rejected_tags:
            p.rejected_tags.append(t)
    return p


def record_love(p: UserProfile, poi: POI) -> UserProfile:
    """收藏 = 正反馈，记它的 planning_tags（你喜欢它提供的体验）。命中 rejected 时对冲掉。"""
    for t in _planning_tags(poi):
        if t and t not in p.loved_tags:
            p.loved_tags.append(t)
        if t in p.rejected_tags:
            p.rejected_tags.remove(t)
    return p


def record_visit(p: UserProfile, poi_name: str) -> UserProfile:
    if poi_name and poi_name not in p.user_marked.been_there:
        p.user_marked.been_there.append(poi_name)
    return p


def append_history(
    p: UserProfile, *, city: str, traveler_type: str, picked: list[POI], date: str
) -> UserProfile:
    tags = [t for poi in picked for t in _planning_tags(poi)]
    prices = [poi.avgprice for poi in picked if getattr(poi, "avgprice", 0)]
    p.history.insert(
        0,
        {
            "date": date,
            "city": city,
            "traveler_type": traveler_type,
            "tags": tags,
            "avg_price": round(sum(prices) / len(prices)) if prices else 0,
        },
    )
    p.history = p.history[:_MAX_HISTORY]
    # 滚动重算人均预算（多次历史平均，避免单次抖动）
    hist_prices = [h["avg_price"] for h in p.history if h.get("avg_price")]
    if hist_prices:
        p.avg_budget_per_day = round(sum(hist_prices) / len(hist_prices))
    return p
