from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import ClassGroup, Student, User, UserCreate, UserRole
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string

PDF_BYTES = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 44 >>
stream
BT /F1 18 Tf 50 120 Td (Hello PDF) Tj ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000141 00000 n
0000000241 00000 n
trailer
<< /Root 1 0 R /Size 6 >>
startxref
405
%%EOF
"""


DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001"


def _create_user_with_role(db: Session, role: UserRole) -> tuple[User, str]:
    email = random_email()
    password = random_lower_string()
    # 学校角色统一挂到默认学校，平台角色 org_id 为 None
    org_id = None if role.value.startswith("platform_") else DEFAULT_ORG_ID
    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=email, password=password, role=role, org_id=org_id
        ),
    )
    return user, password


def _headers(client: TestClient, user: User, password: str) -> dict[str, str]:
    return user_authentication_headers(
        client=client, email=user.email, password=password
    )


def _create_teacher(
    client: TestClient, db: Session, role: UserRole = UserRole.TEACHER
) -> tuple[User, dict[str, str]]:
    user, password = _create_user_with_role(db, role)
    return user, _headers(client, user, password)


def _create_class(client: TestClient, headers: dict[str, str], name: str) -> dict:
    r = client.post(
        f"{settings.API_V1_STR}/classes/", headers=headers, json={"name": name}
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_class_crud(client: TestClient, db: Session) -> None:
    _, headers = _create_teacher(client, db)

    created = _create_class(client, headers, "高三1班")
    assert created["name"] == "高三1班"
    assert created["student_count"] == 0
    class_id = created["id"]

    r = client.get(f"{settings.API_V1_STR}/classes/", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["data"][0]["id"] == class_id

    r = client.patch(
        f"{settings.API_V1_STR}/classes/{class_id}",
        headers=headers,
        json={"name": "高三2班", "grade_level": "高三"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "高三2班"
    assert r.json()["grade_level"] == "高三"

    r = client.delete(f"{settings.API_V1_STR}/classes/{class_id}", headers=headers)
    assert r.status_code == 200
    r = client.get(f"{settings.API_V1_STR}/classes/", headers=headers)
    assert r.json()["count"] == 0


def test_create_class_duplicate_name_conflict(client: TestClient, db: Session) -> None:
    _, headers = _create_teacher(client, db)
    _create_class(client, headers, "重名班")
    r = client.post(
        f"{settings.API_V1_STR}/classes/", headers=headers, json={"name": "重名班"}
    )
    assert r.status_code == 409


def test_delete_class_with_students_conflict(client: TestClient, db: Session) -> None:
    _, headers = _create_teacher(client, db)
    class_id = _create_class(client, headers, "有学生的班")["id"]
    r = client.post(
        f"{settings.API_V1_STR}/classes/{class_id}/students",
        headers=headers,
        json={"name": "学生甲"},
    )
    assert r.status_code == 200
    r = client.delete(f"{settings.API_V1_STR}/classes/{class_id}", headers=headers)
    assert r.status_code == 409


def test_student_crud_and_duplicate_name(client: TestClient, db: Session) -> None:
    _, headers = _create_teacher(client, db)
    class_id = _create_class(client, headers, "学生CRUD班")["id"]

    r = client.post(
        f"{settings.API_V1_STR}/classes/{class_id}/students",
        headers=headers,
        json={"name": "王梓涵", "student_no": "001"},
    )
    assert r.status_code == 200
    student = r.json()
    assert student["student_no"] == "001"
    assert student["user_id"] is None

    r = client.post(
        f"{settings.API_V1_STR}/classes/{class_id}/students",
        headers=headers,
        json={"name": "王梓涵"},
    )
    assert r.status_code == 409

    r = client.patch(
        f"{settings.API_V1_STR}/classes/students/{student['id']}",
        headers=headers,
        json={"name": "王梓涵2", "student_no": "002"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "王梓涵2"
    assert r.json()["student_no"] == "002"

    r = client.get(
        f"{settings.API_V1_STR}/classes/{class_id}/students", headers=headers
    )
    assert r.status_code == 200
    assert r.json()["count"] == 1

    r = client.delete(
        f"{settings.API_V1_STR}/classes/students/{student['id']}", headers=headers
    )
    assert r.status_code == 200
    r = client.get(
        f"{settings.API_V1_STR}/classes/{class_id}/students", headers=headers
    )
    assert r.json()["count"] == 0


def test_batch_create_students_skips_existing(client: TestClient, db: Session) -> None:
    _, headers = _create_teacher(client, db)
    class_id = _create_class(client, headers, "批量班")["id"]
    client.post(
        f"{settings.API_V1_STR}/classes/{class_id}/students",
        headers=headers,
        json={"name": "李思远"},
    )
    r = client.post(
        f"{settings.API_V1_STR}/classes/{class_id}/students/batch",
        headers=headers,
        json={
            "rows": [
                {"name": "李思远"},
                {"name": "张浩然", "student_no": "001"},
                {"name": "刘雨欣"},
                {"name": "张浩然"},
            ]
        },
    )
    assert r.status_code == 200
    content = r.json()
    assert content["created"] == 2
    assert content["skipped"] == 2
    assert content["accounts_created"] == 0
    actions = [row["action"] for row in content["rows"]]
    assert actions == ["skip_exists", "create", "create", "skip_exists"]
    r = client.get(
        f"{settings.API_V1_STR}/classes/{class_id}/students", headers=headers
    )
    assert r.json()["count"] == 3


def test_batch_import_students_dry_run(client: TestClient, db: Session) -> None:
    _, headers = _create_teacher(client, db, role=UserRole.SCHOOL_OWNER)
    class_id = _create_class(client, headers, "预览班")["id"]
    client.post(
        f"{settings.API_V1_STR}/classes/{class_id}/students",
        headers=headers,
        json={"name": "李思远"},
    )
    r = client.post(
        f"{settings.API_V1_STR}/classes/{class_id}/students/batch",
        headers=headers,
        json={
            "rows": [
                {"name": "李思远", "student_no": "001"},
                {"name": "张浩然"},
                {"name": "  ", "student_no": "003"},
                {"name": "刘雨欣", "student_no": "004"},
            ],
            "create_accounts": True,
            "dry_run": True,
        },
    )
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert rows[0]["action"] == "skip_exists"
    assert rows[1]["action"] == "error"
    assert rows[1]["message"] == "创建账号必须填学号"
    assert rows[2]["action"] == "error"
    assert rows[2]["message"] == "姓名不能为空"
    assert rows[3]["action"] == "create"
    # dry_run 不落库
    r = client.get(
        f"{settings.API_V1_STR}/classes/{class_id}/students", headers=headers
    )
    assert r.json()["count"] == 1


def test_batch_import_students_teacher_cannot_create_accounts(
    client: TestClient, db: Session
) -> None:
    _, headers = _create_teacher(client, db)
    class_id = _create_class(client, headers, "权限班")["id"]
    r = client.post(
        f"{settings.API_V1_STR}/classes/{class_id}/students/batch",
        headers=headers,
        json={
            "rows": [{"name": "张浩然", "student_no": "101"}],
            "create_accounts": True,
        },
    )
    assert r.status_code == 403


def test_batch_import_students_with_accounts(client: TestClient, db: Session) -> None:
    _, headers = _create_teacher(client, db, role=UserRole.SCHOOL_OWNER)
    class_id = _create_class(client, headers, "账号班")["id"]
    r = client.post(
        f"{settings.API_V1_STR}/classes/{class_id}/students/batch",
        headers=headers,
        json={
            "rows": [
                {"name": "张浩然", "student_no": "101"},
                {"name": "刘雨欣", "student_no": "102"},
            ],
            "create_accounts": True,
        },
    )
    assert r.status_code == 200
    content = r.json()
    assert content["created"] == 2
    assert content["accounts_created"] == 2
    assert content["errors"] == []
    students = db.exec(select(Student).where(Student.class_id == class_id)).all()
    assert len(students) == 2
    for student in students:
        assert student.user_id is not None
        user = db.get(User, student.user_id)
        assert user is not None
        assert user.role == UserRole.STUDENT
        assert user.email == f"{student.student_no}@school.local"
        assert user.full_name == student.name
        assert str(user.org_id) == DEFAULT_ORG_ID
        assert user.is_active is True
    # 学号重复冲突：已有 101@school.local，再次导入报错
    r = client.post(
        f"{settings.API_V1_STR}/classes/{class_id}/students/batch",
        headers=headers,
        json={
            "rows": [{"name": "王小明", "student_no": "101"}],
            "create_accounts": True,
        },
    )
    assert r.status_code == 200
    content = r.json()
    assert content["created"] == 0
    assert len(content["errors"]) == 1
    assert content["errors"][0]["action"] == "error"
    assert "邮箱已被占用" in content["errors"][0]["message"]


def test_bind_account_flow(client: TestClient, db: Session) -> None:
    _, headers = _create_teacher(client, db)
    class_id = _create_class(client, headers, "绑定班")["id"]
    student_a = client.post(
        f"{settings.API_V1_STR}/classes/{class_id}/students",
        headers=headers,
        json={"name": "学生A"},
    ).json()
    student_b = client.post(
        f"{settings.API_V1_STR}/classes/{class_id}/students",
        headers=headers,
        json={"name": "学生B"},
    ).json()

    teacher_user, _ = _create_user_with_role(db, UserRole.TEACHER)
    student_user, _ = _create_user_with_role(db, UserRole.STUDENT)

    # 非 student 角色账号 → 400
    r = client.post(
        f"{settings.API_V1_STR}/classes/students/{student_a['id']}/bind-account",
        headers=headers,
        json={"user_id": str(teacher_user.id)},
    )
    assert r.status_code == 400

    # 绑定 student 账号成功
    r = client.post(
        f"{settings.API_V1_STR}/classes/students/{student_a['id']}/bind-account",
        headers=headers,
        json={"user_id": str(student_user.id)},
    )
    assert r.status_code == 200
    assert r.json()["user_id"] == str(student_user.id)
    assert r.json()["account_email"] == student_user.email

    listed = client.get(
        f"{settings.API_V1_STR}/classes/{class_id}/students", headers=headers
    )
    assert listed.status_code == 200
    listed_student = next(
        item for item in listed.json()["data"] if item["id"] == student_a["id"]
    )
    assert listed_student["account_email"] == student_user.email

    # 同一账号已绑定其他学生 → 400
    r = client.post(
        f"{settings.API_V1_STR}/classes/students/{student_b['id']}/bind-account",
        headers=headers,
        json={"user_id": str(student_user.id)},
    )
    assert r.status_code == 400

    # 解绑后可将该账号绑到别人
    r = client.delete(
        f"{settings.API_V1_STR}/classes/students/{student_a['id']}/bind-account",
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["user_id"] is None
    r = client.post(
        f"{settings.API_V1_STR}/classes/students/{student_b['id']}/bind-account",
        headers=headers,
        json={"user_id": str(student_user.id)},
    )
    assert r.status_code == 200
    assert r.json()["user_id"] == str(student_user.id)


def test_classes_shared_across_teachers(client: TestClient, db: Session) -> None:
    """班级全校共享：任何教师可见/可维护；班级名全校唯一。"""
    _, headers_a = _create_teacher(client, db)
    _, headers_b = _create_teacher(client, db)
    class_id = _create_class(client, headers_a, "A老师的班")["id"]

    # 另一个 teacher 也能看到
    r = client.get(f"{settings.API_V1_STR}/classes/", headers=headers_b)
    assert r.status_code == 200
    assert any(c["id"] == class_id for c in r.json()["data"])

    # 也能查学生名单
    r = client.get(
        f"{settings.API_V1_STR}/classes/{class_id}/students", headers=headers_b
    )
    assert r.status_code == 200

    # 班级名全校唯一：同名创建被拒
    r = client.post(
        f"{settings.API_V1_STR}/classes/",
        headers=headers_b,
        json={"name": "A老师的班"},
    )
    assert r.status_code == 409


def test_student_role_forbidden(client: TestClient, db: Session) -> None:
    student_user, password = _create_user_with_role(db, UserRole.STUDENT)
    headers = _headers(client, student_user, password)
    r = client.get(f"{settings.API_V1_STR}/classes/", headers=headers)
    assert r.status_code == 403


def test_upload_submission_auto_resolves_student(
    client: TestClient, db: Session
) -> None:
    teacher, headers = _create_teacher(client, db)
    r = client.post(
        f"{settings.API_V1_STR}/exams/", headers=headers, json={"title": "归位考试"}
    )
    exam_id = r.json()["id"]

    # 第一次上传：自动建班 + 建学生
    r = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=headers,
        files={"file": ("s1.pdf", PDF_BYTES, "application/pdf")},
        data={"student_name": "王梓涵", "class_name": "001班"},
    )
    assert r.status_code == 200, r.text
    first_student_id = r.json()["student_id"]
    assert first_student_id

    # 再次上传同名同班：复用既有学生，不重复建
    r = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=headers,
        files={"file": ("s2.pdf", PDF_BYTES, "application/pdf")},
        data={"student_name": "王梓涵", "class_name": "001班"},
    )
    assert r.status_code == 200
    assert r.json()["student_id"] == first_student_id

    class_groups = db.exec(
        select(ClassGroup).where(
            ClassGroup.owner_id == teacher.id, ClassGroup.name == "001班"
        )
    ).all()
    assert len(class_groups) == 1
    students = db.exec(
        select(Student).where(Student.class_id == class_groups[0].id)
    ).all()
    assert len(students) == 1
    assert str(students[0].id) == first_student_id

    # 无班级名的答卷不归位
    r = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=headers,
        files={"file": ("s3.pdf", PDF_BYTES, "application/pdf")},
        data={"student_name": "无班考生"},
    )
    assert r.status_code == 200
    assert r.json()["student_id"] is None

    # 班级出现在班级列表里并带 student_count
    r = client.get(f"{settings.API_V1_STR}/classes/", headers=headers)
    assert r.status_code == 200
    matched = [c for c in r.json()["data"] if c["name"] == "001班"]
    assert len(matched) == 1
    assert matched[0]["student_count"] == 1
