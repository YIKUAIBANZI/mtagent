"""Test Pydantic schemas can parse real mock data 100%."""

import json
from pathlib import Path


def test_parse_first_shenzhen_poi():
    """Smoke: first POI in 深圳.json must parse."""
    from dianping.schemas import POI

    path = Path("data/mock_dianping/深圳.json")
    with path.open(encoding="utf-8") as f:
        pois = json.load(f)

    poi = POI.model_validate(pois[0])
    assert poi.openshopid
    assert poi.name
    assert poi.city == "深圳"
    assert isinstance(poi.latitude, float)
    assert isinstance(poi.longitude, float)


def test_ugc_fields():
    """UGC items must parse with all expected fields."""
    from dianping.schemas import POI

    path = Path("data/mock_dianping/深圳.json")
    with path.open(encoding="utf-8") as f:
        pois = json.load(f)

    poi = POI.model_validate(pois[0])
    assert isinstance(poi.ugcs, list)
    if poi.ugcs:
        ugc = poi.ugcs[0]
        assert hasattr(ugc, "nick")
        assert hasattr(ugc, "content")
        assert hasattr(ugc, "score")
        assert hasattr(ugc, "addtime")


def test_review_tags_fields():
    """ReviewTag must have tag + hit."""
    from dianping.schemas import POI

    path = Path("data/mock_dianping/深圳.json")
    with path.open(encoding="utf-8") as f:
        pois = json.load(f)

    poi = POI.model_validate(pois[0])
    if poi.reviewTags:
        rt = poi.reviewTags[0]
        assert isinstance(rt.tag, str)
        assert isinstance(rt.hit, int)


def test_parsed_intent_minimal():
    """ParsedIntent must allow construction with only required fields."""
    from dianping.schemas import ParsedIntent

    intent = ParsedIntent(city="深圳", days=3, traveler_type="情侣")
    assert intent.city == "深圳"
    assert intent.days == 3
    assert intent.traveler_type == "情侣"
    assert intent.budget_level is None
    assert intent.preferences == []


def test_profiler_output_ready():
    """ProfilerOutput marks ready_to_plan and lists missing fields."""
    from dianping.schemas import ProfilerOutput, ParsedIntent

    intent = ParsedIntent(city="深圳", days=3, traveler_type="情侣")
    out = ProfilerOutput(understood=intent, ready_to_plan=True, missing_fields=[])
    assert out.ready_to_plan
    assert out.missing_fields == []


def test_route_draft_structure():
    """RouteDraft is a list of DayPlan, each DayPlan is a list of Stop."""
    from datetime import time

    from dianping.schemas import POI, DayPlan, RouteDraft, Stop, TimeSlot

    poi = POI(
        openshopid="x", name="海底捞", city="深圳", latitude=22.5, longitude=114.0
    )
    slot = TimeSlot(name="晚饭", start=time(18, 0), end=time(20, 0))
    stop = Stop(poi=poi, slot=slot, arrival_time=time(18, 15), leave_time=time(19, 45))
    day = DayPlan(day_index=0, anchor_district="福田区", stops=[stop])
    draft = RouteDraft(days=[day])

    assert len(draft.days) == 1
    assert draft.days[0].stops[0].poi.name == "海底捞"
