import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from app import crud
from app.core.config import settings
from app.models import (
    AnnotationGradingStatus,
    ScoreRelease,
    ScoreReleaseItem,
    StoredFile,
    StudentSubmission,
    SubmissionAnnotation,
    User,
    UserCreate,
    UserRole,
)
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string

DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001"


def _create_user_with_role(db: Session, role: UserRole) -> tuple[User, str]:
    email = random_email()
    password = random_lower_string()
    # 学校角色统一挂到默认学校，平台角色 org_id 为 None
    org_id = None if role.value.startswith("platform_") else DEFAULT_ORG_ID
    user_in = UserCreate(email=email, password=password, role=role, org_id=org_id)
    user = crud.create_user(session=db, user_create=user_in)
    return user, password


def _headers(client: TestClient, user: User, password: str) -> dict[str, str]:
    return user_authentication_headers(
        client=client, email=user.email, password=password
    )


def _create_class(client: TestClient, headers: dict[str, str], name: str) -> dict:
    r = client.post(
        f"{settings.API_V1_STR}/classes/", headers=headers, json={"name": name}
    )
    assert r.status_code == 200, r.text
    return r.json()


def _create_student(
    client: TestClient, headers: dict[str, str], class_id: str, name: str
) -> dict:
    r = client.post(
        f"{settings.API_V1_STR}/classes/{class_id}/students",
        headers=headers,
        json={"name": name},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _make_stored_file(db: Session, owner_id: uuid.UUID) -> StoredFile:
    stored_file = StoredFile(
        original_filename=f"{uuid.uuid4().hex}.pdf",
        content_type="application/pdf",
        storage_key=f"test/{uuid.uuid4().hex}",
        size_bytes=10,
        sha256=uuid.uuid4().hex * 2,
        uploaded_by_id=owner_id,
    )
    db.add(stored_file)
    db.commit()
    db.refresh(stored_file)
    return stored_file


def _make_submission(
    db: Session,
    *,
    exam_id: uuid.UUID,
    owner_id: uuid.UUID,
    student_name: str,
    class_name: str,
    student_id: uuid.UUID | None = None,
) -> StudentSubmission:
    stored_file = _make_stored_file(db, owner_id)
    submission = StudentSubmission(
        exam_id=exam_id,
        stored_file_id=stored_file.id,
        student_name=student_name,
        class_name=class_name,
        student_id=student_id,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return submission


def _make_annotation(
    db: Session,
    *,
    submission_id: uuid.UUID,
    label: str,
    score: float,
    max_score: float,
    score_source: str | None = None,
    comment: str | None = None,
    suggested_comment: str | None = None,
    grading_status: AnnotationGradingStatus = AnnotationGradingStatus.NOT_STARTED,
) -> SubmissionAnnotation:
    annotation = SubmissionAnnotation(
        submission_id=submission_id,
        label=label,
        page_number=1,
        x=0.1,
        y=0.1,
        width=0.2,
        height=0.2,
        score=score,
        max_score=max_score,
        score_source=score_source,
        comment=comment,
        suggested_comment=suggested_comment,
        grading_status=grading_status,
    )
    db.add(annotation)
    db.commit()
    db.refresh(annotation)
    return annotation


def _publish_scores(db: Session, *, exam_id: uuid.UUID, teacher_id: uuid.UUID) -> None:
    release = ScoreRelease(exam_id=exam_id, version=1, published_by_id=teacher_id)
    db.add(release)
    db.flush()
    submissions = list(
        db.exec(
            select(StudentSubmission).where(StudentSubmission.exam_id == exam_id)
        ).all()
    )
    annotations = db.exec(
        select(SubmissionAnnotation).where(
            col(SubmissionAnnotation.submission_id).in_(
                [item.id for item in submissions]
            )
        )
    ).all()
    db.add_all(
        [
            ScoreReleaseItem(
                release_id=release.id,
                submission_id=item.submission_id,
                annotation_id=item.id,
                label=item.label,
                score=item.score,
                max_score=item.max_score,
                comment=item.comment,
                source="human" if item.score_source == "human" else "suggested",
            )
            for item in annotations
        ]
    )
    db.commit()


def _setup_teacher_with_classes(
    client: TestClient, db: Session
) -> tuple[User, dict[str, str], dict, dict]:
    teacher, password = _create_user_with_role(db, UserRole.TEACHER)
    headers = _headers(client, teacher, password)
    class_1 = _create_class(client, headers, "001班")
    class_2 = _create_class(client, headers, "002班")
    return teacher, headers, class_1, class_2


def _create_bound_student_account(
    client: TestClient,
    db: Session,
    teacher_headers: dict[str, str],
    class_id: str,
    name: str,
) -> tuple[User, dict[str, str], dict]:
    student_profile = _create_student(client, teacher_headers, class_id, name)
    user, password = _create_user_with_role(db, UserRole.STUDENT)
    r = client.post(
        f"{settings.API_V1_STR}/classes/students/{student_profile['id']}/bind-account",
        headers=teacher_headers,
        json={"user_id": str(user.id)},
    )
    assert r.status_code == 200, r.text
    return user, _headers(client, user, password), student_profile


def test_exam_create_and_update_with_new_fields(
    client: TestClient, db: Session
) -> None:
    _teacher, headers, class_1, class_2 = _setup_teacher_with_classes(client, db)

    r = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=headers,
        json={
            "title": "高二物理双页卷",
            "subject": "物理",
            "exam_date": "2026-07-20",
            "description": "高二物理双页卷演示",
            "class_ids": [class_1["id"], class_2["id"]],
        },
    )
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["exam_date"] == "2026-07-20"
    assert created["description"] == "高二物理双页卷演示"
    assert created["class_ids"] == [class_1["id"], class_2["id"]]
    assert created["class_names"] == ["001班", "002班"]
    exam_id = created["id"]

    r = client.get(f"{settings.API_V1_STR}/exams/{exam_id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["class_names"] == ["001班", "002班"]
    assert r.json()["exam_date"] == "2026-07-20"

    r = client.get(f"{settings.API_V1_STR}/exams/", headers=headers)
    assert r.status_code == 200
    listed = next(item for item in r.json()["data"] if item["id"] == exam_id)
    assert listed["class_ids"] == [class_1["id"], class_2["id"]]
    assert listed["description"] == "高二物理双页卷演示"

    # PATCH 重建班级关联 + 更新备注
    r = client.patch(
        f"{settings.API_V1_STR}/exams/{exam_id}",
        headers=headers,
        json={"description": "更新后的备注", "class_ids": [class_2["id"]]},
    )
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["description"] == "更新后的备注"
    assert updated["class_ids"] == [class_2["id"]]
    assert updated["class_names"] == ["002班"]
    assert updated["exam_date"] == "2026-07-20"

    # 不带 class_ids 的 PATCH 不动关联
    r = client.patch(
        f"{settings.API_V1_STR}/exams/{exam_id}",
        headers=headers,
        json={"title": "新标题"},
    )
    assert r.status_code == 200
    assert r.json()["class_ids"] == [class_2["id"]]

    # 不存在的班级 → 400
    r = client.patch(
        f"{settings.API_V1_STR}/exams/{exam_id}",
        headers=headers,
        json={"class_ids": [str(uuid.uuid4())]},
    )
    assert r.status_code == 400

    # 其他教师创建的班级：全校共享，可以关联
    other_teacher, other_password = _create_user_with_role(db, UserRole.TEACHER)
    other_headers = _headers(client, other_teacher, other_password)
    other_class = _create_class(client, other_headers, "003班")
    r = client.patch(
        f"{settings.API_V1_STR}/exams/{exam_id}",
        headers=headers,
        json={"class_ids": [other_class["id"]]},
    )
    assert r.status_code == 200
    assert r.json()["class_names"] == ["003班"]


def test_student_exam_list_and_report(client: TestClient, db: Session) -> None:
    teacher, headers, class_1, class_2 = _setup_teacher_with_classes(client, db)
    _user, student_headers, profile = _create_bound_student_account(
        client, db, headers, class_1["id"], "张三"
    )
    student_id = uuid.UUID(profile["id"])

    # 考试 1：我（student_id 绑定）+ 同班同学 + 别班学生
    r = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=headers,
        json={
            "title": "物理月考",
            "subject": "物理",
            "grade_level": "高二",
            "exam_date": "2026-07-20",
            "class_ids": [class_1["id"]],
        },
    )
    assert r.status_code == 200, r.text
    exam_id = uuid.UUID(r.json()["id"])

    my_submission = _make_submission(
        db,
        exam_id=exam_id,
        owner_id=teacher.id,
        student_name="张三",
        class_name="001班",
        student_id=student_id,
    )
    _make_annotation(
        db,
        submission_id=my_submission.id,
        label="1",
        score=40,
        max_score=50,
        score_source="human",
        comment="步骤分扣 10 分",
        suggested_comment="AI：部分正确",
    )
    _make_annotation(
        db,
        submission_id=my_submission.id,
        label="2",
        score=40,
        max_score=50,
        suggested_comment="AI：建议复核",
        grading_status=AnnotationGradingStatus.NEEDS_REVIEW,
    )
    classmate_submission = _make_submission(
        db,
        exam_id=exam_id,
        owner_id=teacher.id,
        student_name="李四",
        class_name="001班",
    )
    _make_annotation(
        db,
        submission_id=classmate_submission.id,
        label="1",
        score=90,
        max_score=100,
        score_source="human",
    )
    other_class_submission = _make_submission(
        db,
        exam_id=exam_id,
        owner_id=teacher.id,
        student_name="王五",
        class_name="002班",
    )
    _make_annotation(
        db,
        submission_id=other_class_submission.id,
        label="1",
        score=100,
        max_score=100,
        score_source="human",
    )

    # 考试 2：仅靠「班级 + 姓名」兜底匹配（无 student_id）
    r = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=headers,
        json={"title": "物理周测", "exam_date": "2026-07-10"},
    )
    assert r.status_code == 200, r.text
    exam2_id = uuid.UUID(r.json()["id"])
    fallback_submission = _make_submission(
        db,
        exam_id=exam2_id,
        owner_id=teacher.id,
        student_name="张三",
        class_name="001班",
    )
    _make_annotation(
        db,
        submission_id=fallback_submission.id,
        label="1",
        score=60,
        max_score=100,
        score_source="human",
    )

    # 别的学生的考试：我不可见
    r = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=headers,
        json={"title": "别人的考试"},
    )
    assert r.status_code == 200
    other_exam_id = r.json()["id"]
    stranger_submission = _make_submission(
        db,
        exam_id=uuid.UUID(other_exam_id),
        owner_id=teacher.id,
        student_name="赵六",
        class_name="001班",
    )
    _make_annotation(
        db,
        submission_id=stranger_submission.id,
        label="1",
        score=50,
        max_score=100,
    )

    # Draft scores are invisible until the teacher publishes the whole exam.
    hidden = client.get(
        f"{settings.API_V1_STR}/students/me/exams", headers=student_headers
    )
    assert hidden.status_code == 200
    assert hidden.json()["count"] == 0
    _publish_scores(db, exam_id=exam_id, teacher_id=teacher.id)
    _publish_scores(db, exam_id=exam2_id, teacher_id=teacher.id)

    # 考试列表
    r = client.get(f"{settings.API_V1_STR}/students/me/exams", headers=student_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["count"] == 2
    items = {item["title"]: item for item in data["data"]}
    mine = items["物理月考"]
    assert mine["exam_id"] == str(exam_id)
    assert mine["subject"] == "物理"
    assert mine["grade_level"] == "高二"
    assert mine["exam_date"] == "2026-07-20"
    assert mine["class_name"] == "001班"
    assert mine["total_score"] == 80
    assert mine["total_max_score"] == 100
    # 同班 2 人：李四 90 排第 1，我 80 排第 2；别班王五不计入
    assert mine["class_rank"] == 2
    assert mine["class_size"] == 2
    assert mine["question_count"] == 2
    assert mine["pending_review_count"] == 0
    fallback_item = items["物理周测"]
    assert fallback_item["total_score"] == 60
    assert fallback_item["class_rank"] == 1

    # 逐题报告
    r = client.get(
        f"{settings.API_V1_STR}/students/me/exams/{exam_id}/report",
        headers=student_headers,
    )
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["title"] == "物理月考"
    assert report["exam_date"] == "2026-07-20"
    assert report["class_name"] == "001班"
    assert report["student_name"] == "张三"
    assert report["total_score"] == 80
    assert report["total_max_score"] == 100
    assert report["class_rank"] == 2
    assert report["class_size"] == 2
    questions = {q["label"]: q for q in report["questions"]}
    assert questions["1"]["score"] == 40
    assert questions["1"]["max_score"] == 50
    assert questions["1"]["score_source"] == "final"
    assert questions["1"]["comment"] == "步骤分扣 10 分"
    assert questions["1"]["suggested_comment"] is None
    assert questions["2"]["score_source"] == "final"
    assert questions["2"]["suggested_comment"] is None
    # 看不到别人的任何数据
    assert "李四" not in r.text and "王五" not in r.text

    # 数据隔离：未参加的考试 → 404
    r = client.get(
        f"{settings.API_V1_STR}/students/me/exams/{other_exam_id}/report",
        headers=student_headers,
    )
    assert r.status_code == 404
    r = client.get(
        f"{settings.API_V1_STR}/students/me/exams/{uuid.uuid4()}/report",
        headers=student_headers,
    )
    assert r.status_code == 404


def test_student_endpoints_require_bound_profile(
    client: TestClient, db: Session
) -> None:
    user, password = _create_user_with_role(db, UserRole.STUDENT)
    headers = _headers(client, user, password)
    r = client.get(f"{settings.API_V1_STR}/students/me/exams", headers=headers)
    assert r.status_code == 404
    assert "账号未绑定学生档案" in r.json()["detail"]
    r = client.get(
        f"{settings.API_V1_STR}/students/me/exams/{uuid.uuid4()}/report",
        headers=headers,
    )
    assert r.status_code == 404


def test_teacher_cannot_access_student_endpoints(
    client: TestClient, db: Session
) -> None:
    teacher, password = _create_user_with_role(db, UserRole.TEACHER)
    headers = _headers(client, teacher, password)
    r = client.get(f"{settings.API_V1_STR}/students/me/exams", headers=headers)
    assert r.status_code == 403
    r = client.get(
        f"{settings.API_V1_STR}/students/me/exams/{uuid.uuid4()}/report",
        headers=headers,
    )
    assert r.status_code == 403
