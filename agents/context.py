"""TripContext — shared Pydantic state object passed between Agents.

Persists to data/trips/{trip_id}.json after every Agent step. Lightweight
(usually < 100KB), so frequent writes have negligible IO cost.
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from dianping.schemas import (
    Event,
    Feedback,
    ParsedIntent,
    Patch,
    POI,
    RouteDraft,
    UserInput,
    UserProfile,
)


def _trips_dir() -> Path:
    """Resolve trips dir from env at call time (so tests can override)."""
    p = Path(os.environ.get("MTAGENT_TRIPS_DIR", "data/trips"))
    p.mkdir(parents=True, exist_ok=True)
    return p


class TripContext(BaseModel):
    trip_id: str
    user_input: UserInput
    profile: Optional[UserProfile] = None
    intent: Optional[ParsedIntent] = None
    candidate_pois: list[POI] = Field(default_factory=list)
    draft_route: Optional[RouteDraft] = None
    # v1.7 即时出发: 三方案存储. v1.6 多日路径保持 None.
    # key 是 variant 名 (main / low_queue / interest_first), value 是该方案完整 RouteDraft.
    # draft_route 仍存 main, 保证 GET /api/plan/{trip_id} 老前端兼容.
    variants: Optional[dict[str, RouteDraft]] = None
    critic_patches: list[Patch] = Field(default_factory=list)
    user_feedback: list[Feedback] = Field(default_factory=list)
    trace: list[Event] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @classmethod
    def create(cls, *, user_input: UserInput) -> "TripContext":
        return cls(
            trip_id=f"trip_{secrets.token_urlsafe(8)}",
            user_input=user_input,
        )

    def log_event(self, agent: str, type_: str, payload: Optional[dict] = None) -> None:
        self.trace.append(
            Event(
                timestamp=datetime.now(),
                agent=agent,
                type=type_,
                payload=payload or {},
            )
        )

    def save(self) -> Path:
        self.updated_at = datetime.now()
        path = _trips_dir() / f"{self.trip_id}.json"
        path.write_text(
            self.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, trip_id: str) -> "TripContext":
        path = _trips_dir() / f"{trip_id}.json"
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        return cls.model_validate(data)
