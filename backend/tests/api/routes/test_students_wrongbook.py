import uuid
from io import BytesIO
from typing import Literal

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    AnnotationGradingStatus,
    ClassGroup,
    Exam,
    ExamQuestion,
    ExamQuestionKnowledgeLink,
    ExamQuestionRegion,
    ExamQuestionStatus,
    ExamRegion,
    KnowledgePoint,
    Organization,
    QuestionKnowledgeSource,
    StoredFile,
    Student,
    StudentSubmission,
    SubmissionAnnotation,
    User,
    UserCreate,
    UserRole,
    WrongQuestionEntry,
)
from app.services.object_storage import put_storage_bytes
from app.services.wrongbook import build_entry_image_key
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


def build_page_png(width: int = 900, height: int = 1200) -> bytes:
    """造一张有内容的页面图，用于真实裁切与 WebP 编码。"""
    image = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        (
            round(width * 0.05),
            round(height * 0.05),
            round(width * 0.95),
            round(height * 0.45),
        ),
        outline=(20, 20, 20),
        width=3,
    )
    draw.line(
        (
            round(width * 0.1),
            round(height * 0.2),
            round(width * 0.8),
            round(height * 0.3),
        ),
        fill=(30, 60, 120),
        width=5,
    )
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _graded_exam(
    db: Session,
    org: Organization,
    owner: User,
    *,
    student_name: str = "刘雨欣",
    with_knowledge_point: bool = True,
    page_png: bytes | None = None,
    second_question: Literal["none", "wrong", "full"] = "none",
) -> tuple[Exam, Student, StudentSubmission]:
    """建一场已批改的考试：题目、题区、班级学生和逐题批注都齐备。

    `page_png` 给定时把真实页面图写进存储，使裁图与 WebP 编码真正跑起来；
    `second_question` 用于覆盖同页多题（渲染缓存）与满分题不产图。
    """
    exam = Exam(title="期中物理", subject="物理", owner_id=owner.id, org_id=org.id)
    db.add(exam)
    db.commit()
    db.refresh(exam)

    region = ExamRegion(
        exam_id=exam.id,
        label="第1题",
        page_number=1,
        x=0.05,
        y=0.05,
        width=0.9,
        height=0.4,
    )
    db.add(region)
    db.flush()
    question = ExamQuestion(
        exam_id=exam.id,
        question_key="1",
        label="第1题",
        question_text="一物体做匀速直线运动，求其功率。",
        question_type="calculation",
        knowledge_point="功和功率",
        status=ExamQuestionStatus.CONFIRMED,
    )
    db.add(question)
    db.flush()
    db.add(ExamQuestionRegion(question_id=question.id, exam_region_id=region.id))
    if with_knowledge_point:
        point = KnowledgePoint(
            subject="物理",
            code=f"ph.test.{uuid.uuid4().hex[:8]}",
            name="功和功率",
        )
        db.add(point)
        db.flush()
        db.add(
            ExamQuestionKnowledgeLink(
                question_id=question.id,
                knowledge_point_id=point.id,
                source=QuestionKnowledgeSource.TEACHER,
                is_primary=True,
            )
        )

    class_group = ClassGroup(
        name=f"001班-{random_lower_string()[:6]}", org_id=org.id, owner_id=owner.id
    )
    db.add(class_group)
    db.flush()
    student = Student(class_id=class_group.id, name=student_name)
    db.add(student)
    db.flush()

    storage_key = f"test/{uuid.uuid4().hex}"
    if page_png is None:
        stored_file = StoredFile(
            original_filename="answer.pdf",
            content_type="application/pdf",
            storage_key=storage_key,
            size_bytes=10,
            sha256=uuid.uuid4().hex * 2,
            uploaded_by_id=owner.id,
        )
    else:
        put_storage_bytes(storage_key, page_png)
        stored_file = StoredFile(
            original_filename="answer.png",
            content_type="image/png",
            storage_key=storage_key,
            size_bytes=len(page_png),
            sha256=uuid.uuid4().hex * 2,
            uploaded_by_id=owner.id,
        )
    db.add(stored_file)
    db.flush()
    submission = StudentSubmission(
        exam_id=exam.id,
        stored_file_id=stored_file.id,
        student_id=student.id,
        student_name=student_name,
        class_name=class_group.name,
    )
    db.add(submission)
    db.flush()
    annotation = SubmissionAnnotation(
        submission_id=submission.id,
        exam_region_id=region.id,
        label="第1题",
        page_number=1,
        x=0.05,
        y=0.05,
        width=0.9,
        height=0.4,
        score=6,
        max_score=10,
        comment="过程不完整",
        ocr_text="P=W/t",
        score_source="human",
        grading_status=AnnotationGradingStatus.SUCCEEDED,
    )
    annotation.grading_evidence = [
        {"stage": "vision_extraction", "student_answer": "P=W/t"},
        {"point": "写出公式", "matched": True, "points": 4, "reason": "已写出"},
        {"point": "代入数据", "matched": False, "points": 6, "reason": "缺少代入过程"},
    ]
    db.add(annotation)

    if second_question != "none":
        # 第二道题落在同一页，用于验证按页缓存渲染与满分题不产图
        second_region = ExamRegion(
            exam_id=exam.id,
            label="第2题",
            page_number=1,
            x=0.05,
            y=0.5,
            width=0.5,
            height=0.2,
        )
        db.add(second_region)
        db.flush()
        second_exam_question = ExamQuestion(
            exam_id=exam.id,
            question_key="2",
            label="第2题",
            question_text="求电阻两端电压。",
            question_type="calculation",
            status=ExamQuestionStatus.CONFIRMED,
        )
        db.add(second_exam_question)
        db.flush()
        db.add(
            ExamQuestionRegion(
                question_id=second_exam_question.id, exam_region_id=second_region.id
            )
        )
        db.add(
            SubmissionAnnotation(
                submission_id=submission.id,
                exam_region_id=second_region.id,
                label="第2题",
                page_number=1,
                x=0.05,
                y=0.5,
                width=0.5,
                height=0.2,
                score=4 if second_question == "wrong" else 10,
                max_score=10,
                score_source="human",
                grading_status=AnnotationGradingStatus.SUCCEEDED,
            )
        )

    db.commit()
    db.refresh(exam)
    db.refresh(student)
    db.refresh(submission)
    return exam, student, submission


def _bind_student_account(
    db: Session, org: Organization, student: Student
) -> tuple[User, str]:
    user, password = _user(db, UserRole.STUDENT, org)
    student.user_id = user.id
    db.add(student)
    db.commit()
    return user, password


def _publish(client: TestClient, exam: Exam, headers: dict[str, str]) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/grading/exams/{exam.id}/score-releases",
        headers=headers,
        json={},
    )
    assert response.status_code == 200, response.text


def test_student_reads_own_wrongbook_with_reason_and_image(
    client: TestClient, db: Session
) -> None:
    org = Organization(name="错题本一中", code=f"wb-{random_lower_string()}")
    db.add(org)
    db.commit()
    db.refresh(org)
    owner, owner_password = _user(db, UserRole.SCHOOL_OWNER, org)
    owner_headers = _headers(client, owner, owner_password)
    exam, student, _submission = _graded_exam(db, org, owner)
    student_user, student_password = _bind_student_account(db, org, student)
    _publish(client, exam, owner_headers)
    student_headers = _headers(client, student_user, student_password)

    listed = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries", headers=student_headers
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["count"] == 1
    assert body["subjects"] == ["物理"]
    assert body["knowledge_points"] == ["功和功率"]
    item = body["data"][0]
    assert item["question_label"] == "第1题"
    assert item["score"] == 6
    assert item["max_score"] == 10
    assert item["is_wrong"] is True
    assert item["knowledge_point_names"] == ["功和功率"]

    detail = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries/{item['entry_id']}",
        headers=student_headers,
    )
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["question_text"].startswith("一物体做匀速直线运动")
    assert payload["student_answer_text"] == "P=W/t"
    assert payload["teacher_comment"] == "过程不完整"
    assert payload["missed_points"] == [
        {"point": "代入数据", "reason": "缺少代入过程", "points": 6.0}
    ]
    assert payload["knowledge_point_names"] == ["功和功率"]

    # 知识点筛选走 JSONB 包含查询
    filtered = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries?knowledge_point=功和功率",
        headers=student_headers,
    )
    assert filtered.json()["count"] == 1
    missing = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries?knowledge_point=浮力",
        headers=student_headers,
    )
    assert missing.json()["count"] == 0
    # 筛选项不受当前筛选影响，按钮不会自己消失
    assert missing.json()["knowledge_points"] == ["功和功率"]
    # 分页在数据库里做，count 仍是总数
    paged = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries?skip=1",
        headers=student_headers,
    )
    assert paged.json()["count"] == 1
    assert paged.json()["data"] == []

    # 成绩报告要能带着 entry_id 跳进错题本
    report = client.get(
        f"{settings.API_V1_STR}/students/me/exams/{exam.id}/report",
        headers=student_headers,
    )
    assert report.status_code == 200, report.text
    question = report.json()["questions"][0]
    assert question["entry_id"] == item["entry_id"]
    assert question["knowledge_point_names"] == ["功和功率"]


def test_student_cannot_read_another_students_entry(
    client: TestClient, db: Session
) -> None:
    org = Organization(name="错题本二中", code=f"wb2-{random_lower_string()}")
    db.add(org)
    db.commit()
    db.refresh(org)
    owner, owner_password = _user(db, UserRole.SCHOOL_OWNER, org)
    owner_headers = _headers(client, owner, owner_password)
    exam, student, _submission = _graded_exam(db, org, owner, student_name="王小明")
    victim_user, _victim_password = _bind_student_account(db, org, student)
    _publish(client, exam, owner_headers)
    entry = db.exec(
        select(WrongQuestionEntry).where(
            WrongQuestionEntry.student_user_id == victim_user.id
        )
    ).one()

    other_class = ClassGroup(
        name=f"002班-{random_lower_string()[:6]}", org_id=org.id, owner_id=owner.id
    )
    db.add(other_class)
    db.flush()
    other_student = Student(class_id=other_class.id, name="李雷")
    db.add(other_student)
    db.commit()
    other_user, other_password = _bind_student_account(db, org, other_student)
    other_headers = _headers(client, other_user, other_password)

    listed = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries", headers=other_headers
    )
    assert listed.status_code == 200
    assert listed.json()["count"] == 0

    # 别人的错题与不存在的错题返回同一个结果
    detail = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries/{entry.id}",
        headers=other_headers,
    )
    assert detail.status_code == 404
    missing = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries/{uuid.uuid4()}",
        headers=other_headers,
    )
    assert missing.status_code == 404
    assert detail.json()["detail"] == missing.json()["detail"]


def test_wrongbook_entry_image_is_scoped_to_owner(
    client: TestClient, db: Session
) -> None:
    """答题图存在学习者命名空间，取图只校验条目归属，不涉及考试权限。"""
    org = Organization(name="错题图学校", code=f"wbimg-{random_lower_string()}")
    db.add(org)
    db.commit()
    db.refresh(org)
    owner, owner_password = _user(db, UserRole.SCHOOL_OWNER, org)
    owner_headers = _headers(client, owner, owner_password)
    exam, student, _submission = _graded_exam(db, org, owner, student_name="赵敏")
    student_user, student_password = _bind_student_account(db, org, student)
    _publish(client, exam, owner_headers)
    student_headers = _headers(client, student_user, student_password)

    entry = db.exec(
        select(WrongQuestionEntry).where(
            WrongQuestionEntry.student_user_id == student_user.id
        )
    ).one()
    # 测试环境没有真实答卷文件，裁切会优雅失败，这里直接放一张图验证取图链路
    key = build_entry_image_key(entry_id=entry.id)
    put_storage_bytes(key, b"fake-webp-bytes")
    entry.image_storage_key = key
    db.add(entry)
    db.commit()

    listed = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries", headers=student_headers
    )
    assert listed.json()["data"][0]["has_image"] is True

    image_url = f"{settings.API_V1_STR}/students/me/wrongbook/entries/{entry.id}/image"
    image = client.get(image_url, headers=student_headers)
    assert image.status_code == 200, image.text
    assert image.content == b"fake-webp-bytes"
    assert image.headers["content-type"] == "image/webp"

    # 未认证与教师身份都不能取
    assert client.get(image_url).status_code == 401
    assert client.get(image_url, headers=owner_headers).status_code == 403


def test_snapshot_writes_real_webp_and_renders_each_page_once(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """真实页面图下走通裁切 + WebP 编码，并确认同一页只渲染一次。"""
    from app.services import wrongbook as wrongbook_service

    org = Organization(name="真实图学校", code=f"realimg-{random_lower_string()}")
    db.add(org)
    db.commit()
    db.refresh(org)
    owner, owner_password = _user(db, UserRole.SCHOOL_OWNER, org)
    owner_headers = _headers(client, owner, owner_password)

    renders: list[int] = []
    original_render = wrongbook_service.render_stored_file_page_image

    def counting_render(**kwargs: object) -> Image.Image:
        renders.append(1)
        return original_render(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        wrongbook_service, "render_stored_file_page_image", counting_render
    )

    exam, student, _submission = _graded_exam(
        db,
        org,
        owner,
        student_name="孙悦",
        page_png=build_page_png(),
        second_question="wrong",
    )
    student_user, student_password = _bind_student_account(db, org, student)
    _publish(client, exam, owner_headers)
    student_headers = _headers(client, student_user, student_password)

    entries = db.exec(
        select(WrongQuestionEntry)
        .where(WrongQuestionEntry.student_user_id == student_user.id)
        .order_by(WrongQuestionEntry.question_label)
    ).all()
    assert len(entries) == 2
    assert all(entry.is_wrong for entry in entries)
    assert all(entry.image_storage_key for entry in entries)
    # 两道错题在同一页：按页缓存后只渲染一次
    assert len(renders) == 1

    image = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries/{entries[0].id}/image",
        headers=student_headers,
    )
    assert image.status_code == 200, image.text
    assert image.headers["content-type"] == "image/webp"
    assert image.content[:4] == b"RIFF"
    with Image.open(BytesIO(image.content)) as decoded:
        assert decoded.format == "WEBP"
        assert decoded.width > 0


def test_snapshot_downscales_wide_crops_and_skips_full_marks(
    client: TestClient, db: Session
) -> None:
    """超宽裁图缩到上限；满分题只留统计行，不复制图。"""
    org = Organization(name="缩放学校", code=f"resize-{random_lower_string()}")
    db.add(org)
    db.commit()
    db.refresh(org)
    owner, owner_password = _user(db, UserRole.SCHOOL_OWNER, org)
    owner_headers = _headers(client, owner, owner_password)

    exam, student, _submission = _graded_exam(
        db,
        org,
        owner,
        student_name="周涛",
        # 页面宽 3000，题区占 90% 宽，裁出来远超 IMAGE_MAX_WIDTH
        page_png=build_page_png(width=3000, height=2000),
        second_question="full",
    )
    student_user, student_password = _bind_student_account(db, org, student)
    _publish(client, exam, owner_headers)
    student_headers = _headers(client, student_user, student_password)

    entries = {
        entry.question_label: entry
        for entry in db.exec(
            select(WrongQuestionEntry).where(
                WrongQuestionEntry.student_user_id == student_user.id
            )
        ).all()
    }
    wrong, full = entries["第1题"], entries["第2题"]
    assert wrong.is_wrong is True
    assert wrong.image_storage_key
    # 满分题也建行（掌握度需要分母），但不留图
    assert full.is_wrong is False
    assert full.image_storage_key is None

    image = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries/{wrong.id}/image",
        headers=student_headers,
    )
    assert image.status_code == 200
    with Image.open(BytesIO(image.content)) as decoded:
        assert decoded.width == wrongbook_image_max_width()

    # 默认只看错题，满分题不出现在列表里
    listed = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries", headers=student_headers
    )
    assert [item["question_label"] for item in listed.json()["data"]] == ["第1题"]
    with_full = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries?wrong_only=false",
        headers=student_headers,
    )
    assert len(with_full.json()["data"]) == 2


def wrongbook_image_max_width() -> int:
    from app.services.wrongbook import IMAGE_MAX_WIDTH

    return IMAGE_MAX_WIDTH


def test_teacher_cannot_use_student_wrongbook_endpoints(
    client: TestClient, db: Session
) -> None:
    org = Organization(name="错题本三中", code=f"wb3-{random_lower_string()}")
    db.add(org)
    db.commit()
    db.refresh(org)
    teacher, password = _user(db, UserRole.TEACHER, org)
    headers = _headers(client, teacher, password)
    response = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries", headers=headers
    )
    assert response.status_code == 403


def test_wrongbook_survives_exam_deletion(client: TestClient, db: Session) -> None:
    """D-027 回归：老师删掉考试，学生的错题本仍然完整可读。"""
    org = Organization(name="错题本四中", code=f"wb4-{random_lower_string()}")
    db.add(org)
    db.commit()
    db.refresh(org)
    owner, owner_password = _user(db, UserRole.SCHOOL_OWNER, org)
    owner_headers = _headers(client, owner, owner_password)
    exam, student, _submission = _graded_exam(db, org, owner, student_name="陈静")
    student_user, student_password = _bind_student_account(db, org, student)
    _publish(client, exam, owner_headers)
    student_headers = _headers(client, student_user, student_password)

    deleted = client.delete(
        f"{settings.API_V1_STR}/exams/{exam.id}", headers=owner_headers
    )
    assert deleted.status_code == 200, deleted.text

    listed = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries", headers=student_headers
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["count"] == 1
    item = body["data"][0]
    # 来源已被清空，但快照自带题面信息
    assert item["exam_id"] is None
    assert item["exam_title"] == "期中物理"

    detail = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries/{item['entry_id']}",
        headers=student_headers,
    )
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["question_text"].startswith("一物体做匀速直线运动")
    assert payload["missed_points"][0]["point"] == "代入数据"
