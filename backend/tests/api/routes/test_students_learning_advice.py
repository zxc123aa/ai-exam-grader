from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    Organization,
    UserRole,
    WrongQuestionEntry,
    WrongQuestionErrorReason,
    WrongQuestionSource,
)
from tests.api.routes.test_students_wrongbook import (
    _bind_student_account,
    _graded_exam,
    _headers,
    _publish,
    _user,
)
from tests.utils.utils import random_lower_string


def _advice_context(client: TestClient, db: Session, name: str) -> dict:
    """两道不同知识点的错题，各带一个错因，其中一道复习过一次。"""
    org = Organization(name=f"建议学校-{name}", code=f"advice-{random_lower_string()}")
    db.add(org)
    db.commit()
    db.refresh(org)
    owner, owner_password = _user(db, UserRole.SCHOOL_OWNER, org)
    owner_headers = _headers(client, owner, owner_password)
    exam, student, _submission = _graded_exam(
        db, org, owner, student_name=name, second_question="wrong"
    )
    student_user, student_password = _bind_student_account(db, org, student)
    _publish(client, exam, owner_headers)

    rows = db.exec(
        select(WrongQuestionEntry, WrongQuestionSource)
        .join(
            WrongQuestionSource,
            WrongQuestionEntry.source_id == WrongQuestionSource.id,  # type: ignore[arg-type]
        )
        .where(WrongQuestionEntry.student_user_id == student_user.id)
        .order_by(WrongQuestionEntry.question_label)
    ).all()
    assert len(rows) == 2
    # 第2题原本没挂知识点，补一个不同的知识点并分别标错因
    first, second = rows
    second[1].knowledge_point_names = ["浮力"]
    db.add(second[1])
    first[0].error_reason = WrongQuestionErrorReason.CONCEPT
    second[0].error_reason = WrongQuestionErrorReason.CALCULATION
    db.add(first[0])
    db.add(second[0])
    db.commit()

    headers = _headers(client, student_user, student_password)
    reviewed = client.post(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries/{first[0].id}/review",
        headers=headers,
        json={"result": "good"},
    )
    assert reviewed.status_code == 200, reviewed.text
    return {
        "headers": headers,
        "student_user": student_user,
        "org": org,
        "exam": exam,
    }


def _fake_model(payload: dict, captured: list | None = None):
    def fake(**kwargs: object) -> tuple[dict, str, int]:
        if captured is not None:
            captured.append(kwargs)
        return payload, "mock-model", 1

    return fake


def test_learning_advice_without_wrongbook_returns_empty(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list = []
    monkeypatch.setattr(
        "app.api.routes.students.call_json_model",
        lambda **kwargs: called.append(kwargs) or ({}, "m", 0),
    )
    org = Organization(name="建议空学校", code=f"advice0-{random_lower_string()}")
    db.add(org)
    db.commit()
    db.refresh(org)
    owner, _password = _user(db, UserRole.SCHOOL_OWNER, org)
    _exam, student, _submission = _graded_exam(db, org, owner, student_name="无错题")
    student_user, student_password = _bind_student_account(db, org, student)
    # 故意不发布成绩：错题本为空
    headers = _headers(client, student_user, student_password)

    response = client.get(
        f"{settings.API_V1_STR}/students/me/learning-advice", headers=headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["has_data"] is False
    assert body["overall"] is None
    assert body["focus_points"] == []
    assert body["weekly_plan"] == []
    assert body["generated_at"] is None
    # 没有错题时不调用模型
    assert called == []


def test_learning_advice_returns_structured_suggestion(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _advice_context(client, db, "建议甲")
    captured: list = []
    payload = {
        "overall": "你在浮力上错了1次，功和功率错了1次，先补浮力的受力分析。",
        "focus_points": [
            {
                "knowledge_point": "浮力",
                "times": 1,
                "advice": "重做第2题，先画受力分析图再列式。",
            },
            {
                "knowledge_point": "功和功率",
                "times": 1,
                "advice": "背熟 P=W/t 的适用条件，做题先写公式再代入。",
            },
        ],
        "weekly_plan": [
            "今天重做错题本里的浮力题",
            "周三把功和功率的公式默写一遍",
            "周末各找2道同类题练习",
        ],
    }
    monkeypatch.setattr(
        "app.api.routes.students.call_json_model", _fake_model(payload, captured)
    )

    response = client.get(
        f"{settings.API_V1_STR}/students/me/learning-advice", headers=context["headers"]
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["has_data"] is True
    assert body["overall"] == payload["overall"]
    assert body["focus_points"] == payload["focus_points"]
    assert body["weekly_plan"] == payload["weekly_plan"]
    assert body["generated_at"] is not None

    # 聚合统计确实进了提示词：两个知识点、两种错因都在
    assert len(captured) == 1
    prompt = captured[0]["messages"][0]["content"]
    assert "浮力" in prompt
    assert "功和功率" in prompt
    assert "concept" in prompt
    assert "calculation" in prompt


def test_learning_advice_incomplete_payload_returns_502(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _advice_context(client, db, "建议乙")
    monkeypatch.setattr(
        "app.api.routes.students.call_json_model",
        _fake_model({"overall": "只有总述，没有其余字段"}),
    )
    response = client.get(
        f"{settings.API_V1_STR}/students/me/learning-advice", headers=context["headers"]
    )
    assert response.status_code == 502


def test_learning_advice_requires_bound_student_role(
    client: TestClient, db: Session
) -> None:
    context = _advice_context(client, db, "建议丙")

    teacher, teacher_password = _user(db, UserRole.TEACHER, context["org"])
    teacher_headers = _headers(client, teacher, teacher_password)
    forbidden = client.get(
        f"{settings.API_V1_STR}/students/me/learning-advice", headers=teacher_headers
    )
    assert forbidden.status_code == 403

    # 学生角色但没绑定学校档案
    unbound, unbound_password = _user(db, UserRole.STUDENT, context["org"])
    unbound_headers = _headers(client, unbound, unbound_password)
    missing = client.get(
        f"{settings.API_V1_STR}/students/me/learning-advice", headers=unbound_headers
    )
    assert missing.status_code == 404


def test_learning_advice_scoped_by_exam(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """传 exam_id 只统计该考试错题；指向别的考试时无数据且不调模型。"""
    context = _advice_context(client, db, "建议丁")
    exam = context["exam"]
    captured: list = []
    payload = {
        "overall": "本场考试浮力错了1次。",
        "focus_points": [
            {"knowledge_point": "浮力", "times": 1, "advice": "先画受力分析图。"}
        ],
        "weekly_plan": ["今天重做浮力错题"],
    }
    monkeypatch.setattr(
        "app.api.routes.students.call_json_model", _fake_model(payload, captured)
    )

    scoped = client.get(
        f"{settings.API_V1_STR}/students/me/learning-advice",
        headers=context["headers"],
        params={"exam_id": str(exam.id)},
    )
    assert scoped.status_code == 200, scoped.text
    assert scoped.json()["has_data"] is True
    assert len(captured) == 1

    other = client.get(
        f"{settings.API_V1_STR}/students/me/learning-advice",
        headers=context["headers"],
        params={"exam_id": str(uuid4())},
    )
    assert other.status_code == 200, other.text
    assert other.json()["has_data"] is False
    # 该考试没有错题，不再调模型
    assert len(captured) == 1
