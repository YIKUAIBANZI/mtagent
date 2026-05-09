# mtagent v1 SSE Streaming + Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the v1 HTTP layer (FastAPI routes + SSE event protocol) and rework `web/plan_stack.html` to consume the SSE stream — turning the v0 backend-only pipeline into a browser-accessible end-to-end streaming demo.

**Architecture:** Two independent uvicorn processes (mock_server on 9192 + main app on 9191). Main app exposes `POST /api/plan/stream` returning text/event-stream; events follow the v1 spec §5 protocol. Frontend uses fetch + ReadableStream to consume SSE (since EventSource doesn't support POST). Agent layer from v0 is reused as-is — only a stub-LLM fallback is added to support running without DASHSCOPE_API_KEY.

**Tech Stack:** FastAPI 0.115+, httpx async, vanilla JS + Tailwind CDN (no build step), pytest with TestClient streaming. All v0 dependencies already installed in `venv/`.

**Spec reference:** `docs/superpowers/specs/2026-05-08-mtagent-v1-streaming-design.md`

**Prerequisites:**
- v0 implementation complete (`docs/superpowers/plans/2026-05-08-mtagent-v0-backend.md`)
- All v0 46 tests pass before starting v1
- Working directory: `/Users/yikuaibanz1/Desktop/sth/mtagent`
- Python venv: `source venv/bin/activate` from project root

---

## File Structure (v1 additions)

```
mtagent/
├── api/                              # NEW
│   ├── __init__.py
│   ├── main.py                       # FastAPI app, lifespan, CORS, static mount
│   ├── routes.py                     # /api/* endpoints
│   ├── sse.py                        # SSE event serialization helpers
│   ├── deps.py                       # Shared deps (DianpingClient singleton)
│   └── stub_llm.py                   # Fallback LLM when DASHSCOPE_API_KEY missing
├── web/
│   └── plan_stack.html               # MODIFIED: rewrite for SSE
└── tests/
    ├── test_api_health.py            # NEW
    ├── test_sse_protocol.py          # NEW
    ├── test_sse_clarifying.py        # NEW
    └── test_sse_error.py             # NEW
```

**Files NOT touched in v1:** Anything under `dianping/`, `agents/` (except adding the stub_llm helper). The v0 contract is sealed.

---

## Task 0: API Package Skeleton + Health Endpoint

**Goal:** Bootstrap the `api/` package, create the FastAPI app with CORS + a singleton DianpingClient via lifespan, plus a health endpoint to smoke-test.

**Files:**
- Create: `api/__init__.py`, `api/main.py`, `api/deps.py`
- Create: `tests/test_api_health.py`

- [ ] **Step 1: Write the failing health-check test**

Create `tests/test_api_health.py`:

```python
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
```

- [ ] **Step 2: Run test — verify failure**

```bash
PYTHONPATH=. pytest tests/test_api_health.py -v
```

Expected: 2 FAIL with ImportError (`api.main` not found).

- [ ] **Step 3: Create `api/__init__.py`**

Create empty file: `api/__init__.py`

- [ ] **Step 4: Create `api/deps.py`**

Create `api/deps.py`:

```python
"""Shared dependencies for FastAPI routes.

Holds the singleton DianpingClient that's created in lifespan and injected
into route handlers via Depends().
"""
from __future__ import annotations

from typing import Optional

from dianping.client import DianpingClient


class _State:
    client: Optional[DianpingClient] = None


def set_client(client: DianpingClient) -> None:
    _State.client = client


def get_client() -> DianpingClient:
    if _State.client is None:
        raise RuntimeError(
            "DianpingClient is not initialized. "
            "Did the FastAPI lifespan run?"
        )
    return _State.client
```

- [ ] **Step 5: Create `api/main.py`**

Create `api/main.py`:

```python
"""FastAPI main app — entrypoint for v1 HTTP layer.

Run:
    uvicorn api.main:app --host 127.0.0.1 --port 9191

Companion process (must be running too):
    uvicorn dianping.mock_server:mock_app --host 127.0.0.1 --port 9192
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api import deps
from dianping.client import DianpingClient

VERSION = "v1.0.0"
WEB_DIR = Path(__file__).parent.parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create singleton DianpingClient on startup, close on shutdown."""
    client = DianpingClient()  # uses env: MTAGENT_DIANPING_BASE_URL
    deps.set_client(client)
    try:
        yield
    finally:
        await client.close()


app = FastAPI(
    title="mtagent v1 — Travel Planning Streaming API",
    version=VERSION,
    lifespan=lifespan,
)

# Permissive CORS for hackathon dev (file://, localhost:*, 127.0.0.1:*)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "version": VERSION,
        "dianping_base_url": os.environ.get(
            "MTAGENT_DIANPING_BASE_URL", "http://localhost:9192"
        ),
        "llm_configured": bool(os.environ.get("DASHSCOPE_API_KEY")),
    }


# Routes are registered via include_router in Task 3
# (placeholder import to keep this file the single entrypoint)
from api import routes  # noqa: E402

app.include_router(routes.router)


# Static files — serves plan_stack.html at /
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
```

This file imports `api.routes`, which doesn't exist yet — that's fine, Task 3 creates it. For Task 0 we'll temporarily comment those two lines OR create a stub.

- [ ] **Step 6: Create routes.py stub for Task 0**

Create `api/routes.py`:

```python
"""HTTP routes — full implementation in Task 3."""
from fastapi import APIRouter

router = APIRouter()
```

- [ ] **Step 7: Run health test — verify pass**

```bash
PYTHONPATH=. pytest tests/test_api_health.py -v
```

Expected: 2 PASSED.

- [ ] **Step 8: Smoke run via uvicorn**

```bash
PYTHONPATH=. uvicorn api.main:app --host 127.0.0.1 --port 9191 &
sleep 2
curl -s http://127.0.0.1:9191/api/health
kill %1 2>/dev/null
```

Expected: JSON `{"ok": true, "version": "v1.0.0", ...}` printed.

- [ ] **Step 9: Commit**

```bash
git add api/ tests/test_api_health.py
git commit -m "feat(api): bootstrap FastAPI v1 app with health endpoint and CORS"
```

---

## Task 1: SSE Event Serialization Helpers

**Goal:** Build a tiny helper module to format SSE events as the protocol mandates (event/data pairs ending with `\n\n`).

**Files:**
- Create: `api/sse.py`
- Create: `tests/test_sse_helpers.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_sse_helpers.py`:

```python
"""Test SSE event serialization helpers."""


def test_format_event_basic():
    from api.sse import format_event

    out = format_event("trip.started", {"trip_id": "trip_abc"})
    assert out.startswith("event: trip.started\n")
    assert "data: " in out
    assert out.endswith("\n\n")
    assert '"trip_id": "trip_abc"' in out


def test_format_event_chinese_unescaped():
    """Chinese must NOT be \\uXXXX-escaped — UTF-8 should be raw in the data line."""
    from api.sse import format_event

    out = format_event("profiler.understood", {"city": "深圳"})
    assert "深圳" in out


def test_format_event_data_is_single_line():
    """Per SSE protocol: data: must be on a single line."""
    from api.sse import format_event

    out = format_event("planner.token", {"chunk": "今天\n上午"})
    # Newlines inside JSON value are escaped as \\n
    data_line = [ln for ln in out.split("\n") if ln.startswith("data:")][0]
    # Should not contain a literal newline AFTER 'data: '
    assert "\n" not in data_line[6:]


def test_format_event_with_empty_data():
    from api.sse import format_event

    out = format_event("trip.complete", {})
    assert out.startswith("event: trip.complete\n")
    assert "data: {}" in out
```

- [ ] **Step 2: Run — verify failure**

```bash
PYTHONPATH=. pytest tests/test_sse_helpers.py -v
```

Expected: 4 FAIL with ImportError.

- [ ] **Step 3: Implement `api/sse.py`**

Create `api/sse.py`:

```python
"""SSE event serialization.

Per W3C EventSource: each event is a sequence of fields ('event:', 'data:', etc.)
followed by an empty line. We use:

    event: <name>\n
    data: <single-line-json>\n
    \n
"""
from __future__ import annotations

import json
from typing import Any


def format_event(name: str, data: Any) -> str:
    """Format an SSE event with name + JSON data, raw UTF-8 (no \\u escapes)."""
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # JSON spec already escapes literal newlines as \\n inside strings,
    # so payload is single-line. But be defensive against external sources.
    payload = payload.replace("\n", "\\n").replace("\r", "\\r")
    return f"event: {name}\ndata: {payload}\n\n"
```

- [ ] **Step 4: Run tests — verify pass**

```bash
PYTHONPATH=. pytest tests/test_sse_helpers.py -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add api/sse.py tests/test_sse_helpers.py
git commit -m "feat(api): SSE event formatter with UTF-8 raw output"
```

---

## Task 2: Stub LLM Fallback (no-key mode)

**Goal:** When `DASHSCOPE_API_KEY` is not set, fall back to a deterministic stub LLM so v1 demo can run without API costs. The stub LLM returns canned ParsedIntent + an empty Planner JSON (lets fallback synthesis kick in).

**Files:**
- Create: `api/stub_llm.py`
- Create: `tests/test_stub_llm.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_stub_llm.py`:

```python
"""Test stub LLM fallback for no-DASHSCOPE-API-KEY mode."""
import json

import pytest


@pytest.mark.asyncio
async def test_stub_profiler_llm_parses_simple_text():
    from api.stub_llm import stub_profiler_llm

    raw = await stub_profiler_llm("system", "情侣 3 天深圳预算 3000 爱拍照")
    data = json.loads(raw)

    assert data["city"] == "深圳"
    assert data["days"] == 3
    assert data["traveler_type"] == "情侣"


@pytest.mark.asyncio
async def test_stub_profiler_llm_handles_missing_fields():
    from api.stub_llm import stub_profiler_llm

    raw = await stub_profiler_llm("system", "深圳")
    data = json.loads(raw)

    assert data["city"] == "深圳"
    # Either days or traveler_type missing
    assert data.get("days") in (None, 0) or data.get("traveler_type") is None


@pytest.mark.asyncio
async def test_stub_planner_llm_returns_empty_days():
    from api.stub_llm import stub_planner_llm

    raw = await stub_planner_llm("system", "any payload")
    data = json.loads(raw)

    assert "days" in data
    # Empty days triggers fallback synthesis in agents/planner.py
    assert data["days"] == []


@pytest.mark.asyncio
async def test_resolve_llm_uses_real_when_key_present(monkeypatch):
    from api.stub_llm import resolve_profiler_llm
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    fn = resolve_profiler_llm()
    # Non-stub function name (the real one is _default_qwen_call from profiler.py)
    assert fn.__name__ != "stub_profiler_llm"


@pytest.mark.asyncio
async def test_resolve_llm_uses_stub_when_key_missing(monkeypatch):
    from api.stub_llm import resolve_profiler_llm
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    fn = resolve_profiler_llm()
    assert fn.__name__ == "stub_profiler_llm"
```

- [ ] **Step 2: Run — verify failure**

```bash
PYTHONPATH=. pytest tests/test_stub_llm.py -v
```

Expected: 5 FAIL.

- [ ] **Step 3: Implement `api/stub_llm.py`**

Create `api/stub_llm.py`:

```python
"""Stub LLM fallback when DASHSCOPE_API_KEY is missing.

Lets the demo run end-to-end without API costs. The Planner's fallback
synthesis (in agents/planner.py) takes over when the stub returns empty days,
producing a deterministic real route from real mock POIs.
"""
from __future__ import annotations

import json
import os
import re
from typing import Awaitable, Callable

# Regex patterns for the simple Profiler stub
_CITY_PAT = re.compile(r"(深圳|上海|西安)")
_DAYS_PAT = re.compile(r"(\d+)\s*天")
_TRAVELER_PATS = [
    (re.compile(r"(情侣|男朋友|女朋友|对象)"), "情侣"),
    (re.compile(r"(家庭|带孩子|亲子|一家人)"), "家庭亲子"),
    (re.compile(r"(爸妈|长辈|银发)"), "银发"),
    (re.compile(r"(独行|一个人|独自)"), "独行"),
    (re.compile(r"(出差|商务)"), "商务"),
    (re.compile(r"(朋友|闺蜜|一群)"), "朋友团"),
]
_BUDGET_PATS = [
    (re.compile(r"(穷游|性价比|不贵|便宜)"), "性价比"),
    (re.compile(r"(精致|高端|不在乎钱|奢华)"), "精致"),
]
_PREFERENCE_TOKENS = ["拍照", "打卡", "美食", "文化", "历史", "出片", "小众", "网红"]


async def stub_profiler_llm(system: str, user: str) -> str:
    """Pattern-match the user text into a ParsedIntent JSON.

    Best-effort heuristic — fallback when no real LLM available.
    """
    city_match = _CITY_PAT.search(user)
    city = city_match.group(1) if city_match else None

    days_match = _DAYS_PAT.search(user)
    days = int(days_match.group(1)) if days_match else None

    traveler_type = None
    for pat, label in _TRAVELER_PATS:
        if pat.search(user):
            traveler_type = label
            break

    budget_level = None
    for pat, label in _BUDGET_PATS:
        if pat.search(user):
            budget_level = label
            break
    if budget_level is None and re.search(r"预算\s*(\d+)", user):
        # Crude: total budget 推算
        amt = int(re.search(r"预算\s*(\d+)", user).group(1))
        per_day_per_person = amt / max(days or 1, 1) / 2  # assume 2 people
        if per_day_per_person < 100:
            budget_level = "性价比"
        elif per_day_per_person < 300:
            budget_level = "适中"
        else:
            budget_level = "精致"

    preferences = [t for t in _PREFERENCE_TOKENS if t in user]

    out = {
        "city": city,
        "days": days,
        "traveler_type": traveler_type,
        "budget_level": budget_level,
        "pace": None,
        "preferences": preferences,
        "must_visit": [],
        "avoid": [],
        "start_date": None,
    }
    return json.dumps(out, ensure_ascii=False)


async def stub_planner_llm(system: str, user: str) -> str:
    """Returns empty days — triggers Planner.fallback synthesis."""
    return json.dumps({
        "summary": "为你打造的行程——基于真实候选 POI 的智能编排（stub LLM 模式）。",
        "days": [],
    }, ensure_ascii=False)


def resolve_profiler_llm() -> Callable[[str, str], Awaitable[str]]:
    """Return real qwen call if DASHSCOPE_API_KEY is set, else stub."""
    if os.environ.get("DASHSCOPE_API_KEY"):
        from agents.profiler import _default_qwen_call
        return _default_qwen_call
    return stub_profiler_llm


def resolve_planner_llm() -> Callable[[str, str], Awaitable[str]]:
    """Return real qwen call if DASHSCOPE_API_KEY is set, else stub."""
    if os.environ.get("DASHSCOPE_API_KEY"):
        from agents.planner import _default_qwen_call
        return _default_qwen_call
    return stub_planner_llm
```

- [ ] **Step 4: Run tests — verify pass**

```bash
PYTHONPATH=. pytest tests/test_stub_llm.py -v
```

Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add api/stub_llm.py tests/test_stub_llm.py
git commit -m "feat(api): stub LLM fallback for no-API-KEY demo mode"
```

---

## Task 3: Streaming Endpoint `/api/plan/stream`

**Goal:** Implement the SSE streaming endpoint that orchestrates Profiler → Planner → Critic stub and emits the v1 spec §5 event protocol.

**Files:**
- Modify: `api/routes.py` (replace stub)
- Create: `tests/test_sse_protocol.py`

- [ ] **Step 1: Write the failing protocol test**

Create `tests/test_sse_protocol.py`:

```python
"""Test the /api/plan/stream endpoint emits the v1 spec §5 event protocol."""
import json
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def app_client(monkeypatch_module=None):
    # Ensure stub LLM mode
    os.environ.pop("DASHSCOPE_API_KEY", None)
    from api.main import app
    with TestClient(app) as c:
        yield c


def parse_sse_stream(content: bytes) -> list[dict]:
    """Parse raw SSE bytes into a list of {event, data} dicts."""
    text = content.decode("utf-8")
    events = []
    for chunk in text.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        ev_name = None
        ev_data = None
        for line in chunk.splitlines():
            if line.startswith("event: "):
                ev_name = line[len("event: "):]
            elif line.startswith("data: "):
                ev_data = json.loads(line[len("data: "):])
        if ev_name is not None:
            events.append({"event": ev_name, "data": ev_data})
    return events


def test_stream_returns_sse_content_type(app_client):
    with app_client.stream(
        "POST", "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳"},
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]


def test_stream_emits_full_event_sequence(app_client):
    with app_client.stream(
        "POST", "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳预算 3000 爱拍照"},
    ) as resp:
        body = b"".join(resp.iter_bytes())
    events = parse_sse_stream(body)
    names = [e["event"] for e in events]

    # Must contain core event sequence
    assert "trip.started" in names
    assert "profiler.start" in names
    assert "profiler.understood" in names
    assert "profiler.ready" in names
    assert "planner.start" in names
    assert "planner.anchors" in names
    assert "planner.candidates_loaded" in names
    assert "planner.clusters_ready" in names
    assert "planner.compose_start" in names
    assert "planner.done" in names
    assert "critic.start" in names
    assert "critic.done" in names
    assert "trip.complete" in names

    # Order: trip.started before everything; trip.complete is last (or near last)
    assert names.index("trip.started") == 0
    assert names.index("trip.complete") == len(names) - 1


def test_understood_event_has_parsed_intent(app_client):
    with app_client.stream(
        "POST", "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳"},
    ) as resp:
        body = b"".join(resp.iter_bytes())
    events = parse_sse_stream(body)
    understood = next(e for e in events if e["event"] == "profiler.understood")
    assert understood["data"]["city"] == "深圳"
    assert understood["data"]["days"] == 3
    assert understood["data"]["traveler_type"] == "情侣"


def test_planner_done_event_has_route(app_client):
    with app_client.stream(
        "POST", "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳"},
    ) as resp:
        body = b"".join(resp.iter_bytes())
    events = parse_sse_stream(body)
    done = next(e for e in events if e["event"] == "planner.done")
    assert "route" in done["data"]
    route = done["data"]["route"]
    assert "days" in route
    assert len(route["days"]) == 3
```

- [ ] **Step 2: Run — verify failure**

```bash
PYTHONPATH=. pytest tests/test_sse_protocol.py -v
```

Expected: 4 FAIL (route doesn't exist yet).

- [ ] **Step 3: Implement `api/routes.py`**

Replace the contents of `api/routes.py`:

```python
"""HTTP routes — v1 streaming endpoint per spec §5."""
from __future__ import annotations

import asyncio
import json
import time
import traceback
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.context import TripContext
from agents.planner import Planner
from agents.profiler import Profiler
from agents.critic import Critic
from api import deps
from api.sse import format_event
from api.stub_llm import resolve_planner_llm, resolve_profiler_llm
from dianping.client import DianpingClient
from dianping.schemas import ParsedIntent, UserInput

router = APIRouter(prefix="/api")


class StreamRequest(BaseModel):
    free_text: str
    extra: dict | None = None


@router.post("/plan/stream")
async def plan_stream(
    body: StreamRequest,
    client: DianpingClient = Depends(deps.get_client),
):
    """Run the full pipeline (Profiler → Planner → Critic) emitting SSE events
    per spec §5.2."""

    async def event_stream() -> AsyncIterator[str]:
        ctx = TripContext.create(user_input=UserInput(free_text=body.free_text))
        start_time = time.time()
        yield format_event("trip.started", {"trip_id": ctx.trip_id})

        # ----- Profiler -----
        try:
            yield format_event("profiler.start", {"phase": "正在理解需求..."})

            profiler = Profiler(llm_call=resolve_profiler_llm())
            profiler_out = await profiler.run(ctx)

            yield format_event(
                "profiler.understood",
                profiler_out.understood.model_dump(mode="json"),
            )

            # Apply extra fields from clarifying round if present
            if body.extra and not profiler_out.ready_to_plan:
                _merge_extra(ctx, body.extra)
                # Re-evaluate readiness after merge
                if all(
                    getattr(ctx.intent, k) not in (None, "", 0)
                    for k in ("city", "days", "traveler_type")
                ):
                    profiler_out.ready_to_plan = True
                    profiler_out.missing_fields = []

            if not profiler_out.ready_to_plan:
                yield format_event(
                    "profiler.clarifying",
                    {"missing_fields": profiler_out.missing_fields},
                )
                yield format_event("trip.complete", {
                    "trip_id": ctx.trip_id,
                    "duration_ms": int((time.time() - start_time) * 1000),
                    "status": "awaiting_clarification",
                })
                return

            yield format_event("profiler.ready", {})
        except Exception as exc:
            yield format_event("error", {
                "phase": "profiler",
                "message": str(exc),
                "stack_trace": traceback.format_exc()[-500:],
            })
            return

        # ----- Planner -----
        try:
            yield format_event("planner.start", {"phase": "正在挑选 POI..."})

            planner = Planner(client=client, llm_call=resolve_planner_llm())

            # We need fine-grained progress events — wrap planner.run with
            # a side-channel queue or run sub-steps inline. For v1 we run the
            # full planner.run() but emit progress milestones from outside
            # by inspecting ctx after the call.
            # Simpler: run it once, then emit retroactive milestones based on
            # ctx snapshot. Acceptable trade-off for v1.

            # Step-by-step orchestration mirroring Planner.run internals so we
            # can emit per-step events. This duplicates ~30 lines but gives
            # the right UX. (Refactor consideration deferred to v2.)
            from agents.tools import (
                cluster_anchor_orbit,
                default_pace_for_traveler,
                filter_by_intent_constraints,
                generate_day_template,
                rank_by_traveler_type,
                search_pois,
                batch_get_poi_details,
                check_business_hours,
            )
            from agents.planner import _pick_anchors, _synthesize_fallback_route
            from datetime import datetime, time as dt_time, timedelta
            from dianping.schemas import RouteDraft, DayPlan, Stop, TimeSlot

            intent = ctx.intent
            pace = intent.pace or default_pace_for_traveler(intent.traveler_type)
            templates = generate_day_template(
                days=intent.days, traveler_type=intent.traveler_type, pace=pace,
            )
            anchors = _pick_anchors(intent.city, intent.days, intent.must_visit)
            yield format_event("planner.anchors", {
                "anchors": [
                    {"name": a[0], "lat": a[1], "lng": a[2]} for a in anchors
                ],
            })

            all_categories = {
                c for tmpl in templates for slot in tmpl.slots
                for c in slot.category_pool
            }
            search_tasks = []
            for anchor_name, lat, lng in anchors:
                for cat in all_categories:
                    search_tasks.append(
                        search_pois(
                            client, city=intent.city,
                            latitude=lat, longitude=lng, radius=5000,
                            categories=cat, limit=25,
                        )
                    )
            results = await asyncio.gather(*search_tasks, return_exceptions=True)
            all_ids = set()
            for r in results:
                if isinstance(r, Exception):
                    continue
                all_ids.update(rec.openshopid for rec in r)

            details = await batch_get_poi_details(client, list(all_ids))
            pois = list(details.values())
            yield format_event("planner.candidates_loaded", {
                "count": len(pois),
                "preview": [
                    {"openshopid": p.openshopid, "name": p.name, "categories": p.categories}
                    for p in pois[:6]
                ],
            })

            clusters = cluster_anchor_orbit(pois, k=intent.days, max_radius_km=5.0)
            start_date = intent.start_date or datetime.now().date()
            filtered_clusters = []
            for di, cluster in enumerate(clusters):
                day_date = start_date + timedelta(days=di)
                mid = datetime.combine(day_date, dt_time(12, 30))
                kept = [p for p in cluster if check_business_hours(p, mid)]
                kept = filter_by_intent_constraints(kept, intent)
                filtered_clusters.append(kept)
            ranked_clusters = [
                rank_by_traveler_type(c, intent.traveler_type) for c in filtered_clusters
            ]
            ctx.candidate_pois = [p for c in ranked_clusters for p in c]
            yield format_event("planner.clusters_ready", {
                "per_day_count": [len(c) for c in ranked_clusters],
            })

            yield format_event("planner.compose_start", {"phase": "正在编排路线..."})

            payload = planner._build_compose_payload(intent, templates, anchors, ranked_clusters)
            raw_llm = await planner.llm_call(planner._system_prompt, payload)
            try:
                llm_data = json.loads(raw_llm)
            except json.JSONDecodeError:
                llm_data = {"days": [], "summary": ""}

            # Build route: prefer LLM days; fallback synthesis if empty
            poi_index = {p.openshopid: p for p in ctx.candidate_pois}
            days_out = []
            for d, day_data in enumerate(llm_data.get("days", [])):
                stops = []
                for s in (day_data.get("stops") or []):
                    pid = s.get("poi_openshopid")
                    poi = poi_index.get(pid)
                    if poi is None:
                        continue
                    slot_name = s.get("slot_name", "上午景点")
                    slot_def = next(
                        (slot for slot in templates[d].slots if slot.name == slot_name),
                        templates[d].slots[0],
                    )
                    stops.append(Stop(
                        poi=poi,
                        slot=TimeSlot(name=slot_name, start=slot_def.start, end=slot_def.end),
                        arrival_time=slot_def.start,
                        leave_time=slot_def.end,
                    ))
                days_out.append(DayPlan(
                    day_index=day_data.get("day_index", d),
                    anchor_district=day_data.get("anchor_district", anchors[d][0] if d < len(anchors) else ""),
                    stops=stops,
                ))
            if not days_out or all(len(d.stops) == 0 for d in days_out):
                if any(ranked_clusters):
                    days_out = _synthesize_fallback_route(
                        templates, anchors, ranked_clusters, intent
                    )

            for d in days_out:
                yield format_event("planner.day_done", {
                    "day_index": d.day_index,
                    "anchor_district": d.anchor_district,
                    "stops": [
                        {
                            "poi_name": s.poi.name,
                            "poi_openshopid": s.poi.openshopid,
                            "categories": s.poi.categories,
                            "slot_name": s.slot.name,
                            "arrival_time": s.arrival_time.strftime("%H:%M"),
                            "leave_time": s.leave_time.strftime("%H:%M"),
                            "avgprice": s.poi.avgprice,
                            "star": s.poi.star,
                        }
                        for s in d.stops
                    ],
                })

            route = RouteDraft(days=days_out, summary=llm_data.get("summary", ""))
            ctx.draft_route = route
            ctx.save()

            yield format_event("planner.done", {
                "summary": route.summary,
                "route": route.model_dump(mode="json"),
            })
        except Exception as exc:
            yield format_event("error", {
                "phase": "planner",
                "message": str(exc),
                "stack_trace": traceback.format_exc()[-500:],
            })
            return

        # ----- Critic stub -----
        try:
            yield format_event("critic.start", {})
            critic = Critic()
            patches = await critic.run(ctx)
            yield format_event("critic.done", {"patches_count": len(patches)})
        except Exception as exc:
            yield format_event("error", {
                "phase": "critic",
                "message": str(exc),
            })

        # ----- Done -----
        yield format_event("trip.complete", {
            "trip_id": ctx.trip_id,
            "duration_ms": int((time.time() - start_time) * 1000),
            "status": "ok",
        })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _merge_extra(ctx: TripContext, extra: dict) -> None:
    """Apply user-provided clarifying answers to ctx.intent."""
    if ctx.intent is None:
        return
    for k in ("city", "days", "traveler_type", "budget_level", "pace"):
        v = extra.get(k)
        if v not in (None, "", 0):
            setattr(ctx.intent, k, v)


@router.get("/plan/{trip_id}")
async def get_trip(trip_id: str):
    """Retrieve a saved TripContext by trip_id."""
    try:
        ctx = TripContext.load(trip_id)
        return ctx.model_dump(mode="json")
    except FileNotFoundError:
        raise HTTPException(404, f"trip not found: {trip_id}")
```

- [ ] **Step 4: Run protocol test — verify pass**

```bash
PYTHONPATH=. pytest tests/test_sse_protocol.py -v
```

Expected: 4 PASSED. If `test_planner_done_event_has_route` fails because of empty days, check that mock data is loaded (TestClient must be context-manager — already handled in fixture).

- [ ] **Step 5: Commit**

```bash
git add api/routes.py tests/test_sse_protocol.py
git commit -m "feat(api): /api/plan/stream SSE endpoint with full v1 §5 protocol"
```

---

## Task 4: Clarifying + Error Edge Cases

**Goal:** Cover the two non-happy paths — Profiler missing fields and Planner errors — with dedicated tests.

**Files:**
- Create: `tests/test_sse_clarifying.py`
- Create: `tests/test_sse_error.py`

- [ ] **Step 1: Write clarifying test**

Create `tests/test_sse_clarifying.py`:

```python
"""Test Profiler clarifying flow."""
import json
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def app_client():
    os.environ.pop("DASHSCOPE_API_KEY", None)
    from api.main import app
    with TestClient(app) as c:
        yield c


def parse_sse(body: bytes) -> list[dict]:
    events = []
    for chunk in body.decode("utf-8").split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        ev = {"event": None, "data": None}
        for line in chunk.splitlines():
            if line.startswith("event: "):
                ev["event"] = line[len("event: "):]
            elif line.startswith("data: "):
                ev["data"] = json.loads(line[len("data: "):])
        events.append(ev)
    return events


def test_partial_input_emits_clarifying(app_client):
    """Input without days+traveler_type → clarifying event + early close."""
    with app_client.stream(
        "POST", "/api/plan/stream",
        json={"free_text": "深圳"},
    ) as resp:
        body = b"".join(resp.iter_bytes())
    events = parse_sse(body)
    names = [e["event"] for e in events]

    assert "profiler.clarifying" in names
    clarifying = next(e for e in events if e["event"] == "profiler.clarifying")
    assert "days" in clarifying["data"]["missing_fields"]
    assert "traveler_type" in clarifying["data"]["missing_fields"]

    # planner.start should NOT be emitted on early close
    assert "planner.start" not in names
    # trip.complete is still emitted with awaiting_clarification status
    assert "trip.complete" in names
    complete = next(e for e in events if e["event"] == "trip.complete")
    assert complete["data"]["status"] == "awaiting_clarification"


def test_extra_fields_complete_clarifying(app_client):
    """Re-submit with extra fields → full pipeline runs."""
    with app_client.stream(
        "POST", "/api/plan/stream",
        json={
            "free_text": "深圳",
            "extra": {"days": 2, "traveler_type": "情侣"},
        },
    ) as resp:
        body = b"".join(resp.iter_bytes())
    events = parse_sse(body)
    names = [e["event"] for e in events]

    assert "profiler.ready" in names
    assert "planner.start" in names
    assert "planner.done" in names
```

- [ ] **Step 2: Run — verify pass**

```bash
PYTHONPATH=. pytest tests/test_sse_clarifying.py -v
```

Expected: 2 PASSED. (Routes from Task 3 already handle this path.)

- [ ] **Step 3: Write error test**

Create `tests/test_sse_error.py`:

```python
"""Test error path: Planner LLM throws → error event + clean close."""
import json
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client_with_broken_llm(monkeypatch):
    os.environ.pop("DASHSCOPE_API_KEY", None)

    # Patch resolve_profiler_llm/resolve_planner_llm to return a fn that raises
    async def broken(_system, _user):
        raise ValueError("simulated LLM failure")

    from api import stub_llm
    monkeypatch.setattr(stub_llm, "resolve_planner_llm", lambda: broken)

    from api.main import app
    with TestClient(app) as c:
        yield c


def parse_sse(body: bytes) -> list[dict]:
    events = []
    for chunk in body.decode("utf-8").split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        ev = {"event": None, "data": None}
        for line in chunk.splitlines():
            if line.startswith("event: "):
                ev["event"] = line[len("event: "):]
            elif line.startswith("data: "):
                ev["data"] = json.loads(line[len("data: "):])
        events.append(ev)
    return events


def test_planner_llm_failure_emits_error_event(app_client_with_broken_llm):
    with app_client_with_broken_llm.stream(
        "POST", "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳"},
    ) as resp:
        body = b"".join(resp.iter_bytes())
    events = parse_sse(body)
    names = [e["event"] for e in events]

    assert "error" in names
    error = next(e for e in events if e["event"] == "error")
    assert error["data"]["phase"] == "planner"
    assert "simulated LLM failure" in error["data"]["message"]
```

- [ ] **Step 4: Run — verify pass**

```bash
PYTHONPATH=. pytest tests/test_sse_error.py -v
```

Expected: 1 PASSED.

- [ ] **Step 5: Commit**

```bash
git add tests/test_sse_clarifying.py tests/test_sse_error.py
git commit -m "test(api): clarifying + error path coverage for /api/plan/stream"
```

---

## Task 5: Frontend `web/plan_stack.html` Rewrite

**Goal:** Rewrite plan_stack.html as a self-contained vanilla JS + Tailwind CDN page that consumes the SSE stream and renders three reveal stages + final timeline.

**Files:**
- Modify: `web/plan_stack.html` (replace whole content)

- [ ] **Step 1: Replace `web/plan_stack.html`**

Overwrite `web/plan_stack.html` with:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>mtagent · AI 路线规划</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
  <style>
    body { font-family: 'Inter', system-ui, sans-serif; background: #faf8f3; color: #2a2620; }
    .serif { font-family: 'Instrument Serif', serif; }
    .chip { animation: chip-in 0.5s ease-out backwards; }
    @keyframes chip-in {
      from { opacity: 0; transform: translateY(-8px) scale(0.92); }
      to   { opacity: 1; transform: translateY(0) scale(1); }
    }
    .card-slide { animation: card-slide 0.6s ease-out backwards; }
    @keyframes card-slide {
      from { opacity: 0; transform: translateX(40px); }
      to   { opacity: 1; transform: translateX(0); }
    }
    .stage-pulse { animation: stage-pulse 1.5s ease-in-out infinite; }
    @keyframes stage-pulse {
      0%, 100% { opacity: 0.5; }
      50%      { opacity: 1; }
    }
    .day-card  { animation: day-fade 0.7s ease-out backwards; }
    @keyframes day-fade {
      from { opacity: 0; transform: translateY(16px); }
      to   { opacity: 1; transform: translateY(0); }
    }
  </style>
</head>
<body class="min-h-screen">
  <div class="max-w-5xl mx-auto px-6 py-12">
    <!-- Header -->
    <header class="mb-12">
      <h1 class="serif text-5xl mb-2">mtagent</h1>
      <p class="text-stone-500">想去哪里？告诉我你想要的旅行 ✨</p>
    </header>

    <!-- Input -->
    <section id="input-section" class="mb-12">
      <textarea
        id="free-text"
        class="w-full p-5 border-2 border-stone-200 rounded-2xl focus:border-amber-400 focus:outline-none text-lg resize-none transition-colors"
        rows="3"
        placeholder="例：情侣 3 天深圳预算 3000 爱拍照"
      ></textarea>
      <div class="flex gap-3 mt-4">
        <button
          id="generate-btn"
          class="px-8 py-3 bg-stone-800 text-white rounded-full hover:bg-stone-700 transition-colors disabled:opacity-50"
        >
          生成路线
        </button>
        <span class="text-sm text-stone-400 self-center" id="status-text"></span>
      </div>
    </section>

    <!-- Reveal stages -->
    <section id="reveal-section" class="hidden space-y-6 mb-12">
      <!-- Stage 1: profiler -->
      <div id="stage-profiler" class="hidden">
        <div class="text-stone-400 text-sm mb-2 stage-pulse" id="profiler-status">◐ 正在理解需求...</div>
        <div id="understood-chips" class="flex flex-wrap gap-2"></div>
      </div>

      <!-- Stage 2: planner candidates -->
      <div id="stage-candidates" class="hidden">
        <div class="text-stone-400 text-sm mb-2 stage-pulse" id="candidates-status">◐ 正在挑选 POI...</div>
        <div id="candidate-cards" class="flex gap-3 overflow-x-auto pb-2"></div>
      </div>

      <!-- Stage 3: planner compose -->
      <div id="stage-compose" class="hidden">
        <div class="text-stone-400 text-sm mb-2 stage-pulse" id="compose-status">◐ 正在编排路线...</div>
      </div>
    </section>

    <!-- Final timeline -->
    <section id="timeline-section" class="hidden">
      <h2 class="serif text-3xl mb-6" id="timeline-title">你的行程</h2>
      <p class="text-stone-600 mb-8" id="timeline-summary"></p>
      <div id="timeline-days" class="space-y-8"></div>
    </section>

    <!-- Clarifying modal -->
    <div id="clarifying-modal" class="hidden fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div class="bg-white p-8 rounded-2xl max-w-md w-full mx-4">
        <h3 class="serif text-2xl mb-2">还差一点信息</h3>
        <p class="text-stone-600 mb-6">告诉我以下，我才能给你准的路线：</p>
        <div id="clarifying-form" class="space-y-4"></div>
        <button id="clarifying-submit" class="mt-6 px-6 py-2 bg-stone-800 text-white rounded-full">
          继续规划
        </button>
      </div>
    </div>

    <!-- Error toast -->
    <div id="error-toast" class="hidden fixed bottom-6 right-6 bg-red-50 border border-red-200 px-4 py-3 rounded-lg text-red-700 max-w-sm">
      <strong>出错了</strong>
      <p id="error-message" class="text-sm mt-1"></p>
    </div>
  </div>

  <script>
    const $ = (id) => document.getElementById(id);
    const SLOT_ICON = { "上午景点": "🌅", "午饭": "🍜", "下午": "☕", "下午茶": "🧁", "晚饭": "🍽️", "夜场": "🌙" };

    let pendingExtra = null;

    $("generate-btn").addEventListener("click", () => {
      const text = $("free-text").value.trim();
      if (!text) return;
      streamPlan(text, pendingExtra || {});
      pendingExtra = null;
    });

    async function streamPlan(freeText, extra) {
      // Reset UI
      ["reveal-section", "stage-profiler", "stage-candidates", "stage-compose"].forEach(id => $(id).classList.remove("hidden"));
      $("timeline-section").classList.add("hidden");
      $("timeline-days").innerHTML = "";
      $("understood-chips").innerHTML = "";
      $("candidate-cards").innerHTML = "";
      $("error-toast").classList.add("hidden");
      $("generate-btn").disabled = true;
      $("status-text").textContent = "连接中...";

      try {
        const resp = await fetch("/api/plan/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ free_text: freeText, extra }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        await consumeSSE(resp);
      } catch (err) {
        showError(err.message);
      } finally {
        $("generate-btn").disabled = false;
        $("status-text").textContent = "";
      }
    }

    async function consumeSSE(resp) {
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buffer.indexOf("\n\n")) >= 0) {
          const raw = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          const ev = parseEventBlock(raw);
          if (ev) handleEvent(ev);
        }
      }
    }

    function parseEventBlock(block) {
      let event = null;
      let data = null;
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) {
          try { data = JSON.parse(line.slice(6)); } catch { data = null; }
        }
      }
      return event ? { event, data } : null;
    }

    function handleEvent({ event, data }) {
      switch (event) {
        case "trip.started":
          $("status-text").textContent = `trip ${data.trip_id}`;
          break;
        case "profiler.start":
          $("profiler-status").textContent = "◐ 正在理解需求...";
          break;
        case "profiler.understood": {
          const chips = $("understood-chips");
          const items = [];
          if (data.city) items.push(`📍 ${data.city}`);
          if (data.days) items.push(`📅 ${data.days} 天`);
          if (data.traveler_type) items.push(`👥 ${data.traveler_type}`);
          if (data.budget_level) items.push(`💰 ${data.budget_level}`);
          (data.preferences || []).forEach(p => items.push(`✨ ${p}`));
          items.forEach((t, i) => {
            const el = document.createElement("span");
            el.className = "chip px-3 py-1 bg-amber-100 text-amber-900 rounded-full text-sm";
            el.style.animationDelay = `${i * 60}ms`;
            el.textContent = t;
            chips.appendChild(el);
          });
          $("profiler-status").textContent = "✓ 已理解";
          $("profiler-status").classList.remove("stage-pulse");
          break;
        }
        case "profiler.clarifying":
          showClarifying(data.missing_fields);
          break;
        case "profiler.ready":
          break;
        case "planner.start":
          $("candidates-status").textContent = "◐ 正在挑选 POI...";
          break;
        case "planner.anchors":
          $("candidates-status").textContent = `◐ 在 ${data.anchors.map(a => a.name).join(" / ")} 周边搜索...`;
          break;
        case "planner.candidates_loaded": {
          const wrap = $("candidate-cards");
          (data.preview || []).forEach((p, i) => {
            const el = document.createElement("div");
            el.className = "card-slide flex-shrink-0 w-40 p-3 bg-white border border-stone-200 rounded-lg shadow-sm";
            el.style.animationDelay = `${i * 100}ms`;
            el.innerHTML = `
              <div class="text-sm font-medium truncate">${p.name}</div>
              <div class="text-xs text-stone-500 mt-1">${(p.categories || []).join(" · ")}</div>
            `;
            wrap.appendChild(el);
          });
          $("candidates-status").textContent = `✓ 找到 ${data.count} 个候选 POI`;
          $("candidates-status").classList.remove("stage-pulse");
          break;
        }
        case "planner.clusters_ready":
          break;
        case "planner.compose_start":
          $("compose-status").textContent = "◐ 正在编排路线...";
          break;
        case "planner.day_done":
          renderDay(data);
          break;
        case "planner.done":
          $("compose-status").textContent = "✓ 编排完成";
          $("compose-status").classList.remove("stage-pulse");
          $("timeline-summary").textContent = data.summary || "";
          $("timeline-section").classList.remove("hidden");
          // Hide reveal stages, keep timeline
          setTimeout(() => $("reveal-section").classList.add("hidden"), 800);
          break;
        case "trip.complete":
          $("status-text").textContent = `done · ${data.duration_ms}ms`;
          break;
        case "error":
          showError(`${data.phase}: ${data.message}`);
          break;
      }
    }

    function renderDay(day) {
      // Avoid duplicates if day already rendered
      const existing = document.querySelector(`[data-day="${day.day_index}"]`);
      if (existing) existing.remove();

      const el = document.createElement("div");
      el.className = "day-card bg-white p-6 rounded-2xl border border-stone-200";
      el.dataset.day = day.day_index;
      const stops = (day.stops || []).map(s => `
        <div class="flex gap-4 py-3 border-l-2 border-amber-300 pl-5 relative">
          <span class="absolute -left-2 top-3 w-3 h-3 rounded-full bg-amber-400"></span>
          <div class="text-stone-400 text-sm w-16 flex-shrink-0">${s.arrival_time}</div>
          <div class="flex-1">
            <div class="font-medium">${SLOT_ICON[s.slot_name] || ""} ${s.slot_name} · ${s.poi_name}</div>
            <div class="text-xs text-stone-500 mt-1">
              ${(s.categories || []).join(" · ")} · ★${s.star} · ¥${s.avgprice}/人
            </div>
          </div>
        </div>
      `).join("");
      el.innerHTML = `
        <h3 class="serif text-2xl mb-3">Day ${day.day_index + 1} · ${day.anchor_district}</h3>
        <div>${stops}</div>
      `;
      $("timeline-days").appendChild(el);
    }

    function showClarifying(missingFields) {
      const form = $("clarifying-form");
      form.innerHTML = "";
      const labels = { days: "几天？", traveler_type: "和谁去？", city: "去哪个城市？" };
      const options = {
        days: [1, 2, 3, 4, 5, 7],
        traveler_type: ["情侣", "家庭亲子", "银发", "独行", "商务", "朋友团"],
        city: ["深圳", "上海", "西安"],
      };
      missingFields.forEach(field => {
        const block = document.createElement("div");
        block.innerHTML = `<label class="block text-sm font-medium mb-2">${labels[field] || field}</label>`;
        const opts = document.createElement("div");
        opts.className = "flex flex-wrap gap-2";
        (options[field] || []).forEach(opt => {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "px-4 py-2 border border-stone-300 rounded-full hover:bg-amber-100 transition-colors";
          btn.textContent = opt;
          btn.dataset.field = field;
          btn.dataset.value = opt;
          btn.addEventListener("click", () => {
            opts.querySelectorAll("button").forEach(b => b.classList.remove("bg-amber-200"));
            btn.classList.add("bg-amber-200");
          });
          opts.appendChild(btn);
        });
        block.appendChild(opts);
        form.appendChild(block);
      });
      $("clarifying-modal").classList.remove("hidden");

      $("clarifying-submit").onclick = () => {
        const extra = {};
        form.querySelectorAll("button.bg-amber-200").forEach(btn => {
          extra[btn.dataset.field] = btn.dataset.field === "days"
            ? parseInt(btn.dataset.value, 10)
            : btn.dataset.value;
        });
        $("clarifying-modal").classList.add("hidden");
        pendingExtra = extra;
        $("generate-btn").click();
      };
    }

    function showError(msg) {
      $("error-message").textContent = msg;
      $("error-toast").classList.remove("hidden");
      setTimeout(() => $("error-toast").classList.add("hidden"), 6000);
    }
  </script>
</body>
</html>
```

- [ ] **Step 2: Smoke check the file is well-formed**

```bash
python3 -c "
from pathlib import Path
content = Path('web/plan_stack.html').read_text(encoding='utf-8')
assert '<!DOCTYPE html>' in content
assert 'streamPlan' in content
assert '/api/plan/stream' in content
assert 'profiler.understood' in content
assert 'planner.day_done' in content
print('plan_stack.html structure OK')
print(f'size: {len(content)} chars')
"
```

Expected: prints "plan_stack.html structure OK".

- [ ] **Step 3: Commit**

```bash
git add web/plan_stack.html
git commit -m "feat(web): rewrite plan_stack.html for SSE streaming with reveal stages"
```

---

## Task 6: End-to-End Browser Smoke (Manual)

**Goal:** Confirm the whole stack runs in a real browser. This is a manual smoke — no automated test required for v1.

**Files:** No file changes; this is a verification step.

- [ ] **Step 1: Start mock_server (terminal 1)**

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
source venv/bin/activate
PYTHONPATH=. uvicorn dianping.mock_server:mock_app --host 127.0.0.1 --port 9192
```

Expected: see "Application startup complete" and "Uvicorn running on http://127.0.0.1:9192".

- [ ] **Step 2: Start main app (terminal 2)**

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
source venv/bin/activate
PYTHONPATH=. uvicorn api.main:app --host 127.0.0.1 --port 9191
```

Expected: see "Application startup complete" and "Uvicorn running on http://127.0.0.1:9191".

- [ ] **Step 3: Open browser**

Open `http://127.0.0.1:9191/` (or `http://127.0.0.1:9191/plan_stack.html`).

Expected:
- See "mtagent" header + Instrument Serif font
- Textarea + "生成路线" button visible

- [ ] **Step 4: Run a happy-path query**

In the textarea: `情侣 3 天深圳预算 3000 爱拍照`

Click "生成路线".

Expected sequence (visible to user):
1. Status text shows `trip xxxxx` then `连接中...`
2. Profiler stage: chips fly in (📍 深圳 · 📅 3 天 · 👥 情侣 · 💰 适中 · ✨ 拍照 · ✨ 打卡)
3. Candidate stage: 6 POI cards slide in from right with name + categories
4. Compose stage: "正在编排路线..." then "✓ 编排完成"
5. Reveal section fades, timeline appears with 3 day cards
6. Each day shows 4-5 stops with time + name + categories + star/price
7. Status text updates to `done · ~XXXms`

- [ ] **Step 5: Run a clarifying query**

Clear the textarea. Enter: `深圳`. Click "生成路线".

Expected:
1. Profiler chips: 📍 深圳 only
2. Modal pops: "还差一点信息" with 几天? 和谁去? buttons
3. Click options (e.g., 3 天 + 情侣) → "继续规划"
4. New stream starts, full happy path runs

- [ ] **Step 6: Run an error query (optional)**

Stop mock_server (Ctrl+C in terminal 1). In browser, retry "情侣 3 天深圳".

Expected: error toast appears with "planner: ..." or similar. Page stays usable.

Restart mock_server to recover.

- [ ] **Step 7: Verify all v0 + v1 tests still pass**

```bash
PYTHONPATH=. pytest tests/ -v 2>&1 | tail -10
```

Expected: ALL ~58 tests PASSED (v0 46 + v1 ~12).

- [ ] **Step 8: Final commit**

```bash
git status
git add -A
git commit -m "feat(mtagent): v1 SSE streaming + frontend integration COMPLETE

Acceptance per spec §9:
- /api/health returns 200 with version + dianping_base_url ✓
- /api/plan/stream emits full §5 event protocol (10+ events) ✓
- profiler.clarifying + early-close path works ✓
- error path emits error event + closes cleanly ✓
- Frontend plan_stack.html: input + 3-stage reveal + timeline ✓
- Manual browser e2e: happy path + clarifying flow verified ✓
- All v0 (46) + v1 (~12) tests pass ✓"
```

---

## Self-Review Notes

**Spec coverage check:**
- §2 Goal 1 (FastAPI + CORS + health) → Task 0 ✓
- §2 Goal 2 (SSE endpoint) → Task 3 ✓
- §2 Goal 3 (clarifying) → Task 3 + Task 4 ✓
- §2 Goal 4 (error stream) → Task 3 + Task 4 ✓
- §2 Goal 5 (CORS) → Task 0 ✓
- §2 Goal 6 (static mount) → Task 0 ✓
- §2 Goal 7 (frontend rewrite) → Task 5 ✓
- §2 Goal 8 (integration tests) → Tasks 3 + 4 ✓
- §5 SSE event protocol → Task 3 ✓ (every event listed in §5.2 emitted by routes.py)
- §6 frontend reveal stages → Task 5 ✓
- §7 error handling → Task 0 (CORS) + Task 3 (try/except in event_stream) ✓
- §9 acceptance criteria 11 items → all covered across Tasks 0/3/5/6 ✓

**Type consistency check:**
- `StreamRequest.extra: dict | None` defined in routes.py; clarifying test passes `extra={"days":2,"traveler_type":"情侣"}` ✓
- Event names from §5.2 match Task 3 implementation 1:1 ✓
- `format_event(name, data)` signature consistent across api/routes.py and api/sse.py ✓
- Frontend `handleEvent` switch covers all event names emitted by routes ✓

**Placeholder scan:**
- No "TBD", "TODO", "implement later" in plan
- All code blocks complete and runnable
- No "similar to Task N" — code repeated in full

**One known design compromise (documented):**
Task 3 duplicates ~30 lines of Planner.run internals to emit per-step events. v2 should refactor Planner to expose a callback/generator interface so the orchestrator can emit progress without duplication. Tracked as a known trade-off; not blocking v1.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-08-mtagent-v1-streaming.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks.

**2. Inline Execution** — Execute tasks in this session using executing-plans.

**Which approach?**
