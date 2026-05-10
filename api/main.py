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

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api import deps
from dianping.client import DianpingClient

VERSION = "v1.0.0"
WEB_DIR = Path(__file__).parent.parent / "web"


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


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "version": VERSION,
        "dianping_base_url": os.environ.get(
            "MTAGENT_DIANPING_BASE_URL", "http://127.0.0.1:9192"
        ),
        "llm_configured": bool(os.environ.get("DASHSCOPE_API_KEY")),
    }


@app.get("/api/config")
async def get_public_config():
    """Public config exposed to frontend (non-sensitive only).

    AMAP_WEB_JS_KEY is required for client-side JSAPI; it's restricted
    to whitelisted referrers in the Amap console as the security boundary.
    """
    return {
        "amap_web_js_key": os.environ.get("AMAP_WEB_JS_KEY", ""),
    }


@app.get("/", include_in_schema=False)
async def root():
    page = WEB_DIR / "plan_stack.html"
    if not page.exists():
        raise HTTPException(404, "plan_stack.html not found")
    return FileResponse(page)


from api import routes  # noqa: E402

app.include_router(routes.router)


if WEB_DIR.exists():
    app.mount("/web", StaticFiles(directory=str(WEB_DIR)), name="web")
