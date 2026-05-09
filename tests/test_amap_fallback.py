"""Tests for haversine fallback + env disabled switch."""

import pytest

from agents.amap import AmapClient


def test_haversine_drive_returns_reasonable_estimate():
    c = AmapClient(key="x")
    info = c._haversine_one("drive", (108.94, 34.26), (108.96, 34.22))
    assert info.mode == "drive"
    assert info.source == "estimated"
    assert info.distance_km > 0
    assert 0 < info.minutes < 120
    assert info.price_yuan is not None and info.price_yuan > 0


def test_haversine_walk_no_price():
    c = AmapClient(key="x")
    info = c._haversine_one("walk", (108.94, 34.26), (108.96, 34.22))
    assert info.mode == "walk"
    assert info.source == "estimated"
    assert info.price_yuan is None


def test_haversine_speeds_drive_faster_than_walk():
    """Drive should yield fewer minutes than walk for same OD."""
    c = AmapClient(key="x")
    drive = c._haversine_one("drive", (108.94, 34.26), (108.96, 34.22))
    walk = c._haversine_one("walk", (108.94, 34.26), (108.96, 34.22))
    assert drive.minutes < walk.minutes


@pytest.mark.asyncio
async def test_disabled_env_skips_amap_calls(monkeypatch):
    monkeypatch.setenv("MTAGENT_AMAP_DISABLED", "1")
    c = AmapClient(key="x")
    options, _ = await c.get_transit_options(
        (108.94, 34.26),
        (108.96, 34.22),
        city="西安",
    )
    assert all(v.source == "estimated" for v in options.values())
