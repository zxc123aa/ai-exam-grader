import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import WrongQuestionEntry, WrongQuestionReview, WrongQuestionSource
from tests.api.routes.test_students_learning_advice import (
    _advice_context,
    _fake_model,
)

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_sheet(client: TestClient, headers: dict, monkeypatch, kp: str = "浮力"):
    monkeypatch.setattr(
        "app.api.routes.students.call_json_model",
        _fake_model(
            {"questions": [{"question_text": "q1", "answer": "a1", "analysis": ""}]}
        ),
    )
    created = client.post(
        f"{settings.API_V1_STR}/students/me/practice-sheets",
        headers=headers,
        json={"knowledge_point": kp, "count": 1},
    )
    assert created.status_code == 200, created.text
    return created.json()


def _grade_fake(score: float, answer_text: str = "v=3m/s"):
    def fake(**kwargs: object):
        content = kwargs["messages"][0]["content"]
        text = content if isinstance(content, str) else content[0]["text"]
        if "手写作答" in text:
            return {"answer_text": answer_text}, "mock-vision", 1
        return {"score": score, "comment": "评语"}, "mock-grading", 1

    return fake


def _submit(client: TestClient, headers: dict, sheet_id: str, item_index: int = 0):
    return client.post(
        f"{settings.API_V1_STR}/students/me/practice-sheets/{sheet_id}/attempts",
        headers=headers,
        data={"item_index": str(item_index)},
        files={"image": ("answer.png", PNG, "image/png")},
    )


def _seed_review(db: Session, student_user_id, kp: str = "浮力"):
    """按学生限定查找该知识点错题的复习调度，避免吃到别的测试的数据。"""
    seed_entry = db.exec(
        select(WrongQuestionEntry)
        .join(WrongQuestionSource)
        .where(
            WrongQuestionSource.knowledge_point_names.contains([kp]),
            WrongQuestionEntry.student_user_id == student_user_id,
        )
    ).first()
    assert seed_entry is not None
    return db.exec(
        select(WrongQuestionReview).where(WrongQuestionReview.entry_id == seed_entry.id)
    ).first()


def test_practice_attempt_correct_advances_review(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _advice_context(client, db, "判分甲")
    monkeypatch.setattr(
        "app.api.routes.students.call_json_model",
        _fake_model(
            {"questions": [{"question_text": "q1", "answer": "a1", "analysis": ""}]}
        ),
    )
    created = client.post(
        f"{settings.API_V1_STR}/students/me/practice-sheets",
        headers=context["headers"],
        json={"knowledge_point": "浮力", "count": 1},
    )
    sheet_id = created.json()["id"]

    monkeypatch.setattr("app.api.routes.students.call_json_model", _grade_fake(1.0))
    response = _submit(client, context["headers"], sheet_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verdict"] == "correct"
    assert body["student_answer_text"] == "v=3m/s"

    # 卷详情里能看到这次判分
    detail = client.get(
        f"{settings.API_V1_STR}/students/me/practice-sheets/{sheet_id}",
        headers=context["headers"],
    )
    attempts = detail.json()["attempts"]
    assert len(attempts) == 1 and attempts[0]["verdict"] == "correct"

    # 该知识点的错题被推进复习调度（good）
    review = _seed_review(db, context["student_user"].id)
    assert review is not None
    assert review.result == "good"


def test_practice_attempt_wrong_pulls_back_review(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _advice_context(client, db, "判分乙")
    sheet_id = _make_sheet(client, context["headers"], monkeypatch)["id"]
    monkeypatch.setattr("app.api.routes.students.call_json_model", _grade_fake(0.0))
    response = _submit(client, context["headers"], sheet_id)
    assert response.status_code == 200, response.text
    assert response.json()["verdict"] == "wrong"

    review = _seed_review(db, context["student_user"].id)
    assert review is not None
    assert review.result == "again"
    # 打回复习后明天就该复习
    assert review.interval_days == 1


def test_practice_attempt_validates_input(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _advice_context(client, db, "判分丙")
    sheet_id = _make_sheet(client, context["headers"], monkeypatch)["id"]
    monkeypatch.setattr("app.api.routes.students.call_json_model", _grade_fake(1.0))
    # 题号越界
    out_of_range = _submit(client, context["headers"], sheet_id, item_index=9)
    assert out_of_range.status_code == 422
    # 别人的卷
    other = _advice_context(client, db, "判分丁")
    forbidden = _submit(client, other["headers"], sheet_id)
    assert forbidden.status_code == 404


def test_practice_attempt_replaces_previous(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _advice_context(client, db, "判分戊")
    sheet_id = _make_sheet(client, context["headers"], monkeypatch)["id"]
    monkeypatch.setattr("app.api.routes.students.call_json_model", _grade_fake(0.0))
    first = _submit(client, context["headers"], sheet_id)
    assert first.json()["verdict"] == "wrong"
    monkeypatch.setattr("app.api.routes.students.call_json_model", _grade_fake(1.0))
    second = _submit(client, context["headers"], sheet_id)
    assert second.json()["verdict"] == "correct"
    detail = client.get(
        f"{settings.API_V1_STR}/students/me/practice-sheets/{sheet_id}",
        headers=context["headers"],
    )
    attempts = detail.json()["attempts"]
    assert len(attempts) == 1
    assert attempts[0]["verdict"] == "correct"
