import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    AnnotationGradingStatus,
    Exam,
    Organization,
    ScoreRelease,
    ScoreReleaseItem,
    ScoreReleaseStatus,
    StoredFile,
    StudentSubmission,
    SubmissionAnnotation,
    User,
    UserCreate,
    UserRole,
)
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def _user(db: Session, role: UserRole, org: Organization) -> tuple[User, str]:
    password = random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(),
            password=password,
            role=role,
            org_id=org.id,
        ),
    )
    return user, password


def _headers(client: TestClient, user: User, password: str) -> dict[str, str]:
    return user_authentication_headers(
        client=client, email=user.email, password=password
    )


def _submission(
    db: Session,
    exam: Exam,
    uploader: User,
    *,
    student_name: str = "张三",
) -> StudentSubmission:
    stored_file = StoredFile(
        original_filename="answer.pdf",
        content_type="application/pdf",
        storage_key=f"test/{uuid.uuid4().hex}",
        size_bytes=10,
        sha256=uuid.uuid4().hex * 2,
        uploaded_by_id=uploader.id,
    )
    db.add(stored_file)
    db.flush()
    submission = StudentSubmission(
        exam_id=exam.id,
        stored_file_id=stored_file.id,
        student_name=student_name,
        class_name="001班",
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return submission


def test_score_release_requires_review_then_creates_immutable_versions(
    client: TestClient, db: Session
) -> None:
    org = Organization(name="成绩发布学校", code=f"release-{random_lower_string()}")
    db.add(org)
    db.commit()
    db.refresh(org)
    owner, owner_password = _user(db, UserRole.SCHOOL_OWNER, org)
    admin, admin_password = _user(db, UserRole.SCHOOL_ADMIN, org)
    owner_headers = _headers(client, owner, owner_password)
    admin_headers = _headers(client, admin, admin_password)
    exam = Exam(title="成绩发布测试", owner_id=owner.id, org_id=org.id)
    db.add(exam)
    db.commit()
    db.refresh(exam)
    submission = _submission(db, exam, owner)
    annotation = SubmissionAnnotation(
        submission_id=submission.id,
        label="第1题",
        page_number=1,
        x=0.1,
        y=0.1,
        width=0.2,
        height=0.2,
        score=8,
        max_score=10,
        score_source="auto",
        grading_status=AnnotationGradingStatus.NEEDS_REVIEW,
    )
    db.add(annotation)
    db.commit()
    db.refresh(annotation)
    url = f"{settings.API_V1_STR}/grading/exams/{exam.id}/score-releases"

    blocked = client.post(url, headers=owner_headers, json={})
    assert blocked.status_code == 409
    assert "1 道题待复核" in blocked.json()["detail"]

    annotation.score_source = "human"
    db.add(annotation)
    db.commit()
    first = client.post(url, headers=owner_headers, json={})
    assert first.status_code == 200, first.text
    assert first.json()["version"] == 1
    assert first.json()["item_count"] == 1

    first_item = db.exec(
        select(ScoreReleaseItem).where(
            ScoreReleaseItem.release_id == uuid.UUID(first.json()["id"])
        )
    ).one()
    assert first_item.score == 8

    annotation.score = 9
    db.add(annotation)
    db.commit()
    db.refresh(first_item)
    assert first_item.score == 8

    second = client.post(
        url,
        headers=owner_headers,
        json={"reason": "复核后重新发布"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["version"] == 2
    releases = list(
        db.exec(
            select(ScoreRelease)
            .where(ScoreRelease.exam_id == exam.id)
            .order_by(ScoreRelease.version)
        ).all()
    )
    assert [item.status for item in releases] == [
        ScoreReleaseStatus.SUPERSEDED,
        ScoreReleaseStatus.PUBLISHED,
    ]

    current = client.get(f"{url}/current", headers=owner_headers)
    assert current.status_code == 200
    assert current.json()["version"] == 2
    assert current.json()["item_count"] == 1

    forbidden = client.post(url, headers=admin_headers, json={})
    assert forbidden.status_code == 403


def test_score_release_rejects_incomplete_submissions(
    client: TestClient, db: Session
) -> None:
    org = Organization(name="不完整成绩学校", code=f"incomplete-{random_lower_string()}")
    db.add(org)
    db.commit()
    db.refresh(org)
    owner, password = _user(db, UserRole.SCHOOL_OWNER, org)
    headers = _headers(client, owner, password)
    exam = Exam(title="未完成批改", owner_id=owner.id, org_id=org.id)
    db.add(exam)
    db.commit()
    db.refresh(exam)
    scored_submission = _submission(db, exam, owner)
    _submission(db, exam, owner, student_name="李四")
    db.add(
        SubmissionAnnotation(
            submission_id=scored_submission.id,
            label="第1题",
            page_number=1,
            x=0.1,
            y=0.1,
            width=0.2,
            height=0.2,
            score=10,
            max_score=10,
            score_source="human",
            grading_status=AnnotationGradingStatus.SUCCEEDED,
        )
    )
    db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/grading/exams/{exam.id}/score-releases",
        headers=headers,
        json={},
    )
    assert response.status_code == 409
    assert "1 份答卷未完成批改" in response.json()["detail"]
