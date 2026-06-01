"""v1.9.2: stub_llm 抽 must_visit 词."""

import asyncio
import json

from api.stub_llm import stub_profiler_llm


def _parse(text: str) -> dict:
    return json.loads(asyncio.run(stub_profiler_llm("", text)))


def test_extract_must_visit_bi_qu():
    """'必去 X' 抽取."""
    out = _parse("情侣 西安 3 天 必去大唐不夜城")
    assert "大唐不夜城" in out["must_visit"]


def test_extract_must_visit_yi_ding_yao_qu():
    """'一定要去 X' 抽取."""
    out = _parse("北京 2 天 一定要去故宫")
    assert "故宫" in out["must_visit"]


def test_extract_multiple_must_visit():
    """多个 must_visit 词都抽."""
    out = _parse("情侣 西安 3 天 必去钟楼 必去兵马俑")
    assert "钟楼" in out["must_visit"]
    assert "兵马俑" in out["must_visit"]


def test_no_must_visit_when_not_present():
    out = _parse("情侣 西安 3 天")
    assert out["must_visit"] == []
