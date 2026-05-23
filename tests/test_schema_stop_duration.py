"""Stop.recommended_duration_min default + override."""

from datetime import time

from dianping.schemas import POI, Stop, TimeSlot


def _poi() -> POI:
    return POI(
        openshopid="x",
        name="X",
        city="深圳",
        latitude=22.5,
        longitude=114.0,
    )


def _slot() -> TimeSlot:
    return TimeSlot(name="上午景点", start=time(9, 0), end=time(12, 0))


def test_stop_default_recommended_duration_is_60() -> None:
    s = Stop(
        poi=_poi(),
        slot=_slot(),
        arrival_time=time(9, 0),
        leave_time=time(10, 30),
    )
    assert s.recommended_duration_min == 60


def test_stop_override_recommended_duration() -> None:
    s = Stop(
        poi=_poi(),
        slot=_slot(),
        arrival_time=time(9, 0),
        leave_time=time(10, 30),
        recommended_duration_min=120,
    )
    assert s.recommended_duration_min == 120
