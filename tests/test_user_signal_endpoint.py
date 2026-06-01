def test_signal_endpoint_visited(tmp_path, monkeypatch):
    monkeypatch.setenv("MTAGENT_SKIP_DOTENV", "1")
    monkeypatch.setenv("MTAGENT_AMAP_DISABLED", "1")
    monkeypatch.setenv("MTAGENT_USER_PROFILES_DIR", str(tmp_path))
    from fastapi.testclient import TestClient
    from api.main import app

    client = TestClient(app)
    r = client.post("/api/user/signal", json={"action": "visited", "poi_name": "外滩"})
    assert r.status_code == 200
    assert "外滩" in r.json()["user_marked"]["been_there"]
