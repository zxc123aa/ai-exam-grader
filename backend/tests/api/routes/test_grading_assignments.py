"""协作批卷（阶段 1+2）测试：任教档案 + 大考共享批卷分配。"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import (
    Organization,
    StoredFile,
    StudentSubmission,
    SubmissionAnnotation,
    User,
    UserCreate,
    UserRole,
)
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def _create_org(db: Session, name: str) -> Organization:
    org = Organization(name=name, code=f"org-{random_lower_string()[:16]}")
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _create_user(
    db: Session, role: UserRole, org: Organization | None, name: str | None = None
) -> tuple[User, str]:
    password = random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(),
            password=password,
            role=role,
            full_name=name,
            org_id=org.id if org else None,
        ),
    )
    return user, password


def _headers(client: TestClient, user: User, password: str) -> dict[str, str]:
    return user_authentication_headers(
        client=client, email=user.email, password=password
    )


def _create_exam(client: TestClient, headers: dict[str, str], title: str) -> dict:
    r = client.post(
        f"{settings.API_V1_STR}/exams/", headers=headers, json={"title": title}
    )
    assert r.status_code == 200, r.text
    return r.json()


def _create_class(client: TestClient, headers: dict[str, str], name: str) -> dict:
    r = client.post(
        f"{settings.API_V1_STR}/classes/", headers=headers, json={"name": name}
    )
    assert r.status_code == 200, r.text
    return r.json()


def _create_submission(
    db: Session,
    *,
    exam_id: uuid.UUID,
    uploader_id: uuid.UUID,
    student_name: str,
    class_name: str,
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
        exam_id=exam_id,
        stored_file_id=stored_file.id,
        student_name=student_name,
        class_name=class_name,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return submission


def _create_annotation(
    db: Session, *, submission_id: uuid.UUID
) -> SubmissionAnnotation:
    annotation = SubmissionAnnotation(
        submission_id=submission_id,
        label="Q1",
        x=0.1,
        y=0.1,
        width=0.2,
        height=0.2,
        score=1,
        max_score=5,
    )
    db.add(annotation)
    db.commit()
    db.refresh(annotation)
    return annotation


def _make_shared_exam(client: TestClient, db: Session) -> dict:
    """搭一套共享批卷场景：学校 + owner(考试 owner) + 两名老师 + 两个班各一份答卷。"""
    org = _create_org(db, "共享批卷学校")
    owner, pw_owner = _create_user(db, UserRole.TEACHER, org, "王老师")
    teacher_a, pw_a = _create_user(db, UserRole.TEACHER, org, "甲老师")
    teacher_b, pw_b = _create_user(db, UserRole.TEACHER, org, "乙老师")
    headers_owner = _headers(client, owner, pw_owner)
    class_1 = _create_class(client, headers_owner, "001班")
    class_2 = _create_class(client, headers_owner, "002班")
    exam = _create_exam(client, headers_owner, "期末大考")
    sub_1 = _create_submission(
        db,
        exam_id=uuid.UUID(exam["id"]),
        uploader_id=owner.id,
        student_name="学生甲",
        class_name="001班",
    )
    sub_2 = _create_submission(
        db,
        exam_id=uuid.UUID(exam["id"]),
        uploader_id=owner.id,
        student_name="学生乙",
        class_name="002班",
    )
    return {
        "org": org,
        "owner": owner,
        "headers_owner": headers_owner,
        "teacher_a": teacher_a,
        "headers_a": _headers(client, teacher_a, pw_a),
        "teacher_b": teacher_b,
        "headers_b": _headers(client, teacher_b, pw_b),
        "class_1": class_1,
        "class_2": class_2,
        "exam": exam,
        "sub_1": sub_1,
        "sub_2": sub_2,
    }


# ---------------------------------------------------------------------------
# 任教档案
# ---------------------------------------------------------------------------
def test_teaching_profile_put_get_and_permissions(
    client: TestClient, db: Session
) -> None:
    org = _create_org(db, "档案学校")
    owner, pw_owner = _create_user(db, UserRole.SCHOOL_OWNER, org)
    teacher, pw_teacher = _create_user(db, UserRole.TEACHER, org)
    teacher_2, pw_teacher_2 = _create_user(db, UserRole.TEACHER, org)
    headers_owner = _headers(client, owner, pw_owner)
    headers_teacher = _headers(client, teacher, pw_teacher)
    headers_teacher_2 = _headers(client, teacher_2, pw_teacher_2)
    class_1 = _create_class(client, headers_owner, "001班")
    class_2 = _create_class(client, headers_owner, "002班")

    # owner 设置任教档案
    r = client.put(
        f"{settings.API_V1_STR}/users/{teacher.id}/teaching",
        headers=headers_owner,
        json={
            "class_ids": [class_1["id"], class_2["id"]],
            "subjects": ["物理", "数学"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["class_ids"]) == {class_1["id"], class_2["id"]}
    assert body["class_names"] == ["001班", "002班"]
    assert body["subjects"] == ["物理", "数学"]

    # 本人可读
    r = client.get(
        f"{settings.API_V1_STR}/users/{teacher.id}/teaching", headers=headers_teacher
    )
    assert r.status_code == 200
    assert r.json()["subjects"] == ["物理", "数学"]

    # 普通老师不能读他人档案、不能写档案
    r = client.get(
        f"{settings.API_V1_STR}/users/{teacher.id}/teaching",
        headers=headers_teacher_2,
    )
    assert r.status_code == 403
    r = client.put(
        f"{settings.API_V1_STR}/users/{teacher_2.id}/teaching",
        headers=headers_teacher,
        json={"class_ids": [], "subjects": []},
    )
    assert r.status_code == 403

    # 整体覆盖
    r = client.put(
        f"{settings.API_V1_STR}/users/{teacher.id}/teaching",
        headers=headers_owner,
        json={"class_ids": [class_2["id"]], "subjects": ["化学"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["class_ids"] == [class_2["id"]]
    assert body["subjects"] == ["化学"]


def test_teaching_profile_cross_school_and_role_guards(
    client: TestClient, db: Session
) -> None:
    org_a = _create_org(db, "档案学校A")
    org_b = _create_org(db, "档案学校B")
    owner_a, pw_owner_a = _create_user(db, UserRole.SCHOOL_OWNER, org_a)
    teacher_a, _ = _create_user(db, UserRole.TEACHER, org_a)
    teacher_b, _ = _create_user(db, UserRole.TEACHER, org_b)
    student_a, _ = _create_user(db, UserRole.STUDENT, org_a)
    headers_owner_a = _headers(client, owner_a, pw_owner_a)
    headers_owner_b_user, pw_owner_b = _create_user(db, UserRole.SCHOOL_OWNER, org_b)
    headers_owner_b = _headers(client, headers_owner_b_user, pw_owner_b)
    class_b = _create_class(client, headers_owner_b, "B校001班")

    # 班级跨校 → 400
    r = client.put(
        f"{settings.API_V1_STR}/users/{teacher_a.id}/teaching",
        headers=headers_owner_a,
        json={"class_ids": [class_b["id"]], "subjects": []},
    )
    assert r.status_code == 400

    # 目标用户跨校 → 404（不泄露他校用户）
    r = client.put(
        f"{settings.API_V1_STR}/users/{teacher_b.id}/teaching",
        headers=headers_owner_a,
        json={"class_ids": [], "subjects": []},
    )
    assert r.status_code == 404

    # 目标角色不是 teacher/school_admin → 400
    r = client.put(
        f"{settings.API_V1_STR}/users/{student_a.id}/teaching",
        headers=headers_owner_a,
        json={"class_ids": [], "subjects": []},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 共享批卷分配 CRUD
# ---------------------------------------------------------------------------
def test_grading_assignments_put_get_overwrite(client: TestClient, db: Session) -> None:
    ctx = _make_shared_exam(client, db)
    exam_id = ctx["exam"]["id"]

    # 未开启时：enabled=false，两个班都在 unassigned
    r = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/grading-assignments",
        headers=ctx["headers_a"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False
    assert body["assignments"] == []
    assert {item["class_name"] for item in body["unassigned"]} == {"001班", "002班"}
    owner_view = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/grading-assignments",
        headers=ctx["headers_owner"],
    ).json()
    candidate = next(
        item
        for item in owner_view["candidates"]
        if item["user_id"] == str(ctx["teacher_a"].id)
    )
    assert candidate["user_name"] == "甲老师"
    assert candidate["class_ids"] == []

    # owner 开启并整体覆盖分配（001班→甲老师）
    r = client.put(
        f"{settings.API_V1_STR}/exams/{exam_id}/grading-assignments",
        headers=ctx["headers_owner"],
        json={
            "enabled": True,
            "assignments": [
                {"class_id": ctx["class_1"]["id"], "user_id": str(ctx["teacher_a"].id)}
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert len(body["assignments"]) == 1
    assert body["assignments"][0]["class_name"] == "001班"
    assert body["assignments"][0]["user_name"] == "甲老师"
    assert [item["class_name"] for item in body["unassigned"]] == ["002班"]

    # 覆盖：002班→乙老师
    r = client.put(
        f"{settings.API_V1_STR}/exams/{exam_id}/grading-assignments",
        headers=ctx["headers_owner"],
        json={
            "enabled": True,
            "assignments": [
                {"class_id": ctx["class_2"]["id"], "user_id": str(ctx["teacher_b"].id)}
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [item["class_name"] for item in body["assignments"]] == ["002班"]
    assert [item["class_name"] for item in body["unassigned"]] == ["001班"]


def test_grading_assignments_validation_and_permissions(
    client: TestClient, db: Session
) -> None:
    ctx = _make_shared_exam(client, db)
    exam_id = ctx["exam"]["id"]
    org_b = _create_org(db, "另一所学校")
    owner_b, pw_owner_b = _create_user(db, UserRole.SCHOOL_OWNER, org_b)
    student, _ = _create_user(db, UserRole.STUDENT, ctx["org"])
    headers_owner_b = _headers(client, owner_b, pw_owner_b)
    class_b = _create_class(client, headers_owner_b, "B校班级")

    # 非 owner/admin 的老师不能写
    r = client.put(
        f"{settings.API_V1_STR}/exams/{exam_id}/grading-assignments",
        headers=ctx["headers_a"],
        json={"enabled": True, "assignments": []},
    )
    assert r.status_code == 403

    # 班级跨校 → 400
    r = client.put(
        f"{settings.API_V1_STR}/exams/{exam_id}/grading-assignments",
        headers=ctx["headers_owner"],
        json={
            "enabled": True,
            "assignments": [
                {"class_id": class_b["id"], "user_id": str(ctx["teacher_a"].id)}
            ],
        },
    )
    assert r.status_code == 400

    # 被分配人是学生 → 400
    r = client.put(
        f"{settings.API_V1_STR}/exams/{exam_id}/grading-assignments",
        headers=ctx["headers_owner"],
        json={
            "enabled": True,
            "assignments": [
                {"class_id": ctx["class_1"]["id"], "user_id": str(student.id)}
            ],
        },
    )
    assert r.status_code == 400

    # 他校老师读 → 404
    r = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/grading-assignments",
        headers=headers_owner_b,
    )
    assert r.status_code == 404


def test_create_run_blocked_until_all_classes_assigned(
    client: TestClient, db: Session
) -> None:
    ctx = _make_shared_exam(client, db)
    exam_id = ctx["exam"]["id"]

    # 只分配 001班就发起批改 → 400，detail 含缺分配班级名
    r = client.put(
        f"{settings.API_V1_STR}/exams/{exam_id}/grading-assignments",
        headers=ctx["headers_owner"],
        json={
            "enabled": True,
            "assignments": [
                {"class_id": ctx["class_1"]["id"], "user_id": str(ctx["teacher_a"].id)}
            ],
        },
    )
    assert r.status_code == 200, r.text
    r = client.post(
        f"{settings.API_V1_STR}/grading/runs",
        headers=ctx["headers_owner"],
        json={"exam_id": exam_id},
    )
    assert r.status_code == 400, r.text
    assert "002班" in r.json()["detail"]

    # 补齐 002班后守卫放行（后续校验报 409 无已发布标准答案，证明不是 400）
    r = client.put(
        f"{settings.API_V1_STR}/exams/{exam_id}/grading-assignments",
        headers=ctx["headers_owner"],
        json={
            "enabled": True,
            "assignments": [
                {"class_id": ctx["class_1"]["id"], "user_id": str(ctx["teacher_a"].id)},
                {"class_id": ctx["class_2"]["id"], "user_id": str(ctx["teacher_b"].id)},
            ],
        },
    )
    assert r.status_code == 200, r.text
    r = client.post(
        f"{settings.API_V1_STR}/grading/runs",
        headers=ctx["headers_owner"],
        json={"exam_id": exam_id},
    )
    assert r.status_code == 409, r.text

    # 关闭共享批卷后不再有分配校验（同样回落到 409）
    r = client.put(
        f"{settings.API_V1_STR}/exams/{exam_id}/grading-assignments",
        headers=ctx["headers_owner"],
        json={"enabled": False, "assignments": []},
    )
    assert r.status_code == 200, r.text
    r = client.post(
        f"{settings.API_V1_STR}/grading/runs",
        headers=ctx["headers_owner"],
        json={"exam_id": exam_id},
    )
    assert r.status_code == 409, r.text


# ---------------------------------------------------------------------------
# 被分配老师的可见性与写权限
# ---------------------------------------------------------------------------
def _assigned_ctx(client: TestClient, db: Session) -> dict:
    """共享批卷场景 + 开启分配：001班→甲老师，002班→乙老师。"""
    ctx = _make_shared_exam(client, db)
    exam_id = ctx["exam"]["id"]
    r = client.put(
        f"{settings.API_V1_STR}/exams/{exam_id}/grading-assignments",
        headers=ctx["headers_owner"],
        json={
            "enabled": True,
            "assignments": [
                {"class_id": ctx["class_1"]["id"], "user_id": str(ctx["teacher_a"].id)},
                {"class_id": ctx["class_2"]["id"], "user_id": str(ctx["teacher_b"].id)},
            ],
        },
    )
    assert r.status_code == 200, r.text
    return ctx


def test_assigned_teacher_exam_list_and_detail_flags(
    client: TestClient, db: Session
) -> None:
    ctx = _assigned_ctx(client, db)
    exam_id = ctx["exam"]["id"]

    # 被分配的甲老师：列表可见且带 is_assigned / shared_grading_enabled 标记
    r = client.get(f"{settings.API_V1_STR}/exams/", headers=ctx["headers_a"])
    assert r.status_code == 200
    mine = [item for item in r.json()["data"] if item["id"] == exam_id]
    assert len(mine) == 1
    assert mine[0]["shared_grading_enabled"] is True
    assert mine[0]["is_assigned"] is True

    # 详情同样可见
    r = client.get(f"{settings.API_V1_STR}/exams/{exam_id}", headers=ctx["headers_a"])
    assert r.status_code == 200
    assert r.json()["is_assigned"] is True

    # owner 可见但不带 is_assigned
    r = client.get(f"{settings.API_V1_STR}/exams/", headers=ctx["headers_owner"])
    mine = [item for item in r.json()["data"] if item["id"] == exam_id]
    assert len(mine) == 1
    assert mine[0]["is_assigned"] is False

    # 未被分配且 sharing 关闭的同校老师：列表不可见、详情 404
    teacher_c, pw_c = _create_user(db, UserRole.TEACHER, ctx["org"])
    headers_c = _headers(client, teacher_c, pw_c)
    r = client.get(f"{settings.API_V1_STR}/exams/", headers=headers_c)
    assert all(item["id"] != exam_id for item in r.json()["data"])
    r = client.get(f"{settings.API_V1_STR}/exams/{exam_id}", headers=headers_c)
    assert r.status_code == 404


def test_assigned_teacher_submissions_and_scores_scoped_to_class(
    client: TestClient, db: Session
) -> None:
    ctx = _assigned_ctx(client, db)
    exam_id = ctx["exam"]["id"]

    # 甲老师（001班）只见本班答卷
    r = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=ctx["headers_a"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    assert body["data"][0]["class_name"] == "001班"
    assert body["data"][0]["student_name"] == "学生甲"

    # 成绩汇总只含本班学生
    r = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/scores/summary",
        headers=ctx["headers_a"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    assert body["data"][0]["class_name"] == "001班"

    # 跨班答卷详情 404
    r = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{ctx['sub_2'].id}",
        headers=ctx["headers_a"],
    )
    assert r.status_code == 404

    # owner 见全部
    r = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=ctx["headers_owner"],
    )
    assert r.status_code == 200
    assert r.json()["count"] == 2
    r = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/scores/summary",
        headers=ctx["headers_owner"],
    )
    assert r.status_code == 200
    assert r.json()["count"] == 2


def test_assigned_teacher_annotation_write_scoped_to_class(
    client: TestClient, db: Session
) -> None:
    ctx = _assigned_ctx(client, db)
    exam_id = ctx["exam"]["id"]
    ann_1 = _create_annotation(db, submission_id=ctx["sub_1"].id)
    ann_2 = _create_annotation(db, submission_id=ctx["sub_2"].id)

    # 甲老师（001班）改本班批注 → 200
    r = client.patch(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{ctx['sub_1'].id}"
        f"/annotations/{ann_1.id}",
        headers=ctx["headers_a"],
        json={"score": 4, "comment": "复核通过"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["score"] == 4

    # 甲老师改 002班批注 → 403
    r = client.patch(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{ctx['sub_2'].id}"
        f"/annotations/{ann_2.id}",
        headers=ctx["headers_a"],
        json={"score": 4},
    )
    assert r.status_code == 403

    # owner 改任意班批注 → 200
    r = client.patch(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{ctx['sub_2'].id}"
        f"/annotations/{ann_2.id}",
        headers=ctx["headers_owner"],
        json={"score": 3},
    )
    assert r.status_code == 200, r.text
    assert r.json()["score"] == 3
