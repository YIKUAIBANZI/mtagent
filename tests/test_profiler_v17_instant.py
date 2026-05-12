"""v1.7: Profiler 即时出发字段 + 服务器时刻感知 单元测试.

不依赖 enriched labels / candidate pool, 只验证:
  1. ParsedIntent 新字段 default 安全 (backward-compat)
  2. _apply_constraint_defaults backfill 行为
  3. Profiler 把服务器时间注入 user prompt
  4. Profiler 接受/回填 v1.7 LLM output
"""

from __future__ import annotations

import asyncio
import json


from agents.context import TripContext
from agents.profiler import _apply_constraint_defaults, Profiler
from dianping.schemas import ParsedIntent, UserInput


def test_parsed_intent_v17_fields_default_safe():
    """v0/v1 老代码构造 ParsedIntent 不传 v1.7 字段, 应 OK."""
    intent = ParsedIntent(city="深圳", days=1, traveler_type="情侣")
    assert intent.time_window is None
    assert intent.interests == []
    assert intent.constraints == {}
    assert intent.start_location_text is None
    assert intent.start_with_meal is False
    assert intent.estimated_hours is None
    assert intent.current_time is None


def test_constraint_defaults_family_implies_avoid_walking():
    intent = ParsedIntent(city="深圳", days=1, traveler_type="家庭亲子")
    _apply_constraint_defaults(intent)
    assert intent.constraints["avoid_walking"] is True
    # 其它约束 backfill False
    assert intent.constraints["avoid_queue"] is False
    assert intent.constraints["avoid_cross_district"] is False
    assert intent.constraints["need_meal"] is False


def test_constraint_defaults_couple_all_false_when_unspecified():
    intent = ParsedIntent(city="深圳", days=1, traveler_type="情侣")
    _apply_constraint_defaults(intent)
    for k in ("avoid_queue", "avoid_walking", "avoid_cross_district", "need_meal"):
        assert intent.constraints[k] is False


def test_constraint_defaults_does_not_override_explicit_true():
    intent = ParsedIntent(
        city="深圳",
        days=1,
        traveler_type="情侣",
        constraints={"avoid_queue": True, "need_meal": True},
    )
    _apply_constraint_defaults(intent)
    assert intent.constraints["avoid_queue"] is True
    assert intent.constraints["need_meal"] is True
    # missing keys still backfilled False
    assert intent.constraints["avoid_walking"] is False
    assert intent.constraints["avoid_cross_district"] is False


def _fake_llm_capture(captured: dict):
    """Return an llm_call stub that captures the user message and returns fixed v1.7 JSON."""

    async def _llm(system: str, user: str) -> str:
        captured["system"] = system
        captured["user"] = user
        return json.dumps(
            {
                "city": "西安",
                "days": 1,
                "traveler_type": "情侣",
                "time_window": "半日_下午",
                "interests": ["拍照", "美食"],
                "constraints": {"avoid_queue": True, "need_meal": True},
                "start_location_text": "西安钟楼附近",
                "start_with_meal": True,
                "estimated_hours": 4,
                "current_time": "2026-05-13T15:42:00+08:00",
            }
        )

    return _llm


def test_profiler_injects_server_time_into_user_message():
    """Profiler 把 '当前服务器时间: <ISO>' 拼到 user_message 顶部."""
    captured: dict = {}
    profiler = Profiler(llm_call=_fake_llm_capture(captured))
    ctx = TripContext.create(
        user_input=UserInput(free_text="我现在在西安钟楼附近，下午有 4 小时")
    )
    asyncio.run(profiler.run(ctx))
    assert "当前服务器时间:" in captured["user"]
    # 用户原 free_text 也在
    assert "西安钟楼附近" in captured["user"]


def test_profiler_parses_v17_fields_into_intent():
    """LLM 返回 v1.7 字段, Profiler 应回填到 ParsedIntent."""
    captured: dict = {}
    profiler = Profiler(llm_call=_fake_llm_capture(captured))
    ctx = TripContext.create(
        user_input=UserInput(free_text="我现在在西安钟楼附近，下午有 4 小时")
    )
    out = asyncio.run(profiler.run(ctx))
    intent = out.understood
    assert intent.time_window == "半日_下午"
    assert intent.interests == ["拍照", "美食"]
    assert intent.constraints["avoid_queue"] is True
    assert intent.constraints["need_meal"] is True
    # constraint defaults backfilled the unspecified ones
    assert intent.constraints["avoid_walking"] is False
    assert intent.start_location_text == "西安钟楼附近"
    assert intent.start_with_meal is True
    assert intent.estimated_hours == 4
    assert intent.current_time == "2026-05-13T15:42:00+08:00"


def test_profiler_v17_fields_optional_when_llm_omits():
    """LLM 只返回 v0 必填字段 (老 LLM 兼容), v1.7 字段应安全默认."""

    async def _legacy_llm(system: str, user: str) -> str:
        return json.dumps({"city": "深圳", "days": 3, "traveler_type": "情侣"})

    profiler = Profiler(llm_call=_legacy_llm)
    ctx = TripContext.create(user_input=UserInput(free_text="深圳 3 天情侣"))
    out = asyncio.run(profiler.run(ctx))
    intent = out.understood
    assert intent.time_window is None
    assert intent.interests == []
    assert intent.start_with_meal is False
    assert intent.estimated_hours is None
    # current_time 仍由 Profiler 注入服务器时间兜底, 不应是 None
    assert intent.current_time is not None
    assert "T" in intent.current_time  # ISO 形态
