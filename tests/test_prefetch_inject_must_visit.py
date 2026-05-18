"""v1.10: _prefetch_amap_pois mutate ctx.intent.must_visit (model_copy 不再隔离).

根因 (server log 实证): 函数中段 `intent = intent.model_copy(...)` 重新绑定
local var, 之后 inject 改 must_visit 是改副本, caller 的 ctx.intent 没变.
"""

import pytest

from agents.anchor import AroundPOI
from dianping.schemas import ParsedIntent, RequiredSlot, WaypointResolution


def _make_intent():
    return ParsedIntent(
        city="南昌",
        days=1,
        traveler_type="情侣",
        time_window="一日",
        trip_mode="anchor_explore",
        anchor_lng=115.904,
        anchor_lat=28.673,
        anchor_radius_km=2.0,
        must_visit=["八一广场", "南昌博物馆"],
        required_slots=[
            RequiredSlot(slot_name="午饭", categories=["南昌拌粉"]),
        ],
        geocoded_waypoints=[
            WaypointResolution(
                text="八一广场",
                name="八一广场",
                lng=115.904,
                lat=28.673,
            ),
            WaypointResolution(
                text="南昌博物馆",
                name="南昌博物馆",
                lng=115.881,
                lat=28.706,
            ),
        ],
    )


@pytest.mark.asyncio
async def test_prefetch_mutates_caller_intent_must_visit(monkeypatch):
    """关键词 '南昌博物馆' 命中 '江西省博物馆' → append 进 caller 的 intent.must_visit.

    回归条件: id(intent) 必须保持不变, 否则证明函数体中段 model_copy 重新绑定了.
    """
    from api.routes import _prefetch_amap_pois

    intent = _make_intent()
    initial_id = id(intent)

    async def _empty_around(*a, **kw):
        return []

    async def _fake_text_search(keyword, city, limit=8):
        if keyword == "南昌博物馆":
            return [
                AroundPOI(
                    name="江西省博物馆",
                    lng=115.881,
                    lat=28.706,
                    typecode="140100",
                    distance_m=0,
                    address="",
                )
            ]
        return []

    monkeypatch.setattr("agents.anchor.fetch_around", _empty_around)
    monkeypatch.setattr("agents.anchor.text_search", _fake_text_search)

    await _prefetch_amap_pois(intent, [])

    # caller 视角必须看到 mutation
    assert "江西省博物馆" in intent.must_visit, (
        f"expected '江西省博物馆' in must_visit, got: {intent.must_visit}"
    )
    # 且 intent 仍是原对象, 没被 model_copy 替换 (P0.1 根因守卫)
    assert id(intent) == initial_id, (
        "_prefetch_amap_pois must NOT rebind intent — "
        "if you saw this fail, someone re-introduced `intent = intent.model_copy(...)`"
    )


@pytest.mark.asyncio
async def test_prefetch_landmark_must_mode_still_runs_text_search(monkeypatch):
    """landmark_must 模式 (无 anchor 坐标) 仍要跑 text_search inject.

    profiler 对同样输入可能输出 anchor_explore 或 landmark_must, 用户体验必须一致 —
    博物馆/拌粉这类关键词总能进 pool, 不依赖 trip_mode.
    """
    from api.routes import _prefetch_amap_pois

    intent = ParsedIntent(
        city="南昌",
        days=1,
        traveler_type="情侣",
        time_window="一日",
        trip_mode="landmark_must",
        anchor_lng=None,
        anchor_lat=None,
        must_visit=["八一广场", "南昌博物馆"],
        required_slots=[RequiredSlot(slot_name="午饭", categories=["南昌拌粉"])],
    )

    async def _fake_text_search(keyword, city, limit=8):
        mapping = {
            "南昌博物馆": [
                AroundPOI(
                    name="江西省博物馆",
                    lng=115.881,
                    lat=28.706,
                    typecode="140100",
                    distance_m=0,
                    address="",
                )
            ],
            "南昌拌粉": [
                AroundPOI(
                    name="雪三娘南昌拌粉",
                    lng=115.908,
                    lat=28.671,
                    typecode="050700",
                    distance_m=0,
                    address="",
                )
            ],
        }
        return mapping.get(keyword, [])

    monkeypatch.setattr("agents.anchor.text_search", _fake_text_search)

    result = await _prefetch_amap_pois(intent, [])

    assert result is not None, "landmark_must with keywords must NOT return None"
    names = [p.name for p in result]
    assert "江西省博物馆" in names, f"博物馆 missing: {names}"
    assert "雪三娘南昌拌粉" in names, f"拌粉 missing: {names}"
    assert "江西省博物馆" in intent.must_visit, (
        f"must_visit not mutated: {intent.must_visit}"
    )
