"""Test error path: Planner LLM throws → error event + clean close."""

import json
import os

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client_with_broken_llm(monkeypatch, tmp_path):
    """Wire MockTransport mock_app + override both planner LLMs to fail.

    v1.6: compose段用 llm_call_stream (not llm_call), so override both — the
    legacy non-stream broken fixture is kept for back-compat assertions, and
    the new stream override drives the per-day failure path.
    """
    os.environ.pop("DASHSCOPE_API_KEY", None)
    monkeypatch.setenv("MTAGENT_TRIPS_DIR", str(tmp_path))

    async def broken(_system, _user):
        raise ValueError("simulated LLM failure")

    async def broken_stream(_system, _user):
        if False:
            yield ""
        raise ValueError("simulated LLM failure")

    from api import deps
    from api.routers import plan as plan_router
    from api.main import app
    from dianping.client import DianpingClient
    from dianping.mock_server import mock_app

    # Patch the imported bindings inside api.routers.plan (not the source module)
    monkeypatch.setattr(plan_router, "resolve_planner_llm", lambda: broken)
    monkeypatch.setattr(
        plan_router, "resolve_planner_llm_stream", lambda: broken_stream
    )

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


def test_planner_llm_failure_emits_day_done_fallback(app_client_with_broken_llm):
    """v1.6: per-day LLM failure → day_done_fallback event + fallback synthesis.

    Previously the entire planner stage emitted an error event when LLM failed.
    With per-day compose, each day independently falls back to deterministic
    synthesis from candidate POIs — better UX, demo never breaks. Stream still
    emits day_done with longitude/latitude (from synthesized real POIs).
    """
    with app_client_with_broken_llm.stream(
        "POST",
        "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳"},
    ) as resp:
        body = b"".join(resp.iter_bytes())
    events = parse_sse(body)
    names = [e["event"] for e in events]

    assert "planner.day_done_fallback" in names, (
        f"Expected day_done_fallback in events, got: {names}"
    )
    fallback = next(e for e in events if e["event"] == "planner.day_done_fallback")
    assert "simulated LLM failure" in fallback["data"]["reason"]
    # And standard day_done still emits after fallback
    assert "planner.day_done" in names
