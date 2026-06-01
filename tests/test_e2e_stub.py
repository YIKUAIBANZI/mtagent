"""End-to-end stub: free text → Profiler → Planner → RouteDraft, verifying spec §10."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest


@pytest.fixture
async def real_dianping_client(monkeypatch, tmp_path):
    """DianpingClient backed by mock_server via TestClient.

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
async def test_e2e_shenzhen_couple_3_days(real_dianping_client):
    """Spec §10 acceptance: 情侣 3 天深圳 produces compliant 3-day route."""
    from agents.context import TripContext
    from agents.critic import Critic
    from agents.planner import Planner
    from agents.profiler import Profiler
    from agents.tools import _haversine_km
    from dianping.schemas import UserInput

    profiler_response = json.dumps(
        {
            "city": "深圳",
            "days": 3,
            "traveler_type": "情侣",
            "budget_level": "适中",
            "pace": None,
            "preferences": ["拍照", "打卡"],
            "must_visit": [],
            "avoid": [],
            "start_date": None,
        }
    )
    fake_profiler_llm = AsyncMock(return_value=profiler_response)

    fake_planner_llm = AsyncMock(
        return_value=json.dumps(
            {
                "summary": "为你打造的 3 天深圳情侣行——拍照打卡 + 美食 + 商场。",
                "days": [],
            }
        )
    )

    profiler = Profiler(llm_call=fake_profiler_llm)
    planner = Planner(client=real_dianping_client, llm_call=fake_planner_llm)
    critic = Critic()

    ctx = TripContext.create(
        user_input=UserInput(free_text="情侣 3 天深圳预算 3000 爱拍照"),
    )

    # --- Profiler ---
    profile_out = await profiler.run(ctx)
    assert profile_out.ready_to_plan
    assert ctx.intent.city == "深圳"
    assert ctx.intent.days == 3
    assert ctx.intent.traveler_type == "情侣"

    # --- Planner ---
    route = await planner.run(ctx)
    assert route is not None
    assert len(route.days) == 3, "must produce 3 day plans"

    for d, day in enumerate(route.days):
        # Acceptance: each day has >= 3 POIs (赛题 ≥3 POI)
        assert len(day.stops) >= 3, (
            f"day {d} has only {len(day.stops)} stops, spec requires ≥3"
        )

        # Acceptance: must contain 美食 (餐饮) + non-food category
        cats_seen: set[str] = set()
        for stop in day.stops:
            for c in stop.poi.categories:
                cats_seen.add(c)
        assert "美食" in cats_seen, f"day {d} missing 美食 (餐饮)"
        non_food = cats_seen - {"美食"}
        assert non_food, f"day {d} missing non-food category"

        # Acceptance: meal slots correctly anchored
        for stop in day.stops:
            if stop.slot.name == "午饭":
                assert stop.slot.start.hour == 12 and stop.slot.end.hour == 13
            elif stop.slot.name == "晚饭":
                assert stop.slot.start.hour == 18 and stop.slot.end.hour == 20

        # Acceptance: cluster radius constraint (loose 12km gate per spec)
        coords = [(s.poi.latitude, s.poi.longitude) for s in day.stops]
        if len(coords) >= 2:
            for i in range(len(coords)):
                for j in range(i + 1, len(coords)):
                    d_km = _haversine_km(*coords[i], *coords[j])
                    assert d_km <= 12, f"day {d} stops too far apart: {d_km:.1f}km"

    # --- Critic stub ---
    patches = await critic.run(ctx)
    assert patches == []

    # --- TripContext persisted ---
    loaded = TripContext.load(ctx.trip_id)
    assert loaded.intent.city == "深圳"
    assert loaded.draft_route is not None
    assert len(loaded.draft_route.days) == 3
