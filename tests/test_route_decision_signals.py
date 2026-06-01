"""UGC decision signals should affect route generation, not only card display."""

from datetime import time

from agents.planner import _synthesize_fallback_route
from agents.tools import DaySlotSpec, DayTemplate
from dianping.schemas import POI, ParsedIntent


def _poi(name: str, oid: str, cats: list[str]) -> POI:
    return POI(
        openshopid=oid,
        name=name,
        city="上海",
        latitude=31.23,
        longitude=121.47,
        categories=cats,
        star=4.8,
    )


def _template() -> DayTemplate:
    return DayTemplate(
        day_index=0,
        slots=[
            DaySlotSpec(
                name="上午景点",
                start=time(9, 0),
                end=time(12, 0),
                category_pool=["景点"],
                is_meal=False,
                min_stay_minutes=60,
                max_stay_minutes=120,
            ),
            DaySlotSpec(
                name="午饭",
                start=time(12, 0),
                end=time(13, 30),
                category_pool=["美食"],
                is_meal=True,
                min_stay_minutes=60,
                max_stay_minutes=90,
            ),
            DaySlotSpec(
                name="下午",
                start=time(13, 30),
                end=time(17, 0),
                category_pool=["景点"],
                is_meal=False,
                min_stay_minutes=60,
                max_stay_minutes=120,
            ),
        ],
    )


def test_fallback_route_avoids_high_queue_lunch_when_user_avoids_queue() -> None:
    high_queue = _poi("兰心餐厅(进贤路店)", "mock_3bd9b3609873f2cd", ["美食"])
    low_queue = _poi("顺路家常菜", "quiet_lunch", ["美食"])
    pool = [
        _poi("外滩", "mock_be2203153436f232", ["景点"]),
        high_queue,
        low_queue,
        _poi("上海博物馆", "museum", ["景点"]),
    ]
    intent = ParsedIntent(
        city="上海",
        days=1,
        traveler_type="情侣",
        preferences=["美食", "拍照"],
        modifiers={"怕排队": True},
        constraints={"avoid_queue": True},
        required_slots=[],
    )

    days = _synthesize_fallback_route(
        templates=[_template()],
        anchors=[("外滩", 31.23, 121.47)],
        day_clusters=[pool],
        intent=intent,
    )

    lunch = next(stop for stop in days[0].stops if stop.slot.name == "午饭")
    assert lunch.poi.openshopid == "quiet_lunch"
    assert lunch.decision_notes == []


def test_fallback_route_attaches_ugc_decision_notes_to_selected_stops() -> None:
    pool = [
        _poi("外滩", "mock_be2203153436f232", ["景点"]),
        _poi("顺路家常菜", "quiet_lunch", ["美食"]),
    ]
    intent = ParsedIntent(
        city="上海",
        days=1,
        traveler_type="情侣",
        preferences=["拍照"],
        required_slots=[],
    )

    days = _synthesize_fallback_route(
        templates=[_template()],
        anchors=[("外滩", 31.23, 121.47)],
        day_clusters=[pool],
        intent=intent,
    )

    bund = next(stop for stop in days[0].stops if stop.poi.openshopid == "mock_be2203153436f232")
    assert bund.decision_signals["queue_risk"]["label"] == "日落和节假日人流高"
    assert any("UGC" in note for note in bund.decision_notes)
