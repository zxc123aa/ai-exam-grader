"""终身身份的回归：这几条是「伴随一生」能否成立的判据（D-029）。"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    ClassGroup,
    LearnerProfile,
    Organization,
    OrganizationServiceState,
    Student,
    UserRole,
    WrongQuestionEntry,
)
from tests.api.routes.test_students_wrongbook import (
    _bind_student_account,
    _graded_exam,
    _headers,
    _publish,
    _user,
)
from tests.utils.utils import random_lower_string


def _org(db: Session, label: str) -> Organization:
    org = Organization(name=f"{label}学校", code=f"{label}-{random_lower_string()}")
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def test_learner_keeps_history_across_class_change(
    client: TestClient, db: Session
) -> None:
    """升班等于新建学校档案，但错题本必须连续。"""
    org = _org(db, "升班")
    owner, owner_password = _user(db, UserRole.SCHOOL_OWNER, org)
    owner_headers = _headers(client, owner, owner_password)

    # 七年级：发布一场，学生已绑账号
    exam_one, student_one, _submission = _graded_exam(
        db, org, owner, student_name="李明"
    )
    student_user, student_password = _bind_student_account(db, org, student_one)
    _publish(client, exam_one, owner_headers)
    headers = _headers(client, student_user, student_password)
    assert (
        client.get(
            f"{settings.API_V1_STR}/students/me/wrongbook/entries", headers=headers
        ).json()["count"]
        == 1
    )

    # 八年级：新班级、新学校档案，账号换绑到新档案（现实中的升班流程）
    new_class = ClassGroup(
        name=f"002班-{random_lower_string()[:6]}", org_id=org.id, owner_id=owner.id
    )
    db.add(new_class)
    db.flush()
    student_one.user_id = None
    db.add(student_one)
    student_two = Student(class_id=new_class.id, name="李明", user_id=student_user.id)
    db.add(student_two)
    db.commit()

    exam_two, _student, submission_two = _graded_exam(
        db, org, owner, student_name="李明"
    )
    # 让第二场考试的答卷归到升班后的档案
    submission_two.student_id = student_two.id
    submission_two.class_name = new_class.name
    db.add(submission_two)
    db.commit()
    _publish(client, exam_two, owner_headers)

    listed = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries", headers=headers
    )
    assert listed.status_code == 200, listed.text
    # 两个学年的错题都在同一个本子里
    assert listed.json()["count"] == 2
    titles = {item["exam_title"] for item in listed.json()["data"]}
    assert titles == {"期中物理"}

    profile = client.get(
        f"{settings.API_V1_STR}/students/me/profile", headers=headers
    ).json()
    # 在校经历留了两条，且带学校名与班级名快照
    assert len(profile["enrollments"]) == 2
    assert {item["class_name"] for item in profile["enrollments"]} == {
        student_one.class_id and _class_name(db, student_one.class_id),
        new_class.name,
    }
    assert profile["wrong_count"] == 2


def _class_name(db: Session, class_id: uuid.UUID) -> str | None:
    group = db.get(ClassGroup, class_id)
    return group.name if group else None


def test_late_bound_account_claims_earlier_wrong_questions(
    client: TestClient, db: Session
) -> None:
    """成绩先发布、学生后绑账号，历史错题要能被认领回来。"""
    org = _org(db, "后绑")
    owner, owner_password = _user(db, UserRole.SCHOOL_OWNER, org)
    owner_headers = _headers(client, owner, owner_password)
    exam, student, _submission = _graded_exam(db, org, owner, student_name="王芳")

    # 发布时学生还没有账号，条目只记了学校档案
    _publish(client, exam, owner_headers)
    entry = db.exec(
        select(WrongQuestionEntry).where(WrongQuestionEntry.student_id == student.id)
    ).first()
    assert entry is not None
    assert entry.learner_id is None

    student_user, student_password = _bind_student_account(db, org, student)
    headers = _headers(client, student_user, student_password)
    listed = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries", headers=headers
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["count"] == 1

    db.refresh(entry)
    learner = db.exec(
        select(LearnerProfile).where(LearnerProfile.user_id == student_user.id)
    ).one()
    assert entry.learner_id == learner.id


def test_frozen_school_does_not_lock_student_out_of_wrongbook(
    client: TestClient, db: Session
) -> None:
    """学校欠费冻结后，学生仍然能打开自己的错题本（D-029）。"""
    org = _org(db, "冻结")
    owner, owner_password = _user(db, UserRole.SCHOOL_OWNER, org)
    owner_headers = _headers(client, owner, owner_password)
    exam, student, _submission = _graded_exam(db, org, owner, student_name="陈刚")
    student_user, student_password = _bind_student_account(db, org, student)
    _publish(client, exam, owner_headers)
    headers = _headers(client, student_user, student_password)
    assert (
        client.get(
            f"{settings.API_V1_STR}/students/me/wrongbook/entries", headers=headers
        ).status_code
        == 200
    )

    org.status = OrganizationServiceState.FROZEN
    db.add(org)
    db.commit()

    # 老师被挡住
    blocked = client.get(f"{settings.API_V1_STR}/exams/", headers=owner_headers)
    assert blocked.status_code == 403
    # 学生照常访问自己的学习记录，包括提交复习
    listed = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries", headers=headers
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["count"] == 1
    entry_id = listed.json()["data"][0]["entry_id"]
    reviewed = client.post(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries/{entry_id}/review",
        headers=headers,
        json={"result": "good"},
    )
    assert reviewed.status_code == 200, reviewed.text


def test_learner_survives_school_record_deletion(
    client: TestClient, db: Session
) -> None:
    """学校把学生档案删了，学生自己的错题本还在。"""
    org = _org(db, "删档")
    owner, owner_password = _user(db, UserRole.SCHOOL_OWNER, org)
    owner_headers = _headers(client, owner, owner_password)
    exam, student, _submission = _graded_exam(db, org, owner, student_name="赵磊")
    student_user, student_password = _bind_student_account(db, org, student)
    _publish(client, exam, owner_headers)
    headers = _headers(client, student_user, student_password)
    assert (
        client.get(
            f"{settings.API_V1_STR}/students/me/wrongbook/entries", headers=headers
        ).json()["count"]
        == 1
    )

    db.delete(student)
    db.commit()

    listed = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries", headers=headers
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["count"] == 1
    profile = client.get(
        f"{settings.API_V1_STR}/students/me/profile", headers=headers
    ).json()
    # 档案没了，但在校经历的学校名与班级名快照留着
    assert len(profile["enrollments"]) == 1
    assert profile["enrollments"][0]["org_name"] == org.name
