"""v1.9 Stage 2: cookie middleware + /api/user/profile 单测."""

from __future__ import annotations




def test_first_visit_sets_cookie(sse_app_client, tmp_path_factory, monkeypatch):
    """没 cookie 时 GET /api/user/profile 应签发 cookie + 返 null."""
    profiles_dir = tmp_path_factory.mktemp("profiles")
    monkeypatch.setenv("MTAGENT_USER_PROFILES_DIR", str(profiles_dir))

    sse_app_client.cookies.clear()
    resp = sse_app_client.get("/api/user/profile")
    assert resp.status_code == 200
    assert resp.json() is None
    assert "mtagent_cid" in resp.cookies


def test_put_then_get_roundtrip(sse_app_client, tmp_path_factory, monkeypatch):
    profiles_dir = tmp_path_factory.mktemp("profiles2")
    monkeypatch.setenv("MTAGENT_USER_PROFILES_DIR", str(profiles_dir))

    sse_app_client.cookies.clear()
    # 触发 cookie 签发
    sse_app_client.get("/api/user/profile")
    # PUT 偏好
    resp = sse_app_client.put(
        "/api/user/profile",
        json={
            "modifiers": {"重美食": True, "怕排队": True},
            "interests_text": "拍照",
        },
    )
    assert resp.status_code == 200
    profile = resp.json()
    assert profile["modifiers"] == {"重美食": True, "怕排队": True}
    assert profile["interests_text"] == "拍照"

    # GET 应拿到刚写入的
    resp2 = sse_app_client.get("/api/user/profile")
    assert resp2.status_code == 200
    assert resp2.json()["interests_text"] == "拍照"


def test_partial_update_preserves_other_fields(
    sse_app_client, tmp_path_factory, monkeypatch
):
    profiles_dir = tmp_path_factory.mktemp("profiles3")
    monkeypatch.setenv("MTAGENT_USER_PROFILES_DIR", str(profiles_dir))

    sse_app_client.cookies.clear()
    sse_app_client.get("/api/user/profile")  # cookie 签发
    sse_app_client.put(
        "/api/user/profile",
        json={"modifiers": {"重美食": True}, "interests_text": "美食"},
    )
    # 仅更新 interests_text — modifiers 应保留
    sse_app_client.put(
        "/api/user/profile",
        json={"interests_text": "拍照"},
    )
    resp = sse_app_client.get("/api/user/profile")
    profile = resp.json()
    assert profile["modifiers"] == {"重美食": True}
    assert profile["interests_text"] == "拍照"


def test_different_cookies_isolated(sse_app_client, tmp_path_factory, monkeypatch):
    profiles_dir = tmp_path_factory.mktemp("profiles4")
    monkeypatch.setenv("MTAGENT_USER_PROFILES_DIR", str(profiles_dir))

    # 用户 A
    sse_app_client.cookies.clear()
    sse_app_client.get("/api/user/profile")
    sse_app_client.put(
        "/api/user/profile",
        json={"interests_text": "A 用户"},
    )

    # 用户 B (清 cookie 拿新)
    sse_app_client.cookies.clear()
    sse_app_client.get("/api/user/profile")
    resp = sse_app_client.get("/api/user/profile")
    # B 的 profile 应为 null (cookie 不同)
    assert resp.json() is None
