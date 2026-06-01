"""Test DianpingClient using httpx.MockTransport (no real network)."""

import httpx
import pytest


def make_client(handler):
    """Build a DianpingClient backed by a MockTransport handler."""
    from dianping.client import DianpingClient

    transport = httpx.MockTransport(handler)
    client = DianpingClient(
        base_url="http://test",
        appkey="demo-appkey",
        secret="demo-secret",
        session="demo-session",
    )
    client._client = httpx.AsyncClient(transport=transport, timeout=5.0)
    return client


@pytest.mark.asyncio
async def test_opencity_returns_city_list():
    def handler(request):
        body = request.content.decode()
        import json

        params = json.loads(body)
        assert "sign" in params
        assert params["appkey"] == "demo-appkey"
        return httpx.Response(
            200,
            json={
                "data": ["深圳", "上海", "西安"],
                "status": "success",
                "success": True,
            },
        )

    client = make_client(handler)
    result = await client.opencity()
    await client.close()

    assert result == ["深圳", "上海", "西安"]


@pytest.mark.asyncio
async def test_search_returns_records():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "records": [
                    {"openshopid": "abc", "name": "海底捞"},
                    {"openshopid": "def", "name": "西贝"},
                ],
                "status": "OK",
                "total_count": 2,
            },
        )

    client = make_client(handler)
    records = await client.search(keyword="火锅", city="深圳")
    await client.close()

    assert len(records) == 2
    assert records[0].openshopid == "abc"
    assert records[0].name == "海底捞"


@pytest.mark.asyncio
async def test_get_single_poi_returns_full_poi():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "data": {
                    "openshopid": "xxx",
                    "name": "海底捞·万象天地店",
                    "city": "深圳",
                    "latitude": 22.5,
                    "longitude": 114.0,
                    "categories": ["美食"],
                    "star": 4.5,
                    "avgprice": 150,
                },
                "status": "success",
                "success": True,
            },
        )

    client = make_client(handler)
    poi = await client.get_single_poi("xxx")
    await client.close()

    assert poi.openshopid == "xxx"
    assert poi.star == 4.5


@pytest.mark.asyncio
async def test_batch_get_poi_returns_dict():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "data": {
                    "id1": {
                        "openshopid": "id1",
                        "name": "店1",
                        "city": "深圳",
                        "latitude": 22.5,
                        "longitude": 114.0,
                    },
                    "id2": {
                        "openshopid": "id2",
                        "name": "店2",
                        "city": "深圳",
                        "latitude": 22.6,
                        "longitude": 114.1,
                    },
                },
                "status": "success",
                "success": True,
            },
        )

    client = make_client(handler)
    pois = await client.batch_get_poi(["id1", "id2"])
    await client.close()

    assert set(pois.keys()) == {"id1", "id2"}
    assert pois["id1"].name == "店1"


@pytest.mark.asyncio
async def test_failure_raises_dianping_api_error():
    def handler(request):
        return httpx.Response(
            200,
            json={"status": "fail", "success": False, "message": "签名错误"},
        )

    from dianping.client import DianpingAPIError

    client = make_client(handler)
    with pytest.raises(DianpingAPIError):
        await client.opencity()
    await client.close()
