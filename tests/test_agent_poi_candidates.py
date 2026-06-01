"""Smoke tests for mtagentv2 POI-first candidate endpoint."""


def test_agent_poi_candidates_returns_grouped_pois(sse_app_client):
    resp = sse_app_client.post(
        "/api/agent/poi-candidates",
        json={
            "free_text": "上海半日游，想吃点本地美食，也想看景点",
            "traveler_type": "独行",
            "pace": "适中",
            "interests": ["美食", "景点"],
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["trip_id"].startswith("trip_")
    assert data["intent"]["city"] == "上海"
    assert set(data["groups"]) == {"attractions", "food", "entertainment"}
    assert any(data["groups"].values()), "at least one POI group should be populated"

    first_group = next(group for group in data["groups"].values() if group)
    first = first_group[0]
    assert {"openshopid", "name", "latitude", "longitude", "categories"} <= set(first)


def test_agent_poi_candidates_includes_ugc_decision_signals(sse_app_client):
    resp = sse_app_client.post(
        "/api/agent/poi-candidates",
        json={
            "free_text": "上海一日情侣美食拍照，不想排队",
            "traveler_type": "情侣",
            "pace": "适中",
            "interests": ["美食", "拍照"],
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    pois = [poi for group in data["groups"].values() for poi in group]
    signaled = [poi for poi in pois if poi.get("decision_signals")]

    assert signaled, "at least one candidate should expose UGC decision signals"
    signals = signaled[0]["decision_signals"]
    assert {"queue_risk", "best_time", "agent_advice", "evidence"} <= set(signals)
    assert signals["evidence"], "decision signals should show UGC-derived evidence"
