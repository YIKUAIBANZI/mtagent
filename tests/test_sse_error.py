"""Test error path: Planner LLM throws → error event + clean close."""

import json
import os

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client_with_broken_llm(monkeypatch, tmp_path):
    """Wire MockTransport mock_app + override resolve_planner_llm to raise."""
    os.environ.pop("DASHSCOPE_API_KEY", None)
    monkeypatch.setenv("MTAGENT_TRIPS_DIR", str(tmp_path))

    async def broken(_system, _user):
        raise ValueError("simulated LLM failure")

    from api import deps, routes
    from api.main import app
    from dianping.client import DianpingClient
    from dianping.mock_server import mock_app

    # Patch the imported binding inside api.routes (not the source module)
    monkeypatch.setattr(routes, "resolve_planner_llm", lambda: broken)

    mock_test_client = TestClient(mock_app)
    mock_test_client.__enter__()

    def handler(request):
        resp = mock_test_client.post(
            request.url.path,
            content=request.content,
            headers={"content-type": "application/json"},
        )
        return httpx.Response(resp.status_code, json=resp.json())

    transport = httpx.MockTransport(handler)
    client = DianpingClient(
        base_url="http://test",
        appkey="demo-appkey",
        secret="demo-secret",
        session="demo-session",
    )
    client._client = httpx.AsyncClient(transport=transport, timeout=5.0)
    app.dependency_overrides[deps.get_client] = lambda: client

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.pop(deps.get_client, None)
    mock_test_client.__exit__(None, None, None)


def parse_sse(body: bytes) -> list[dict]:
    events = []
    for chunk in body.decode("utf-8").split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        ev = {"event": None, "data": None}
        for line in chunk.splitlines():
            if line.startswith("event: "):
                ev["event"] = line[len("event: ") :]
            elif line.startswith("data: "):
                ev["data"] = json.loads(line[len("data: ") :])
        events.append(ev)
    return events


def test_planner_llm_failure_emits_error_event(app_client_with_broken_llm):
    with app_client_with_broken_llm.stream(
        "POST",
        "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳"},
    ) as resp:
        body = b"".join(resp.iter_bytes())
    events = parse_sse(body)
    names = [e["event"] for e in events]

    assert "error" in names
    error = next(e for e in events if e["event"] == "error")
    assert error["data"]["phase"] == "planner"
    assert "simulated LLM failure" in error["data"]["message"]
