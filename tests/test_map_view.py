"""/map view 集成测试 — 后端 endpoint (config/map) + (后续 task 加 schema 持久化)."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def app_client():
    """Module-scoped FastAPI TestClient with AMAP_WEB_JS_KEY set.

    Uses MonkeyPatch.context() (exception-safe) instead of the function-scoped
    `monkeypatch` fixture, so we can keep module scope and only fire lifespan once.
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("AMAP_WEB_JS_KEY", "test_web_js_key_xyz")
        from api.main import app

        with TestClient(app) as c:
            yield c


def test_public_config_returns_amap_web_js_key(app_client):
    """GET /api/config 暴露 web js key 给前端动态 inject JSAPI."""
    resp = app_client.get("/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "amap_web_js_key" in data
    assert data["amap_web_js_key"] == "test_web_js_key_xyz"


def test_map_view_returns_html(app_client):
    """GET /map returns the current mtagentv2 app for compatibility."""
    resp = app_client.get("/map")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "<html" in resp.text.lower()
    assert "plannerForm" in resp.text


def test_trip_persistence_includes_transit_segments(sse_app_client):
    """SSE 完成后 GET /api/plan/{trip_id} 应含 transit_segments per day."""
    # 跑一次 trip
    resp = sse_app_client.post(
        "/api/plan/stream",
        json={"free_text": "深圳两天情侣，预算精致"},
    )
    assert resp.status_code == 200
    # 提取 trip_id
    body = resp.text
    trip_id = None
    for line in body.split("\n"):
        if line.startswith("data:") and "trip_id" in line and "duration_ms" in line:
            import json

            data = json.loads(line[5:].strip())
            trip_id = data["trip_id"]
            break
    assert trip_id is not None, "no trip_id in SSE complete event"

    # 拿持久化 trip
    resp2 = sse_app_client.get(f"/api/plan/{trip_id}")
    assert resp2.status_code == 200
    trip = resp2.json()
    days = trip["draft_route"]["days"]
    assert len(days) >= 2
    for day in days:
        assert "transit_segments" in day, (
            f"day {day['day_index']} missing transit_segments"
        )
        # 至少 stops_count - 1 段 (≥1 if ≥2 stops)
        if len(day["stops"]) >= 2:
            assert len(day["transit_segments"]) >= 1
