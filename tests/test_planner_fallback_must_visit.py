"""Test that _synthesize_fallback_route honors intent.must_visit."""

import pytest
from dianping.schemas import ParsedIntent, POI, EnrichedLabel
from agents.tools import DaySlotSpec, DayTemplate
from datetime import time


def _make_poi(openshopid, name, categories):
    return POI(
        openshopid=openshopid,
        name=name,
        city="北京",
        latitude=39.92,
        longitude=116.40,
        categories=categories,
        star=4.5,
        avgprice=80,
        business_hour="09:00-18:00",
    )


def _make_scenic_poi(oid, name):
    p = _make_poi(oid, name, ["旅游景点", "风景名胜"])
    p.enriched = EnrichedLabel(
        poi_role="city_essential",
        universal_level="high",
        manual_priority=999,
        min_stay_minutes=90,
        max_stay_minutes=180,
    )
    return p


def _make_restaurant_poi(oid, name):
    return _make_poi(oid, name, ["美食", "中餐厅"])


@pytest.fixture
def template():
    return DayTemplate(
        day_index=0,
        slots=[
            DaySlotSpec(
                name="上午景点",
                start=time(9, 0),
                end=time(12, 0),
                category_pool=["休闲娱乐", "旅游景点"],
                is_meal=False,
                min_stay_minutes=60,
                max_stay_minutes=180,
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
                category_pool=["休闲娱乐", "旅游景点"],
                is_meal=False,
                min_stay_minutes=90,
                max_stay_minutes=180,
            ),
            DaySlotSpec(
                name="晚饭",
                start=time(18, 0),
                end=time(20, 0),
                category_pool=["美食"],
                is_meal=True,
                min_stay_minutes=60,
                max_stay_minutes=120,
            ),
        ],
    )


def test_fallback_includes_all_must_visit(template):
    """_synthesize_fallback_route must assign must_visit POIs to matching slots."""
    from agents.planner import _synthesize_fallback_route

    gugong = _make_scenic_poi("poi_gugong", "故宫博物院")
    changcheng = _make_scenic_poi("poi_changcheng", "长城")
    restaurant = _make_restaurant_poi("poi_rest", "随机餐厅")
    other_scenic = _make_scenic_poi("poi_other", "颐和园")

    intent = ParsedIntent(
        city="北京",
        days=1,
        traveler_type="独行",
        must_visit=["故宫", "长城"],
        time_window="一日",
    )
    cluster = [gugong, changcheng, restaurant, other_scenic]

    days = _synthesize_fallback_route(
        templates=[template],
        anchors=[("故宫", 39.92, 116.40)],
        day_clusters=[cluster],
        intent=intent,
    )

    assert len(days) == 1
    stop_names = [s.poi.name for s in days[0].stops]
    assert "故宫博物院" in stop_names, f"故宫 missing from {stop_names}"
    assert "长城" in stop_names, f"长城 missing from {stop_names}"


def test_fallback_must_visit_with_no_match_in_cluster(template):
    """If a must_visit POI is not in cluster, fallback should not crash."""
    from agents.planner import _synthesize_fallback_route

    restaurant = _make_restaurant_poi("poi_rest", "随机餐厅")

    intent = ParsedIntent(
        city="北京",
        days=1,
        traveler_type="独行",
        must_visit=["故宫"],  # 故宫 NOT in cluster
        time_window="一日",
    )
    cluster = [restaurant]

    days = _synthesize_fallback_route(
        templates=[template],
        anchors=[("市中心", 39.92, 116.40)],
        day_clusters=[cluster],
        intent=intent,
    )
    assert len(days) == 1  # no crash
