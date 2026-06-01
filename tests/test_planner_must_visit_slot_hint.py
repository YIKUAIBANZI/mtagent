"""Test that _build_one_day_payload injects slot hints for must_visit POIs."""

import json
from datetime import time
from dianping.schemas import ParsedIntent, POI
from agents.tools import DaySlotSpec, DayTemplate
from agents.planner import Planner, _build_must_visit_slot_hints


def _slot_template():
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


def _make_scenic_poi(oid, name):
    p = POI(
        openshopid=oid,
        name=name,
        city="北京",
        latitude=39.92,
        longitude=116.40,
        categories=["旅游景点"],
        star=4.8,
        avgprice=0,
        business_hour="09:00-18:00",
    )
    return p


def _make_restaurant_poi(oid, name):
    return POI(
        openshopid=oid,
        name=name,
        city="北京",
        latitude=39.92,
        longitude=116.40,
        categories=["美食", "中餐厅"],
        star=4.5,
        avgprice=80,
        business_hour="10:00-22:00",
    )


def test_slot_hint_contains_both_must_visit():
    """_build_must_visit_slot_hints produces hint string with both POI names and openshopids."""
    gugong = _make_scenic_poi("oid_gugong", "故宫博物院")
    changcheng = _make_scenic_poi("oid_changcheng", "长城景区")
    template = _slot_template()

    hint = _build_must_visit_slot_hints(
        must_visit=["故宫", "长城"],
        day_cluster_pois=[gugong, changcheng],
        template=template,
    )

    assert "故宫" in hint
    assert "oid_gugong" in hint
    assert "长城" in hint or "oid_changcheng" in hint
    assert "上午景点" in hint or "下午" in hint


def test_slot_hint_empty_when_no_must_visit():
    """Returns empty string when must_visit list is empty."""
    gugong = _make_scenic_poi("oid_gugong", "故宫博物院")
    template = _slot_template()

    hint = _build_must_visit_slot_hints(
        must_visit=[],
        day_cluster_pois=[gugong],
        template=template,
    )

    assert hint == ""


def test_slot_hint_no_crash_when_poi_not_in_cluster():
    """Does not crash if must_visit name has no matching POI in cluster."""
    restaurant = _make_restaurant_poi("oid_rest", "随机餐厅")
    template = _slot_template()

    hint = _build_must_visit_slot_hints(
        must_visit=["故宫"],  # not in cluster
        day_cluster_pois=[restaurant],
        template=template,
    )
    # No crash, returns empty or partial
    assert isinstance(hint, str)


def test_payload_instruction_contains_slot_hint():
    """_build_one_day_payload includes slot hint when must_visit is set."""
    planner = Planner(client=None, llm_call=None, llm_call_stream=None)
    intent = ParsedIntent(
        city="北京",
        days=1,
        traveler_type="独行",
        must_visit=["故宫", "长城"],
        time_window="一日",
    )
    gugong = _make_scenic_poi("oid_gugong", "故宫博物院")
    changcheng = _make_scenic_poi("oid_changcheng", "长城景区")

    payload_str = planner._build_one_day_payload(
        day_idx=0,
        intent=intent,
        template=_slot_template(),
        anchor=("故宫", 39.92, 116.40),
        day_cluster_pois=[gugong, changcheng],
    )
    payload = json.loads(payload_str)
    instruction = payload["_instruction"]

    assert "故宫" in instruction
    assert "oid_gugong" in instruction
