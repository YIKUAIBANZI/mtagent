"""FastAPI main app — entrypoint for v1 HTTP layer.

Run:
    uvicorn api.main:app --host 127.0.0.1 --port 9191

Companion process (must be running too):
    uvicorn dianping.mock_server:mock_app --host 127.0.0.1 --port 9192
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("MTAGENT_SKIP_DOTENV") != "1":
    load_dotenv(PROJECT_ROOT / ".env")

from api import deps
from dianping.client import DianpingClient

VERSION = "v1.0.0"
MTAGENTV2_DIR = PROJECT_ROOT / "mtagentv2"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create singleton DianpingClient on startup, close on shutdown.

    Cap concurrent connections so the dev mock_server (single uvicorn worker)
    isn't overwhelmed by ~27 parallel search requests.
    """
    client = DianpingClient()
    client._client = httpx.AsyncClient(
        timeout=10.0,
        limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
    )
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# v1.9 Stage 2: cookie_key 中间件 — 首访签 httponly cookie 'mtagent_cid' (设备级 ID)
@app.middleware("http")
async def ensure_cookie(request, call_next):
    from agents.user_profile_store import new_cookie_key

    cookie_key = request.cookies.get("mtagent_cid")
    set_new = False
    if not cookie_key:
        cookie_key = new_cookie_key()
        set_new = True
    request.state.cookie_key = cookie_key
    response = await call_next(request)
    if set_new:
        response.set_cookie(
            key="mtagent_cid",
            value=cookie_key,
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 365,  # 1 年
        )
    return response


@app.get("/", include_in_schema=False)
async def root():
    page = MTAGENTV2_DIR / "index.html"
    if not page.exists():
        raise HTTPException(404, "mtagentv2/index.html not found")
    return FileResponse(page)


@app.get("/map", include_in_schema=False)
async def map_view():
    """Compatibility route: the new main app owns map rendering inline."""
    return await root()


@app.get("/mtagentv2", include_in_schema=False)
async def mtagentv2_view():
    """Standalone Agent v2 prototype page."""
    page = MTAGENTV2_DIR / "index.html"
    if not page.exists():
        raise HTTPException(404, "mtagentv2/index.html not found")
    return FileResponse(page)


from api.routers import agent as _agent_router  # noqa: E402
from api.routers import config as _config_router  # noqa: E402
from api.routers import plan as _plan_router  # noqa: E402
from api.routers import trip as _trip_router  # noqa: E402
from api.routers import user as _user_router  # noqa: E402

app.include_router(_agent_router.router)
app.include_router(_config_router.router)
app.include_router(_plan_router.router)
app.include_router(_trip_router.router)
app.include_router(_user_router.router)


if MTAGENTV2_DIR.exists():
    app.mount(
        "/mtagentv2/assets",
        StaticFiles(directory=str(MTAGENTV2_DIR)),
        name="mtagentv2-assets",
    )
