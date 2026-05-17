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


def test_answer_endpoint_emits_next_question(tmp_path, monkeypatch):
    """POST /answer 还有问题 → emit clarify.question，不触发 variant 生成。"""
    monkeypatch.setenv("MTAGENT_TRIPS_DIR", str(tmp_path))

    from agents.context import TripContext
    from dianping.schemas import ClarifyQuestion, ParsedIntent, UserInput

    ctx = TripContext.create(user_input=UserInput(free_text="去北京"))
    ctx.intent = ParsedIntent(city="北京", days=1, traveler_type="情侣")
    ctx.clarify_questions = [
        ClarifyQuestion(idx=0, text="吃什么？", options=["A", "B", "C"]),
        ClarifyQuestion(idx=1, text="约好了吗？", options=["X", "Y", "Z"]),
    ]
    ctx.save()

    from fastapi.testclient import TestClient

    from api.main import app

    with TestClient(app) as tc:
        resp = tc.post(
            f"/api/plan/{ctx.trip_id}/answer",
            json={"idx": 0, "choice": "A"},
        )
    assert resp.status_code == 200
    text = resp.text
    assert "clarify.question" in text
    assert "约好了吗" in text
