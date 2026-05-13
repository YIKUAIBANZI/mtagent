"""v1.8 trip_router 5 mode 路由规则单测."""

from datetime import date

from agents.trip_router import (
    HUB_SAFETY_MARGIN,
    infer_hub_type,
    is_chinese_holiday,
    route_trip_mode,
)
from dianping.schemas import ParsedIntent


def _intent(**kwargs) -> ParsedIntent:
    defaults = dict(city="深圳", days=1, traveler_type="情侣")
    defaults.update(kwargs)
    return ParsedIntent(**defaults)


def test_route_multi_day_when_days_geq_2():
    assert route_trip_mode(_intent(days=2), "深圳3天家庭游") == "multi_day"
    assert route_trip_mode(_intent(days=5), "随便玩玩") == "multi_day"


def test_route_layover_eat_when_transit_keyword_and_food_intent():
    text = "上海中转 7 小时 想吃吃吃 之后赶火车"
    intent = _intent(city="上海", start_location_text="上海站", estimated_hours=7)
    assert route_trip_mode(intent, text) == "layover_eat"


def test_route_layover_explore_when_transit_keyword_and_visit_intent():
    text = "上海中转 7 小时 想去外滩附近转转 然后赶火车"
    intent = _intent(city="上海", start_location_text="上海站", estimated_hours=7)
    assert route_trip_mode(intent, text) == "layover_explore"


def test_route_anchor_explore_when_start_location_with_nearby_word():
    text = "深圳明天我想去万象天地附近转一转"
    intent = _intent(start_location_text="万象天地")
    assert route_trip_mode(intent, text) == "anchor_explore"


def test_route_anchor_explore_when_only_start_location_no_nearby():
    """用户说锚点本身就是探索意图, 不需要"附近""转转"关键词."""
    intent = _intent(start_location_text="万象天地")
    assert route_trip_mode(intent, "深圳万象天地") == "anchor_explore"


def test_route_landmark_must_when_no_anchor_no_layover():
    intent = _intent(city="西安", time_window="半日_下午")
    assert route_trip_mode(intent, "西安半天拍照") == "landmark_must"


def test_infer_hub_type_train():
    assert infer_hub_type("上海站") == "train"
    assert infer_hub_type("深圳北站") == "highspeed"
    assert infer_hub_type("西安咸阳国际机场") == "airport"
    assert infer_hub_type("深圳福田汽车站") == "bus"
    assert infer_hub_type("万象天地") is None


def test_hub_safety_margin_values():
    """火车 30min, 飞机 2h, 客运 20min, 高铁 30min."""
    assert HUB_SAFETY_MARGIN["train"] == 30
    assert HUB_SAFETY_MARGIN["airport"] == 120
    assert HUB_SAFETY_MARGIN["bus"] == 20
    assert HUB_SAFETY_MARGIN["highspeed"] == 30


def test_is_chinese_holiday_2026():
    """2026 春节 2/17."""
    assert is_chinese_holiday(date(2026, 2, 17)) is True
    # 平常工作日
    assert is_chinese_holiday(date(2026, 5, 14)) is False
