# mtagent v2 高德 API 多模态路径 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 mtagent 接入高德 4 模式（驾车/步行/公交+地铁/骑行）路径 API，每个 stop pair 异步并发拿真实通勤时间和价格，前端 chip selector 让用户切换最优模式，并把 transit 数据反哺 v1.5 rationale 形成「全程地铁 92 分钟，比打车省 ¥80」这种带硬数字的决策理由。

**Architecture:** 新增 `agents/amap.py` 异步 client（4 个 endpoint 并发 + haversine 兜底）；`dianping/schemas.Stop` 加 `Optional[dict] transport_options` 字段向后兼容；`api/routes.py` 在所有 day_done 完成后并发触发 amap，via `asyncio.as_completed` 流式 yield `transit.updated` 事件；前端 `web/plan_stack.html` 在每对 stop 间渲染 4 chip，点击切换 mode 重算当日总通勤时长并联动 rationale 文案。

**Tech Stack:** Python 3.11 + httpx async + pytest（既有），无新依赖。前端 vanilla JS + Tailwind CDN（既有）。

**Spec reference:** `docs/superpowers/specs/2026-05-09-mtagent-v2-amap-multimodal-design.md`

**Prerequisites:**
- v1.5 全套 ship + 真 qwen3.6-plus 配置 ship（commit `e37287c` on main）
- 工作目录：`/Users/yikuaibanz1/Desktop/sth/mtagent`
- 当前在 `feat/v2-amap-multimodal` 分支
- `.env` 已有 `AMAP_KEY=51744eaf...`
- venv 激活：`source venv/bin/activate`
- 测试基线：`PYTHONPATH=. pytest tests/ -v` 应 77 全过

---

## File Structure (v2 改动)

```
mtagent/
├── agents/
│   └── amap.py                         # NEW: 4 模式 client + haversine fallback
├── api/
│   └── routes.py                       # MODIFIED: 接 amap 并 yield transit.updated 事件
├── agents/
│   └── rationale.py                    # MODIFIED: build_rationale_for_day 接收 transit_summary
├── dianping/
│   └── schemas.py                      # MODIFIED: Stop 加 transport_options 字段 + TransitInfo 新类
├── web/
│   └── plan_stack.html                 # MODIFIED: chip selector + 状态 Map + rationale 联动
└── tests/
    ├── test_amap_client.py             # NEW: 4 模式 client 单测
    ├── test_amap_fallback.py           # NEW: haversine + env 开关
    ├── test_sse_transit.py             # NEW: SSE 协议
    ├── test_rationale.py               # MODIFIED: +3 case transit_summary
    └── test_schemas_stop_transit.py    # NEW: Stop schema 反序列化兼容
```

**不动：** Planner、Profiler、Critic、agents/tools.py、agents/mapper.py（mapper 是静态图工具与 v2 共存）。

---

## Task 1: schemas.Stop 加 TransitInfo + transport_options 字段（TDD）

**Goal:** 加 `TransitInfo` 模型和 `Stop.transport_options` 字段，确保旧 trip JSON 反序列化照常。

**Files:**
- Modify: `dianping/schemas.py`
- Create: `tests/test_schemas_stop_transit.py`

- [ ] **Step 1: 写 failing 反序列化兼容测试**

Create `tests/test_schemas_stop_transit.py`:

```python
"""Test backward-compat for Stop with new transport_options field."""

from dianping.schemas import Stop, POI, TimeSlot
import datetime as _dt


def _stop_kwargs():
    poi = POI(
        openshopid="id1", name="钟楼", city="西安",
        latitude=34.26, longitude=108.94,
    )
    slot = TimeSlot(name="上午景点", start=_dt.time(9, 0), end=_dt.time(12, 0))
    return dict(
        poi=poi, slot=slot,
        arrival_time=_dt.time(9, 0), leave_time=_dt.time(12, 0),
    )


def test_stop_without_transport_options_loads():
    """Old Stop dict (pre-v2) should deserialize with transport_options=None."""
    s = Stop(**_stop_kwargs())
    assert s.transport_options is None
    assert s.transport_to_next_minutes == 30


def test_stop_with_transport_options_loads():
    s = Stop(
        **_stop_kwargs(),
        transport_options={
            "drive": {"mode": "drive", "minutes": 8, "distance_km": 4.2,
                      "price_yuan": 15.0, "source": "amap"},
            "walk":  {"mode": "walk",  "minutes": 28, "distance_km": 2.1,
                      "price_yuan": None, "source": "amap"},
        },
    )
    assert s.transport_options is not None
    assert s.transport_options["drive"].minutes == 8
    assert s.transport_options["walk"].price_yuan is None


def test_transit_info_source_validates():
    """TransitInfo.source must be one of 'amap' / 'estimated'."""
    import pytest
    from pydantic import ValidationError
    from dianping.schemas import TransitInfo

    with pytest.raises(ValidationError):
        TransitInfo(mode="drive", minutes=5, distance_km=1.0, source="invalid")
```

- [ ] **Step 2: 运行确认 fail**

```bash
source venv/bin/activate && PYTHONPATH=. pytest tests/test_schemas_stop_transit.py -v
```
Expected: ImportError on `TransitInfo`

- [ ] **Step 3: 改 `dianping/schemas.py` 加 TransitInfo + Stop 字段**

In `dianping/schemas.py`, before `class Stop`:

```python
TransitMode = Literal["drive", "walk", "transit", "bicycle"]
TransitSource = Literal["amap", "estimated"]


class TransitInfo(BaseModel):
    """Per-mode transit details for one stop pair."""
    mode: TransitMode
    minutes: int
    distance_km: float
    price_yuan: Optional[float] = None
    source: TransitSource
```

Then in `class Stop`, add a new field after `transport_to_next_minutes`:

```python
class Stop(BaseModel):
    poi: POI
    slot: TimeSlot
    arrival_time: time
    leave_time: time
    transport_to_next_minutes: int = 30
    transport_options: Optional[dict[str, TransitInfo]] = None  # NEW
```

- [ ] **Step 4: 跑测试确认 PASS**

```bash
PYTHONPATH=. pytest tests/test_schemas_stop_transit.py -v
```
Expected: 3 PASS

- [ ] **Step 5: 全量回归**

```bash
PYTHONPATH=. pytest tests/ -v 2>&1 | tail -3
```
Expected: 77 + 3 = 80 PASS

- [ ] **Step 6: Commit**

```bash
git add dianping/schemas.py tests/test_schemas_stop_transit.py && git commit -m "feat(v2): add TransitInfo schema + Stop.transport_options field

Optional dict field; defaults None so legacy trip JSONs deserialize cleanly.
TransitInfo carries per-mode minutes/distance/price plus source attribution
(amap | estimated)."
```

---

## Task 2: amap client 骨架 + driving endpoint（TDD）

**Goal:** 写 `agents/amap.py` 骨架（AmapClient 类 + driving endpoint 解析）。先只跑通 driving，其他 mode 在 Task 3。

**Files:**
- Create: `agents/amap.py`
- Create: `tests/test_amap_client.py`

- [ ] **Step 1: 写 failing driving 测试（用 MockTransport）**

Create `tests/test_amap_client.py`:

```python
"""Unit tests for agents/amap.py."""

import json
import os

import httpx
import pytest

from agents.amap import AmapClient


def _make_client(handler) -> AmapClient:
    transport = httpx.MockTransport(handler)
    c = AmapClient(key="test-key", base_url="https://restapi.amap.com")
    c._client = httpx.AsyncClient(transport=transport, timeout=5.0)
    return c


@pytest.mark.asyncio
async def test_driving_parses_amap_response():
    """driving endpoint returns minutes/distance from amap response shape."""

    def handler(request):
        assert "/v3/direction/driving" in request.url.path
        assert "key=test-key" in str(request.url)
        return httpx.Response(
            200,
            json={
                "status": "1",
                "info": "OK",
                "route": {
                    "paths": [
                        {
                            "duration": "480",   # 480s = 8min
                            "distance": "4200",  # 4200m = 4.2km
                            "tolls": "0",
                            "taxi_cost": "15.0",
                        }
                    ]
                },
            },
        )

    c = _make_client(handler)
    info = await c._driving((108.94, 34.26), (108.96, 34.22))

    assert info.mode == "drive"
    assert info.minutes == 8
    assert info.distance_km == pytest.approx(4.2, abs=0.01)
    assert info.price_yuan == 15.0
    assert info.source == "amap"
```

- [ ] **Step 2: 运行确认 fail**

```bash
PYTHONPATH=. pytest tests/test_amap_client.py::test_driving_parses_amap_response -v
```
Expected: ImportError on `AmapClient`

- [ ] **Step 3: 写最小 AmapClient + _driving**

Create `agents/amap.py`:

```python
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
            raise RuntimeError(f"amap driving status={data.get('status')} info={data.get('info')}")
        path = data["route"]["paths"][0]
        return TransitInfo(
            mode="drive",
            minutes=int(int(path["duration"]) / 60),
            distance_km=int(path["distance"]) / 1000,
            price_yuan=float(path.get("taxi_cost") or 0) or None,
            source="amap",
        )
```

- [ ] **Step 4: 跑测试**

```bash
PYTHONPATH=. pytest tests/test_amap_client.py::test_driving_parses_amap_response -v
```
Expected: PASS

- [ ] **Step 5: 跑全量**

```bash
PYTHONPATH=. pytest tests/ 2>&1 | tail -3
```
Expected: 81 PASS（80 + 1）

---

## Task 3: walk / transit / bicycle 三个 endpoint（TDD）

**Goal:** 加剩余 3 个 endpoint 实现。

**Files:**
- Modify: `agents/amap.py`
- Modify: `tests/test_amap_client.py`

- [ ] **Step 1: 写 failing 3 个测试**

Append to `tests/test_amap_client.py`:

```python
@pytest.mark.asyncio
async def test_walking_parses_amap_response():
    def handler(request):
        assert "/v3/direction/walking" in request.url.path
        return httpx.Response(200, json={
            "status": "1", "info": "OK",
            "route": {"paths": [{"duration": "1680", "distance": "2100"}]},
        })

    c = _make_client(handler)
    info = await c._walking((108.94, 34.26), (108.96, 34.22))
    assert info.mode == "walk"
    assert info.minutes == 28
    assert info.distance_km == pytest.approx(2.1, abs=0.01)
    assert info.price_yuan is None
    assert info.source == "amap"


@pytest.mark.asyncio
async def test_transit_parses_amap_response():
    def handler(request):
        assert "/v3/direction/transit/integrated" in request.url.path
        assert "city=" in str(request.url)
        return httpx.Response(200, json={
            "status": "1", "info": "OK",
            "route": {"transits": [{
                "duration": "720",  # 12min
                "distance": "4000",
                "cost": "4.0",
            }]},
        })

    c = _make_client(handler)
    info = await c._transit((108.94, 34.26), (108.96, 34.22), city="西安")
    assert info.mode == "transit"
    assert info.minutes == 12
    assert info.distance_km == pytest.approx(4.0, abs=0.01)
    assert info.price_yuan == 4.0
    assert info.source == "amap"


@pytest.mark.asyncio
async def test_bicycling_parses_amap_response():
    def handler(request):
        assert "/v4/direction/bicycling" in request.url.path
        return httpx.Response(200, json={
            "errcode": 0,
            "data": {"paths": [{"duration": "1080", "distance": "4000"}]},
        })

    c = _make_client(handler)
    info = await c._bicycling((108.94, 34.26), (108.96, 34.22))
    assert info.mode == "bicycle"
    assert info.minutes == 18
    assert info.distance_km == pytest.approx(4.0, abs=0.01)
    assert info.source == "amap"
```

- [ ] **Step 2: 实现 3 个方法**

Append to `agents/amap.py` after `_driving`:

```python
    async def _walking(self, origin, dest) -> TransitInfo:
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

    async def _transit(self, origin, dest, city: str = "") -> TransitInfo:
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

    async def _bicycling(self, origin, dest) -> TransitInfo:
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
        return TransitInfo(
            mode="bicycle",
            minutes=int(int(path["duration"]) / 60),
            distance_km=int(path["distance"]) / 1000,
            price_yuan=self._estimate_bicycle_price(int(path["duration"]) / 60),
            source="amap",
        )

    @staticmethod
    def _estimate_bicycle_price(minutes: int) -> Optional[float]:
        """共享单车 1.5¥/30min + 0.5¥/10min."""
        if minutes <= 30:
            return 1.5
        return 1.5 + 0.5 * ((minutes - 30 + 9) // 10)
```

- [ ] **Step 3: 跑测试**

```bash
PYTHONPATH=. pytest tests/test_amap_client.py -v
```
Expected: 4 PASS

---

## Task 4: get_transit_options 并发 + recommended mode（TDD）

**Goal:** 公开方法 `get_transit_options` 并发 4 mode 调用 + traveler_type 推荐。

**Files:**
- Modify: `agents/amap.py`
- Modify: `tests/test_amap_client.py`

- [ ] **Step 1: 写 failing 测试**

Append to `tests/test_amap_client.py`:

```python
@pytest.mark.asyncio
async def test_get_transit_options_returns_all_4_modes():
    """All 4 modes returned via single call."""
    def handler(request):
        path = request.url.path
        if "driving" in path:
            return httpx.Response(200, json={
                "status": "1",
                "route": {"paths": [{"duration": "480", "distance": "4200", "taxi_cost": "15"}]},
            })
        if "walking" in path:
            return httpx.Response(200, json={
                "status": "1",
                "route": {"paths": [{"duration": "1680", "distance": "2100"}]},
            })
        if "transit/integrated" in path:
            return httpx.Response(200, json={
                "status": "1",
                "route": {"transits": [{"duration": "720", "distance": "4000", "cost": "4"}]},
            })
        if "bicycling" in path:
            return httpx.Response(200, json={
                "errcode": 0,
                "data": {"paths": [{"duration": "1080", "distance": "4000"}]},
            })
        return httpx.Response(404, json={})

    c = _make_client(handler)
    options, recommended = await c.get_transit_options(
        (108.94, 34.26), (108.96, 34.22), city="西安", traveler_type="家庭亲子",
    )
    assert set(options.keys()) == {"drive", "walk", "transit", "bicycle"}
    assert options["drive"].minutes == 8
    assert options["transit"].price_yuan == 4
    assert recommended == "drive"  # 家庭亲子推荐 drive
```

- [ ] **Step 2: 实现公共方法**

Append to `agents/amap.py`:

```python
_RECOMMENDED_MODE = {
    "情侣": "transit",
    "家庭亲子": "drive",
    "银发": "drive",
    "独行": "walk",
    "商务": "drive",
    "朋友团": "transit",
}


class AmapClient:
    # ... 既有方法 ...

    async def get_transit_options(
        self,
        origin: tuple[float, float],
        dest: tuple[float, float],
        city: str = "",
        traveler_type: Optional[str] = None,
    ) -> tuple[dict[str, TransitInfo], str]:
        """Concurrent 4-mode fetch. Returns (options, recommended_mode)."""
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
```

注：`_haversine_all` / `_haversine_one` 在 Task 5 实现。Task 4 测试不依赖它们（mock 全成功）。临时桩函数：

```python
    def _haversine_all(self, o, d):
        return {"drive": self._haversine_one("drive", o, d),
                "walk": self._haversine_one("walk", o, d),
                "transit": self._haversine_one("transit", o, d),
                "bicycle": self._haversine_one("bicycle", o, d)}

    def _haversine_one(self, mode, o, d):
        # placeholder, real impl in Task 5
        return TransitInfo(mode=mode, minutes=0, distance_km=0, source="estimated")
```

- [ ] **Step 3: 跑测试**

```bash
PYTHONPATH=. pytest tests/test_amap_client.py -v
```
Expected: 5 PASS

---

## Task 5: haversine fallback + env 开关（TDD）

**Goal:** 实现真 haversine fallback，让任一 mode 失败或全 disabled 时仍能给合理估算。

**Files:**
- Modify: `agents/amap.py`
- Create: `tests/test_amap_fallback.py`

- [ ] **Step 1: 写 failing 测试**

Create `tests/test_amap_fallback.py`:

```python
"""Tests for haversine fallback + env disabled switch."""

import os
import pytest

from agents.amap import AmapClient
from dianping.schemas import TransitInfo


def test_haversine_drive_returns_reasonable_estimate():
    c = AmapClient(key="x")
    info = c._haversine_one("drive", (108.94, 34.26), (108.96, 34.22))
    assert info.mode == "drive"
    assert info.source == "estimated"
    assert info.distance_km > 0
    assert 0 < info.minutes < 120
    assert info.price_yuan is not None and info.price_yuan > 0


def test_haversine_walk_no_price():
    c = AmapClient(key="x")
    info = c._haversine_one("walk", (108.94, 34.26), (108.96, 34.22))
    assert info.mode == "walk"
    assert info.source == "estimated"
    assert info.price_yuan is None


def test_haversine_speeds_drive_faster_than_walk():
    """Drive should yield fewer minutes than walk for same OD."""
    c = AmapClient(key="x")
    drive = c._haversine_one("drive", (108.94, 34.26), (108.96, 34.22))
    walk = c._haversine_one("walk", (108.94, 34.26), (108.96, 34.22))
    assert drive.minutes < walk.minutes


@pytest.mark.asyncio
async def test_disabled_env_skips_amap_calls(monkeypatch):
    monkeypatch.setenv("MTAGENT_AMAP_DISABLED", "1")
    c = AmapClient(key="x")
    options, _ = await c.get_transit_options(
        (108.94, 34.26), (108.96, 34.22), city="西安",
    )
    assert all(v.source == "estimated" for v in options.values())
```

- [ ] **Step 2: 替换 placeholder _haversine_one 为真实现**

In `agents/amap.py`, replace the placeholder:

```python
    @staticmethod
    def _haversine_km(o: tuple[float, float], d: tuple[float, float]) -> float:
        """great-circle distance in km, lng-lat input."""
        lng1, lat1 = math.radians(o[0]), math.radians(o[1])
        lng2, lat2 = math.radians(d[0]), math.radians(d[1])
        dl = lng2 - lng1
        dp = lat2 - lat1
        a = math.sin(dp / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dl / 2) ** 2
        return 6371 * 2 * math.asin(math.sqrt(a))

    _SPEED_KMH = {"drive": 30, "walk": 5, "transit": 20, "bicycle": 15}

    def _haversine_one(self, mode: str, o, d) -> TransitInfo:
        km = self._haversine_km(o, d) * 1.4  # detour factor
        speed = self._SPEED_KMH.get(mode, 20)
        minutes = max(1, int(km / speed * 60))
        if mode == "drive":
            price = 11 + 2.4 * max(0, km - 3)
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

    def _haversine_all(self, o, d) -> dict[str, TransitInfo]:
        return {m: self._haversine_one(m, o, d) for m in ["drive", "walk", "transit", "bicycle"]}
```

- [ ] **Step 3: 跑测试**

```bash
PYTHONPATH=. pytest tests/test_amap_fallback.py -v
```
Expected: 4 PASS

- [ ] **Step 4: Commit Task 1-5**

```bash
PYTHONPATH=. pytest tests/ 2>&1 | tail -3   # baseline check
git add agents/amap.py tests/test_amap_client.py tests/test_amap_fallback.py && \
  git commit -m "feat(v2): amap 4-mode transit client with haversine fallback

- AmapClient driving/walking/transit/bicycling endpoints
- get_transit_options concurrent fetch + traveler_type recommended mode
- haversine 1.4x detour fallback when amap fails or MTAGENT_AMAP_DISABLED set
- 9 unit tests"
```

---

## Task 6: routes.py 集成 amap + transit.updated SSE 事件（TDD）

**Goal:** 在 routes.py 主流的 day_done + rationale 之后并发触发 amap，via as_completed 流式 yield 每天的 `transit.updated`。测试默认 `MTAGENT_AMAP_DISABLED=1` 走 haversine。

**Files:**
- Modify: `api/routes.py`
- Create: `tests/test_sse_transit.py`
- Modify: `tests/conftest.py`（让 sse_app_client 默认 set MTAGENT_AMAP_DISABLED=1）

- [ ] **Step 1: 改 conftest 让测试默认 disable amap**

Edit `tests/conftest.py`. Find:

```python
    os.environ.pop("DASHSCOPE_API_KEY", None)
    os.environ["MTAGENT_TRIPS_DIR"] = str(tmp_path_factory.mktemp("trips"))
```

Append:

```python
    os.environ["MTAGENT_AMAP_DISABLED"] = "1"  # tests use haversine fallback
```

- [ ] **Step 2: 写 failing transit SSE 测试**

Create `tests/test_sse_transit.py`:

```python
"""SSE protocol tests for v2 transit.updated events."""

import json


def _parse_events(raw: str) -> list[dict]:
    out = []
    for block in raw.strip().split("\n\n"):
        ev = data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                ev = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if ev:
            out.append({"event": ev, "data": data})
    return out


def test_one_transit_updated_per_day(sse_app_client):
    resp = sse_app_client.post(
        "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳预算 3000 爱拍照"},
    )
    assert resp.status_code == 200
    events = _parse_events(resp.text)
    transits = [e for e in events if e["event"] == "transit.updated"]
    day_dones = [e for e in events if e["event"] == "planner.day_done"]

    assert len(transits) == len(day_dones)
    transit_days = sorted(t["data"]["day_index"] for t in transits)
    day_done_days = sorted(d["data"]["day_index"] for d in day_dones)
    assert transit_days == day_done_days


def test_transit_segments_have_4_modes_each(sse_app_client):
    resp = sse_app_client.post(
        "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳预算 3000 爱拍照"},
    )
    events = _parse_events(resp.text)
    for t in (e for e in events if e["event"] == "transit.updated"):
        for seg in t["data"]["segments"]:
            assert set(seg["options"].keys()) == {"drive", "walk", "transit", "bicycle"}
            assert seg["recommended"] in {"drive", "walk", "transit", "bicycle"}


def test_transit_segments_count_equals_stops_minus_one(sse_app_client):
    resp = sse_app_client.post(
        "/api/plan/stream",
        json={"free_text": "情侣 3 天深圳预算 3000 爱拍照"},
    )
    events = _parse_events(resp.text)
    day_done_by_idx = {
        e["data"]["day_index"]: e for e in events if e["event"] == "planner.day_done"
    }
    for t in (e for e in events if e["event"] == "transit.updated"):
        di = t["data"]["day_index"]
        n_stops = len(day_done_by_idx[di]["data"]["stops"])
        assert len(t["data"]["segments"]) == max(0, n_stops - 1)
```

- [ ] **Step 3: 运行确认 fail**

```bash
PYTHONPATH=. pytest tests/test_sse_transit.py -v
```
Expected: assertion error — no transit.updated events yet

- [ ] **Step 4: 改 `api/routes.py` 接 amap**

Find in `api/routes.py` the loop:

```python
            for d in days_out:
                yield format_event("planner.day_done", ...)
                yield format_event("planner.rationale", build_rationale_for_day(...))
```

After this loop（在 `route = RouteDraft(...)` 之前），加：

```python
            # ----- v2: amap transit options for each day -----
            from agents.amap import AmapClient

            amap = AmapClient(key=os.environ.get("AMAP_KEY", ""))
            try:
                transit_tasks = [
                    _compute_day_transits(d, intent, amap) for d in days_out
                ]
                for coro in asyncio.as_completed(transit_tasks):
                    day_index, segments = await coro
                    yield format_event(
                        "transit.updated",
                        {"day_index": day_index, "segments": segments},
                    )
            finally:
                await amap._client.aclose()
```

并 import `os` 顶部（如未 import）。

Then add a helper at module end:

```python
async def _compute_day_transits(day_plan, intent, amap):
    """Compute 4-mode transit for each consecutive stop pair in a day."""
    segments = []
    stops = day_plan.stops
    for i in range(len(stops) - 1):
        a = stops[i].poi
        b = stops[i + 1].poi
        options, recommended = await amap.get_transit_options(
            origin=(a.longitude, a.latitude),
            dest=(b.longitude, b.latitude),
            city=intent.city or "",
            traveler_type=intent.traveler_type,
        )
        segments.append({
            "from_index": i,
            "to_index": i + 1,
            "options": {m: v.model_dump(mode="json") for m, v in options.items()},
            "recommended": recommended,
        })
    return day_plan.day_index, segments
```

- [ ] **Step 5: 跑测试 + 全量回归**

```bash
PYTHONPATH=. pytest tests/test_sse_transit.py -v
PYTHONPATH=. pytest tests/ 2>&1 | tail -3
```
Expected: 3 transit + 全量 80 + 9 amap + 3 transit = **92 PASS**

- [ ] **Step 6: Commit**

```bash
git add api/routes.py tests/conftest.py tests/test_sse_transit.py && \
  git commit -m "feat(v2): emit transit.updated SSE events with 4-mode options per day

After all day_done events, run amap.get_transit_options concurrently for
each day's stop pairs via asyncio.as_completed. Test fixture sets
MTAGENT_AMAP_DISABLED=1 so unit tests use haversine fallback."
```

---

## Task 7: rationale.py 接收 transit_summary（TDD）

**Goal:** `build_rationale_for_day` 接收可选 `transit_summary` 参数，文案带具体通勤数字。

**Files:**
- Modify: `agents/rationale.py`
- Modify: `tests/test_rationale.py`

- [ ] **Step 1: 写 failing 测试**

Append to `tests/test_rationale.py`:

```python
def test_day_rationale_with_transit_summary_includes_numbers():
    intent = _intent(traveler_type="家庭亲子", days=2)
    day = _day([
        _stop("钟楼", "上午景点", 9, 12),
        _stop("回民街", "午饭", 12, 14),
        _stop("大悦城", "下午", 14, 17),
    ])
    transit_summary = {"total_min": 92, "main_mode": "transit", "saved_yuan": 80}
    out = build_rationale_for_day(intent, 0, day, "钟楼", transit_summary=transit_summary)

    text = out["text"]
    assert "Day 1" in text
    assert "92" in text
    assert "地铁" in text or "transit" in text


def test_day_rationale_without_transit_summary_unchanged():
    intent = _intent(traveler_type="情侣")
    day = _day([_stop("外滩", "上午景点", 9, 12)])
    out = build_rationale_for_day(intent, 0, day, "外滩")
    assert "Day 1" in out["text"]
    assert "通勤" not in out["text"]


def test_day_rationale_with_estimated_summary_marks_uncertainty():
    intent = _intent(traveler_type="情侣")
    day = _day([_stop("外滩", "上午景点", 9, 12)])
    transit_summary = {"total_min": 35, "main_mode": "drive", "estimated": True}
    out = build_rationale_for_day(intent, 0, day, "外滩", transit_summary=transit_summary)
    assert "估算" in out["text"] or "约" in out["text"]
```

- [ ] **Step 2: 改 build_rationale_for_day**

Modify in `agents/rationale.py`:

```python
_MODE_CN = {
    "drive": "打车",
    "walk": "步行",
    "transit": "地铁",
    "bicycle": "骑行",
}


def build_rationale_for_day(
    intent: ParsedIntent,
    day_index: int,
    day_plan: DayPlan,
    anchor_name: str,
    transit_summary: Optional[dict] = None,  # NEW
) -> dict:
    # ... existing logic ...
    text = f"Day {day_index + 1} 集中在 {anchor} 附近，{rhythm}。"
    if tail:
        text += tail
    if transit_summary:
        prefix = "约 " if transit_summary.get("estimated") else ""
        mode_cn = _MODE_CN.get(transit_summary.get("main_mode", ""), "")
        bits = [f"{prefix}{transit_summary['total_min']} 分钟通勤"]
        if mode_cn:
            bits.append(f"{mode_cn}为主")
        if transit_summary.get("saved_yuan"):
            bits.append(f"比打车省 ¥{transit_summary['saved_yuan']}")
        text += "（" + "，".join(bits) + ("，估算）" if transit_summary.get("estimated") else "）")

    factors = [...既有...]
    return {...既有 + transit factor...}
```

注意：`Optional[dict]` 需要 import `from typing import Optional` 在文件头。

- [ ] **Step 3: 跑测试**

```bash
PYTHONPATH=. pytest tests/test_rationale.py -v
PYTHONPATH=. pytest tests/ 2>&1 | tail -3
```
Expected: 9 + 3 = 12 rationale tests + 全量 95 PASS

- [ ] **Step 4: 集成进 routes.py（让 transit summary 流回 day rationale）**

这一步 OPTIONAL — 第一版可不做，rationale 文案不带 transit 数字（前端拿到 transit.updated 后自己拼）。**第一版默认走前端拼，省工程**。

如果决定第一版后端就拼好：在 routes.py 的 `_compute_day_transits` 完成后，根据选 recommended mode 重发一个 rationale 事件覆盖。复杂度上升，**留 v2.1**。

- [ ] **Step 5: Commit**

```bash
git add agents/rationale.py tests/test_rationale.py && \
  git commit -m "feat(v2): build_rationale_for_day accepts transit_summary

Optional dict adds '（X 分钟通勤，地铁为主，比打车省 ¥Y）' tail to
day rationale. Backward compatible — None preserves v1.5 wording.
Estimated source marked with '约' prefix and '估算' suffix."
```

---

## Task 8: 前端 chip selector + 状态切换 + rationale 联动

**Goal:** 前端接 `transit.updated` 事件，渲染 chip selector 在每对 stop 之间，实现 mode 切换 + 当日总通勤动态计算 + rationale 文案追加。

**Files:**
- Modify: `web/plan_stack.html`

> 这是 v2 工程量最大的 task。本 task 不写 unit 测试（vanilla JS 无 test runner），靠 Task 9 真 uvicorn + 浏览器人眼验收。

- [ ] **Step 1: 加全局状态 Map**

In `<script>` near `pendingDayRationales`:

```javascript
const transitSelections = new Map();  // key: `${dayIdx}_${segIdx}`, value: mode
const transitData = new Map();        // key: `${dayIdx}_${segIdx}`, value: {options, recommended}
const MODE_ICON = { drive: "🚗", walk: "🚶", transit: "🚇", bicycle: "🚲" };
const MODE_NAME = { drive: "打车", walk: "步行", transit: "地铁", bicycle: "骑行" };
```

并在 `streamPlan` 开头加清理：

```javascript
transitSelections.clear();
transitData.clear();
```

- [ ] **Step 2: handleEvent 加 case**

In `handleEvent` switch:

```javascript
        case "transit.updated":
          handleTransitUpdated(data);
          break;
```

- [ ] **Step 3: 加 handleTransitUpdated + 渲染函数**

Append to `<script>`:

```javascript
    function handleTransitUpdated(data) {
      const dayIdx = data.day_index;
      data.segments.forEach((seg) => {
        const key = `${dayIdx}_${seg.from_index}`;
        transitData.set(key, seg);
        if (!transitSelections.has(key)) {
          transitSelections.set(key, seg.recommended);
        }
      });
      renderTransitForDay(dayIdx);
      updateDayRationaleWithTransit(dayIdx);
    }

    function renderTransitForDay(dayIdx) {
      const card = document.querySelector(`[data-day="${dayIdx}"]`);
      if (!card) return;
      const stopRows = card.querySelectorAll(".flex.gap-4.py-3");
      // Insert chip row after each stop row except last
      stopRows.forEach((row, i) => {
        if (i >= stopRows.length - 1) return;
        const key = `${dayIdx}_${i}`;
        const seg = transitData.get(key);
        if (!seg) return;
        let chipRow = row.nextElementSibling;
        if (!chipRow || !chipRow.classList.contains("transit-chips")) {
          chipRow = document.createElement("div");
          chipRow.className = "transit-chips flex gap-2 ml-20 mb-2 text-xs";
          row.insertAdjacentElement("afterend", chipRow);
        }
        chipRow.innerHTML = "";
        ["drive", "transit", "walk", "bicycle"].forEach((mode) => {
          const opt = seg.options[mode];
          const selected = transitSelections.get(key) === mode;
          const estimated = opt.source === "estimated";
          const chip = document.createElement("button");
          chip.className = `px-2 py-1 rounded-full border ${
            selected
              ? "bg-amber-200 border-amber-400 font-medium"
              : "bg-white border-stone-200 hover:bg-stone-50"
          } ${estimated ? "border-dashed" : ""}`;
          chip.dataset.key = key;
          chip.dataset.mode = mode;
          const priceStr = opt.price_yuan != null ? ` ¥${Math.round(opt.price_yuan)}` : "";
          chip.innerHTML = `${MODE_ICON[mode]} ${opt.minutes}min${priceStr}${estimated ? " ⚠" : ""}`;
          chip.addEventListener("click", () => {
            transitSelections.set(key, mode);
            renderTransitForDay(dayIdx);
            updateDayRationaleWithTransit(dayIdx);
          });
          chipRow.appendChild(chip);
        });
      });
    }

    function updateDayRationaleWithTransit(dayIdx) {
      let total = 0;
      let mainModeCount = {};
      let totalPrice = 0;
      let hasEstimated = false;
      for (let i = 0; ; i++) {
        const key = `${dayIdx}_${i}`;
        const seg = transitData.get(key);
        if (!seg) break;
        const mode = transitSelections.get(key);
        const opt = seg.options[mode];
        total += opt.minutes;
        mainModeCount[mode] = (mainModeCount[mode] || 0) + 1;
        if (opt.price_yuan) totalPrice += opt.price_yuan;
        if (opt.source === "estimated") hasEstimated = true;
      }
      if (total === 0) return;
      const mainMode = Object.entries(mainModeCount).sort((a, b) => b[1] - a[1])[0][0];
      const baseLine = pendingDayRationales.get(dayIdx) || "";
      const tail = `（当前 ${MODE_NAME[mainMode]}为主，全程 ${total} 分钟${
        totalPrice ? `，¥${Math.round(totalPrice)}` : ""
      }${hasEstimated ? "，估算" : ""}）`;
      upsertDayRationale(dayIdx, baseLine + tail);
    }
```

注意：因为 `pendingDayRationales` 已存了 v1.5 base text，`updateDayRationaleWithTransit` 在它后面拼 transit 尾即可。

- [ ] **Step 4: 浏览器代码标记验证**

```bash
python3 -c "
from pathlib import Path
html = Path('/Users/yikuaibanz1/Desktop/sth/mtagent/web/plan_stack.html').read_text()
markers = ['transit.updated', 'handleTransitUpdated', 'renderTransitForDay',
           'updateDayRationaleWithTransit', 'transitSelections', 'transitData', 'MODE_ICON']
for m in markers:
    print('OK ' if m in html else 'MISS ', m)
"
```
Expected: all OK

---

## Task 9: 真 uvicorn + curl + 浏览器人眼验收 + final commit

**Goal:** 真 amap key 跑端到端，curl 验证 transit.updated 事件结构，浏览器人眼验收 chip 切换和 rationale 联动。

**Files:** 无修改

- [ ] **Step 1: 重启主 app（加载 amap key）**

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent && \
  pkill -9 -f "uvicorn api.main:app" 2>/dev/null; sleep 1; \
  source venv/bin/activate && set -a && source .env && set +a && \
  unset MTAGENT_AMAP_DISABLED && \
  nohup uvicorn api.main:app --host 127.0.0.1 --port 9191 > /tmp/mtagent_v2.log 2>&1 &
sleep 3
curl -s http://127.0.0.1:9191/api/health | python3 -m json.tool
```
Expected: `llm_configured: true`

- [ ] **Step 2: curl SSE 验证 transit.updated 事件**

```bash
curl -sN -X POST http://127.0.0.1:9191/api/plan/stream \
  -H "Content-Type: application/json" \
  -d '{"free_text":"带长辈小孩五人西安三天预算 6000"}' \
  --max-time 90 > /tmp/v2_sse.txt
grep "^event:" /tmp/v2_sse.txt | sort | uniq -c
echo "=== 第 1 个 transit.updated data 摘要 ==="
python3 <<'PY'
import json
text = open('/tmp/v2_sse.txt').read()
for block in text.strip().split('\n\n'):
    name=data=None
    for line in block.split('\n'):
        if line.startswith('event: '): name=line[7:]
        elif line.startswith('data: '):
            try: data=json.loads(line[6:])
            except: pass
    if name == 'transit.updated':
        print(f"day={data['day_index']} segments={len(data['segments'])}")
        if data['segments']:
            seg = data['segments'][0]
            for mode, opt in seg['options'].items():
                print(f"  {mode}: {opt['minutes']}min, ¥{opt.get('price_yuan')}, {opt['source']}")
            print(f"  recommended={seg['recommended']}")
        break
PY
```

Expected: 3 个 transit.updated 事件（每天一个），每天 (n_stops - 1) 个 segments，每个 segment 有 4 个 mode，至少有几个 source=amap 而不全是 estimated（如果 amap key 有效）。

- [ ] **Step 3: 浏览器人眼验收**

通知用户：
```
后端验证通过。请在浏览器打开 http://127.0.0.1:9191/ 输入：
  "带长辈小孩五人西安三天预算 6000"
人眼检查：
  1. 每天 day card 内每对 stop 之间出现 4 个 chip
  2. 默认推荐 mode 高亮 amber（家庭亲子→打车）
  3. 点其他 chip 切换，rationale 文案 💭 行立刻追加新尾："（当前打车为主，全程 X 分钟，¥Y）"
  4. 估算来源 chip 边框虚线 + ⚠
  5. 切换不影响其他 day card
```

- [ ] **Step 4: Commit Task 8（前端） + close v2**

```bash
git add web/plan_stack.html && \
  git commit -m "feat(v2): chip selector for 4-mode transit + rationale livesync

- transitSelections / transitData Maps track per-segment user choice
- renderTransitForDay inserts chip row between each stop pair
- click switches mode, recomputes day total and updates rationale tail
- Estimated chips dashed border + ⚠
- Default selection from amap recommended (per traveler_type)"
```

- [ ] **Step 5: Push branch**

```bash
git push -u origin feat/v2-amap-multimodal
echo "PR URL: https://github.com/YIKUAIBANZI/mtagent/pull/new/feat/v2-amap-multimodal"
```

---

## Self-Review

**Spec coverage（核对 spec §2 Goals 1-8）：**

| Spec Goal | Task |
|---|---|
| 1. amap 4 模式 client | Task 2-4 |
| 2. Stop.transport_options 字段 | Task 1 |
| 3. 每天 transit 异步并发 | Task 6 |
| 4. haversine fallback | Task 5 |
| 5. env 开关 | Task 5 |
| 6. 前端 chip selector | Task 8 |
| 7. rationale 升级带 transit 硬证据 | Task 7 + Task 8 前端拼 |
| 8. 测试覆盖 | Task 1-7 共加 ~20 case |

**Placeholder scan：** Task 6 step 4 / Task 8 步骤含完整代码块。无 TBD。

**Type 一致性：** TransitInfo 字段 mode/minutes/distance_km/price_yuan/source 在 schema、client、SSE、前端字段名一致。

**测试基线：** 77 (v1.5) → 80 (Task 1) → 81 (Task 2) → 84 (Task 3) → 85 (Task 4) → 89 (Task 5) → 92 (Task 6) → 95 (Task 7) → 95（Task 8 前端无单测）= **95 全过完工**。

---

## Execution Handoff

Plan 完成，已存到：

```
docs/superpowers/specs/2026-05-09-mtagent-v2-amap-multimodal-design.md
docs/superpowers/plans/2026-05-09-mtagent-v2-amap-multimodal.md
```

两种执行模式：

1. **Subagent-Driven（推荐）** —— 每 task 派独立 subagent + review 间隙
2. **Inline Execution** —— 当前 session 顺着 plan 跑

哪种？或者先 `/clear` 开新 session 再开干（与 v1 / v1.5 成功流一致）？
