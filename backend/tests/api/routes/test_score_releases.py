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
    WrongQuestionEntry,
    WrongQuestionEntryStatus,
    WrongQuestionSource,
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


def _publish(client: TestClient, exam: Exam, headers: dict[str, str]) -> dict:
    response = client.post(
        f"{settings.API_V1_STR}/grading/exams/{exam.id}/score-releases",
        headers=headers,
        json={},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _entries(db: Session, exam_id: uuid.UUID) -> list[WrongQuestionEntry]:
    return list(
        db.exec(
            select(WrongQuestionEntry)
            .join(
                WrongQuestionSource,
                WrongQuestionEntry.source_id == WrongQuestionSource.id,
            )
            .where(WrongQuestionSource.exam_id == exam_id)
            .order_by(WrongQuestionEntry.question_label)
        ).all()
    )


def test_score_release_snapshots_wrongbook_entries(
    client: TestClient, db: Session
) -> None:
    """发布成绩会把逐题结果快照进错题本，满分题也留统计行但不算错题。"""
    org = Organization(name="错题本学校", code=f"wrongbook-{random_lower_string()}")
    db.add(org)
    db.commit()
    db.refresh(org)
    owner, password = _user(db, UserRole.SCHOOL_OWNER, org)
    headers = _headers(client, owner, password)
    exam = Exam(title="错题本快照", subject="物理", owner_id=owner.id, org_id=org.id)
    db.add(exam)
    db.commit()
    db.refresh(exam)
    submission = _submission(db, exam, owner)
    wrong = SubmissionAnnotation(
        submission_id=submission.id,
        label="第1题",
        page_number=1,
        x=0.1,
        y=0.1,
        width=0.2,
        height=0.2,
        score=6,
        max_score=10,
        comment="过程不完整",
        ocr_text="P=W/t",
        score_source="human",
        grading_status=AnnotationGradingStatus.SUCCEEDED,
    )
    wrong.grading_evidence = [
        {"stage": "vision_extraction", "student_answer": "P=W/t"},
        {"point": "写出公式", "matched": True, "points": 4, "reason": "已写出"},
        {"point": "代入数据", "matched": False, "points": 4, "reason": "缺少代入过程"},
        {"stage": "grading", "provider": "p"},
    ]
    full = SubmissionAnnotation(
        submission_id=submission.id,
        label="第2题",
        page_number=1,
        x=0.1,
        y=0.4,
        width=0.2,
        height=0.2,
        score=10,
        max_score=10,
        score_source="human",
        grading_status=AnnotationGradingStatus.SUCCEEDED,
    )
    db.add_all([wrong, full])
    db.commit()

    published = _publish(client, exam, headers)
    entries = _entries(db, exam.id)
    assert [entry.question_label for entry in entries] == ["第1题", "第2题"]
    first, second = entries
    assert first.is_wrong is True
    assert second.is_wrong is False
    # 只留未命中的评分点，流水线阶段记录不进错题本
    assert first.missed_points == [
        {"point": "代入数据", "reason": "缺少代入过程", "points": 4.0}
    ]
    assert first.student_answer_text == "P=W/t"
    assert first.teacher_comment == "过程不完整"
    assert first.release_version == published["version"]
    assert first.student_user_id is None

    # 幂等：同一次发布重复投递不产生重复条目
    from app.worker import run_wrongbook_snapshot

    run_wrongbook_snapshot(published["id"])
    assert len(_entries(db, exam.id)) == 2

    # 重新发布：旧条目被取代，新条目为 active
    wrong.score = 8
    db.add(wrong)
    db.commit()
    republished = _publish(client, exam, headers)
    entries = _entries(db, exam.id)
    assert len(entries) == 4
    active = [
        entry for entry in entries if entry.status == WrongQuestionEntryStatus.ACTIVE
    ]
    assert {entry.release_version for entry in active} == {republished["version"]}
    superseded = [
        entry
        for entry in entries
        if entry.status == WrongQuestionEntryStatus.SUPERSEDED
    ]
    assert len(superseded) == 2


def test_wrongbook_hides_model_scoring_points_after_teacher_override(
    client: TestClient, db: Session
) -> None:
    """教师改过分就不展示模型的评分点判断，避免两套互相矛盾的说法。"""
    org = Organization(name="改分学校", code=f"override-{random_lower_string()}")
    db.add(org)
    db.commit()
    db.refresh(org)
    owner, password = _user(db, UserRole.SCHOOL_OWNER, org)
    headers = _headers(client, owner, password)
    exam = Exam(title="教师改分", subject="物理", owner_id=owner.id, org_id=org.id)
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
        score=9,
        max_score=10,
        model_score=5,
        comment="步骤合理，酌情给分",
        score_source="human",
        grading_status=AnnotationGradingStatus.SUCCEEDED,
    )
    annotation.grading_evidence = [
        {"point": "代入数据", "matched": False, "points": 4, "reason": "缺少代入过程"}
    ]
    db.add(annotation)
    db.commit()

    _publish(client, exam, headers)
    entry = _entries(db, exam.id)[0]
    assert entry.missed_points == []
    assert entry.teacher_comment == "步骤合理，酌情给分"


def test_score_release_rejects_incomplete_submissions(
    client: TestClient, db: Session
) -> None:
    org = Organization(
        name="不完整成绩学校", code=f"incomplete-{random_lower_string()}"
    )
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
