"""Critic 真规则检查测试 (P1.2)."""

from datetime import time

import pytest

from agents.context import TripContext
from agents.critic import Critic
from dianping.schemas import (
    DayPlan,
    POI,
    ParsedIntent,
    RouteDraft,
    Stop,
    TimeSlot,
    UserInput,
)


def _stop(name: str, slot_name: str, hour: int, role_cat: str = "美食") -> Stop:
    return Stop(
        poi=POI(
            openshopid=f"id-{name}",
            name=name,
            city="南昌",
            categories=[role_cat],
            avgprice=80,
            star=4.5,
            longitude=115.89,
            latitude=28.68,
        ),
        slot=TimeSlot(name=slot_name, start=time(hour, 0), end=time(hour + 2, 0)),
        arrival_time=time(hour, 0),
        leave_time=time(hour + 2, 0),
    )


def _ctx(day: DayPlan, intent: ParsedIntent) -> TripContext:
    ctx = TripContext(trip_id="t1", user_input=UserInput(free_text="x"))
    ctx.intent = intent
    ctx.draft_route = RouteDraft(days=[day])
    return ctx


@pytest.mark.asyncio
async def test_critic_flags_missing_lunch():
    intent = ParsedIntent(city="南昌", days=1, traveler_type="独行", pace="适中")
    day = DayPlan(
        day_index=0,
        stops=[
            _stop("八一广场", "上午景点", 9, "景点"),
            _stop("江西省博物馆", "上午景点", 10, "景点"),
            _stop("秋水广场", "下午", 14, "景点"),
            _stop("万达广场", "晚饭", 19, "购物"),
        ],
    )
    ctx = _ctx(day, intent)
    patches = await Critic().run(ctx)
    issues = [p.issue for p in patches]
    assert any("午饭" in i for i in issues)


@pytest.mark.asyncio
async def test_critic_returns_empty_when_all_pass():
    intent = ParsedIntent(city="南昌", days=1, traveler_type="独行", pace="适中")
    day = DayPlan(
        day_index=0,
        stops=[
            _stop("八一广场", "上午景点", 9, "景点"),
            _stop("瓦罐汤", "午饭", 12, "美食"),
            _stop("秋水广场", "下午", 15, "景点"),
            _stop("江西小炒", "晚饭", 19, "美食"),
        ],
    )
    ctx = _ctx(day, intent)
    patches = await Critic().run(ctx)
    issues = [p.issue for p in patches]
    assert not any("午饭" in i for i in issues)
    assert not any("晚饭" in i for i in issues)


@pytest.mark.asyncio
async def test_critic_no_draft_route_returns_empty():
    ctx = TripContext(trip_id="t1", user_input=UserInput(free_text="x"))
    ctx.intent = ParsedIntent(city="南昌", days=1, traveler_type="独行")
    patches = await Critic().run(ctx)
    assert patches == []
