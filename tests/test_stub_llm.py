"""Test stub LLM fallback for no-DASHSCOPE-API-KEY mode."""

import json

import pytest


@pytest.mark.asyncio
async def test_stub_profiler_llm_parses_simple_text():
    from api.stub_llm import stub_profiler_llm

    raw = await stub_profiler_llm("system", "情侣 3 天深圳预算 3000 爱拍照")
    data = json.loads(raw)

    assert data["city"] == "深圳"
    assert data["days"] == 3
    assert data["traveler_type"] == "情侣"


@pytest.mark.asyncio
async def test_stub_profiler_llm_handles_missing_fields():
    from api.stub_llm import stub_profiler_llm

    raw = await stub_profiler_llm("system", "深圳")
    data = json.loads(raw)

    assert data["city"] == "深圳"
    assert data.get("days") in (None, 0) or data.get("traveler_type") is None


@pytest.mark.asyncio
async def test_stub_profiler_llm_recognizes_chinese_numerals():
    """Chinese numerals like 三天/五天/十天 must parse as days."""
    from api.stub_llm import stub_profiler_llm

    cases = [
        ("西安三天带长辈", "西安", 3),
        ("朋友团两天上海", "上海", 2),
        ("一家人五天西安", "西安", 5),
        ("深圳十天", "深圳", 10),
    ]
    for text, city, days in cases:
        raw = await stub_profiler_llm("s", text)
        data = json.loads(raw)
        assert data["city"] == city, f"{text!r}: city {data['city']} != {city}"
        assert data["days"] == days, f"{text!r}: days {data['days']} != {days}"


@pytest.mark.asyncio
async def test_stub_planner_llm_returns_empty_days():
    from api.stub_llm import stub_planner_llm

    raw = await stub_planner_llm("system", "any payload")
    data = json.loads(raw)

    assert "days" in data
    assert data["days"] == []


@pytest.mark.asyncio
async def test_resolve_llm_uses_real_when_key_present(monkeypatch):
    from api.stub_llm import resolve_profiler_llm

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    fn = resolve_profiler_llm()
    assert fn.__name__ != "stub_profiler_llm"


@pytest.mark.asyncio
async def test_resolve_llm_uses_stub_when_key_missing(monkeypatch):
    from api.stub_llm import resolve_profiler_llm

    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    fn = resolve_profiler_llm()
    assert fn.__name__ == "stub_profiler_llm"
