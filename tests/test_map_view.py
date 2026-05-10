"""/map view 集成测试 — endpoint + schema persistence."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def app_client():
    # NOTE: Built-in `monkeypatch` is function-scoped, but we want module scope so
    # TestClient lifespan fires once. Use pytest.MonkeyPatch() manually with
    # explicit teardown to set AMAP_WEB_JS_KEY for this test module.
    mp = pytest.MonkeyPatch()
    mp.setenv("AMAP_WEB_JS_KEY", "test_web_js_key_xyz")
    from api.main import app

    with TestClient(app) as c:
        yield c
    mp.undo()


def test_public_config_returns_amap_web_js_key(app_client):
    """GET /api/config 暴露 web js key 给前端动态 inject JSAPI."""
    resp = app_client.get("/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "amap_web_js_key" in data
    assert data["amap_web_js_key"] == "test_web_js_key_xyz"
