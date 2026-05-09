"""Shared pytest fixtures.

The `sse_app_client` fixture wires the FastAPI v1 app to an in-process
mock_server via httpx.MockTransport, so SSE tests don't depend on a
real uvicorn process listening on port 9192.
"""

from __future__ import annotations

import os

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def sse_app_client(tmp_path_factory):
    """A v1 FastAPI app whose DianpingClient is redirected via MockTransport
    to an in-process TestClient(mock_app)."""
    os.environ.pop("DASHSCOPE_API_KEY", None)
    os.environ["MTAGENT_TRIPS_DIR"] = str(tmp_path_factory.mktemp("trips"))

    from api import deps
    from api.main import app
    from dianping.client import DianpingClient
    from dianping.mock_server import mock_app

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
