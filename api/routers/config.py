"""Public config + health endpoints (frontend bootstrap)."""

from __future__ import annotations

import os

from fastapi import APIRouter

VERSION = "v1.0.0"  # mirrors api/main.py VERSION

router = APIRouter()  # NO prefix — endpoints use literal /api paths


@router.get("/api/health")
async def health():
    return {
        "ok": True,
        "version": VERSION,
        "dianping_base_url": os.environ.get(
            "MTAGENT_DIANPING_BASE_URL", "http://127.0.0.1:9192"
        ),
        "llm_configured": bool(os.environ.get("DASHSCOPE_API_KEY")),
    }


@router.get("/api/config")
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
