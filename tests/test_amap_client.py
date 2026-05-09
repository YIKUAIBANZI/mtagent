"""Unit tests for agents/amap.py."""

import httpx
import pytest

from agents.amap import AmapClient


def _make_client(handler) -> AmapClient:
    transport = httpx.MockTransport(handler)
    c = AmapClient(key="test-key", base_url="https://restapi.amap.com")
    c._client = httpx.AsyncClient(transport=transport, timeout=5.0)
    return c


@pytest.mark.asyncio
async def test_driving_parses_amap_response():
    """driving endpoint returns minutes/distance from amap response shape."""

    def handler(request):
        assert "/v3/direction/driving" in request.url.path
        assert "key=test-key" in str(request.url)
        return httpx.Response(
            200,
            json={
                "status": "1",
                "info": "OK",
                "route": {
                    "paths": [
                        {
                            "duration": "480",  # 480s = 8min
                            "distance": "4200",  # 4200m = 4.2km
                            "tolls": "0",
                            "taxi_cost": "15.0",
                        }
                    ]
                },
            },
        )

    c = _make_client(handler)
    info = await c._driving((108.94, 34.26), (108.96, 34.22))

    assert info.mode == "drive"
    assert info.minutes == 8
    assert info.distance_km == pytest.approx(4.2, abs=0.01)
    assert info.price_yuan == 15.0
    assert info.source == "amap"


@pytest.mark.asyncio
async def test_walking_parses_amap_response():
    def handler(request):
        assert "/v3/direction/walking" in request.url.path
        return httpx.Response(
            200,
            json={
                "status": "1",
                "info": "OK",
                "route": {"paths": [{"duration": "1680", "distance": "2100"}]},
            },
        )

    c = _make_client(handler)
    info = await c._walking((108.94, 34.26), (108.96, 34.22))
    assert info.mode == "walk"
    assert info.minutes == 28
    assert info.distance_km == pytest.approx(2.1, abs=0.01)
    assert info.price_yuan is None
    assert info.source == "amap"


@pytest.mark.asyncio
async def test_transit_parses_amap_response():
    def handler(request):
        assert "/v3/direction/transit/integrated" in request.url.path
        assert "city=" in str(request.url)
        return httpx.Response(
            200,
            json={
                "status": "1",
                "info": "OK",
                "route": {
                    "transits": [{"duration": "720", "distance": "4000", "cost": "4.0"}]
                },
            },
        )

    c = _make_client(handler)
    info = await c._transit((108.94, 34.26), (108.96, 34.22), city="西安")
    assert info.mode == "transit"
    assert info.minutes == 12
    assert info.distance_km == pytest.approx(4.0, abs=0.01)
    assert info.price_yuan == 4.0
    assert info.source == "amap"


@pytest.mark.asyncio
async def test_bicycling_parses_amap_response():
    def handler(request):
        assert "/v4/direction/bicycling" in request.url.path
        return httpx.Response(
            200,
            json={
                "errcode": 0,
                "data": {"paths": [{"duration": "1080", "distance": "4000"}]},
            },
        )

    c = _make_client(handler)
    info = await c._bicycling((108.94, 34.26), (108.96, 34.22))
    assert info.mode == "bicycle"
    assert info.minutes == 18
    assert info.distance_km == pytest.approx(4.0, abs=0.01)
    assert info.source == "amap"
