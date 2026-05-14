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

    - AMAP_WEB_JS_KEY: JSAPI 加载用 key
    - AMAP_WEB_JS_SECURITY_CODE: 2021/12 后高德强制要求, 调路径规划等 webservice
      必须配, 否则 INVALID_USER_SCODE. 跟 web js key 在同一应用下生成.
    Both restricted to whitelisted referrers in Amap console.
    """
    return {
        "amap_web_js_key": os.environ.get("AMAP_WEB_JS_KEY", ""),
        "amap_web_js_security_code": os.environ.get("AMAP_WEB_JS_SECURITY_CODE", ""),
    }


@app.get("/", include_in_schema=False)
async def root():
    page = WEB_DIR / "plan_stack.html"
    if not page.exists():
        raise HTTPException(404, "plan_stack.html not found")
    return FileResponse(page)


@app.get("/map")
async def map_view():
    """Map view page — left floating panel + full-screen Amap JSAPI."""
    return FileResponse(WEB_DIR / "map.html")


from api import routes  # noqa: E402

app.include_router(routes.router)


if WEB_DIR.exists():
    app.mount("/web", StaticFiles(directory=str(WEB_DIR)), name="web")
