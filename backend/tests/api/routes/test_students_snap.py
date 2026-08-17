import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import Organization, UserRole
from tests.api.routes.test_students_wrongbook import _headers, _user
from tests.utils.utils import random_lower_string

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00"
    b"\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _student_headers(client: TestClient, db: Session, name: str) -> dict[str, str]:
    org = Organization(name=f"拍题学校-{name}", code=f"snap-{random_lower_string()}")
    db.add(org)
    db.commit()
    db.refresh(org)
    user, password = _user(db, UserRole.STUDENT, org)
    return _headers(client, user, password)


def _teacher_headers(client: TestClient, db: Session, name: str) -> dict[str, str]:
    org = Organization(
        name=f"拍题教师学校-{name}", code=f"snap-t-{random_lower_string()}"
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    user, password = _user(db, UserRole.TEACHER, org)
    return _headers(client, user, password)


def _post_snap(
    client: TestClient,
    headers: dict[str, str],
    *,
    image: bytes = PNG_BYTES,
    mode: str = "solve",
    max_score: float | None = None,
):
    data: dict[str, str] = {"mode": mode}
    if max_score is not None:
        data["max_score"] = str(max_score)
    return client.post(
        f"{settings.API_V1_STR}/students/me/snap",
        headers=headers,
        files={"image": ("question.png", image, "image/png")},
        data=data,
    )


def test_snap_solve_returns_answer_and_explanation(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = _student_headers(client, db, "答疑")
    calls: list[dict] = []
    payloads = [
        {"question_text": "已知物体质量 2kg，求重力加速度为 10 时的重力。"},
        {"answer": "20N", "explanation": "重力 G=mg=2×10=20N。"},
    ]

    def fake_call_json_model(**kwargs: object) -> tuple[dict, str, int]:
        calls.append(kwargs)
        return payloads[len(calls) - 1], "mock-model", 1

    monkeypatch.setattr("app.api.routes.students.call_json_model", fake_call_json_model)

    response = _post_snap(client, headers, mode="solve")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "solve"
    assert body["question_text"] == "已知物体质量 2kg，求重力加速度为 10 时的重力。"
    assert body["answer"] == "20N"
    assert body["explanation"] == "重力 G=mg=2×10=20N。"
    # 两次调用：视觉转录 + 解题
    assert len(calls) == 2
    assert "image_url" in str(calls[0]["messages"])
    assert "20N" not in str(calls[0]["messages"])


def test_snap_grade_returns_score_and_comment(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = _student_headers(client, db, "批改")
    monkeypatch.setattr(
        "app.api.routes.students._snap_extract",
        lambda *args, **kwargs: ("计算 3+4×2。", "3+4×2=14"),
    )
    calls: list[dict] = []
    payloads = [
        {"answer": "11", "explanation": "先乘后加：4×2=8，3+8=11。"},
        {"score": 99, "comment": "运算顺序错了，应先算乘法。"},
    ]

    def fake_call_json_model(**kwargs: object) -> tuple[dict, str, int]:
        calls.append(kwargs)
        return payloads[len(calls) - 1], "mock-model", 1

    monkeypatch.setattr("app.api.routes.students.call_json_model", fake_call_json_model)

    response = _post_snap(client, headers, mode="grade", max_score=10)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "grade"
    assert body["question_text"] == "计算 3+4×2。"
    assert body["student_answer"] == "3+4×2=14"
    # 模型给的分被钳制到满分 10
    assert body["score"] == 10
    assert body["max_score"] == 10
    assert body["comment"] == "运算顺序错了，应先算乘法。"
    # 两次调用：先独立解标准答案，再判分
    assert len(calls) == 2
    assert "标准答案" in str(calls[1]["messages"])


def test_snap_grade_without_student_answer_returns_422(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = _student_headers(client, db, "空作答")
    monkeypatch.setattr(
        "app.api.routes.students._snap_extract",
        lambda *args, **kwargs: ("计算 3+4×2。", ""),
    )
    response = _post_snap(client, headers, mode="grade")
    assert response.status_code == 422, response.text
    assert "作答" in response.json()["detail"]


def test_snap_teacher_forbidden(client: TestClient, db: Session) -> None:
    headers = _teacher_headers(client, db, "教师")
    response = _post_snap(client, headers)
    assert response.status_code == 403, response.text


def test_snap_oversized_image_returns_422(client: TestClient, db: Session) -> None:
    headers = _student_headers(client, db, "大图")
    big_image = PNG_BYTES + b"\x00" * (10 * 1024 * 1024)
    response = _post_snap(client, headers, image=big_image)
    assert response.status_code == 422, response.text
    assert "10MB" in response.json()["detail"]


def test_snap_invalid_mode_returns_422(client: TestClient, db: Session) -> None:
    headers = _student_headers(client, db, "坏模式")
    response = _post_snap(client, headers, mode="chat")
    assert response.status_code == 422, response.text
