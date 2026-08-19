"""花名册比对（roster-check）+ 答卷改绑学生（reassign）。"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import (
    ClassGroup,
    Organization,
    StoredFile,
    Student,
    StudentSubmission,
    User,
    UserCreate,
    UserRole,
)
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def _school(client: TestClient, db: Session, label: str):
    org = Organization(name=f"比对学校-{label}", code=f"roster-{random_lower_string()}")
    db.add(org)
    db.commit()
    db.refresh(org)
    password = random_lower_string()
    owner = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(),
            password=password,
            role=UserRole.SCHOOL_OWNER,
            full_name=f"校长{label}",
            org_id=org.id,
        ),
    )
    headers = user_authentication_headers(
        client=client, email=owner.email, password=password
    )
    return org, owner, headers


def _exam(client: TestClient, headers: dict[str, str], title: str) -> dict:
    r = client.post(
        f"{settings.API_V1_STR}/exams/", headers=headers, json={"title": title}
    )
    assert r.status_code == 200, r.text
    return r.json()


def _roster_student(
    db: Session, org: Organization, owner: User, class_name: str, name: str, no: str
) -> Student:
    class_group = ClassGroup(name=class_name, org_id=org.id, owner_id=owner.id)
    db.add(class_group)
    db.flush()
    student = Student(class_id=class_group.id, name=name, student_no=no)
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def _submission(
    db: Session, *, exam_id: str, uploader_id: uuid.UUID, student_name: str
) -> StudentSubmission:
    stored_file = StoredFile(
        original_filename=f"{student_name}.png",
        content_type="image/png",
        storage_key=f"test/{random_lower_string()}.png",
        size_bytes=10,
        sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        uploaded_by_id=uploader_id,
    )
    db.add(stored_file)
    db.commit()
    db.refresh(stored_file)
    submission = StudentSubmission(
        exam_id=uuid.UUID(exam_id),
        stored_file_id=stored_file.id,
        student_name=student_name,
        class_name="001班",
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return submission


def test_roster_check_marks_exact_fuzzy_missing(
    client: TestClient, db: Session
) -> None:
    org, owner, headers = _school(client, db, "比对")
    _roster_student(db, org, owner, "001班", "张杉", "2026001")
    exam = _exam(client, headers, "比对考试")

    r = client.post(
        f"{settings.API_V1_STR}/exams/{exam['id']}/roster-check",
        headers=headers,
        json={
            "entries": [
                {"class_name": "001班", "student_name": "张杉"},  # exact
                {"class_name": "001班", "student_name": "张彬"},  # fuzzy → 张杉
                {"class_name": "001班", "student_name": "孙悟空"},  # missing
                {"student_identifier": "2026001"},  # 学号 exact
            ]
        },
    )
    assert r.status_code == 200, r.text
    results = r.json()["results"]
    assert [r["status"] for r in results] == ["exact", "fuzzy", "missing", "exact"]
    assert results[1]["suggestion"] == "张杉"


def test_reassign_submission_to_roster_student(client: TestClient, db: Session) -> None:
    """归错人的答卷改绑到花名册学生，姓名快照同步校正。"""
    org, owner, headers = _school(client, db, "改绑")
    roster = _roster_student(db, org, owner, "001班", "张杉", "2026001")
    exam = _exam(client, headers, "改绑考试")
    submission = _submission(
        db, exam_id=exam["id"], uploader_id=owner.id, student_name="张彬"
    )

    r = client.patch(
        f"{settings.API_V1_STR}/exams/{exam['id']}/submissions/{submission.id}/student",
        headers=headers,
        json={
            "class_name": "001班",
            "student_name": "张彬",
            "student_identifier": "2026001",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["student_name"] == "张杉"  # 以花名册为准
    db.refresh(submission)
    assert submission.student_id == roster.id


def test_reassign_requires_identity_info(client: TestClient, db: Session) -> None:
    _org, owner, headers = _school(client, db, "空改绑")
    exam = _exam(client, headers, "空改绑考试")
    submission = _submission(
        db, exam_id=exam["id"], uploader_id=owner.id, student_name="某人"
    )
    r = client.patch(
        f"{settings.API_V1_STR}/exams/{exam['id']}/submissions/{submission.id}/student",
        headers=headers,
        json={},
    )
    assert r.status_code == 422


def test_exam_annotations_returns_all_submissions_annotations(
    client: TestClient, db: Session
) -> None:
    """横批合并接口：一次返回全考试批注，带 submission_id。"""
    from app.models import SubmissionAnnotation

    _org, owner, headers = _school(client, db, "横批")
    exam = _exam(client, headers, "横批考试")
    sub_a = _submission(db, exam_id=exam["id"], uploader_id=owner.id, student_name="甲")
    sub_b = _submission(db, exam_id=exam["id"], uploader_id=owner.id, student_name="乙")
    for submission, label in ((sub_a, "Q1"), (sub_a, "Q2"), (sub_b, "Q1")):
        db.add(
            SubmissionAnnotation(
                submission_id=submission.id,
                label=label,
                x=0.1,
                y=0.1,
                width=0.2,
                height=0.2,
            )
        )
    db.commit()

    r = client.get(
        f"{settings.API_V1_STR}/exams/{exam['id']}/annotations", headers=headers
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert len(data) == 3
    by_sub = {}
    for item in data:
        by_sub.setdefault(item["submission_id"], []).append(item["label"])
    assert sorted(by_sub[str(sub_a.id)]) == ["Q1", "Q2"]
    assert by_sub[str(sub_b.id)] == ["Q1"]
