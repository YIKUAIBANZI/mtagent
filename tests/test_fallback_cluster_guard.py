"""Cluster-aware fallback picking — prevent fallback from selecting POIs
that would blow up the day's spatial spread."""

from __future__ import annotations

from datetime import time


from agents.planner import _synthesize_fallback_route
from agents.tools import DaySlotSpec, DayTemplate
from dianping.schemas import POI


def _poi(sid: str, lat: float, lng: float, cats: list[str]) -> POI:
    return POI(
        openshopid=sid,
        name=sid,
        city="测试市",
        latitude=lat,
        longitude=lng,
        categories=cats,
    )


def _tmpl() -> DayTemplate:
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
                category_pool=["景点"],
                is_meal=False,
                min_stay_minutes=60,
                max_stay_minutes=180,
            ),
        ],
    )


def test_fallback_prefers_near_poi_when_far_one_listed_first():
    """合成场景: 第一个景点在 (22.54, 114.05). 午饭候选列表里, 远的 (22.65, 114.05, ~12km)
    排在近的 (22.545, 114.052, ~0.7km) 前面. 修复后 fallback 必须选近的."""
    anchor_poi = _poi("a", 22.5400, 114.0500, ["景点"])
    far_meal = _poi("far_meal", 22.6500, 114.0500, ["美食"])  # ~12km from anchor
    near_meal = _poi("near_meal", 22.5450, 114.0520, ["美食"])  # ~0.7km
    aft = _poi("c", 22.5410, 114.0510, ["景点"])

    cluster = [anchor_poi, far_meal, near_meal, aft]

    days = _synthesize_fallback_route(
        templates=[_tmpl()],
        anchors=[("测试区", 0.0)],
        day_clusters=[cluster],
        intent=None,
    )
    assert len(days) == 1
    stop_names = [s.poi.name for s in days[0].stops]
    assert stop_names[0] == "a"
    assert "near_meal" in stop_names, f"got {stop_names}; far_meal was picked"
    assert "far_meal" not in stop_names


def test_fallback_relaxes_to_any_when_no_near_candidate_exists():
    """合成场景: 只有远的 meal 候选. fallback 必须降级接受远的, 不能留空 slot."""
    anchor_poi = _poi("a", 22.5400, 114.0500, ["景点"])
    far_meal = _poi("far_meal", 22.6500, 114.0500, ["美食"])  # 12km, only meal option
    aft = _poi("c", 22.5410, 114.0510, ["景点"])

    cluster = [anchor_poi, far_meal, aft]

    days = _synthesize_fallback_route(
        templates=[_tmpl()],
        anchors=[("测试区", 0.0)],
        day_clusters=[cluster],
        intent=None,
    )
    stop_names = [s.poi.name for s in days[0].stops]
    assert "far_meal" in stop_names
    assert len(days[0].stops) == 3
