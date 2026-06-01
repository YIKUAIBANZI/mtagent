"""Unit tests for agents/rationale.py — pure function rationale generators."""

import datetime as _dt

from dianping.schemas import DayPlan, ParsedIntent, POI, Stop, TimeSlot
from agents.rationale import build_rationale_for_anchors, build_rationale_for_day


def _stop(poi_name: str, slot_name: str, h_start: int, h_end: int) -> Stop:
    poi = POI(
        openshopid=f"id_{poi_name}",
        name=poi_name,
        city="西安",
        latitude=0.0,
        longitude=0.0,
        categories=["景点"],
        avgprice=100,
        star=4.0,
    )
    return Stop(
        poi=poi,
        slot=TimeSlot(
            name=slot_name,
            start=_dt.time(h_start, 0),
            end=_dt.time(h_end, 0),
        ),
        arrival_time=_dt.time(h_start, 0),
        leave_time=_dt.time(h_end, 0),
    )


def _day(stops: list, day_index: int = 0, anchor_district: str = "钟楼") -> DayPlan:
    return DayPlan(
        day_index=day_index,
        anchor_district=anchor_district,
        stops=stops,
    )


def _intent(**kwargs):
    """Build a ParsedIntent with sensible defaults for tests."""
    defaults = dict(
        city="西安",
        days=3,
        traveler_type="独行",
        budget_level=None,
        pace=None,
        preferences=[],
        must_visit=[],
        avoid=[],
        start_date=None,
    )
    defaults.update(kwargs)
    return ParsedIntent(**defaults)


def test_anchors_family_with_photo_budget():
    intent = _intent(
        traveler_type="家庭亲子",
        preferences=["拍照"],
        budget_level="性价比",
    )
    anchors = [("钟楼", 34.26, 108.94), ("大悦城", 34.22, 108.96)]
    out = build_rationale_for_anchors(intent, anchors)

    assert out["stage"] == "anchors"
    assert out["day_index"] is None
    text = out["text"]
    assert "带孩子" in text
    assert "拍照" in text
    assert "钟楼" in text
    assert "大悦城" in text
    assert "控住" in text or "性价比" in text


def test_anchors_couple_food_premium():
    intent = _intent(
        city="上海",
        traveler_type="情侣",
        preferences=["美食"],
        budget_level="精致",
    )
    anchors = [("外滩", 31.24, 121.49), ("新天地", 31.22, 121.48)]
    out = build_rationale_for_anchors(intent, anchors)

    text = out["text"]
    assert "情侣" in text
    assert "爱吃" in text
    assert "外滩" in text
    assert "品质感" in text


def test_anchors_solo_no_extras():
    """No preferences and no budget — phrase should not contain '+' or budget tail."""
    intent = _intent(traveler_type="独行")
    anchors = [("钟楼", 34.26, 108.94)]
    out = build_rationale_for_anchors(intent, anchors)

    text = out["text"]
    assert "你一个人" in text
    assert "钟楼" in text
    assert "+" not in text
    assert "控住" not in text
    assert "品质感" not in text


def test_anchors_empty_list_uses_fallback():
    intent = _intent(traveler_type="情侣")
    out = build_rationale_for_anchors(intent, [])

    assert out["stage"] == "anchors"
    assert out["day_index"] is None
    assert "城市核心" in out["text"]


def test_anchors_truncates_when_more_than_three():
    intent = _intent(traveler_type="家庭亲子")
    anchors = [
        ("A", 0, 0),
        ("B", 0, 0),
        ("C", 0, 0),
        ("D", 0, 0),
        ("E", 0, 0),
    ]
    out = build_rationale_for_anchors(intent, anchors)

    text = out["text"]
    assert "A" in text and "B" in text and "C" in text
    assert "D" not in text and "E" not in text
    assert "等" in text


def test_day_silver_three_stops():
    intent = _intent(traveler_type="银发", days=3)
    day = _day(
        [
            _stop("钟楼", "上午景点", 9, 12),
            _stop("回民街", "午饭", 12, 14),
            _stop("大悦城", "下午", 14, 18),
        ]
    )
    out = build_rationale_for_day(intent, 0, day, "钟楼")

    assert out["stage"] == "compose"
    assert out["day_index"] == 0
    text = out["text"]
    assert "Day 1" in text
    assert "钟楼" in text
    assert "节奏舒缓" in text


def test_day_family_four_stops_includes_slots():
    intent = _intent(traveler_type="家庭亲子", days=2)
    day = _day(
        [
            _stop("钟楼", "上午景点", 9, 12),
            _stop("回民街", "午饭", 12, 14),
            _stop("大悦城", "下午", 14, 17),
            _stop("永宁门", "晚饭", 18, 20),
        ],
        day_index=1,
        anchor_district="钟楼",
    )
    out = build_rationale_for_day(intent, 1, day, "钟楼")

    text = out["text"]
    assert "Day 2" in text
    assert "钟楼" in text
    assert "上午景点" in text
    assert "午饭" in text
    assert "下午" in text
    assert "方便带娃" in text


def test_day_three_stops_uses_short_phrase():
    intent = _intent(traveler_type="情侣", days=2)
    day = _day(
        [
            _stop("外滩", "上午景点", 9, 12),
            _stop("新天地", "午饭", 12, 14),
            _stop("豫园", "下午", 14, 18),
        ]
    )
    out = build_rationale_for_day(intent, 0, day, "外滩")

    text = out["text"]
    assert "Day 1" in text
    assert "外滩" in text
    assert "早午晚就近串成一线" in text
    assert "拍照点" in text


def test_day_empty_stops_uses_fallback():
    intent = _intent(traveler_type="情侣")
    day = _day([], day_index=2)
    out = build_rationale_for_day(intent, 2, day, "钟楼")

    assert out["stage"] == "compose"
    assert out["day_index"] == 2
    assert "暂无" in out["text"]
    assert "Day 3" in out["text"]


def test_day_rationale_with_transit_summary_includes_numbers():
    intent = _intent(traveler_type="家庭亲子", days=2)
    day = _day(
        [
            _stop("钟楼", "上午景点", 9, 12),
            _stop("回民街", "午饭", 12, 14),
            _stop("大悦城", "下午", 14, 17),
        ]
    )
    transit_summary = {"total_min": 92, "main_mode": "transit", "saved_yuan": 80}
    out = build_rationale_for_day(
        intent, 0, day, "钟楼", transit_summary=transit_summary
    )

    text = out["text"]
    assert "Day 1" in text
    assert "92" in text
    assert "地铁" in text


def test_day_rationale_without_transit_summary_unchanged():
    intent = _intent(traveler_type="情侣")
    day = _day([_stop("外滩", "上午景点", 9, 12)])
    out = build_rationale_for_day(intent, 0, day, "外滩")
    assert "Day 1" in out["text"]
    assert "通勤" not in out["text"]


def test_day_rationale_with_estimated_summary_marks_uncertainty():
    intent = _intent(traveler_type="情侣")
    day = _day([_stop("外滩", "上午景点", 9, 12)])
    transit_summary = {
        "total_min": 35,
        "main_mode": "drive",
        "estimated": True,
    }
    out = build_rationale_for_day(
        intent, 0, day, "外滩", transit_summary=transit_summary
    )
    assert "估算" in out["text"] or "约" in out["text"]
