"""v1.9 Refine: POST /api/plan/{trip_id}/refine SSE 集成测试.

策略: monkeypatch resolve_profiler_llm 让 Refiner 拿到固定 JSON,
不实际调外部 LLM. 验 endpoint 调度 (profile 写 / adjust 触发 / SSE 事件).
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


def _mk_poi(oid, name, *, role="meal") -> POI:
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
        city_zone="A",
        manual_priority=50,
        planning_tags=[],
    )
    return poi


def _mk_stop(poi, slot, sh, eh) -> Stop:
    return Stop(
        poi=poi,
        slot=TimeSlot(name=slot, start=time(sh, 0), end=time(eh, 0)),
        arrival_time=time(sh, 0),
        leave_time=time(eh, 0),
    )


def _save_trip(stops) -> str:
    ctx = TripContext.create(user_input=UserInput(free_text="t"))
    ctx.intent = ParsedIntent(city="深圳", days=1, traveler_type="情侣")
    ctx.draft_route = RouteDraft(
        days=[DayPlan(day_index=0, anchor_district="A", stops=stops)]
    )
    ctx.save()
    return ctx.trip_id


def _parse_events(text: str) -> list[dict]:
    out = []
    for blk in text.strip().split("\n\n"):
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


def _patch_refiner_llm(monkeypatch, response: dict):
    """让 Refiner 拿到固定 JSON response."""

    async def _fake(system: str, user: str) -> str:
        return json.dumps(response, ensure_ascii=False)

    monkeypatch.setattr("api.routes.resolve_profiler_llm", lambda: _fake)


def test_refine_profile_only_path(sse_app_client, monkeypatch):
    """纯偏好 → refine.profile_updated 发, adjust.* 不出现."""
    a = _mk_poi("A", "大雁塔", role="city_essential")
    b = _mk_poi("B", "午饭店", role="meal")
    trip_id = _save_trip([_mk_stop(a, "上午景点", 9, 11), _mk_stop(b, "午饭", 12, 13)])

    _patch_refiner_llm(
        monkeypatch,
        {
            "reasoning": "记下博物馆偏好",
            "profile_update": {
                "interests_text_append": "博物馆",
                "modifiers_set": {"重文化": True},
            },
            "adjust": None,
            "chat_reply": None,
        },
    )

    resp = sse_app_client.post(
        f"/api/plan/{trip_id}/refine",
        json={"user_text": "他喜欢博物馆"},
    )
    assert resp.status_code == 200
    events = _parse_events(resp.text)
    names = [e["event"] for e in events]

    assert "refine.thinking" in names
    assert "refine.routed" in names
    assert "refine.profile_updated" in names
    assert "refine.done" in names
    # 不应出现 adjust.*
    assert not any(n.startswith("adjust.") for n in names)

    # GET /user/profile 应能拿到新偏好 (sse_app_client 复用 cookie)
    prof_resp = sse_app_client.get("/api/user/profile")
    prof = prof_resp.json()
    assert prof is not None
    assert prof["modifiers"].get("重文化") is True
    assert "博物馆" in prof["interests_text"]


def test_refine_adjust_only_path(sse_app_client, monkeypatch):
    """纯调整 (remove_stop) → adjust.stop_removed 出现, refine.profile_updated 不出现."""
    a = _mk_poi("A", "上午", role="city_essential")
    b = _mk_poi("B", "午饭店", role="meal")
    trip_id = _save_trip([_mk_stop(a, "上午景点", 9, 11), _mk_stop(b, "午饭", 12, 13)])

    _patch_refiner_llm(
        monkeypatch,
        {
            "reasoning": "好, 删掉午饭",
            "profile_update": None,
            "adjust": {
                "operation": "remove_stop",
                "day_index": 0,
                "slot_name": "午饭",
                "variant": "",
                "user_hint": "",
            },
            "chat_reply": None,
        },
    )

    resp = sse_app_client.post(
        f"/api/plan/{trip_id}/refine",
        json={"user_text": "把午饭删了"},
    )
    assert resp.status_code == 200
    events = _parse_events(resp.text)
    names = [e["event"] for e in events]

    assert "refine.thinking" in names
    assert "refine.routed" in names
    assert "adjust.stop_removed" in names
    assert "refine.done" in names
    assert "refine.profile_updated" not in names

    removed = next(e for e in events if e["event"] == "adjust.stop_removed")
    assert removed["data"]["slot_name"] == "午饭"


def test_refine_combined_profile_and_adjust(sse_app_client, monkeypatch):
    """同句两件事 → refine.profile_updated 和 adjust.stop_removed 都出现."""
    a = _mk_poi("A", "上午", role="city_essential")
    b = _mk_poi("B", "午饭店", role="meal")
    trip_id = _save_trip([_mk_stop(a, "上午景点", 9, 11), _mk_stop(b, "午饭", 12, 13)])

    _patch_refiner_llm(
        monkeypatch,
        {
            "reasoning": "记下博物馆偏好, 同时删掉午饭",
            "profile_update": {
                "interests_text_append": "博物馆",
                "modifiers_set": {"重文化": True},
            },
            "adjust": {
                "operation": "remove_stop",
                "day_index": 0,
                "slot_name": "午饭",
                "variant": "",
                "user_hint": "",
            },
            "chat_reply": None,
        },
    )

    resp = sse_app_client.post(
        f"/api/plan/{trip_id}/refine",
        json={"user_text": "他喜欢博物馆, 把午饭删了"},
    )
    assert resp.status_code == 200
    events = _parse_events(resp.text)
    names = [e["event"] for e in events]

    assert "refine.profile_updated" in names
    assert "adjust.stop_removed" in names
    assert "refine.done" in names

    routed = next(e for e in events if e["event"] == "refine.routed")
    assert "profile" in routed["data"]["actions"]
    assert "adjust" in routed["data"]["actions"]


def test_refine_chat_reply_only(sse_app_client, monkeypatch):
    """无法路由 → refine.chat_reply 出现, profile/adjust 不出现."""
    a = _mk_poi("A", "上午", role="city_essential")
    trip_id = _save_trip([_mk_stop(a, "上午景点", 9, 11)])

    _patch_refiner_llm(
        monkeypatch,
        {
            "reasoning": "新增站点暂时不支持",
            "profile_update": None,
            "adjust": None,
            "chat_reply": "暂时还不能加新站",
        },
    )

    resp = sse_app_client.post(
        f"/api/plan/{trip_id}/refine",
        json={"user_text": "再加一个夜景"},
    )
    assert resp.status_code == 200
    events = _parse_events(resp.text)
    names = [e["event"] for e in events]

    assert "refine.chat_reply" in names
    assert "refine.profile_updated" not in names
    assert not any(n.startswith("adjust.") for n in names)

    chat = next(e for e in events if e["event"] == "refine.chat_reply")
    assert "新站" in chat["data"]["text"]


def test_refine_unknown_trip_404(sse_app_client, monkeypatch):
    _patch_refiner_llm(monkeypatch, {"reasoning": "x", "chat_reply": "x"})
    resp = sse_app_client.post(
        "/api/plan/trip_nonexistent/refine",
        json={"user_text": "test"},
    )
    assert resp.status_code == 404


def test_refine_empty_text_400(sse_app_client, monkeypatch):
    a = _mk_poi("A", "上午", role="city_essential")
    trip_id = _save_trip([_mk_stop(a, "上午景点", 9, 11)])
    _patch_refiner_llm(monkeypatch, {"reasoning": "x"})
    resp = sse_app_client.post(
        f"/api/plan/{trip_id}/refine",
        json={"user_text": "   "},
    )
    assert resp.status_code == 400


def test_refine_modifier_merge_preserves_existing(sse_app_client, monkeypatch):
    """已有 profile 的 modifiers 在 refine 后应保留, 新的合并进去."""
    a = _mk_poi("A", "上午", role="city_essential")
    trip_id = _save_trip([_mk_stop(a, "上午景点", 9, 11)])

    # 先 PUT 一个 profile
    sse_app_client.put(
        "/api/user/profile",
        json={"modifiers": {"重美食": True}, "interests_text": "咖啡馆"},
    )

    _patch_refiner_llm(
        monkeypatch,
        {
            "reasoning": "再加重文化",
            "profile_update": {
                "interests_text_append": "博物馆",
                "modifiers_set": {"重文化": True},
            },
            "adjust": None,
            "chat_reply": None,
        },
    )

    resp = sse_app_client.post(
        f"/api/plan/{trip_id}/refine",
        json={"user_text": "他也喜欢博物馆"},
    )
    assert resp.status_code == 200

    prof = sse_app_client.get("/api/user/profile").json()
    # 老的 重美食 保留 + 新的 重文化 加进来
    assert prof["modifiers"].get("重美食") is True
    assert prof["modifiers"].get("重文化") is True
    # 老的 interests_text 也保留
    assert "咖啡馆" in prof["interests_text"]
    assert "博物馆" in prof["interests_text"]
