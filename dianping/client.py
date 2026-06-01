"""Dianping HTTP client using httpx (async).

Default points to local mock_server; switch to real API by setting
MTAGENT_DIANPING_BASE_URL=https://poiopen.dianping.com env var (one-line switch).
"""

import json
import os
import time
from pathlib import Path
from typing import Optional

import httpx

from .auth import sign
from .schemas import POI, EnrichedLabel, PersonaLabels, SearchRecord


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
        self._labels_cache: dict[str, dict[str, dict]] = self._load_labels()
        # v1.7: enriched routing labels (poi_role / planning_tags / risk_tags / ...)
        self._enriched_cache: dict[str, dict[str, dict]] = self._load_enriched()

    @staticmethod
    def _load_labels() -> dict[str, dict[str, dict]]:
        """Load data/poi_labels.json. Empty dict if file missing (graceful degrade)."""
        path = Path("data/poi_labels.json")
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _load_enriched() -> dict[str, dict[str, dict]]:
        """Load data/poi_enriched_labels.json. Empty dict if file missing (graceful degrade).

        Structure: { city: { openshopid: enriched_label_dict } }
        """
        path = Path("data/poi_enriched_labels.json")
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _attach_labels(self, pois: list[POI], city: str) -> None:
        """Inject persona_labels + enriched into each POI matching openshopid (in-place).

        v1.7: 同时注入 EnrichedLabel (poi_role / planning_tags / city_zone / ...).
        Backward-compatible: missing labels stay None.
        """
        city_labels = self._labels_cache.get(city, {})
        city_enriched = self._enriched_cache.get(city, {})
        for poi in pois:
            label_dict = city_labels.get(poi.openshopid)
            if label_dict:
                poi.persona_labels = PersonaLabels(**label_dict)
            enriched_dict = city_enriched.get(poi.openshopid)
            if enriched_dict:
                poi.enriched = EnrichedLabel(**enriched_dict)

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
        poi = POI(**data["data"])
        if poi.city:
            self._attach_labels([poi], city=poi.city)
        return poi

    async def batch_get_poi(self, ids: list[str]) -> dict[str, POI]:
        data = await self._post(
            "/router/poi/batchgetpoi",
            {"multiopenshopid": ",".join(ids)},
        )
        pois = {k: POI(**v) for k, v in data["data"].items()}
        # Group by city (typically all from one city, but be defensive)
        by_city: dict[str, list[POI]] = {}
        for poi in pois.values():
            if poi.city:
                by_city.setdefault(poi.city, []).append(poi)
        for city, city_pois in by_city.items():
            self._attach_labels(city_pois, city=city)
        return pois

    async def close(self) -> None:
        await self._client.aclose()
