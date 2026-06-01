"""v1.9 Stage 2: cookie 级 UserProfile JSON 文件存储 (最简版).

存 data/user_profiles/{cookie_key}.json. 由 cookie middleware 设置 cookie.
后续阶段会迁 SQLite, 接口保持稳定.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from dianping.schemas import UserProfile


def _profiles_dir() -> Path:
    p = Path(os.environ.get("MTAGENT_USER_PROFILES_DIR", "data/user_profiles"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def new_cookie_key() -> str:
    """生成新 cookie key (UUID v4 无 dash)."""
    return uuid.uuid4().hex


def get_profile(cookie_key: str) -> Optional[UserProfile]:
    """读 profile; 不存在返 None."""
    if not cookie_key:
        return None
    path = _profiles_dir() / f"{cookie_key}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return UserProfile.model_validate(data)
    except Exception:
        return None


def save_profile(profile: UserProfile) -> Path:
    """写 profile, 更新 updated_at (原子写: temp + os.replace, 防高频写并发损坏)."""
    profile.updated_at = datetime.now()
    if profile.created_at is None:
        profile.created_at = profile.updated_at
    path = _profiles_dir() / f"{profile.cookie_key}.json"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(profile.model_dump_json(indent=2))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return path


def upsert_profile(
    cookie_key: str,
    *,
    modifiers: Optional[dict] = None,
    interests_text: Optional[str] = None,
) -> UserProfile:
    """更新或创建 profile. None 字段保留旧值."""
    existing = get_profile(cookie_key)
    if existing is None:
        existing = UserProfile(cookie_key=cookie_key)
    if modifiers is not None:
        existing.modifiers = modifiers
    if interests_text is not None:
        existing.interests_text = interests_text
    save_profile(existing)
    return existing


def apply_signal(
    cookie_key: str,
    action: str,
    *,
    poi=None,
    poi_name: Optional[str] = None,
) -> UserProfile:
    """统一信号入口: get-or-new -> record -> save. action: love|reject|dislike|visited.

    被 POST /api/user/signal 与 adjust 捕获接入点共用 (DRY)。
    """
    from agents.preference_signals import (
        record_love,
        record_rejection,
        record_visit,
    )

    p = get_profile(cookie_key) or UserProfile(cookie_key=cookie_key or "")
    if action == "love" and poi is not None:
        record_love(p, poi)
    elif action in ("reject", "dislike") and poi is not None:
        record_rejection(p, poi)
    elif action == "visited" and poi_name:
        record_visit(p, poi_name)
    save_profile(p)
    return p
