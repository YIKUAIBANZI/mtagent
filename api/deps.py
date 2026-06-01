"""Shared dependencies for FastAPI routes.

Holds the singleton DianpingClient that's created in lifespan and injected
into route handlers via Depends().
"""

from __future__ import annotations

from typing import Optional

from dianping.client import DianpingClient


class _State:
    client: Optional[DianpingClient] = None


def set_client(client: DianpingClient) -> None:
    _State.client = client


def get_client() -> DianpingClient:
    if _State.client is None:
        raise RuntimeError(
            "DianpingClient is not initialized. Did the FastAPI lifespan run?"
        )
    return _State.client
