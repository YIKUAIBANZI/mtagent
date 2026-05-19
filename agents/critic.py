"""Critic — 规则级 route 自检 agent (P1.2 真启用版).

复用 agents.route_validator 的 6 条规则，把 failed CheckResult 翻译成
dianping.schemas.Patch 列表。不调 LLM，纯函数 + 规则。
"""

from __future__ import annotations

from typing import Callable, Optional

from agents.context import TripContext
from agents.route_validator import validate_route
from dianping.schemas import DayPlan, Patch


_CHECK_TO_ISSUE = {
    "stop_count_ok": "stop 数量不达节奏目标",
    "has_lunch": "缺午饭",
    "has_dinner": "缺晚饭",
    "transit_ok": "通勤过长",
    "type_diversity": "同类 POI 过多",
    "no_lunch_skipped": "饭点被跳过",
}


class Critic:
    """Rule-based route critic. Outputs Patch suggestions for failed checks."""

    def __init__(self, llm_call: Optional[Callable] = None):
        # llm_call 保留参数兼容老代码，本版本不使用
        self.llm_call = llm_call

    async def run(self, ctx: TripContext) -> list[Patch]:
        draft = getattr(ctx, "draft_route", None)
        intent = getattr(ctx, "intent", None)
        if draft is None or intent is None or not draft.days:
            ctx.log_event("Critic", "skip_no_draft", {})
            return []

        reports = validate_route(draft, intent)
        patches: list[Patch] = []
        for day_idx, report in enumerate(reports):
            for check in report.failed:
                issue = _CHECK_TO_ISSUE.get(check.name, check.name)
                detail = f"{issue}: {check.detail}" if check.detail else issue
                stop_idx = self._guess_stop_idx(check.name, draft.days[day_idx])
                patches.append(
                    Patch(
                        day=day_idx,
                        stop_idx=stop_idx,
                        issue=detail,
                        suggestion_type="replace",
                        new_poi_id=None,
                    )
                )

        ctx.log_event(
            "Critic",
            "rules_done",
            {
                "days_checked": len(reports),
                "patches_total": len(patches),
                "issues": [p.issue for p in patches],
            },
        )
        return patches

    @staticmethod
    def _guess_stop_idx(check_name: str, day: DayPlan) -> int:
        """Pick a plausible stop_idx for the patch; defaults to 0.

        Only meaningful for `has_lunch` / `has_dinner` (returns the meal-slot
        index). Day-level checks (`stop_count_ok`, `transit_ok`,
        `type_diversity`, `no_lunch_skipped`) fall through to 0 — downstream
        Adjuster must NOT treat 0 as the literal target stop for these; it's
        a placeholder until v2 Adjuster re-derives from the issue text."""
        stops = day.stops
        if not stops:
            return 0
        if check_name == "has_lunch":
            for i, s in enumerate(stops):
                if 11 <= s.arrival_time.hour <= 13:
                    return i
        if check_name == "has_dinner":
            for i, s in enumerate(stops):
                if 18 <= s.arrival_time.hour <= 20:
                    return i
        return 0
