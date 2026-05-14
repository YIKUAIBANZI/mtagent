"""v1.9 Stage 3: POST /api/plan/{trip_id}/adjust SSE 集成测试.

预先 ctx.save() 一个 trip 到 MTAGENT_TRIPS_DIR (sse_app_client fixture 已设),
然后 POST adjust 各 operation, 验事件流.
"""

from __future__ import annotations

import json
from datetime import time


from agents.context import TripContext
from dianping.schemas import (
    DayPlan,
    EnrichedLabel,
    ParsedIntent,
    POI,
    RouteDraft,
    Stop,
    TimeSlot,
    UserInput,
)


def _mk_poi(oid, name, *, role="meal", zone="A") -> POI:
    poi = POI(
        openshopid=oid,
        name=name,
        city="深圳",
        latitude=22.54,
        longitude=113.95,
        categories=["美食"] if role == "meal" else ["景点"],
    )
    poi.enriched = EnrichedLabel(
        poi_role=role,
        city_zone=zone,
        manual_priority=50,
        planning_tags=[],
    )
    return poi


def _mk_slot(name, sh, eh) -> TimeSlot:
    return TimeSlot(name=name, start=time(sh, 0), end=time(eh, 0))


def _mk_stop(poi, slot, sh, eh) -> Stop:
    return Stop(
        poi=poi,
        slot=_mk_slot(slot, sh, eh),
        arrival_time=time(sh, 0),
        leave_time=time(eh, 0),
    )


def _save_trip(stops, variants=None) -> str:
    ctx = TripContext.create(user_input=UserInput(free_text="t"))
    ctx.intent = ParsedIntent(city="深圳", days=1, traveler_type="情侣")
    ctx.draft_route = RouteDraft(
        days=[DayPlan(day_index=0, anchor_district="A", stops=stops)]
    )
    if variants is not None:
        ctx.variants = variants
        ctx.draft_route = variants["main"]
    ctx.save()
    return ctx.trip_id


def _parse_events(text: str) -> list[dict]:
    out = []
    blocks = text.strip().split("\n\n")
    for blk in blocks:
        ev = {"data": None, "event": None}
        for line in blk.splitlines():
            if line.startswith("event:"):
                ev["event"] = line[len("event:") :].strip()
            elif line.startswith("data:"):
                try:
                    ev["data"] = json.loads(line[len("data:") :].strip())
                except Exception:
                    ev["data"] = line[len("data:") :].strip()
        if ev["event"]:
            out.append(ev)
    return out


def test_adjust_remove_stop_emits_correct_sse(sse_app_client, tmp_path, monkeypatch):
    a = _mk_poi("A", "A", role="city_essential")
    b = _mk_poi("B", "B", role="meal")
    trip_id = _save_trip([_mk_stop(a, "上午景点", 9, 11), _mk_stop(b, "午饭", 12, 13)])

    resp = sse_app_client.post(
        f"/api/plan/{trip_id}/adjust",
        json={"operation": "remove_stop", "day_index": 0, "slot_name": "午饭"},
    )
    assert resp.status_code == 200
    events = _parse_events(resp.text)
    names = [e["event"] for e in events]
    assert "adjust.thinking" in names
    assert "adjust.stop_removed" in names
    assert "adjust.done" in names
    removed = next(e for e in events if e["event"] == "adjust.stop_removed")
    assert removed["data"]["slot_name"] == "午饭"
    assert len(removed["data"]["new_day_plan"]["stops"]) == 1


def test_adjust_switch_variant_emits_correct_sse(sse_app_client):
    a = _mk_poi("A", "A", role="city_essential")
    b = _mk_poi("B", "B", role="city_essential")
    main = RouteDraft(
        days=[DayPlan(day_index=0, stops=[_mk_stop(a, "上午景点", 9, 11)])]
    )
    lq = RouteDraft(days=[DayPlan(day_index=0, stops=[_mk_stop(b, "上午景点", 9, 11)])])
    trip_id = _save_trip(
        [_mk_stop(a, "上午景点", 9, 11)], variants={"main": main, "low_queue": lq}
    )

    resp = sse_app_client.post(
        f"/api/plan/{trip_id}/adjust",
        json={"operation": "switch_variant", "variant": "low_queue"},
    )
    assert resp.status_code == 200
    events = _parse_events(resp.text)
    names = [e["event"] for e in events]
    assert "adjust.variant_switched" in names
    sw = next(e for e in events if e["event"] == "adjust.variant_switched")
    assert sw["data"]["variant"] == "low_queue"
    # ctx 持久化后 draft_route 应已切到 low_queue
    ctx_after = TripContext.load(trip_id)
    assert ctx_after.draft_route.days[0].stops[0].poi.openshopid == "B"


def test_adjust_unknown_trip_404(sse_app_client):
    resp = sse_app_client.post(
        "/api/plan/trip_nonexistent/adjust",
        json={"operation": "switch_variant", "variant": "main"},
    )
    assert resp.status_code == 404


def test_adjust_invalid_body_400(sse_app_client):
    # 先建一个有效 trip
    a = _mk_poi("A", "A")
    trip_id = _save_trip([_mk_stop(a, "上午景点", 9, 11)])
    resp = sse_app_client.post(
        f"/api/plan/{trip_id}/adjust",
        json={"operation": "not_a_real_op"},
    )
    assert resp.status_code == 400


def test_adjust_replace_stop_pool_path(sse_app_client, monkeypatch, tmp_path):
    """cache 空 → 落 pool. 用 env 把 cache 指向空临时文件."""
    # 临时空 cache
    empty_cache = tmp_path / "empty_cache.json"
    empty_cache.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("MTAGENT_POI_CACHE_PATH", str(empty_cache))

    a = _mk_poi("OLD", "旧店", role="meal", zone="A")
    backup = _mk_poi("BACKUP", "Pool 替代", role="meal", zone="A")

    ctx = TripContext.create(user_input=UserInput(free_text="t"))
    ctx.intent = ParsedIntent(city="深圳", days=1, traveler_type="情侣")
    ctx.draft_route = RouteDraft(
        days=[
            DayPlan(
                day_index=0, anchor_district="A", stops=[_mk_stop(a, "午饭", 12, 13)]
            )
        ]
    )
    ctx.candidate_pois = [backup]
    ctx.save()
    trip_id = ctx.trip_id

    resp = sse_app_client.post(
        f"/api/plan/{trip_id}/adjust",
        json={"operation": "replace_stop", "day_index": 0, "slot_name": "午饭"},
    )
    assert resp.status_code == 200
    events = _parse_events(resp.text)
    names = [e["event"] for e in events]
    assert "adjust.stop_replaced" in names
    rep = next(e for e in events if e["event"] == "adjust.stop_replaced")
    assert rep["data"]["source"] == "pool"
    assert rep["data"]["new_stop"]["poi"]["openshopid"] == "BACKUP"
