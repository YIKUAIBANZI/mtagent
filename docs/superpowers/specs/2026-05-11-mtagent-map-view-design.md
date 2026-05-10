# /map View — Map Integration Design Spec

| | |
|---|---|
| **Date** | 2026-05-11 |
| **Author** | Banz + Claude |
| **Status** | Spec ready, awaiting user review → writing-plans |
| **Brainstorm** | inline (this session) |
| **Estimated work** | ~1 day (frontend dominant) |
| **Test delta** | +2 backend tests (`/map` 200 + `/api/config` payload) |

---

## 1 · Context & Motivation

Trip 生成完成后，评委只能看到一列 day cards 文本，**没有任何空间感**——5 个 POI 在西安城里到底分布在哪、合不合理、行程顺不顺，全靠脑补。

新增 `/map` 视图：左浮窗保留 trip 文本结构，全屏地图给评委直观的空间证据 + 真实路径线，把"AI 真的懂这座城"立起来。

**为什么不在 plan_stack.html 内嵌**：
- SSE 流式 cards 的现有逻辑复杂，内嵌地图要改动 SSE 渲染路径
- 评委体验流：先看到 AI **流式生成**（戏剧感）→ 点按钮跳地图（视觉冲击），剧场效果更好
- 单页职责清晰：plan_stack 负责"生成"，/map 负责"展示"

---

## 2 · Out of Scope（明确不做）

- Marker ↔ card 双向高亮同步（点 marker 滚到 card / 反之）
- 类型 layer toggle（餐饮 / 住宿 / 步行筛选）
- 浮窗底部 "再调整一下" chat input → 这是 Adjuster 功能，单独立项
- 移动端响应式（hackathon demo 用桌面浏览器）
- POI 数据 schema 重构（distilled `PoiCard` view 是单独 backlog 立项）
- E2E 浏览器测试（Playwright），仅手动浏览器验收

---

## 3 · Architecture

```
plan_stack.html (现有, SSE 流式生成 trip)
    │
    │ trip.complete 事件后, 顶部出现按钮
    │ [🗺️ 在地图上看完整路线]
    │   onclick: window.open(`/map?trip_id=${trip_id}`)
    ▼
GET /map?trip_id=xxx                    ← 新路由 (api/main.py)
    │ 仅返回 web/map.html 静态文件
    ▼
web/map.html (新文件, 单文件 ~280 行)
    │ window.onload:
    │   1. fetch GET /api/config           → 拿 amap_web_js_key (env 不暴露源码)
    │   2. fetch GET /api/plan/{trip_id}   → 已有 endpoint, 拿 trip 数据
    │   3. 加载 AMap JSAPI 1.4.x
    │   4. 渲染左浮窗 (流式淡入)
    │   5. 渲染地图 (markers drop + polyline 浮现)
```

**核心设计原则**：
- 后端只加 2 个最小 endpoint，不动 amap.py / routes.py / SSE
- 前端单文件零框架，HTML + 原生 JS + JSAPI
- 路径数据走 JSAPI 自带 `AMap.Driving` plugin（前端调用，配额池跟后端 webservice 分离）

---

## 4 · Backend Changes

### 4.1 `api/main.py` — 加 2 个 endpoint

```python
from fastapi.responses import FileResponse
from pathlib import Path

WEB_DIR = Path(__file__).parent.parent / "web"

@app.get("/map")
async def map_view():
    return FileResponse(WEB_DIR / "map.html")

@app.get("/api/config")
async def get_public_config():
    """前端可见的配置项, 仅返回非敏感公开 key"""
    return {
        "amap_web_js_key": os.environ.get("AMAP_WEB_JS_KEY", ""),
    }
```

**为什么 `/api/config`**：`AMAP_WEB_JS_KEY` 不能硬编码进 `web/map.html`（被 push 上 GitHub）。前端首次加载时取 → 然后动态 inject `<script src="https://webapi.amap.com/maps?v=1.4.15&key=${key}">`。配合高德控制台限制 referrer 域名做安全兜底。

### 4.2 复用，不改

- `GET /api/plan/{trip_id}` — 已有，返回完整 `TripContext.model_dump()`，含 `draft_route.days[i].stops[j].poi.latitude/longitude` ✓ verified
- `agents/amap.py` — 不动
- `api/routes.py` SSE — 不动

---

## 5 · Frontend: `web/map.html`

### 5.1 布局结构

```
<body>
  <div id="map-container">                    /* 100vw × 100vh, JSAPI 容器 */
  </div>

  <aside id="floating-panel">                  /* 360 × calc(100vh - 32px) */
    <header>                                   /* trip 标题 + 城市/天数/人群 */
    <div id="totals-row">                      /* 总距离 / 总时长 chip */
    <div id="day-filter">                      /* Day1 / Day2 / Day3 chip toggle */
    <ol id="day-list">                         /* day cards 流式淡入 */
      <li class="day-card" data-day="0">...</li>
      ...
    </ol>
  </aside>

  <a id="back-link">← 返回生成页</a>          /* 左下角返回 plan_stack */
</body>
```

**CSS 关键值**：
- `#floating-panel` — `position: absolute; top: 16px; left: 16px; z-index: 10; background: rgba(255,255,255,0.92); backdrop-filter: blur(8px); border-radius: 16px; padding: 20px; overflow-y: auto`
- `#day-filter chip` — 圆角胶囊, 选中态 = day color 实心, 未选中 = 灰边框
- `#totals-row chip` — 跟 day filter 同款，但显示文字（"22.4 km · 全程" / "11h · 游玩"）

### 5.2 Day 颜色编码

```js
const DAY_COLORS = ['#FF6B35', '#3D8BFD', '#10B981', '#A855F7', '#F59E0B'];
// 最多支持 5 天 (赛题硬约束 ≤ 5 天)
```

同色 = 同一天，用于：marker 颜色、polyline 颜色、day filter chip、day-card 左边框 4px。

### 5.3 流式淡入动画

```js
async function renderDaysProgressively(days) {
  for (let i = 0; i < days.length; i++) {
    const card = renderDayCard(days[i]);
    panel.appendChild(card);
    requestAnimationFrame(() => card.classList.add('fade-in'));
    await dropDayMarkers(days[i], i);          // markers 一个个 drop, 200ms 间隔
    await drawDayPolyline(days[i], i);         // polyline 浮现
    await sleep(300);                          // 每天间停顿
  }
}
```

CSS 动画细节：
- card 淡入：`opacity 0 → 1, translateY(8px) → 0, 400ms ease-out`
- marker drop：JSAPI `AMap.Marker.setAnimation('AMAP_ANIMATION_DROP')`
- polyline 浮现：`strokeOpacity 0 → 0.85, 600ms`

### 5.4 地图初始化

```js
async function initMap() {
  const cfg = await (await fetch('/api/config')).json();
  await loadJsApi(cfg.amap_web_js_key);        // 动态 inject script tag
  const map = new AMap.Map('map-container', {
    mapStyle: 'amap://styles/light',           // 浅色, 接近浮窗气质
    zoom: 12,
    viewMode: '2D',
  });
  AMap.plugin(['AMap.Driving'], () => {
    window._driving = new AMap.Driving({ map, hideMarkers: true, autoFitView: false });
  });
  return map;
}
```

### 5.5 Marker 渲染

```js
function dropDayMarkers(day, dayIndex) {
  return new Promise(resolve => {
    day.stops.forEach((stop, i) => {
      setTimeout(() => {
        const marker = new AMap.Marker({
          position: [stop.poi.longitude, stop.poi.latitude],
          content: `<div class="marker" style="background:${DAY_COLORS[dayIndex]}">${i + 1}</div>`,
          offset: new AMap.Pixel(-14, -28),
          animation: 'AMAP_ANIMATION_DROP',
        });
        marker.setMap(map);
        markersByDay[dayIndex].push(marker);
        if (i === day.stops.length - 1) resolve();
      }, i * 200);
    });
  });
}
```

### 5.6 真实路径 polyline（JSAPI Driving service）

```js
async function drawDayPolyline(day, dayIndex) {
  const stops = day.stops;
  if (stops.length < 2) return;
  const stopCoords = stops.map(s => [s.poi.longitude, s.poi.latitude]);
  const origin = stopCoords[0];
  const destination = stopCoords[stopCoords.length - 1];
  const waypoints = stopCoords.slice(1, -1).map(p => ({ location: p }));
  return new Promise((resolve) => {
    _driving.search(origin, destination, { waypoints }, (status, result) => {
      let pathLngLat;
      if (status === 'complete' && result.routes?.[0]) {
        // 提取 JSAPI 算出的真实街道路径坐标
        const route = result.routes[0];
        pathLngLat = route.steps.flatMap(s => s.path).map(p => [p.lng, p.lat]);
      } else {
        // fallback: 直线连两点 (5.7 在 8.3 列了风险)
        console.warn(`Driving.search failed for day ${dayIndex}, status=${status}, fallback to straight line`);
        pathLngLat = stopCoords;
      }
      const line = new AMap.Polyline({
        path: pathLngLat,
        strokeColor: DAY_COLORS[dayIndex],
        strokeWeight: 5,
        strokeOpacity: 0.85,
        showDir: true,
      });
      line.setMap(map);
      polylinesByDay[dayIndex] = line;          // 存 polyline 对象, 供 toggle 用
      resolve();
    });
  });
}
```

**注意**：`AMap.Driving` 默认会自动渲染 polyline + 起终点 marker。我们传 `hideMarkers: true` 隐藏默认 marker，并自己 new `AMap.Polyline` 用 day color 重画——这样能跟 day filter toggle 联动控制显隐。

### 5.7 总距离 / 总时长统计

```js
function computeTotals(days) {
  let totalKm = 0, totalMin = 0;
  for (const day of days) {
    for (const seg of day.transit_segments || []) {
      const rec = seg.options[seg.recommended];
      totalKm += rec.distance_km;
      totalMin += rec.minutes;
    }
  }
  return {
    distance: totalKm.toFixed(1) + ' km',
    duration: Math.round(totalMin / 60) + ' h',
  };
}
```

**数据来源**：v2 已经在 `transit.updated` 事件里把每个 segment 的 4 模式 transit 数据写进了 `ctx.draft_route` 的某处。**需要 verify** `GET /api/plan/{trip_id}` 返回的 trip 数据是否包含 transit_segments。

> **TODO during implementation**: 跑 `curl /api/plan/{trip_id}` 看 schema, 如 transit 数据没在 ctx 持久化, 需要在 routes.py 把 transit segments 存到 `day.transit_segments`。

### 5.8 Day filter toggle

```js
dayFilterChip.onclick = (e) => {
  const dayIndex = parseInt(e.target.dataset.day);
  const visible = !markersByDay[dayIndex][0].getMap();
  markersByDay[dayIndex].forEach(m => visible ? m.setMap(map) : m.setMap(null));
  polylinesByDay[dayIndex].setMap(visible ? map : null);
  e.target.classList.toggle('active', visible);
  // 重新计算 totals: 仅 sum 当前可见的天 (5.7 的 computeTotals 接受 days 子集参数)
  const visibleDays = days.filter((_, i) => markersByDay[i][0]?.getMap());
  renderTotals(computeTotals(visibleDays));
};
```

### 5.9 plan_stack.html 改动（最小）

在 `trip.complete` SSE 事件 handler 里加 4 行：

```js
case 'trip.complete':
  // ... 现有逻辑
  const mapBtn = document.createElement('a');
  mapBtn.href = `/map?trip_id=${data.trip_id}`;
  mapBtn.target = '_blank';
  mapBtn.textContent = '🗺️ 在地图上看完整路线';
  mapBtn.className = 'map-cta';   // 新 CSS class, 顶部居中圆角按钮
  document.querySelector('#timeline-section').prepend(mapBtn);
  break;
```

---

## 6 · Data Flow

```
1. User submits free_text 在 plan_stack.html
2. SSE 流式生成 trip → trip.complete 事件 (含 trip_id)
3. 顶部出现 "🗺️ 在地图上看完整路线" 按钮
4. 用户点击 → /map?trip_id=xxx 新窗口
5. /map 页面:
   a. fetch /api/config → amap_web_js_key
   b. 动态 load JSAPI script
   c. fetch /api/plan/{trip_id} → trip JSON
   d. 渲染浮窗 (静态布局)
   e. 流式动画: forEach day → drop markers → draw polyline
   f. 总距离/时长 chip 渲染
   g. day filter chip 绑定 toggle
```

---

## 7 · Error Handling

| 失败场景 | 处理 |
|---|---|
| `/api/config` 返回空 amap_web_js_key | 浮窗显示 "地图服务未配置, 请联系管理员", 不加载 JSAPI |
| `/api/plan/{trip_id}` 404 | 浮窗显示 "trip 不存在或已过期", 提供返回链接 |
| JSAPI 加载失败 (网络/CDN) | 浮窗仍正常显示, 地图区域显示 fallback "地图加载失败, 请刷新" |
| `AMap.Driving.search` 失败某段 | 该 segment 改用直线 polyline (`AMap.Polyline` 直接连两点) + `console.warn` |
| POI 缺 lat/lng (理论不可能, 防御) | 跳过该 marker, 该天 polyline 跳过该 stop |
| transit_segments 数据缺失 | totals chip 显示 "—", 不阻塞地图渲染 |

---

## 8 · Testing

### 8.1 后端自动化（pytest）
- `test_map_view_returns_html` — `GET /map` 返回 200 + content-type=text/html
- `test_public_config_returns_amap_key` — `GET /api/config` 返回 dict 含 `amap_web_js_key` 字段（值可空, 测试只验 key 存在）

### 8.2 前端手动验收（hackathon scope）
检查清单（demo 前必跑）：
1. trip 生成完毕，按钮出现，点击新窗口打开 `/map?trip_id=xxx`
2. 地图加载 ≤ 3s（JSAPI + 自定义 mapStyle）
3. 浮窗按 day 顺序淡入，每天 markers drop 进来
4. 每天 polyline 沿真实街道画出（不是直线）
5. 同一天的 marker / polyline / day chip 颜色一致
6. 点 day chip 切换显隐生效
7. 总距离/时长 chip 数字合理（西安 3 天 ~10-30 km）
8. 浏览器 console 无 error

### 8.3 风险点（implementation 时验）
- transit_segments 数据是否在 trip JSON 里 → 5.7 节有 TODO
- AMap.Driving waypoints 数量上限（实测 16 个）→ 单天 stops > 16 时分段调用，hackathon trip 单天 ≤ 7 stops 不会触发

---

## 9 · Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `AMAP_WEB_JS_KEY` 域名限制未配, 上 demo 域名后地图加载失败 | 中 | 部署前在高德控制台加 referrer 白名单 |
| JSAPI Driving 在某段 (尤其偏远 POI) 找不到路径 | 低 | fallback 直线 polyline + warn |
| `_driving.search` 串行 N 段 (N = 总天数) 慢 | 低 | 西安 3 天 = 3 次调用 ~1-2s, 可接受。如慢可改 `Promise.all` 并发 |
| 流式动画与用户操作冲突 (动画过程中点 day chip) | 低 | 动画期间禁用 chip, 完成后启用 |
| 移动端打开布局错乱 | 中 | spec 范围明确仅桌面, demo 不演移动端 |

---

## 10 · Decisions Made (sign-off 记录)

1. **路由**：plan_stack.html 完成后顶部按钮 → 新窗口跳 `/map`，不替换现页面 → 评委体验"流式生成 → 跳地图"两段剧场感
2. **路径数据**：JSAPI `AMap.Driving` 服务（前端调用），不在后端抓 polyline 字段 → 配额池分离 + 实现简单
3. **地图样式**：高德 `amap://styles/light`，不画自家手绘底图 → 真实感优先
4. **scope #1234 in, #56 out**：层 toggle / chat input 不做
5. **流式动画**：浮窗 day card + 地图 marker / polyline 同步淡入 drop → 评委有"AI 正在画路线"剧场感
6. **POI 数据契约不动**：`PoiCard` distilled view 是 hackathon 后单独 backlog
7. **测试**：后端 2 个自动化 + 前端手动验收，不上 Playwright

---

## 11 · Backlog (out of scope, follow-up)

| 项 | 触发条件 |
|---|---|
| Marker ↔ card 双向高亮同步 | 主线全跑通后, 视觉打磨阶段 |
| Layer toggle (类型筛选) | 用户实际反馈"我想只看餐饮" |
| Chat input "再调整一下" | Adjuster 功能立项 |
| 移动端响应式 | 评委要求 / 上线前 |
| LLM prompt 缩窄字段 (Plan C, 见 brainstorm) | v1.6 完成后 |
| Distilled `PoiCard` schema (Plan B) | hackathon 后, 接真实大众点评 API 时 |
| 离线 review summarize (Plan D) | hackathon 后 |

---

## 12 · File Manifest

**新增**：
- `web/map.html` (~280 行 HTML + JS)
- `tests/test_map_view.py` (~30 行)

**改动**：
- `api/main.py` (+15 行: `/map` + `/api/config` 路由)
- `web/plan_stack.html` (+8 行: trip.complete 加按钮)

**不改**：
- `agents/amap.py` ✓
- `api/routes.py` ✓
- `dianping/schemas.py` ✓
- 任何 agent / planner / profiler 代码 ✓
