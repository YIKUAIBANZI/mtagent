"""Mock server reproducing the Dianping POI Open Platform endpoints.

Loads data/mock_dianping/{深圳,上海,西安}.json into memory at startup.
Verifies request signature with the canonical algorithm.

Run standalone:
    uvicorn dianping.mock_server:mock_app --host 127.0.0.1 --port 9192
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

from .auth import sign


# Mock credentials. Real keys would come from env in production.
MOCK_APPKEY = "demo-appkey"
MOCK_SECRET = "demo-secret"

DATA_DIR = Path(os.environ.get("MTAGENT_MOCK_DATA_DIR", "data/mock_dianping"))


class MockState:
    pois_by_id: dict[str, dict] = {}
    pois_by_city: dict[str, list[dict]] = {}
    index: dict = {}


def _load_data() -> None:
    """Load all city JSONs into memory. Called from lifespan."""
    MockState.pois_by_id.clear()
    MockState.pois_by_city.clear()
    for city in ["深圳", "上海", "西安", "北京", "南昌"]:
        path = DATA_DIR / f"{city}.json"
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as f:
            pois = json.load(f)
        MockState.pois_by_city[city] = pois
        for p in pois:
            MockState.pois_by_id[p["openshopid"]] = p
    index_path = DATA_DIR / "index.json"
    if index_path.exists():
        with index_path.open(encoding="utf-8") as f:
            MockState.index = json.load(f)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_data()
    yield


mock_app = FastAPI(title="Dianping Mock Server", lifespan=lifespan)


def _verify_sign(params: dict) -> None:
    received = params.pop("sign", None)
    if received is None:
        raise HTTPException(401, "missing sign")
    expected = sign(params, MOCK_SECRET)
    if received != expected:
        raise HTTPException(401, "签名验证失败")
    if params.get("appkey") != MOCK_APPKEY:
        raise HTTPException(401, "appkey 错误")


def _haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    lat1_r, lat2_r = radians(lat1), radians(lat2)
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(dlng / 2) ** 2
    return 2 * r * asin(sqrt(a))


@mock_app.post("/router/city/opencity")
async def opencity(request: Request):
    body = await request.json()
    _verify_sign(body)
    return {
        "data": list(MockState.pois_by_city.keys()),
        "status": "success",
        "success": True,
    }


@mock_app.post("/router/poisearch/search")
async def search(request: Request):
    body = await request.json()
    _verify_sign(body)

    keyword = body.get("keyword", "") or ""
    city = body.get("city")
    lat = body.get("latitude")
    lng = body.get("longitude")
    radius = int(body.get("radius", 1000))
    categories_raw = body.get("categories", "") or ""
    page = max(1, int(body.get("page", 1)))
    limit = min(100, int(body.get("limit", 25)))
    mall = body.get("mall")

    # Choose pool by city, fallback to all
    if city and city in MockState.pois_by_city:
        candidates = list(MockState.pois_by_city[city])
    else:
        candidates = [p for ps in MockState.pois_by_city.values() for p in ps]

    if categories_raw:
        cats = {c.strip() for c in categories_raw.split(",") if c.strip()}
        candidates = [
            p for p in candidates if any(c in cats for c in p.get("categories", []))
        ]

    if mall == 1:
        candidates = [p for p in candidates if p.get("mallInfo")]

    if keyword:
        candidates = [p for p in candidates if keyword in p.get("name", "")]

    if lat is not None and lng is not None:
        try:
            lat_f, lng_f = float(lat), float(lng)
            candidates = [
                p
                for p in candidates
                if _haversine_meters(lat_f, lng_f, p["latitude"], p["longitude"])
                <= radius
            ]
        except (TypeError, ValueError):
            pass

    start = (page - 1) * limit
    page_records = candidates[start : start + limit]

    # Default permission: only return openshopid + name + branchname
    records = [
        {
            "openshopid": p["openshopid"],
            "name": p["name"],
            "branchname": p.get("branch_name", ""),
        }
        for p in page_records
    ]
    return {"records": records, "status": "OK", "total_count": len(candidates)}


@mock_app.post("/router/poi/getsinglepoi")
async def get_single_poi(request: Request):
    body = await request.json()
    _verify_sign(body)
    openshopid = body.get("openshopid")
    if not openshopid or openshopid not in MockState.pois_by_id:
        raise HTTPException(404, "POI not found")
    return {
        "data": MockState.pois_by_id[openshopid],
        "status": "success",
        "success": True,
    }


@mock_app.post("/router/poi/batchgetpoi")
async def batch_get_poi(request: Request):
    body = await request.json()
    _verify_sign(body)
    ids_str = body.get("multiopenshopid", "") or ""
    ids = [i.strip() for i in ids_str.split(",") if i.strip()]
    result = {i: MockState.pois_by_id[i] for i in ids if i in MockState.pois_by_id}
    return {"data": result, "status": "success", "success": True}
