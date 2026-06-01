"""planner._synthesize_fallback_route uses scheduler for time/duration."""

from datetime import time

from dianping.schemas import POI, ParsedIntent
from agents.tools import DaySlotSpec, DayTemplate
from agents.scheduler import LUNCH_ANCHOR
from agents.planner import _synthesize_fallback_route


def _poi(name: str, oid: str, cats: list[str]) -> POI:
    return POI(
        openshopid=oid,
        name=name,
        city="深圳",
        latitude=22.5,
        longitude=114.0,
        categories=cats,
    )


def _template() -> DayTemplate:
    return DayTemplate(
        day_index=0,
        slots=[
            DaySlotSpec(
                name="上午景点",
                start=time(9, 0),
                end=time(12, 0),
                category_pool=["公园", "博物馆", "旅游景点"],
                is_meal=False,
                min_stay_minutes=60,
                max_stay_minutes=180,
            ),
            DaySlotSpec(
                name="午饭",
                start=time(12, 0),
                end=time(13, 30),
                category_pool=["美食", "中餐厅", "西餐厅"],
                is_meal=True,
                min_stay_minutes=60,
                max_stay_minutes=90,
            ),
            DaySlotSpec(
                name="下午",
                start=time(13, 30),
                end=time(17, 0),
                category_pool=["公园", "博物馆", "旅游景点"],
                is_meal=False,
                min_stay_minutes=90,
                max_stay_minutes=180,
            ),
        ],
    )


def _intent(traveler: str = "情侣") -> ParsedIntent:
    return ParsedIntent(
        city="深圳",
        days=1,
        traveler_type=traveler,
        must_visit=[],
        required_slots=[],
    )


def test_synthesize_fallback_route_uses_scheduler() -> None:
    """_synthesize_fallback_route 输出的 Stop 应有 recommended_duration_min 来自 scheduler."""
    pool = [
        _poi("公园 A", "p1", ["公园"]),
        _poi("中餐厅 B", "r1", ["中餐厅", "美食"]),
        _poi("博物馆 C", "m1", ["博物馆"]),
    ]
    intent = _intent("情侣")
    days = _synthesize_fallback_route(
        templates=[_template()],
        anchors=[("福田CBD", 22.54, 114.06)],
        day_clusters=[pool],
        intent=intent,
    )
    assert days, "synth should produce ≥1 day"
    stops = days[0].stops
    assert stops, "day should have stops"
    for st in stops:
        assert st.recommended_duration_min >= 20, (
            f"got {st.recommended_duration_min} (should be from scheduler, not default 60)"
        )
    # 情侣 起点 10:00
    assert stops[0].arrival_time == time(10, 0)


def test_synthesize_fallback_route_meal_anchored() -> None:
    """若 fallback synth 输出包含 '午饭' slot, arrival 必须在 LUNCH_ANCHOR 内."""
    pool = [
        _poi("公园 A", "p1", ["公园"]),
        _poi("中餐厅 B", "r1", ["中餐厅", "美食"]),
        _poi("博物馆 C", "m1", ["博物馆"]),
        _poi("西餐厅 D", "r2", ["西餐厅", "美食"]),
    ]
    intent = _intent("情侣")
    days = _synthesize_fallback_route(
        templates=[_template()],
        anchors=[("福田CBD", 22.54, 114.06)],
        day_clusters=[pool],
        intent=intent,
    )
    stops = days[0].stops
    meal_stops = [s for s in stops if "午饭" in s.slot.name]
    if meal_stops:
        m = meal_stops[0]
        assert LUNCH_ANCHOR[0] <= m.arrival_time <= LUNCH_ANCHOR[1], (
            f"lunch arrival {m.arrival_time} outside anchor {LUNCH_ANCHOR}"
        )
