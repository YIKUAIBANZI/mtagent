# mtagent2

Clean runtime fork for the hackathon demo.

## Product Spine

```text
一句话输入
-> 10s 内生成 main route V1
-> mtagentv2 页面展示路线 / POI 候选 / Agent 说明
-> 用户点选 POI 或对话修改路线
-> Agent 基于候选池和 UGC 决策信号替换 / 重排
-> 地图和路线同步更新
```

## Main Entry

```bash
PYTHONPATH=. uvicorn api.main:app --host 127.0.0.1 --port 9191
```

Open:

```text
http://127.0.0.1:9191/
```

`/` and `/map` both route to the current `mtagentv2` app. The old `web/`
prototype is intentionally not copied into this fork.

## Kept Runtime Surface

- `api/` - FastAPI app, SSE routes, route adjustment endpoints.
- `agents/` - profiler, instant planner, candidate pool, adjuster, refiner.
- `dianping/` - POI and route schemas plus mock-compatible client.
- `mtagentv2/` - only frontend surface for new work.
- `data/mock_dianping/` - local POI runtime data.
- `data/poi_enriched_labels.json` - final planner label input.
- `data/poi_labels.json` and `data/tag_mapping.json` - compatibility inputs.
- `data/real_sources/` - UGC/source evidence for the next decision-signal layer.

## Not Copied On Purpose

- Old `web/plan_stack.html` and `web/map.html` prototypes.
- Historical `docs/superpowers/*` plan/spec backlog.
- `data_generator/`, `scripts/`, deploy files, caches, venv, and pycache.

## Fast Checks

```bash
MTAGENT_SKIP_DOTENV=1 PYTHONPATH=. /Users/yikuaibanz1/Desktop/sth/mtagent/venv/bin/pytest \
  tests/test_api_health.py \
  tests/test_map_view.py \
  tests/test_agent_poi_candidates.py \
  tests/test_adjust_route.py -q

node tests/frontend/test_mtagentv2_route_first.mjs
```
