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
    """GET /map returns the map.html static file."""
    resp = app_client.get("/map")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "<html" in resp.text.lower()
