"""Test TripContext save/load roundtrip and JSON persistence."""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def trips_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("MTAGENT_TRIPS_DIR", d)
        yield Path(d)


def test_context_create_and_save(trips_dir):
    from agents.context import TripContext
    from dianping.schemas import UserInput

    ctx = TripContext.create(user_input=UserInput(free_text="深圳 3 天情侣"))
    ctx.save()

    expected = trips_dir / f"{ctx.trip_id}.json"
    assert expected.exists()


def test_context_save_load_roundtrip(trips_dir):
    from agents.context import TripContext
    from dianping.schemas import ParsedIntent, UserInput

    ctx = TripContext.create(user_input=UserInput(free_text="深圳 3 天情侣"))
    ctx.intent = ParsedIntent(city="深圳", days=3, traveler_type="情侣")
    ctx.save()

    loaded = TripContext.load(ctx.trip_id)
    assert loaded.trip_id == ctx.trip_id
    assert loaded.user_input.free_text == "深圳 3 天情侣"
    assert loaded.intent.city == "深圳"
    assert loaded.intent.days == 3


def test_context_log_event_appends_to_trace(trips_dir):
    from agents.context import TripContext
    from dianping.schemas import UserInput

    ctx = TripContext.create(user_input=UserInput(free_text="x"))
    ctx.log_event("Profiler", "start", {"phase": "init"})
    ctx.log_event("Profiler", "done", {"city": "深圳"})

    assert len(ctx.trace) == 2
    assert ctx.trace[0].agent == "Profiler"
    assert ctx.trace[0].type == "start"
    assert ctx.trace[1].payload["city"] == "深圳"
