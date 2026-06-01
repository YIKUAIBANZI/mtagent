"""Test the /api/health endpoint smoke."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def app_client():
    from api.main import app

    with TestClient(app) as c:
        yield c


def test_health_endpoint_returns_ok(app_client):
    resp = app_client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "version" in data


def test_health_includes_dianping_base_url(app_client):
    resp = app_client.get("/api/health")
    data = resp.json()
    assert "dianping_base_url" in data
