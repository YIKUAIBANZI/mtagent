from dianping.schemas import UserProfile, POI, EnrichedLabel
from agents.preference_signals import (
    record_rejection,
    record_love,
    record_visit,
    append_history,
)


def _poi(name, planning, risk, price=100):
    return POI(
        openshopid=name,
        name=name,
        city="上海",
        latitude=31.2,
        longitude=121.4,
        avgprice=price,
        star=4.0,
        enriched=EnrichedLabel(planning_tags=planning, risk_tags=risk),
    )


def test_record_rejection_collects_risk_tags_deduped():
    p = UserProfile(cookie_key="k")
    record_rejection(p, _poi("某火锅", ["food"], ["queue_heavy"]))
    record_rejection(p, _poi("另家", ["food"], ["queue_heavy", "crowded_weekend"]))
    assert p.rejected_tags == ["queue_heavy", "crowded_weekend"]  # 去重 + 不记 planning


def test_record_love_collects_planning_and_cancels_reject():
    p = UserProfile(cookie_key="k", rejected_tags=["photo_friendly"])
    record_love(p, _poi("咖啡馆", ["photo_friendly", "rest_friendly"], []))
    assert p.loved_tags == ["photo_friendly", "rest_friendly"]
    assert "photo_friendly" not in p.rejected_tags  # love 对冲掉旧 reject


def test_record_visit_dedup():
    p = UserProfile(cookie_key="k")
    record_visit(p, "外滩")
    record_visit(p, "外滩")
    assert p.user_marked.been_there == ["外滩"]


def test_append_history_truncates_and_recomputes_budget():
    p = UserProfile(cookie_key="k")
    for i in range(25):
        append_history(
            p,
            city="上海",
            traveler_type="情侣",
            picked=[_poi(f"a{i}", ["food"], [], price=200)],
            date="2026-06-01",
        )
    assert len(p.history) == 20  # 截断
    assert p.avg_budget_per_day == 200  # 预算重算


def test_append_history_records_tags():
    p = UserProfile(cookie_key="k")
    append_history(
        p,
        city="上海",
        traveler_type="情侣",
        picked=[_poi("x", ["photo_friendly"], [])],
        date="2026-06-01",
    )
    assert p.history[0]["tags"] == ["photo_friendly"]
    assert p.history[0]["city"] == "上海"
