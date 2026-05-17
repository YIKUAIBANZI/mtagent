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
