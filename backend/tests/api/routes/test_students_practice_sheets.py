import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from tests.api.routes.test_students_learning_advice import (
    _advice_context,
    _fake_model,
)


def test_practice_sheet_generate_and_read(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _advice_context(client, db, "练习甲")
    captured: list = []
    payload = {
        "questions": [
            {
                "question_text": "一个木块漂浮在水面上，若将它按入水中，浮力如何变化？",
                "answer": "浮力变大",
                "analysis": "排开液体的体积增大。",
            },
            {
                "question_text": "同体积的铁块和铝块浸没在水中，谁受到的浮力大？",
                "answer": "一样大",
                "analysis": "浮力只与排开液体体积和液体密度有关。",
            },
        ]
    }
    monkeypatch.setattr(
        "app.api.routes.students.call_json_model", _fake_model(payload, captured)
    )

    created = client.post(
        f"{settings.API_V1_STR}/students/me/practice-sheets",
        headers=context["headers"],
        json={"knowledge_point": "浮力", "count": 2},
    )
    assert created.status_code == 200, created.text
    sheet = created.json()
    assert sheet["knowledge_point"] == "浮力"
    assert len(sheet["items"]) == 2
    assert sheet["items"][0]["answer"]
    assert sheet["seed_count"] == 1
    # 种子错题确实进了提示词
    assert len(captured) == 1
    assert "浮力" in captured[0]["messages"][0]["content"]

    listed = client.get(
        f"{settings.API_V1_STR}/students/me/practice-sheets",
        headers=context["headers"],
    )
    assert listed.status_code == 200
    body = listed.json()
    assert body["count"] == 1
    assert body["data"][0]["item_count"] == 2

    detail = client.get(
        f"{settings.API_V1_STR}/students/me/practice-sheets/{sheet['id']}",
        headers=context["headers"],
    )
    assert detail.status_code == 200
    assert detail.json()["items"][1]["analysis"]


def test_practice_sheet_requires_seed_wrong_questions(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _advice_context(client, db, "练习乙")
    called: list = []
    monkeypatch.setattr(
        "app.api.routes.students.call_json_model",
        lambda **kwargs: called.append(kwargs) or ({}, "m", 0),
    )
    response = client.post(
        f"{settings.API_V1_STR}/students/me/practice-sheets",
        headers=context["headers"],
        json={"knowledge_point": "不存在的知识点"},
    )
    assert response.status_code == 422
    assert called == []


def test_practice_sheet_not_visible_to_other_students(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _advice_context(client, db, "练习丙")
    second = _advice_context(client, db, "练习丁")
    monkeypatch.setattr(
        "app.api.routes.students.call_json_model",
        _fake_model(
            {
                "questions": [
                    {"question_text": "q", "answer": "a", "analysis": ""},
                ]
            }
        ),
    )
    created = client.post(
        f"{settings.API_V1_STR}/students/me/practice-sheets",
        headers=first["headers"],
        json={"knowledge_point": "浮力"},
    )
    assert created.status_code == 200, created.text
    forbidden = client.get(
        f"{settings.API_V1_STR}/students/me/practice-sheets/{created.json()['id']}",
        headers=second["headers"],
    )
    assert forbidden.status_code == 404
    # 别人的列表里也看不到
    listed = client.get(
        f"{settings.API_V1_STR}/students/me/practice-sheets",
        headers=second["headers"],
    )
    assert listed.json()["count"] == 0
