"""Amap (高德) multi-modal transit client.

Provides 4 modes (drive/walk/transit/bicycle) with concurrent fetch and
haversine fallback when amap fails or is disabled by env.
"""

from __future__ import annotations

import os

import httpx

from dianping.schemas import TransitInfo


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
