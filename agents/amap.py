"""Amap (高德) multi-modal transit client.

Provides 4 modes (drive/walk/transit/bicycle) with concurrent fetch and
haversine fallback when amap fails or is disabled by env.
"""

from __future__ import annotations

import asyncio
import math
import os
from typing import Optional

import httpx

from dianping.schemas import TransitInfo


_RECOMMENDED_MODE = {
    "情侣": "transit",
    "家庭亲子": "drive",
    "银发": "drive",
    "独行": "walk",
    "商务": "drive",
    "朋友团": "transit",
}


class AmapClient:
    def __init__(
        self,
        key: str,
        base_url: str = "https://restapi.amap.com",
        timeout: float = 5.0,
    ):
        self.key = key
        self.base_url = base_url
        self._client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_connections=8),
        )
        self.disabled = bool(os.environ.get("MTAGENT_AMAP_DISABLED"))

    async def _driving(
        self,
        origin: tuple[float, float],
        dest: tuple[float, float],
    ) -> TransitInfo:
        """高德 v3 driving endpoint."""
        params = {
            "key": self.key,
            "origin": f"{origin[0]:.6f},{origin[1]:.6f}",
            "destination": f"{dest[0]:.6f},{dest[1]:.6f}",
            "strategy": 0,
            "extensions": "base",
        }
        resp = await self._client.get(
            f"{self.base_url}/v3/direction/driving",
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "1":
            raise RuntimeError(
                f"amap driving status={data.get('status')} info={data.get('info')}"
            )
        path = data["route"]["paths"][0]
        return TransitInfo(
            mode="drive",
            minutes=int(int(path["duration"]) / 60),
            distance_km=int(path["distance"]) / 1000,
            price_yuan=float(path.get("taxi_cost") or 0) or None,
            source="amap",
        )

    async def _walking(
        self,
        origin: tuple[float, float],
        dest: tuple[float, float],
    ) -> TransitInfo:
        params = {
            "key": self.key,
            "origin": f"{origin[0]:.6f},{origin[1]:.6f}",
            "destination": f"{dest[0]:.6f},{dest[1]:.6f}",
        }
        resp = await self._client.get(
            f"{self.base_url}/v3/direction/walking", params=params
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "1":
            raise RuntimeError(f"amap walking status={data.get('status')}")
        path = data["route"]["paths"][0]
        return TransitInfo(
            mode="walk",
            minutes=int(int(path["duration"]) / 60),
            distance_km=int(path["distance"]) / 1000,
            price_yuan=None,
            source="amap",
        )

    async def _transit(
        self,
        origin: tuple[float, float],
        dest: tuple[float, float],
        city: str = "",
    ) -> TransitInfo:
        params = {
            "key": self.key,
            "origin": f"{origin[0]:.6f},{origin[1]:.6f}",
            "destination": f"{dest[0]:.6f},{dest[1]:.6f}",
            "city": city,
            "city1": city,
        }
        resp = await self._client.get(
            f"{self.base_url}/v3/direction/transit/integrated", params=params
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "1":
            raise RuntimeError(f"amap transit status={data.get('status')}")
        transits = data.get("route", {}).get("transits", [])
        if not transits:
            raise RuntimeError("amap transit returned no route")
        t = transits[0]
        return TransitInfo(
            mode="transit",
            minutes=int(int(t["duration"]) / 60),
            distance_km=int(t["distance"]) / 1000,
            price_yuan=float(t.get("cost") or 0) or None,
            source="amap",
        )

    async def _bicycling(
        self,
        origin: tuple[float, float],
        dest: tuple[float, float],
    ) -> TransitInfo:
        params = {
            "key": self.key,
            "origin": f"{origin[0]:.6f},{origin[1]:.6f}",
            "destination": f"{dest[0]:.6f},{dest[1]:.6f}",
        }
        resp = await self._client.get(
            f"{self.base_url}/v4/direction/bicycling", params=params
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode") != 0:
            raise RuntimeError(f"amap bicycling errcode={data.get('errcode')}")
        path = data["data"]["paths"][0]
        minutes = int(int(path["duration"]) / 60)
        return TransitInfo(
            mode="bicycle",
            minutes=minutes,
            distance_km=int(path["distance"]) / 1000,
            price_yuan=self._estimate_bicycle_price(minutes),
            source="amap",
        )

    @staticmethod
    def _estimate_bicycle_price(minutes: int) -> Optional[float]:
        """共享单车 1.5¥/30min + 0.5¥/10min."""
        if minutes <= 30:
            return 1.5
        return 1.5 + 0.5 * ((minutes - 30 + 9) // 10)

    @staticmethod
    def _haversine_km(o: tuple[float, float], d: tuple[float, float]) -> float:
        """great-circle distance in km, lng-lat input."""
        lng1, lat1 = math.radians(o[0]), math.radians(o[1])
        lng2, lat2 = math.radians(d[0]), math.radians(d[1])
        dl = lng2 - lng1
        dp = lat2 - lat1
        a = (
            math.sin(dp / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(dl / 2) ** 2
        )
        return 6371 * 2 * math.asin(math.sqrt(a))

    _SPEED_KMH = {"drive": 30, "walk": 5, "transit": 20, "bicycle": 15}

    def _haversine_one(
        self,
        mode: str,
        o: tuple[float, float],
        d: tuple[float, float],
    ) -> TransitInfo:
        km = self._haversine_km(o, d) * 1.4  # detour factor
        speed = self._SPEED_KMH.get(mode, 20)
        minutes = max(1, int(km / speed * 60))
        if mode == "drive":
            price: Optional[float] = 11 + 2.4 * max(0.0, km - 3)
        elif mode == "transit":
            price = 2.0 if km < 6 else 4.0 if km < 15 else 6.0
        elif mode == "bicycle":
            price = self._estimate_bicycle_price(minutes)
        else:
            price = None
        return TransitInfo(
            mode=mode,
            minutes=minutes,
            distance_km=round(km, 2),
            price_yuan=round(price, 2) if price is not None else None,
            source="estimated",
        )

    def _haversine_all(
        self,
        o: tuple[float, float],
        d: tuple[float, float],
    ) -> dict[str, TransitInfo]:
        return {
            m: self._haversine_one(m, o, d)
            for m in ["drive", "walk", "transit", "bicycle"]
        }

    async def get_transit_options(
        self,
        origin: tuple[float, float],
        dest: tuple[float, float],
        city: str = "",
        traveler_type: Optional[str] = None,
    ) -> tuple[dict[str, TransitInfo], str]:
        """Concurrent 4-mode fetch. Returns (options, recommended_mode).

        Falls back to haversine estimates per-mode on exception, or all
        modes if MTAGENT_AMAP_DISABLED is set.
        """
        if self.disabled:
            options = self._haversine_all(origin, dest)
        else:
            results = await asyncio.gather(
                self._driving(origin, dest),
                self._walking(origin, dest),
                self._transit(origin, dest, city=city),
                self._bicycling(origin, dest),
                return_exceptions=True,
            )
            modes = ["drive", "walk", "transit", "bicycle"]
            options = {}
            for mode, r in zip(modes, results):
                if isinstance(r, Exception):
                    options[mode] = self._haversine_one(mode, origin, dest)
                else:
                    options[mode] = r
        recommended = _RECOMMENDED_MODE.get(traveler_type or "", "transit")
        return options, recommended
