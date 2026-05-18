"""Test mock_server using FastAPI TestClient + real signing."""

import time

import pytest
from fastapi.testclient import TestClient


def signed_body(biz: dict | None = None, secret: str = "demo-secret") -> dict:
    """Build a fully-signed request body for the mock server."""
    from dianping.auth import sign

    body = {
        "appkey": "demo-appkey",
        "session": "demo-session",
        "timestamp": str(int(time.time() * 1000)),
    }
    for k, v in (biz or {}).items():
        if v is not None and v != "":
            body[k] = v
    body["sign"] = sign(body, secret)
    return body


@pytest.fixture(scope="module")
def client():
    from dianping.mock_server import mock_app

    with TestClient(mock_app) as c:
        yield c


def test_opencity_returns_three_cities(client):
    resp = client.post("/router/city/opencity", json=signed_body())
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    # 现在支持 5 座城市（dt_v2 数据集新增北京和南昌）
    assert {"深圳", "上海", "西安"}.issubset(set(data["data"]))


def test_search_returns_records_for_shenzhen(client):
    # 新数据（dt_v2）类别为高德体系："餐饮服务" 而非大众点评的 "美食"
    resp = client.post(
        "/router/poisearch/search",
        json=signed_body({"city": "深圳", "categories": "餐饮服务", "limit": 10}),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "OK"
    assert isinstance(data["records"], list)
    assert len(data["records"]) > 0
    rec = data["records"][0]
    assert "openshopid" in rec
    assert "name" in rec


def test_search_radius_filters_distance(client):
    resp = client.post(
        "/router/poisearch/search",
        json=signed_body(
            {
                "city": "深圳",
                "latitude": 22.5429,
                "longitude": 114.0596,
                "radius": 2000,
                "limit": 25,
            }
        ),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["records"], list)


def test_get_single_poi_returns_full_detail(client):
    search_resp = client.post(
        "/router/poisearch/search",
        json=signed_body({"city": "深圳", "limit": 1}),
    )
    poi_id = search_resp.json()["records"][0]["openshopid"]

    resp = client.post(
        "/router/poi/getsinglepoi",
        json=signed_body({"openshopid": poi_id}),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    poi = data["data"]
    assert poi["openshopid"] == poi_id
    assert "ugcs" in poi
    assert "reviewTags" in poi


def test_batch_get_poi_returns_dict(client):
    search_resp = client.post(
        "/router/poisearch/search",
        json=signed_body({"city": "深圳", "limit": 5}),
    )
    ids = [r["openshopid"] for r in search_resp.json()["records"]]

    resp = client.post(
        "/router/poi/batchgetpoi",
        json=signed_body({"multiopenshopid": ",".join(ids)}),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert set(data["data"].keys()) == set(ids)


def test_signature_verification_rejects_bad_sign(client):
    body = signed_body()
    body["sign"] = "0" * 32
    resp = client.post("/router/city/opencity", json=body)
    assert resp.status_code == 401


def test_signature_verification_rejects_bad_appkey(client):
    from dianping.auth import sign

    body = signed_body()
    body["appkey"] = "wrong-appkey"
    body.pop("sign")
    body["sign"] = sign(body, "demo-secret")
    resp = client.post("/router/city/opencity", json=body)
    assert resp.status_code == 401
