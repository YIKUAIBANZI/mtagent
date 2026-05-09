"""Test Planner with a real mock_server (TestClient) and a fake LLM."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest


@pytest.fixture
async def real_client(monkeypatch, tmp_path):
    """A DianpingClient pointed at an in-process TestClient.

    TestClient must be used as a context manager so FastAPI's lifespan fires
    and the mock data loads into MockState.
    """
    monkeypatch.setenv("MTAGENT_TRIPS_DIR", str(tmp_path))
    from fastapi.testclient import TestClient

    from dianping.client import DianpingClient
    from dianping.mock_server import mock_app

    with TestClient(mock_app) as test_client:

        def handler(request):
            resp = test_client.post(
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
        yield client
        await client.close()


@pytest.mark.asyncio
async def test_planner_returns_3_day_route(real_client):
    from agents.context import TripContext
    from agents.planner import Planner
    from dianping.schemas import ParsedIntent, UserInput

    fake_route_json = json.dumps(
        {
            "summary": "3 天深圳情侣行",
            "days": [
                {"day_index": d, "anchor_district": "福田区", "stops": []}
                for d in range(3)
            ],
        }
    )
    fake_llm = AsyncMock(return_value=fake_route_json)

    planner = Planner(client=real_client, llm_call=fake_llm)
    ctx = TripContext.create(user_input=UserInput(free_text="x"))
    ctx.intent = ParsedIntent(
        city="深圳", days=3, traveler_type="情侣", budget_level="适中"
    )

    route = await planner.run(ctx)

    assert route is not None
    assert len(route.days) == 3
    assert ctx.draft_route is not None


@pytest.mark.asyncio
async def test_planner_respects_intent_avoid_filter(real_client):
    from agents.context import TripContext
    from agents.planner import Planner
    from dianping.schemas import ParsedIntent, UserInput

    fake_llm = AsyncMock(return_value=json.dumps({"summary": "", "days": []}))
    planner = Planner(client=real_client, llm_call=fake_llm)
    ctx = TripContext.create(user_input=UserInput(free_text="x"))
    ctx.intent = ParsedIntent(
        city="深圳",
        days=1,
        traveler_type="情侣",
        avoid=["夜店", "KTV"],
    )

    await planner.run(ctx)

    for poi in ctx.candidate_pois:
        assert "夜店" not in poi.name
        assert "KTV" not in poi.name
