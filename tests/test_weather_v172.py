"""v1.7.2 天气感知: classify_weather + score_poi weather penalty 单测.

不打真高德 weather API. classify 是纯函数; score 用 stub intent.weather_hint.
"""

from __future__ import annotations

from agents.candidate_pool import score_poi
from agents.weather import classify_weather
from dianping.schemas import EnrichedLabel, ParsedIntent, POI


def _poi(name, *, planning_tags=None, risk_tags=None) -> POI:
    return POI(
        openshopid=name,
        name=name,
        city="西安",
        latitude=34.26,
        longitude=108.94,
        star=4.5,
        enriched=EnrichedLabel(
            poi_role="city_essential",
            manual_priority=80,
            planning_tags=planning_tags or [],
            risk_tags=risk_tags or [],
        ),
    )


def _intent(**over) -> ParsedIntent:
    base = dict(city="西安", days=1, traveler_type="情侣", time_window="一日")
    base.update(over)
    return ParsedIntent(**base)


def test_classify_sunny_normal():
    assert classify_weather("晴", 22) == "normal"


def test_classify_rain():
    assert classify_weather("小雨", 18) == "rainy"
    assert classify_weather("阵雨", 20) == "rainy"


def test_classify_storm():
    assert classify_weather("暴雨", 22) == "stormy"
    assert classify_weather("雷阵雨", 26) == "stormy"


def test_classify_snow():
    assert classify_weather("中雪", -2) == "snowy"


def test_classify_hot():
    assert classify_weather("晴", 38) == "hot"


def test_classify_cold():
    assert classify_weather("多云", 2) == "cold"


def test_score_rainy_penalizes_walk_heavy_outdoor_landmark():
    """雨天: 户外大景点 walk_heavy + landmark 双重 -, rain_friendly +."""
    outdoor_landmark = _poi(
        "大雁塔", planning_tags=["landmark", "photo_friendly"], risk_tags=["walk_heavy"]
    )
    indoor_mall = _poi("商场", planning_tags=["rain_friendly", "shopping_friendly"])
    sunny_intent = _intent(weather_hint="normal")
    rainy_intent = _intent(weather_hint="rainy")

    outdoor_sunny = score_poi(outdoor_landmark, sunny_intent)
    outdoor_rainy = score_poi(outdoor_landmark, rainy_intent)
    indoor_sunny = score_poi(indoor_mall, sunny_intent)
    indoor_rainy = score_poi(indoor_mall, rainy_intent)

    # 户外大景点雨天分数显著下降
    assert outdoor_rainy < outdoor_sunny - 30, (
        f"户外景点雨天没被惩罚: sunny={outdoor_sunny} rainy={outdoor_rainy}"
    )
    # 室内商场雨天分数上升
    assert indoor_rainy > indoor_sunny + 10, (
        f"室内 rain_friendly 雨天没加分: sunny={indoor_sunny} rainy={indoor_rainy}"
    )
    # 雨天: 商场分数应该追上户外或反超
    assert indoor_rainy > outdoor_rainy - 50, (
        f"雨天室内仍远低于户外: indoor={indoor_rainy} outdoor={outdoor_rainy}"
    )


def test_score_stormy_penalizes_more_than_rainy():
    p = _poi("大雁塔", planning_tags=["landmark"], risk_tags=["walk_heavy"])
    rainy_s = score_poi(p, _intent(weather_hint="rainy"))
    stormy_s = score_poi(p, _intent(weather_hint="stormy"))
    assert stormy_s < rainy_s, "stormy 应该比 rainy 惩罚更狠"


def test_score_unknown_weather_no_penalty():
    """weather_hint=unknown 不应该改变 score (跟 normal 同等)."""
    p = _poi("大雁塔", planning_tags=["landmark"], risk_tags=["walk_heavy"])
    normal_s = score_poi(p, _intent(weather_hint="normal"))
    unknown_s = score_poi(p, _intent(weather_hint="unknown"))
    assert normal_s == unknown_s


def test_score_no_weather_field_no_penalty():
    """老 intent (无 weather_hint) 走 normal 路径, score 不变."""
    p = _poi("大雁塔", planning_tags=["landmark"], risk_tags=["walk_heavy"])
    # weather_hint=None
    s = score_poi(p, _intent(weather_hint=None))
    s_normal = score_poi(p, _intent(weather_hint="normal"))
    assert s == s_normal
