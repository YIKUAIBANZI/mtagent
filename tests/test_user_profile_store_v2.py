from dianping.schemas import POI, EnrichedLabel


def test_apply_signal_visited(tmp_path, monkeypatch):
    monkeypatch.setenv("MTAGENT_USER_PROFILES_DIR", str(tmp_path))
    from agents.user_profile_store import apply_signal, get_profile

    apply_signal("ck1", "visited", poi_name="外滩")
    assert "外滩" in get_profile("ck1").user_marked.been_there


def test_apply_signal_reject_records_risk_tags(tmp_path, monkeypatch):
    monkeypatch.setenv("MTAGENT_USER_PROFILES_DIR", str(tmp_path))
    from agents.user_profile_store import apply_signal, get_profile

    poi = POI(
        openshopid="x",
        name="某火锅",
        city="上海",
        latitude=31.2,
        longitude=121.4,
        enriched=EnrichedLabel(risk_tags=["queue_heavy"]),
    )
    apply_signal("ck2", "reject", poi=poi)
    assert "queue_heavy" in get_profile("ck2").rejected_tags


def test_save_profile_atomic_no_tmp_left(tmp_path, monkeypatch):
    monkeypatch.setenv("MTAGENT_USER_PROFILES_DIR", str(tmp_path))
    from agents.user_profile_store import apply_signal

    apply_signal("ck3", "visited", poi_name="豫园")
    # 原子写不应残留 .tmp 文件
    assert not list(tmp_path.glob("*.tmp"))
    assert (tmp_path / "ck3.json").exists()
