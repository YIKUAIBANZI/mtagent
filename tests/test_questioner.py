"""Tests for QuestionGenerator."""

import json
import pytest
from unittest.mock import AsyncMock
from dianping.schemas import ClarifyQuestion, ParsedIntent


@pytest.mark.asyncio
async def test_questioner_returns_two_questions_for_sparse_intent():
    """稀疏意图（无餐饮偏好、含排队地标）→ 返回 2 个问题。"""
    from agents.questioner import QuestionGenerator

    fake_response = json.dumps(
        {
            "questions": [
                {
                    "idx": 0,
                    "text": "中午想吃什么？",
                    "options": ["北京烤鸭", "胡同小吃", "随便清淡"],
                },
                {
                    "idx": 1,
                    "text": "故宫需要预约，您约好了吗？",
                    "options": ["约好了", "还没约", "帮我考虑进去"],
                },
            ]
        }
    )
    fake_llm = AsyncMock(return_value=fake_response)

    intent = ParsedIntent(
        city="北京", days=1, traveler_type="情侣", must_visit=["故宫", "天坛"]
    )
    qg = QuestionGenerator(llm_call=fake_llm)
    questions = await qg.generate(intent=intent, user_input="明天去北京玩故宫天坛")

    assert len(questions) == 2
    assert all(isinstance(q, ClarifyQuestion) for q in questions)
    assert questions[0].idx == 0
    assert len(questions[0].options) == 3


@pytest.mark.asyncio
async def test_questioner_returns_empty_for_rich_intent():
    """意图已很丰富（有餐饮偏好 + 无排队地标）→ 返回 0 个问题。"""
    from agents.questioner import QuestionGenerator

    fake_response = json.dumps({"questions": []})
    fake_llm = AsyncMock(return_value=fake_response)

    intent = ParsedIntent(
        city="上海",
        days=1,
        traveler_type="朋友团",
        preferences=["美食", "拍照"],
        must_visit=[],
    )
    qg = QuestionGenerator(llm_call=fake_llm)
    questions = await qg.generate(intent=intent, user_input="上海外滩吃吃喝喝拍拍照")

    assert questions == []


@pytest.mark.asyncio
async def test_questioner_falls_back_on_llm_error():
    """LLM 抛异常 → 返回空列表，不崩溃。"""
    from agents.questioner import QuestionGenerator

    failing_llm = AsyncMock(side_effect=Exception("timeout"))
    intent = ParsedIntent(city="北京", days=1, traveler_type="情侣")
    qg = QuestionGenerator(llm_call=failing_llm)
    questions = await qg.generate(intent=intent, user_input="去北京")

    assert questions == []
