"""Test backward-compat for Stop with new transport_options field."""

from dianping.schemas import Stop, POI, TimeSlot
import datetime as _dt


def _stop_kwargs():
    poi = POI(
        openshopid="id1",
        name="钟楼",
        city="西安",
        latitude=34.26,
        longitude=108.94,
    )
    slot = TimeSlot(name="上午景点", start=_dt.time(9, 0), end=_dt.time(12, 0))
    return dict(
        poi=poi,
        slot=slot,
        arrival_time=_dt.time(9, 0),
        leave_time=_dt.time(12, 0),
    )


def test_stop_without_transport_options_loads():
    """Old Stop dict (pre-v2) should deserialize with transport_options=None."""
    s = Stop(**_stop_kwargs())
    assert s.transport_options is None
    assert s.transport_to_next_minutes == 30


def test_stop_with_transport_options_loads():
    s = Stop(
        **_stop_kwargs(),
        transport_options={
            "drive": {
                "mode": "drive",
                "minutes": 8,
                "distance_km": 4.2,
                "price_yuan": 15.0,
                "source": "amap",
            },
            "walk": {
                "mode": "walk",
                "minutes": 28,
                "distance_km": 2.1,
                "price_yuan": None,
                "source": "amap",
            },
        },
    )
    assert s.transport_options is not None
    assert s.transport_options["drive"].minutes == 8
    assert s.transport_options["walk"].price_yuan is None


def test_transit_info_source_validates():
    """TransitInfo.source must be one of 'amap' / 'estimated'."""
    import pytest
    from pydantic import ValidationError
    from dianping.schemas import TransitInfo

    with pytest.raises(ValidationError):
        TransitInfo(mode="drive", minutes=5, distance_km=1.0, source="invalid")
