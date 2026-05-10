# /map View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hackathon demo 加分项——trip 生成完毕后新增 `/map` 视图，左浮窗 + 全屏高德地图 + 真实路径连线，给评委直观空间证据。

**Architecture:** plan_stack.html 完成后顶部加按钮跳新窗口 `/map?trip_id=xxx`。后端只加 2 个 endpoint（`/map` 静态路由 + `/api/config` 暴露 web js key）+ 1 个 schema 字段（DayPlan.transit_segments 持久化）。前端 `web/map.html` 单文件 ~280 行，原生 JS + 高德 JSAPI，路径用 `AMap.Driving` 服务（前端调用，配额池跟后端 webservice 分离）。

**Tech Stack:** FastAPI / Pydantic / 高德 JSAPI 1.4.15 (AMap.Driving plugin) / pytest / 原生 HTML+CSS+JS

**Spec:** `docs/superpowers/specs/2026-05-11-mtagent-map-view-design.md`

---

## File Structure

| Action | File | Responsibility |
|---|---|---|
| Create | `web/map.html` | 单文件页面: HTML 布局 + CSS + 原生 JS, 加载 JSAPI 渲染 markers/polylines, 流式动画 |
| Create | `tests/test_map_view.py` | 后端 endpoint 测试: `/map` 200, `/api/config` payload, transit_segments 持久化 |
| Modify | `api/main.py` | 加 `/map` + `/api/config` 路由 (~15 行) |
| Modify | `api/routes.py` | 把已计算的 transit segments 写进 `ctx.draft_route` 让 `GET /api/plan/{trip_id}` 拿到 |
| Modify | `dianping/schemas.py` | DayPlan 加 `transit_segments` 字段 |
| Modify | `web/plan_stack.html` | trip.complete 事件时顶部出 "🗺️ 在地图上看完整路线" 按钮 (~8 行 + CSS) |

**不改**：`agents/amap.py` / `agents/planner.py` / `agents/profiler.py` / `agents/tools.py` / SSE 事件流

---

## Branch Strategy

新建 `feat/map-view` 分支从当前 `feat/v2.5-persona-poi-routing` 拉（含 v2.5 实施代码 + 本 plan 的 spec commit）。

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
git checkout -b feat/map-view
git log --oneline -3   # 应见 d17a937 spec commit + 64fed84 v2.5 task 4
```

---

## Pre-Flight Verification

不写代码、不改文件，先跑命令确认假设。

- [ ] **Verify trip JSON 不含 transit_segments（确认需要 Task 4）**

```bash
# 启 mock + main app, 跑一次 trip, 看持久化的 trip JSON 缺什么
PYTHONPATH=. venv/bin/uvicorn dianping.mock_server:mock_app --host 127.0.0.1 --port 9192 &
MOCK_PID=$!
set -a && source .env && set +a && unset MTAGENT_AMAP_DISABLED && \
  PYTHONPATH=. venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 9191 &
APP_PID=$!
sleep 3

# 跑 trip 拿 trip_id
curl -s -N -X POST http://127.0.0.1:9191/api/plan/stream \
  -H 'Content-Type: application/json' \
  -d '{"free_text":"我和女朋友去西安三天"}' | grep "trip_id" | head -1

# 用上面的 trip_id 拿持久化 JSON
TRIP_ID=trip_xxx  # 替换为实际值
curl -s http://127.0.0.1:9191/api/plan/$TRIP_ID | python3 -m json.tool | grep -A2 "transit\|segments"
# 预期: 无任何 transit_segments 字段, 仅 transport_options (Stop 上的, 当前未填)

kill $MOCK_PID $APP_PID
```

Expected: `draft_route.days[i]` 没有 `transit_segments` 字段 → 确认需要 Task 4。

---

## Task 1: Branch + Backend — `GET /api/config` endpoint (TDD)

**Files:**
- Create: `tests/test_map_view.py` (新文件)
- Modify: `api/main.py` (加 endpoint)

- [ ] **Step 1: 切分支**

```bash
cd /Users/yikuaibanz1/Desktop/sth/mtagent
git checkout -b feat/map-view
```

- [ ] **Step 2: 写失败测试**

新建 `tests/test_map_view.py`:

```python
"""/map view 集成测试 — endpoint + schema persistence."""

import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def app_client(monkeypatch):
    monkeypatch.setenv("AMAP_WEB_JS_KEY", "test_web_js_key_xyz")
    from api.main import app

    with TestClient(app) as c:
        yield c


def test_public_config_returns_amap_web_js_key(app_client):
    """GET /api/config 暴露 web js key 给前端动态 inject JSAPI."""
    resp = app_client.get("/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "amap_web_js_key" in data
    assert data["amap_web_js_key"] == "test_web_js_key_xyz"
```

- [ ] **Step 3: 跑测试确认失败**

```bash
venv/bin/python -m pytest tests/test_map_view.py::test_public_config_returns_amap_web_js_key -v
```

Expected: FAIL with 404 (endpoint 不存在)

- [ ] **Step 4: 加 endpoint 到 `api/main.py`**

在 main.py 现有路由声明附近（用 `grep -n "@app.get" api/main.py` 找位置），追加：

```python
@app.get("/api/config")
async def get_public_config():
    """Public config exposed to frontend (non-sensitive only).

    AMAP_WEB_JS_KEY is required for client-side JSAPI; it's restricted
    to whitelisted referrers in the Amap console as the security boundary.
    """
    return {
        "amap_web_js_key": os.environ.get("AMAP_WEB_JS_KEY", ""),
    }
```

注：`os` 已 import（main.py:11）。

- [ ] **Step 5: 跑测试确认通过**

```bash
venv/bin/python -m pytest tests/test_map_view.py::test_public_config_returns_amap_web_js_key -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_map_view.py api/main.py
git commit -m "feat(map): GET /api/config exposes amap_web_js_key for frontend"
```

---

## Task 2: Backend — `GET /map` static route (TDD)

**Files:**
- Modify: `tests/test_map_view.py` (加测试)
- Modify: `api/main.py` (加路由)
- Create: `web/map.html` (空骨架, 让测试跟着 endpoint 走)

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_map_view.py`:

```python
def test_map_view_returns_html(app_client):
    """GET /map returns the map.html static file."""
    resp = app_client.get("/map")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "<html" in resp.text.lower()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
venv/bin/python -m pytest tests/test_map_view.py::test_map_view_returns_html -v
```

Expected: FAIL (404 或 file not found)

- [ ] **Step 3: 创建空 `web/map.html` 骨架**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>路线地图 — mtagent</title>
</head>
<body>
  <p>地图加载中...</p>
</body>
</html>
```

- [ ] **Step 4: 加 `/map` endpoint 到 `api/main.py`**

```python
@app.get("/map")
async def map_view():
    """Map view page — left floating panel + full-screen Amap JSAPI."""
    return FileResponse(WEB_DIR / "map.html")
```

注：`FileResponse` 和 `WEB_DIR` 已存在（main.py:19, :27）。

- [ ] **Step 5: 跑测试确认通过**

```bash
venv/bin/python -m pytest tests/test_map_view.py -v
```

Expected: 2 PASSED

- [ ] **Step 6: Commit**

```bash
git add tests/test_map_view.py api/main.py web/map.html
git commit -m "feat(map): GET /map returns map.html skeleton"
```

---

## Task 3: Backend — Persist `transit_segments` to DayPlan (TDD)

为什么：`api/routes.py` 已计算 transit segments 通过 SSE 推送，但**没写进 `ctx.draft_route`**——`GET /api/plan/{trip_id}` 拿不到，/map 页面无法算 totals。

**Files:**
- Modify: `dianping/schemas.py` (DayPlan 加字段)
- Modify: `api/routes.py` (把 segments 写进 day)
- Modify: `tests/test_map_view.py` (加 e2e 测试)

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_map_view.py`:

```python
def test_trip_persistence_includes_transit_segments(sse_app_client):
    """SSE 完成后 GET /api/plan/{trip_id} 应含 transit_segments per day."""
    # 跑一次 trip
    resp = sse_app_client.post(
        "/api/plan/stream",
        json={"free_text": "深圳两天情侣，预算精致"},
    )
    assert resp.status_code == 200
    # 提取 trip_id
    body = resp.text
    trip_id = None
    for line in body.split("\n"):
        if line.startswith("data:") and "trip_id" in line and "duration_ms" in line:
            import json
            data = json.loads(line[5:].strip())
            trip_id = data["trip_id"]
            break
    assert trip_id is not None, "no trip_id in SSE complete event"

    # 拿持久化 trip
    resp2 = sse_app_client.get(f"/api/plan/{trip_id}")
    assert resp2.status_code == 200
    trip = resp2.json()
    days = trip["draft_route"]["days"]
    assert len(days) >= 2
    for day in days:
        assert "transit_segments" in day, f"day {day['day_index']} missing transit_segments"
        # 至少 stops_count - 1 段 (≥1 if ≥2 stops)
        if len(day["stops"]) >= 2:
            assert len(day["transit_segments"]) >= 1
```

注：`sse_app_client` fixture 来自 `tests/conftest.py`。

- [ ] **Step 2: 跑测试确认失败**

```bash
venv/bin/python -m pytest tests/test_map_view.py::test_trip_persistence_includes_transit_segments -v
```

Expected: FAIL with `'transit_segments'` KeyError 或 attribute missing

- [ ] **Step 3: 修改 `dianping/schemas.py` — DayPlan 加字段**

找到（约 line 280）：

```python
class DayPlan(BaseModel):
    day_index: int
    anchor_district: str = ""
    stops: list[Stop] = Field(default_factory=list)
```

改为：

```python
class DayPlan(BaseModel):
    day_index: int
    anchor_district: str = ""
    stops: list[Stop] = Field(default_factory=list)
    transit_segments: list[dict] = Field(default_factory=list)
    # 每段形如: {"from_index": 0, "to_index": 1,
    #           "options": {mode: TransitInfo dict}, "recommended": "transit"}
```

注：用 `list[dict]` 而非 dedicated TransitSegment model — 形状跟 SSE 已发送的一致 (api/routes.py:286-296)，前端直接消费，YAGNI。

- [ ] **Step 4: 修改 `api/routes.py` — 把 segments 写进 day**

找到 `_compute_day_transits` 调用处（约 line 286-298）：

```python
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

改为：

```python
            try:
                transit_tasks = [
                    _compute_day_transits(d, intent, amap) for d in days_out
                ]
                for coro in asyncio.as_completed(transit_tasks):
                    day_index, segments = await coro
                    # 持久化到 days_out: /map 页面通过 GET /api/plan/{id} 拿
                    days_out[day_index].transit_segments = segments
                    yield format_event(
                        "transit.updated",
                        {"day_index": day_index, "segments": segments},
                    )
            finally:
                await amap._client.aclose()
```

注：`days_out[day_index]` 索引正确——见 routes.py:236-244 创建 days_out 时 `day_index=day_data.get("day_index", d)`，且 `_compute_day_transits` 在 routes.py:394 返回 `day_plan.day_index`。如果 LLM 返回的 day_index 跟列表位置不一致（理论应该一致），后面 ctx.save() 仍会保存所有 days_out 的 segments，OK。

- [ ] **Step 5: 跑测试确认通过 + 全量回归**

```bash
venv/bin/python -m pytest tests/test_map_view.py -v
venv/bin/python -m pytest tests/ -q   # 全量回归, 119 + 2 新 = 121 PASS 预期
```

Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
git add dianping/schemas.py api/routes.py tests/test_map_view.py
git commit -m "feat(map): persist transit_segments to DayPlan for /map page totals"
```

---

## Task 4: Frontend — `web/map.html` skeleton (HTML + CSS, no JS yet)

**Files:**
- Modify: `web/map.html` (重写, 从 Task 2 的空骨架 → 完整布局)

- [ ] **Step 1: 写完整 HTML + CSS**

完全替换 `web/map.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>路线地图 — mtagent</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html, body { width: 100%; height: 100%; overflow: hidden; font-family: -apple-system, "PingFang SC", sans-serif; }

    /* 全屏地图容器 */
    #map-container { position: absolute; inset: 0; z-index: 0; background: #f5f1eb; }

    /* 左浮窗 */
    #floating-panel {
      position: absolute; top: 16px; left: 16px; z-index: 10;
      width: 360px; max-height: calc(100vh - 32px);
      background: rgba(255, 255, 255, 0.92);
      backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
      border-radius: 16px;
      box-shadow: 0 4px 24px rgba(0, 0, 0, 0.08);
      padding: 20px;
      overflow-y: auto;
      display: flex; flex-direction: column; gap: 16px;
    }

    /* 浮窗 header */
    #panel-header h1 { font-size: 18px; font-weight: 600; color: #1c1917; margin-bottom: 4px; }
    #panel-header .subtitle { font-size: 12px; color: #78716c; }

    /* totals + day filter chip 横排 */
    .chip-row { display: flex; flex-wrap: wrap; gap: 8px; }
    .chip {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 6px 12px; border-radius: 16px;
      font-size: 12px; font-weight: 500;
      background: #fafaf9; border: 1px solid #e7e5e4; color: #57534e;
      cursor: pointer; user-select: none;
      transition: all 0.2s;
    }
    .chip.active { color: #fff; border-color: transparent; }
    .chip-dot { width: 8px; height: 8px; border-radius: 50%; }

    /* day cards */
    #day-list { list-style: none; display: flex; flex-direction: column; gap: 12px; }
    .day-card {
      border-left: 4px solid var(--day-color, #d6d3d1);
      background: #fff; border-radius: 8px; padding: 12px;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
      opacity: 0; transform: translateY(8px);
      transition: opacity 0.4s ease-out, transform 0.4s ease-out;
    }
    .day-card.fade-in { opacity: 1; transform: translateY(0); }
    .day-card-title { font-size: 13px; font-weight: 600; color: #1c1917; margin-bottom: 8px; }
    .stop-row { display: flex; gap: 8px; padding: 6px 0; font-size: 12px; color: #44403c; }
    .stop-time { width: 44px; color: #78716c; flex-shrink: 0; }
    .stop-name { flex: 1; }

    /* marker (内容由 JS 注入) */
    .marker {
      width: 28px; height: 28px; border-radius: 50%;
      color: #fff; font-weight: 600; font-size: 13px;
      display: flex; align-items: center; justify-content: center;
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.25);
      border: 2px solid #fff;
    }

    /* fallback / error */
    #status-banner {
      position: absolute; top: 16px; left: 50%; transform: translateX(-50%);
      z-index: 20; background: #fef2f2; color: #991b1b;
      padding: 10px 16px; border-radius: 8px; font-size: 13px;
      display: none;
    }
    #status-banner.show { display: block; }

    #back-link {
      position: absolute; bottom: 16px; left: 16px; z-index: 10;
      color: #57534e; font-size: 12px; text-decoration: none;
      background: rgba(255, 255, 255, 0.9); padding: 8px 12px; border-radius: 8px;
    }
    #back-link:hover { color: #1c1917; }
  </style>
</head>
<body>
  <div id="map-container"></div>

  <aside id="floating-panel">
    <header id="panel-header">
      <h1 id="trip-title">加载中...</h1>
      <div class="subtitle" id="trip-subtitle"></div>
    </header>

    <div class="chip-row" id="totals-row"></div>
    <div class="chip-row" id="day-filter"></div>

    <ol id="day-list"></ol>
  </aside>

  <a id="back-link" href="/">← 返回生成页</a>

  <div id="status-banner"></div>

  <script>
    // JS in Task 5+
    document.getElementById('trip-title').textContent = '骨架就位, JS 待加入';
  </script>
</body>
</html>
```

- [ ] **Step 2: 浏览器手动验证骨架**

```bash
# 起服务（如未起）
PYTHONPATH=. venv/bin/uvicorn dianping.mock_server:mock_app --host 127.0.0.1 --port 9192 &
set -a && source .env && set +a && \
  PYTHONPATH=. venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 9191 &
sleep 2

open http://127.0.0.1:9191/map
```

Expected: 看到左浮窗（圆角白底带 backdrop blur）+ 米色背景（map-container 的 fallback 色）+ 左下角"返回生成页"链接 + 浮窗里 "骨架就位, JS 待加入"。

- [ ] **Step 3: 跑后端测试确保没破**

```bash
venv/bin/python -m pytest tests/test_map_view.py -v
```

Expected: 3 PASSED

- [ ] **Step 4: Commit**

```bash
git add web/map.html
git commit -m "feat(map): web/map.html skeleton — floating panel + map container CSS"
```

---

## Task 5: Frontend — JS load config + dynamic JSAPI injection

**Files:**
- Modify: `web/map.html` (替换 `<script>` 块)

- [ ] **Step 1: 替换 `<script>` 块**

把 `web/map.html` 的 `<script>...</script>` 替换为：

```html
  <script>
    'use strict';

    // ============= Globals =============
    let map = null;            // AMap.Map instance
    let driving = null;        // AMap.Driving plugin instance
    let tripData = null;       // GET /api/plan/{trip_id} response
    const markersByDay = [];   // markersByDay[i] = [marker1, marker2, ...]
    const polylinesByDay = []; // polylinesByDay[i] = AMap.Polyline
    const DAY_COLORS = ['#FF6B35', '#3D8BFD', '#10B981', '#A855F7', '#F59E0B'];

    // ============= Bootstrap =============
    async function bootstrap() {
      try {
        const tripId = new URLSearchParams(location.search).get('trip_id');
        if (!tripId) {
          showError('缺少 trip_id 参数. 请从生成页跳转过来.');
          return;
        }

        // 1. fetch public config
        const cfgResp = await fetch('/api/config');
        if (!cfgResp.ok) throw new Error('config endpoint failed');
        const cfg = await cfgResp.json();
        if (!cfg.amap_web_js_key) {
          showError('地图服务未配置 (AMAP_WEB_JS_KEY 缺失). 请联系管理员.');
          return;
        }

        // 2. dynamic load JSAPI
        await loadAmapJsApi(cfg.amap_web_js_key);

        // 3. fetch trip
        const tripResp = await fetch(`/api/plan/${tripId}`);
        if (!tripResp.ok) {
          showError(`trip 不存在或已过期 (HTTP ${tripResp.status})`);
          return;
        }
        tripData = await tripResp.json();

        // 4. init map
        map = new AMap.Map('map-container', {
          mapStyle: 'amap://styles/light',
          zoom: 12,
          viewMode: '2D',
        });
        await new Promise(resolve => {
          AMap.plugin(['AMap.Driving'], () => {
            driving = new AMap.Driving({ map, hideMarkers: true, autoFitView: false });
            resolve();
          });
        });

        // 5. handoff to render (Tasks 7-12 will fill this)
        document.getElementById('trip-title').textContent = '加载完成 — render 待加入';
        document.getElementById('trip-subtitle').textContent = `trip_id=${tripId}`;
        console.log('tripData', tripData);

      } catch (err) {
        console.error(err);
        showError('地图加载失败: ' + err.message);
      }
    }

    function loadAmapJsApi(key) {
      return new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = `https://webapi.amap.com/maps?v=1.4.15&key=${key}`;
        script.onload = resolve;
        script.onerror = () => reject(new Error('JSAPI 加载失败 (网络/CDN)'));
        document.head.appendChild(script);
      });
    }

    function showError(msg) {
      const el = document.getElementById('status-banner');
      el.textContent = msg;
      el.classList.add('show');
    }

    // ============= Run =============
    bootstrap();
  </script>
```

- [ ] **Step 2: 浏览器手动验证**

```bash
# 先跑一次 trip 拿 trip_id
curl -s -N -X POST http://127.0.0.1:9191/api/plan/stream \
  -H 'Content-Type: application/json' \
  -d '{"free_text":"我和女朋友去西安三天"}' | grep "trip_id" | head -1
# 拷贝 trip_id 形如 trip_xxx

open "http://127.0.0.1:9191/map?trip_id=trip_xxx"
```

Expected:
- 浮窗 title 变成 "加载完成 — render 待加入"
- subtitle 显示 trip_id
- 地图加载（高德浅色瓦片）
- 浏览器 console 打印 tripData (含 draft_route.days 数组)
- 无 error banner

如果 JSAPI 加载失败：检查 `.env` 里 `AMAP_WEB_JS_KEY` 是否设了，referrer 白名单是否限制了 localhost。

- [ ] **Step 3: Commit**

```bash
git add web/map.html
git commit -m "feat(map): bootstrap loads config + JSAPI + trip data"
```

---

## Task 6: Frontend — Render floating panel (static, no animation)

**Files:**
- Modify: `web/map.html` (扩展 `<script>`)

- [ ] **Step 1: 在 bootstrap 末尾加 renderPanel 调用 + 实现**

把第 5 步 "handoff to render" 那 3 行替换为：

```js
        // 5. render
        renderHeader(tripData);
        renderDayList(tripData);
```

在 `function bootstrap()` 之后、`function loadAmapJsApi` 之前加：

```js
    // ============= Panel rendering =============
    function renderHeader(trip) {
      const intent = trip.intent || {};
      const days = trip.draft_route?.days || [];
      document.getElementById('trip-title').textContent =
        `${intent.city || '未知'} · ${days.length} 天行程`;
      document.getElementById('trip-subtitle').textContent =
        `${intent.traveler_type || ''} · ${intent.budget_level || ''}`;
    }

    function renderDayList(trip) {
      const days = trip.draft_route?.days || [];
      const list = document.getElementById('day-list');
      list.innerHTML = '';
      days.forEach((day, i) => {
        const li = document.createElement('li');
        li.className = 'day-card fade-in';   // 直接加 fade-in (Task 12 改成流式)
        li.style.setProperty('--day-color', DAY_COLORS[i] || '#d6d3d1');
        li.dataset.dayIndex = i;

        const title = document.createElement('div');
        title.className = 'day-card-title';
        title.textContent = `Day ${i + 1} · ${day.anchor_district || ''}`;
        li.appendChild(title);

        (day.stops || []).forEach(stop => {
          const row = document.createElement('div');
          row.className = 'stop-row';
          row.innerHTML = `
            <span class="stop-time">${stop.arrival_time || ''}</span>
            <span class="stop-name">${escapeHtml(stop.poi?.name || '未命名')}</span>
          `;
          li.appendChild(row);
        });
        list.appendChild(li);
      });
    }

    function escapeHtml(s) {
      return String(s).replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
      ));
    }
```

- [ ] **Step 2: 浏览器手动验证**

```bash
# 服务还在跑, 直接刷新
open "http://127.0.0.1:9191/map?trip_id=trip_xxx"
```

Expected:
- 标题变 "西安 · 3 天行程" (假设跑的是西安)
- subtitle "情侣 · 精致"
- 浮窗下面是 3 张 day card, 每张含 day index + 各 stop 时间 + 名称
- 每张 card 左边框是 day color (橙/蓝/绿)
- card 直接显示 (无动画, Task 12 加)

- [ ] **Step 3: Commit**

```bash
git add web/map.html
git commit -m "feat(map): render floating panel header + day cards (static)"
```

---

## Task 7: Frontend — Render markers per day (no animation)

**Files:**
- Modify: `web/map.html`

- [ ] **Step 1: bootstrap 末尾加 renderMarkers 调用 + 实现**

修改 bootstrap 末尾：

```js
        // 5. render
        renderHeader(tripData);
        renderDayList(tripData);
        renderAllMarkers(tripData);
        fitMapToAllMarkers();
```

加新函数（与 renderDayList 同 section）：

```js
    // ============= Map: markers =============
    function renderAllMarkers(trip) {
      const days = trip.draft_route?.days || [];
      days.forEach((day, dayIndex) => {
        markersByDay[dayIndex] = [];
        (day.stops || []).forEach((stop, stopIndex) => {
          const lng = stop.poi?.longitude;
          const lat = stop.poi?.latitude;
          if (typeof lng !== 'number' || typeof lat !== 'number') {
            console.warn(`day ${dayIndex} stop ${stopIndex} missing coords, skip`);
            return;
          }
          const color = DAY_COLORS[dayIndex] || '#d6d3d1';
          const marker = new AMap.Marker({
            position: [lng, lat],
            offset: new AMap.Pixel(-14, -28),
            content: `<div class="marker" style="background:${color}">${stopIndex + 1}</div>`,
            title: stop.poi.name,
          });
          marker.setMap(map);
          markersByDay[dayIndex].push(marker);
        });
      });
    }

    function fitMapToAllMarkers() {
      const all = markersByDay.flat();
      if (all.length > 0) {
        map.setFitView(all, false, [60, 60, 60, 380]);  // 左 padding 380 留浮窗
      }
    }
```

- [ ] **Step 2: 浏览器手动验证**

刷新页面。Expected:
- 地图缩放到所有 marker 的 fit view
- 每个 marker 是 28×28 圆形彩色徽章, 数字 1/2/3...
- 同一天的 marker 同色 (Day 1 橙 / Day 2 蓝 / Day 3 绿)
- console 无 warn (POI 都有坐标)

如果某天 marker 不显示：F12 看 console，可能是该天 stops 全 0 (filter 过严)，spec 里已 cover。

- [ ] **Step 3: Commit**

```bash
git add web/map.html
git commit -m "feat(map): render numbered markers per day with day color"
```

---

## Task 8: Frontend — Render polylines (Driving service + fallback)

**Files:**
- Modify: `web/map.html`

- [ ] **Step 1: bootstrap 末尾加 polyline 调用 + 实现**

修改 bootstrap 末尾：

```js
        // 5. render
        renderHeader(tripData);
        renderDayList(tripData);
        renderAllMarkers(tripData);
        fitMapToAllMarkers();
        await renderAllPolylines(tripData);
```

加新函数：

```js
    // ============= Map: polylines =============
    async function renderAllPolylines(trip) {
      const days = trip.draft_route?.days || [];
      // 串行画 (3 天 = 3 次 Driving.search, ~1-2s 总计, 可接受)
      for (let i = 0; i < days.length; i++) {
        await drawDayPolyline(days[i], i);
      }
    }

    function drawDayPolyline(day, dayIndex) {
      const stops = day.stops || [];
      if (stops.length < 2) return Promise.resolve();
      const stopCoords = stops
        .filter(s => typeof s.poi?.longitude === 'number')
        .map(s => [s.poi.longitude, s.poi.latitude]);
      if (stopCoords.length < 2) return Promise.resolve();

      const origin = stopCoords[0];
      const destination = stopCoords[stopCoords.length - 1];
      const waypoints = stopCoords.slice(1, -1).map(p => ({ location: p }));
      const color = DAY_COLORS[dayIndex] || '#d6d3d1';

      return new Promise((resolve) => {
        driving.search(origin, destination, { waypoints }, (status, result) => {
          let pathLngLat;
          if (status === 'complete' && result.routes?.[0]) {
            const route = result.routes[0];
            pathLngLat = route.steps.flatMap(s => s.path).map(p => [p.lng, p.lat]);
          } else {
            console.warn(`Driving.search day ${dayIndex} failed (${status}), fallback straight line`);
            pathLngLat = stopCoords;
          }
          const line = new AMap.Polyline({
            path: pathLngLat,
            strokeColor: color,
            strokeWeight: 5,
            strokeOpacity: 0.85,
            showDir: true,
          });
          line.setMap(map);
          polylinesByDay[dayIndex] = line;
          resolve();
        });
      });
    }
```

- [ ] **Step 2: 浏览器手动验证**

刷新页面，等 1-2s polyline 出现。Expected:
- 每天 marker 之间有彩色路径线，**沿真实街道走**（不是直线）
- 路径颜色跟该天 marker 同色
- 路径有箭头方向（`showDir: true`）
- 如某段失败：console 看到 warn + 该段是直线，page 不崩

如果所有路径都是直线：可能 web js key 没启用 Driving 服务，或域名限制 — 在高德控制台核对。

- [ ] **Step 3: Commit**

```bash
git add web/map.html
git commit -m "feat(map): render real-street polylines via JSAPI Driving service"
```

---

## Task 9: Frontend — Totals chip (distance + duration)

**Files:**
- Modify: `web/map.html`

- [ ] **Step 1: bootstrap 末尾加 renderTotals 调用 + 实现**

修改 bootstrap 末尾：

```js
        // 5. render
        renderHeader(tripData);
        renderTotals(tripData.draft_route?.days || []);   // 新加
        renderDayList(tripData);
        renderAllMarkers(tripData);
        fitMapToAllMarkers();
        await renderAllPolylines(tripData);
```

加新函数：

```js
    // ============= Totals chip =============
    function computeTotals(days) {
      let totalKm = 0, totalMin = 0;
      for (const day of days) {
        for (const seg of (day.transit_segments || [])) {
          const rec = seg.options?.[seg.recommended];
          if (!rec) continue;
          totalKm += rec.distance_km || 0;
          totalMin += rec.minutes || 0;
        }
      }
      return { km: totalKm, min: totalMin };
    }

    function renderTotals(days) {
      const { km, min } = computeTotals(days);
      const row = document.getElementById('totals-row');
      row.innerHTML = '';
      if (days.length === 0) return;
      const label = (km > 0 || min > 0)
        ? `${km.toFixed(1)} km · 全程`
        : '— 距离数据未计算';
      const labelTime = (min > 0)
        ? `${(min / 60).toFixed(1)} h · 在途`
        : '— 时长数据未计算';
      const c1 = document.createElement('div');
      c1.className = 'chip';
      c1.style.background = '#1c1917';
      c1.style.color = '#fff';
      c1.style.borderColor = 'transparent';
      c1.textContent = label;
      const c2 = c1.cloneNode(true);
      c2.textContent = labelTime;
      row.appendChild(c1);
      row.appendChild(c2);
    }
```

- [ ] **Step 2: 浏览器手动验证**

刷新页面。Expected:
- 浮窗 header 下方出现 2 个深色 chip：`X.X km · 全程` 和 `X.X h · 在途`
- 数字合理（西安 3 天 5-30 km, 0.5-3 h）
- 如果 transit_segments 缺失（旧 trip）：显示 "— 距离数据未计算"

- [ ] **Step 3: Commit**

```bash
git add web/map.html
git commit -m "feat(map): totals chip — sum distance + duration from transit_segments"
```

---

## Task 10: Frontend — Day filter chip (toggle + recompute totals)

**Files:**
- Modify: `web/map.html`

- [ ] **Step 1: bootstrap 末尾加 renderDayFilter + 实现**

修改 bootstrap 末尾：

```js
        // 5. render
        renderHeader(tripData);
        renderTotals(tripData.draft_route?.days || []);
        renderDayList(tripData);
        renderAllMarkers(tripData);
        fitMapToAllMarkers();
        await renderAllPolylines(tripData);
        renderDayFilter(tripData);   // 新加, 必须在 markers/polylines 之后
```

加新函数：

```js
    // ============= Day filter =============
    const dayVisibility = [];   // dayVisibility[i] = bool

    function renderDayFilter(trip) {
      const days = trip.draft_route?.days || [];
      const filter = document.getElementById('day-filter');
      filter.innerHTML = '';
      days.forEach((_, i) => {
        dayVisibility[i] = true;
        const chip = document.createElement('div');
        chip.className = 'chip active';
        chip.dataset.dayIndex = i;
        const color = DAY_COLORS[i] || '#d6d3d1';
        chip.style.background = color;
        chip.style.color = '#fff';
        chip.style.borderColor = 'transparent';
        chip.innerHTML = `<span class="chip-dot" style="background:#fff"></span>Day ${i + 1}`;
        chip.onclick = () => toggleDay(i, chip);
        filter.appendChild(chip);
      });
    }

    function toggleDay(i, chip) {
      const visible = !dayVisibility[i];
      dayVisibility[i] = visible;

      (markersByDay[i] || []).forEach(m => visible ? m.setMap(map) : m.setMap(null));
      const line = polylinesByDay[i];
      if (line) line.setMap(visible ? map : null);

      // chip 视觉态
      const color = DAY_COLORS[i] || '#d6d3d1';
      chip.classList.toggle('active', visible);
      if (visible) {
        chip.style.background = color;
        chip.style.color = '#fff';
        chip.style.borderColor = 'transparent';
      } else {
        chip.style.background = '#fafaf9';
        chip.style.color = '#a8a29e';
        chip.style.borderColor = '#e7e5e4';
      }

      // day card 灰化
      const card = document.querySelector(`.day-card[data-day-index="${i}"]`);
      if (card) card.style.opacity = visible ? '1' : '0.35';

      // recompute totals (仅可见天)
      const visibleDays = (tripData.draft_route?.days || []).filter((_, idx) => dayVisibility[idx]);
      renderTotals(visibleDays);
    }
```

- [ ] **Step 2: 浏览器手动验证**

刷新页面。Expected:
- 浮窗顶部 totals 下方出现 N 个 day chip (Day 1 / Day 2 / Day 3 ...) 同色
- 点 chip → 该天 marker + polyline 隐藏 + chip 变灰 + 对应 card 灰化 + totals 重算
- 再点 → 显示回来
- 全关也不崩 (totals 显示为 0)

- [ ] **Step 3: Commit**

```bash
git add web/map.html
git commit -m "feat(map): day filter chip — toggle visibility + recompute totals"
```

---

## Task 11: Frontend — Streaming animation (replace static day card render)

**Files:**
- Modify: `web/map.html`

- [ ] **Step 1: 把 renderDayList 改成流式 + markers 改成顺序 drop**

修改 bootstrap 末尾，把多个独立 render 调用改成一个 sequenced 渲染：

```js
        // 5. render — sequenced for streaming feel
        renderHeader(tripData);
        renderTotals(tripData.draft_route?.days || []);
        await renderTripStreaming(tripData);
        renderDayFilter(tripData);
```

替换 `renderDayList`、`renderAllMarkers`、`renderAllPolylines`、`fitMapToAllMarkers` 这 4 个函数为单一 sequenced 函数：

```js
    // ============= Streaming render =============
    async function renderTripStreaming(trip) {
      const days = trip.draft_route?.days || [];
      const list = document.getElementById('day-list');
      list.innerHTML = '';

      for (let i = 0; i < days.length; i++) {
        // (a) 浮窗 day card 淡入
        const card = buildDayCard(days[i], i);
        list.appendChild(card);
        requestAnimationFrame(() => card.classList.add('fade-in'));
        await sleep(150);

        // (b) markers 顺序 drop (每 stop 间隔 200ms)
        markersByDay[i] = [];
        await dropDayMarkers(days[i], i);

        // (c) polyline 浮现
        await drawDayPolyline(days[i], i);

        // (d) 每天间停顿
        await sleep(200);
      }

      // 全画完后 fit view
      fitMapToAllMarkers();
    }

    function buildDayCard(day, dayIndex) {
      const li = document.createElement('li');
      li.className = 'day-card';   // 不立即加 fade-in (在调用方 RAF 后加)
      li.style.setProperty('--day-color', DAY_COLORS[dayIndex] || '#d6d3d1');
      li.dataset.dayIndex = dayIndex;

      const title = document.createElement('div');
      title.className = 'day-card-title';
      title.textContent = `Day ${dayIndex + 1} · ${day.anchor_district || ''}`;
      li.appendChild(title);

      (day.stops || []).forEach(stop => {
        const row = document.createElement('div');
        row.className = 'stop-row';
        row.innerHTML = `
          <span class="stop-time">${stop.arrival_time || ''}</span>
          <span class="stop-name">${escapeHtml(stop.poi?.name || '未命名')}</span>
        `;
        li.appendChild(row);
      });
      return li;
    }

    function dropDayMarkers(day, dayIndex) {
      return new Promise(resolve => {
        const stops = day.stops || [];
        if (stops.length === 0) return resolve();
        let dropped = 0;
        stops.forEach((stop, stopIndex) => {
          setTimeout(() => {
            const lng = stop.poi?.longitude;
            const lat = stop.poi?.latitude;
            if (typeof lng === 'number' && typeof lat === 'number') {
              const color = DAY_COLORS[dayIndex] || '#d6d3d1';
              const marker = new AMap.Marker({
                position: [lng, lat],
                offset: new AMap.Pixel(-14, -28),
                content: `<div class="marker" style="background:${color}">${stopIndex + 1}</div>`,
                title: stop.poi.name,
                animation: 'AMAP_ANIMATION_DROP',
              });
              marker.setMap(map);
              markersByDay[dayIndex].push(marker);
            }
            dropped++;
            if (dropped === stops.length) resolve();
          }, stopIndex * 200);
        });
      });
    }

    function fitMapToAllMarkers() {
      const all = markersByDay.flat();
      if (all.length > 0) {
        map.setFitView(all, false, [60, 60, 60, 380]);
      }
    }

    function sleep(ms) {
      return new Promise(r => setTimeout(r, ms));
    }
```

**注意**：删除老的 `renderDayList`、`renderAllMarkers`、`renderAllPolylines` 函数定义——它们的功能已经被 `renderTripStreaming` 接管。`drawDayPolyline` 仍保留（被新流程调用）。`escapeHtml` 仍保留。

- [ ] **Step 2: 浏览器手动验证**

刷新页面。Expected:
- 页面打开 → 浮窗 header + totals + day filter (动画前全部就位) + 空 day-list
- 然后 day card 一张张淡入，每张 card 出现后 0.15s 开始 drop 该天 markers
- markers 一个个 drop 进来 (每 stop 200ms 间隔)
- 该天 markers 全 drop 完后画 polyline
- 下一天，重复
- 总时长 ~3 天 × (150ms + 200ms × stops + polyline_search + 200ms) ≈ 5-10s 戏剧节奏

如果觉得太慢：把 sleep(150)/sleep(200)/marker 间隔 200 调小（如 100/100/100）。如果太快没戏剧感：调大。

- [ ] **Step 3: Commit**

```bash
git add web/map.html
git commit -m "feat(map): streaming animation — sequenced card fade-in + marker drop"
```

---

## Task 12: Modify plan_stack.html — add "在地图上看" button on trip.complete

**Files:**
- Modify: `web/plan_stack.html`

- [ ] **Step 1: 找到 trip.complete handler**

```bash
grep -n "trip.complete\|trip\\.complete" web/plan_stack.html
```

记下行号。trip.complete handler 应该在 SSE message 处理函数里，类似 `case 'trip.complete':` 或 `event === 'trip.complete'`。

- [ ] **Step 2: 在 handler 里 prepend map button**

在 trip.complete handler 内部加：

```js
            // ↓↓↓ 加这一段 ↓↓↓
            const mapBtn = document.createElement('a');
            mapBtn.href = `/map?trip_id=${data.trip_id}`;
            mapBtn.target = '_blank';
            mapBtn.textContent = '🗺️ 在地图上看完整路线';
            mapBtn.className = 'map-cta';
            const timeline = document.getElementById('timeline-section');
            if (timeline && !timeline.querySelector('.map-cta')) {
              timeline.prepend(mapBtn);
            }
            // ↑↑↑ 加这一段 ↑↑↑
```

注：`data.trip_id` 是 trip.complete 事件的 payload 字段（已在 SSE 里）。`if (!timeline.querySelector('.map-cta'))` 防止重复点击 trip 时按钮重复 prepend。

- [ ] **Step 3: 加 `.map-cta` CSS**

在 plan_stack.html 的 `<style>` 块尾部加：

```css
.map-cta {
  display: block;
  margin: 0 auto 24px;
  width: fit-content;
  padding: 10px 20px;
  background: #d2691e;
  color: #fff !important;
  text-decoration: none;
  border-radius: 24px;
  font-size: 14px;
  font-weight: 500;
  box-shadow: 0 4px 12px rgba(210, 105, 30, 0.3);
  transition: transform 0.2s, box-shadow 0.2s;
}
.map-cta:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(210, 105, 30, 0.4);
}
```

- [ ] **Step 4: 浏览器手动验证**

```bash
open http://127.0.0.1:9191/
# 输入 query, 等 trip 跑完
```

Expected:
- trip 完成后 timeline 顶部出现橙色圆角按钮 "🗺️ 在地图上看完整路线"
- 点击 → 新窗口打开 /map?trip_id=xxx → 地图正常渲染

- [ ] **Step 5: Commit**

```bash
git add web/plan_stack.html
git commit -m "feat(map): plan_stack adds map CTA button on trip.complete"
```

---

## Task 13: Final smoke test + manual acceptance

**Files:** 无新文件

- [ ] **Step 1: 全量 pytest 回归**

```bash
venv/bin/python -m pytest tests/ -q
```

Expected: 119 baseline + 3 新 (test_map_view) = **122 PASS** (假设无回归)

- [ ] **Step 2: 端到端浏览器手动验收 (按 spec §8.2 清单)**

启服务，跑 query "我和女朋友去西安三天精致" → 等 SSE 完成 → 点 "🗺️ 在地图上看" → 在新页面验证：

| # | Check | Pass? |
|---|---|---|
| 1 | trip 生成完毕，按钮出现，点击新窗口打开 `/map?trip_id=xxx` | ⬜ |
| 2 | 地图加载 ≤ 3s（JSAPI + 自定义 mapStyle 浅色） | ⬜ |
| 3 | 浮窗按 day 顺序淡入，每天 markers 一个个 drop | ⬜ |
| 4 | 每天 polyline 沿真实街道画出（不是直线） | ⬜ |
| 5 | 同一天的 marker / polyline / day chip 颜色一致 | ⬜ |
| 6 | 点 day chip 切换显隐生效 + totals 重算 | ⬜ |
| 7 | 总距离/时长 chip 数字合理（西安 3 天 ~10-30 km） | ⬜ |
| 8 | 浏览器 console 无 error（warn 可接受） | ⬜ |

如有 fail：在该 task 内 fix + 加 commit, 不开新 task。

- [ ] **Step 3: 收尾**

```bash
pkill -9 -f uvicorn 2>/dev/null
git log --oneline -15   # review map-view 分支所有 commit
```

最终预期 commit 链（约 9-12 个 commit）：
```
xxx feat(map): plan_stack adds map CTA button on trip.complete
xxx feat(map): streaming animation — sequenced card fade-in + marker drop
xxx feat(map): day filter chip — toggle visibility + recompute totals
xxx feat(map): totals chip — sum distance + duration
xxx feat(map): render real-street polylines via JSAPI Driving service
xxx feat(map): render numbered markers per day with day color
xxx feat(map): render floating panel header + day cards (static)
xxx feat(map): bootstrap loads config + JSAPI + trip data
xxx feat(map): web/map.html skeleton — floating panel + map container CSS
xxx feat(map): persist transit_segments to DayPlan for /map page totals
xxx feat(map): GET /map returns map.html skeleton
xxx feat(map): GET /api/config exposes amap_web_js_key for frontend
```

- [ ] **Step 4: (可选) Push + 决定 PR / merge**

```bash
git push -u origin feat/map-view
# 是否开 PR / merge 到 main 由 banz 决定
```

---

## Risks (mid-implementation watch list)

| Risk | Where | Mitigation |
|---|---|---|
| AMAP_WEB_JS_KEY 域名限制阻挡 localhost | Task 5 | 高德控制台加 `localhost`, `127.0.0.1` 白名单 |
| Driving.search 超时 / API 限频 | Task 8 | fallback 直线已写, page 不崩 |
| 流式动画太慢 / 太快 | Task 11 | 调 `sleep(150)` / `sleep(200)` 数值 |
| trip JSON 缺 transit_segments (旧 trip) | Task 9 | totals 显示 "— ... 未计算", 不阻塞地图 |
| 大量 stops (>16) 撑爆 Driving waypoints | Task 8 | hackathon trip 单天 ≤ 7 stops, 不触发 |

---

## Out of Scope (明确不做)

见 spec §2:
- Marker ↔ card 双向高亮同步
- 类型 layer toggle (餐饮/住宿)
- 浮窗底部 chat input "再调整一下" → Adjuster 单独立项
- 移动端响应式
- Playwright e2e
- POI schema 重构 (PoiCard distilled view)
