"""Shared helpers used by multiple router files (DRY)."""

from __future__ import annotations

from agents.context import TripContext


def cookie_key(request) -> str:
    """Read mtagent_cid cookie key from request.state (set by middleware) or fallback to raw cookie."""
    return getattr(request.state, "cookie_key", "") or request.cookies.get(
        "mtagent_cid", ""
    )


def merge_extra(ctx: TripContext, extra: dict) -> None:
    """Apply user-provided clarifying answers to ctx.intent."""
    if ctx.intent is None:
        return
    for k in ("city", "days", "traveler_type", "budget_level", "pace"):
        v = extra.get(k)
        if v not in (None, "", 0):
            setattr(ctx.intent, k, v)
