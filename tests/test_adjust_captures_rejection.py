def test_capture_rejection_helper(tmp_path, monkeypatch):
    monkeypatch.setenv("MTAGENT_USER_PROFILES_DIR", str(tmp_path))
    from dianping.schemas import POI, EnrichedLabel
    from api.services.adjust import _capture_rejection
    from agents.user_profile_store import get_profile

    old_poi = POI(
        openshopid="x",
        name="某排队店",
        city="上海",
        latitude=31.2,
        longitude=121.4,
        enriched=EnrichedLabel(risk_tags=["queue_heavy"]),
    )
    _capture_rejection("ckA", old_poi)
    assert "queue_heavy" in get_profile("ckA").rejected_tags


def test_capture_rejection_noop_on_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("MTAGENT_USER_PROFILES_DIR", str(tmp_path))
    from api.services.adjust import _capture_rejection

    # 空 cookie / None poi 不应抛错
    _capture_rejection("", None)
    _capture_rejection("ckB", None)
