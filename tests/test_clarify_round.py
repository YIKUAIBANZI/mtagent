"""Tests for ClarifyQuestion / ClarifyAnswer schemas."""

from dianping.schemas import ClarifyAnswer, ClarifyQuestion


def test_clarify_question_schema():
    q = ClarifyQuestion(
        idx=0, text="中午想吃什么？", options=["北京烤鸭", "胡同小吃", "随便清淡"]
    )
    assert q.idx == 0
    assert len(q.options) == 3


def test_clarify_answer_skip():
    a = ClarifyAnswer(idx=0, choice=None, skipped=True)
    assert a.skipped is True
    assert a.choice is None


def test_clarify_answer_choice():
    a = ClarifyAnswer(idx=0, choice="北京烤鸭")
    assert a.skipped is False
    assert a.choice == "北京烤鸭"


def test_trip_context_clarify_fields():
    from agents.context import TripContext
    from dianping.schemas import ClarifyAnswer, ClarifyQuestion, UserInput

    ctx = TripContext.create(user_input=UserInput(free_text="去北京玩"))
    assert ctx.clarify_questions == []
    assert ctx.clarify_answers == []
    assert ctx.pre_fetched_pois == []

    ctx.clarify_questions = [
        ClarifyQuestion(idx=0, text="吃什么？", options=["A", "B", "C"])
    ]
    ctx.clarify_answers = [ClarifyAnswer(idx=0, choice="A")]
    assert len(ctx.clarify_questions) == 1
    assert ctx.clarify_answers[0].choice == "A"
