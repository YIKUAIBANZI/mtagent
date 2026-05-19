"""Stop 级 rationale 纯函数测试."""

from datetime import time

from agents.rationale import build_rationale_for_stop
from dianping.schemas import POI, EnrichedLabel, ParsedIntent, Stop, TimeSlot


def _make_stop(name: str, *, categories=None, enriched=None) -> Stop:
    poi = POI(
        openshopid=f"id-{name}",
        name=name,
        city="南昌",
        categories=categories or [],
        avgprice=80,
        star=4.5,
        longitude=115.89,
        latitude=28.68,
        enriched=enriched,
    )
    return Stop(
        poi=poi,
        slot=TimeSlot(name="上午景点", start=time(9, 0), end=time(11, 0)),
        arrival_time=time(9, 0),
        leave_time=time(11, 0),
    )


def test_must_visit_substring_hit_uses_user_keyword():
    intent = ParsedIntent(
        city="南昌", days=1, traveler_type="独行", must_visit=["南昌博物馆"]
    )
    stop = _make_stop("江西省博物馆")
    r = build_rationale_for_stop(intent, stop, variant="main")
    assert r["stage"] == "stop"
    assert r["poi_name"] == "江西省博物馆"
    assert "南昌博物馆" in r["text"]
    assert "must_visit" in r["key_factors"]


def test_must_consider_amap_inject_branch():
    intent = ParsedIntent(city="南昌", days=1, traveler_type="独行", must_visit=[])
    enriched = EnrichedLabel(must_consider=True)
    stop = _make_stop("瓦罐汤(胜利路店)", enriched=enriched)
    r = build_rationale_for_stop(intent, stop)
    assert "地图实搜" in r["text"]
    assert "amap_inject" in r["key_factors"]


def test_low_queue_variant_prefers_branch_store():
    intent = ParsedIntent(city="南昌", days=1, traveler_type="独行")
    stop = _make_stop("小罗子汤店(二分店)")
    r = build_rationale_for_stop(intent, stop, variant="low_queue")
    assert "少排队" in r["text"] and "分店" in r["text"]
    assert "variant_bias=low_queue" in r["key_factors"]


def test_interest_first_variant_prefers_culture_tag():
    intent = ParsedIntent(city="南昌", days=1, traveler_type="独行")
    enriched = EnrichedLabel(planning_tags=["文化", "历史"])
    stop = _make_stop("八一起义纪念馆", enriched=enriched)
    r = build_rationale_for_stop(intent, stop, variant="interest_first")
    assert "兴趣优先" in r["text"] and "文化向" in r["text"]
    assert "variant_bias=interest_first" in r["key_factors"]


def test_planning_tags_with_traveler_type():
    intent = ParsedIntent(city="南昌", days=1, traveler_type="情侣")
    enriched = EnrichedLabel(planning_tags=["拍照", "氛围"])
    stop = _make_stop("秋水广场", enriched=enriched)
    r = build_rationale_for_stop(intent, stop)
    assert "情侣" in r["text"]
    assert "拍照" in r["text"]


def test_fallback_when_no_signal():
    intent = ParsedIntent(city="南昌", days=1, traveler_type="独行")
    stop = _make_stop("某无标签 POI")
    r = build_rationale_for_stop(intent, stop)
    assert "fallback" in r["key_factors"]
    assert "就近顺路" in r["text"]
