from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    Organization,
    UserRole,
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


def _two_exam_context(client: TestClient, db: Session) -> dict[str, str]:
    """同一个学生两场已发布的考试，知识点「功和功率」错误率从 100% 降到 50%。

    场 1：第1题错（6/10）→ 1 次作答 1 次出错。
    场 2：第1题错（6/10）+ 第2题满分（10/10，补挂同一知识点）→ 2 次作答 1 次出错。
    """
    org = Organization(name="趋势一中", code=f"trend-{random_lower_string()}")
    db.add(org)
    db.commit()
    db.refresh(org)
    owner, owner_password = _user(db, UserRole.SCHOOL_OWNER, org)
    owner_headers = _headers(client, owner, owner_password)
    exam1, student, _sub1 = _graded_exam(db, org, owner, student_name="趋势生")
    exam2, _student2, submission2 = _graded_exam(
        db, org, owner, student_name="趋势生", second_question="full"
    )
    # 两场记到同一个学生头上，共用一条终身身份
    submission2.student_id = student.id
    db.add(submission2)
    db.commit()
    student_user, student_password = _bind_student_account(db, org, student)
    _publish(client, exam1, owner_headers)
    _publish(client, exam2, owner_headers)
    # 场 2 的第2题原本没挂知识点，补挂「功和功率」凑成 2 次作答
    source2 = db.exec(
        select(WrongQuestionSource).where(
            WrongQuestionSource.exam_id == exam2.id,
            WrongQuestionSource.question_label == "第2题",
        )
    ).one()
    source2.knowledge_point_names = ["功和功率"]
    db.add(source2)
    db.commit()
    return _headers(client, student_user, student_password)


def test_knowledge_trends_two_exams(client: TestClient, db: Session) -> None:
    headers = _two_exam_context(client, db)

    response = client.get(
        f"{settings.API_V1_STR}/students/me/knowledge-trends", headers=headers
    )
    assert response.status_code == 200, response.text
    body = response.json()

    # 总分曲线：两场按发布时间升序
    score_trend = body["score_trend"]
    assert len(score_trend) == 2
    assert [point["exam_title"] for point in score_trend] == ["期中物理", "期中物理"]
    assert score_trend[0]["total_score"] == 6
    assert score_trend[0]["total_max_score"] == 10
    assert score_trend[1]["total_score"] == 16
    assert score_trend[1]["total_max_score"] == 20
    assert score_trend[0]["released_at"] < score_trend[1]["released_at"]

    # 知识点错误率曲线：同一知识点两场，错误率 100% → 50%
    kp_trends = body["kp_trends"]
    assert len(kp_trends) == 1
    series = kp_trends[0]
    assert series["subject"] == "物理"
    assert series["knowledge_point"] == "功和功率"
    points = series["points"]
    assert len(points) == 2
    assert points[0]["wrong_rate"] == 100
    assert points[0]["attempts"] == 1
    assert points[0]["wrong"] == 1
    assert points[1]["wrong_rate"] == 50
    assert points[1]["attempts"] == 2
    assert points[1]["wrong"] == 1
    assert points[0]["released_at"] < points[1]["released_at"]


def test_knowledge_trends_empty_without_releases(
    client: TestClient, db: Session
) -> None:
    org = Organization(name="趋势空校", code=f"trend-empty-{random_lower_string()}")
    db.add(org)
    db.commit()
    db.refresh(org)
    user, password = _user(db, UserRole.STUDENT, org)
    headers = _headers(client, user, password)

    response = client.get(
        f"{settings.API_V1_STR}/students/me/knowledge-trends", headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"score_trend": [], "kp_trends": []}


def test_knowledge_trends_rejects_teacher(client: TestClient, db: Session) -> None:
    org = Organization(name="趋势教师校", code=f"trend-t-{random_lower_string()}")
    db.add(org)
    db.commit()
    db.refresh(org)
    teacher, password = _user(db, UserRole.TEACHER, org)
    headers = _headers(client, teacher, password)

    response = client.get(
        f"{settings.API_V1_STR}/students/me/knowledge-trends", headers=headers
    )
    assert response.status_code == 403
