"""v1.7 即时出发: SSE 集成测试.

走完整 /api/plan/stream → profiler.understood → 检测 time_window → 走 instant 分流
→ emit 三 variant. 用 stub_planner_llm_stream (fallback synthesis 出 stops).

不依赖真 LLM. 用 sse_app_client fixture (in-process FastAPI + MockTransport).
"""

from __future__ import annotations

import json

import pytest


def _parse_sse(body: str):
    """Split SSE body to list of (event_name, data_dict)."""
    out = []
    cur_event = None
    cur_data = ""
    for line in body.splitlines():
        if line.startswith("event:"):
            cur_event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            cur_data = line[len("data:") :].strip()
        elif line == "":
            if cur_event:
                try:
                    out.append((cur_event, json.loads(cur_data)))
                except Exception:
                    out.append((cur_event, {"_raw": cur_data}))
                cur_event = None
                cur_data = ""
    return out


def test_instant_window_triggers_variant_path(sse_app_client):
    """半天关键词 → time_window=半日_下午 → 走 instant → 收到 variant.queued + 3 variant.done."""
    resp = sse_app_client.post(
        "/api/plan/stream",
        json={"free_text": "情侣 西安 半天 拍照"},
    )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    names = [e[0] for e in events]
    assert "variant.queued" in names, f"未触发 v1.7 instant 路径. events={names}"
    # main + 2 branches done
    assert names.count("variant.main_done") == 1
    assert names.count("variant.branch_done") == 2


def test_instant_each_variant_has_day_done(sse_app_client):
    """每个 variant 至少一个 day_done with variant 字段."""
    resp = sse_app_client.post(
        "/api/plan/stream",
        json={"free_text": "情侣 西安 半天 拍照"},
    )
    events = _parse_sse(resp.text)
    day_done_by_variant: dict[str, list] = {}
    for ev, data in events:
        if ev == "planner.day_done":
            v = data.get("variant")
            day_done_by_variant.setdefault(v, []).append(data)
    assert set(day_done_by_variant.keys()) == {"main", "low_queue", "interest_first"}, (
        f"未收齐三 variant 的 day_done, got {set(day_done_by_variant.keys())}"
    )


def test_instant_variant_stops_differ(sse_app_client):
    """main 和 low_queue 的 stops 至少 1 个 POI 不同 (scorer 真有差异)."""
    resp = sse_app_client.post(
        "/api/plan/stream",
        json={"free_text": "情侣 西安 半天 拍照"},
    )
    events = _parse_sse(resp.text)
    stops_by_variant: dict[str, list] = {}
    for ev, data in events:
        if ev == "planner.day_done":
            v = data.get("variant")
            stops_by_variant[v] = [s["poi_openshopid"] for s in data["stops"]]
    main_set = set(stops_by_variant.get("main", []))
    low_set = set(stops_by_variant.get("low_queue", []))
    assert main_set ^ low_set, "main 和 low_queue stops 完全相同 — scorer 失效"


def test_instant_trip_complete_mode_field(sse_app_client):
    """trip.complete 含 mode='instant' 标识."""
    resp = sse_app_client.post(
        "/api/plan/stream",
        json={"free_text": "情侣 西安 半天"},
    )
    events = _parse_sse(resp.text)
    for ev, data in events:
        if ev == "trip.complete":
            assert data.get("mode") == "instant"
            return
    pytest.fail("no trip.complete event seen")


def test_multi_day_still_goes_old_path(sse_app_client):
    """多日输入 (days=3) 仍走 v1.6 老路径, 不触发 variant.queued."""
    resp = sse_app_client.post(
        "/api/plan/stream",
        json={"free_text": "深圳 3 天情侣预算 3000 爱拍照"},
    )
    events = _parse_sse(resp.text)
    names = [e[0] for e in events]
    assert "variant.queued" not in names, "多日不应触发 instant 路径"
    # 仍要看到 v1.6 老 day_done
    assert any(ev == "planner.day_done" for ev, _ in events)


def test_instant_persists_variants_to_trip(sse_app_client):
    """SSE 完成后 GET /api/plan/{trip_id} 应含 variants dict."""
    resp = sse_app_client.post(
        "/api/plan/stream",
        json={"free_text": "情侣 西安 半天 拍照"},
    )
    events = _parse_sse(resp.text)
    trip_id = None
    for ev, data in events:
        if ev == "trip.started":
            trip_id = data["trip_id"]
            break
    assert trip_id is not None

    r2 = sse_app_client.get(f"/api/plan/{trip_id}")
    assert r2.status_code == 200
    ctx_data = r2.json()
    variants = ctx_data.get("variants")
    assert variants is not None and set(variants.keys()) == {
        "main",
        "low_queue",
        "interest_first",
    }
    # draft_route should mirror main (老前端 GET 兼容)
    assert ctx_data.get("draft_route") is not None
