"""Dianping HTTP client using httpx (async).

Default points to local mock_server; switch to real API by setting
MTAGENT_DIANPING_BASE_URL=https://poiopen.dianping.com env var (one-line switch).
"""

import os
import time
from typing import Optional

import httpx

from .auth import sign
from .schemas import POI, SearchRecord


class DianpingAPIError(Exception):
    """Raised when an API call returns a non-success status."""


class DianpingClient:
    """Async client for Dianping POI Open Platform endpoints."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        appkey: Optional[str] = None,
        secret: Optional[str] = None,
        session: Optional[str] = None,
        timeout: float = 10.0,
    ):
        self.base_url = base_url or os.environ.get(
            "MTAGENT_DIANPING_BASE_URL", "http://127.0.0.1:9192"
        )
        self.appkey = appkey or os.environ.get("DIANPING_APPKEY", "demo-appkey")
        self.secret = secret or os.environ.get("DIANPING_SECRET", "demo-secret")
        self.session = session or os.environ.get("DIANPING_SESSION", "demo-session")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def _post(self, path: str, biz_params: Optional[dict] = None) -> dict:
        biz = biz_params or {}
        params: dict = {
            "appkey": self.appkey,
            "session": self.session,
            "timestamp": str(int(time.time() * 1000)),
        }
        for k, v in biz.items():
            if v is not None and v != "":
                params[k] = v
        params["sign"] = sign(params, self.secret)
        resp = await self._client.post(f"{self.base_url}{path}", json=params)
        try:
            data = resp.json()
        except Exception as exc:
            raise DianpingAPIError(f"Bad JSON response: {resp.text[:200]}") from exc
        # success can be at top level (success=True) or status="OK" / "success"
        success = data.get("success") or data.get("status") in ("success", "OK")
        if not success:
            raise DianpingAPIError(data.get("message") or f"API error: {data}")
        return data

    async def opencity(self) -> list[str]:
        data = await self._post("/router/city/opencity")
        return data.get("data", [])

    async def search(
        self,
        *,
        keyword: Optional[str] = None,
        city: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        radius: int = 1000,
        categories: Optional[str] = None,
        page: int = 1,
        limit: int = 25,
        mall: Optional[int] = None,
    ) -> list[SearchRecord]:
        biz = {
            "keyword": keyword,
            "city": city,
            "latitude": latitude,
            "longitude": longitude,
            "radius": radius,
            "categories": categories,
            "page": page,
            "limit": limit,
            "mall": mall,
        }
        data = await self._post("/router/poisearch/search", biz)
        records = data.get("records", [])
        return [SearchRecord(**r) for r in records]

    async def get_single_poi(self, openshopid: str) -> POI:
        data = await self._post("/router/poi/getsinglepoi", {"openshopid": openshopid})
        return POI(**data["data"])

    async def batch_get_poi(self, ids: list[str]) -> dict[str, POI]:
        data = await self._post(
            "/router/poi/batchgetpoi",
            {"multiopenshopid": ",".join(ids)},
        )
        return {k: POI(**v) for k, v in data["data"].items()}

    async def close(self) -> None:
        await self._client.aclose()
