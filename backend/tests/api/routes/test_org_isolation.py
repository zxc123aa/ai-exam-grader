"""阶段 2 多租户数据隔离测试：考试 / 班级 / 学生名单按学校（org）隔离。"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import ClassGroup, Organization, User, UserCreate, UserRole
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
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000241 00000 n
trailer
<< /Root 1 0 R /Size 6 >>
startxref
405
%%EOF
"""


def _create_org(db: Session, name: str, *, sharing: bool = False) -> Organization:
    org = Organization(
        name=name,
        code=f"org-{random_lower_string()[:16]}",
        exam_sharing_enabled=sharing,
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _create_user(
    db: Session, role: UserRole, org: Organization | None
) -> tuple[User, str]:
    password = random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(),
            password=password,
            role=role,
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


def test_exam_isolation_between_orgs(client: TestClient, db: Session) -> None:
    """A 校教师看不到 B 校考试：列表不含、详情 404；B 校管理员同样不可见。"""
    org_a = _create_org(db, "学校A")
    org_b = _create_org(db, "学校B")
    teacher_a, pw_a = _create_user(db, UserRole.TEACHER, org_a)
    teacher_b, pw_b = _create_user(db, UserRole.TEACHER, org_b)
    admin_b, pw_ab = _create_user(db, UserRole.SCHOOL_ADMIN, org_b)
    headers_a = _headers(client, teacher_a, pw_a)
    headers_b = _headers(client, teacher_b, pw_b)
    headers_admin_b = _headers(client, admin_b, pw_ab)

    exam = _create_exam(client, headers_a, "A校月考")

    r = client.get(f"{settings.API_V1_STR}/exams/", headers=headers_b)
    assert r.status_code == 200
    assert all(item["id"] != exam["id"] for item in r.json()["data"])

    r = client.get(f"{settings.API_V1_STR}/exams/{exam['id']}", headers=headers_b)
    assert r.status_code == 404

    r = client.get(f"{settings.API_V1_STR}/exams/{exam['id']}", headers=headers_admin_b)
    assert r.status_code == 404

    # 考试输出带 org_id，且等于创建者所在学校
    r = client.get(f"{settings.API_V1_STR}/exams/{exam['id']}", headers=headers_a)
    assert r.status_code == 200
    assert r.json()["org_id"] == str(org_a.id)


def test_class_isolation_and_same_name_across_orgs(
    client: TestClient, db: Session
) -> None:
    """跨校允许同名班；班级与学生名单跨校不可见。"""
    org_a = _create_org(db, "学校A")
    org_b = _create_org(db, "学校B")
    teacher_a, pw_a = _create_user(db, UserRole.TEACHER, org_a)
    teacher_b, pw_b = _create_user(db, UserRole.TEACHER, org_b)
    headers_a = _headers(client, teacher_a, pw_a)
    headers_b = _headers(client, teacher_b, pw_b)

    class_a = _create_class(client, headers_a, "001班")
    class_b = _create_class(client, headers_b, "001班")
    assert class_a["id"] != class_b["id"]
    assert class_a["org_id"] == str(org_a.id)
    assert class_b["org_id"] == str(org_b.id)

    # A 校教师在 A 校再建 001班 → 409
    r = client.post(
        f"{settings.API_V1_STR}/classes/", headers=headers_a, json={"name": "001班"}
    )
    assert r.status_code == 409

    # 班级列表跨校隔离
    r = client.get(f"{settings.API_V1_STR}/classes/", headers=headers_b)
    assert r.status_code == 200
    assert all(c["id"] != class_a["id"] for c in r.json()["data"])

    # 跨校班级详情 / 学生名单 404
    r = client.get(
        f"{settings.API_V1_STR}/classes/{class_a['id']}/students", headers=headers_b
    )
    assert r.status_code == 404
    r = client.patch(
        f"{settings.API_V1_STR}/classes/{class_a['id']}",
        headers=headers_b,
        json={"name": "改名"},
    )
    assert r.status_code == 404

    # A 校学生名单跨校不可见（经学生 id 也不行）
    r = client.post(
        f"{settings.API_V1_STR}/classes/{class_a['id']}/students",
        headers=headers_a,
        json={"name": "张三"},
    )
    assert r.status_code == 200
    student_id = r.json()["id"]
    r = client.patch(
        f"{settings.API_V1_STR}/classes/students/{student_id}",
        headers=headers_b,
        json={"name": "李四"},
    )
    assert r.status_code == 404


def test_teacher_sharing_disabled_sees_only_own(
    client: TestClient, db: Session
) -> None:
    """sharing 关：同校教师互不可见对方考试。"""
    org = _create_org(db, "学校C", sharing=False)
    t1, pw1 = _create_user(db, UserRole.TEACHER, org)
    t2, pw2 = _create_user(db, UserRole.TEACHER, org)
    headers_1 = _headers(client, t1, pw1)
    headers_2 = _headers(client, t2, pw2)

    exam = _create_exam(client, headers_1, "教师1的考试")

    r = client.get(f"{settings.API_V1_STR}/exams/", headers=headers_2)
    assert all(item["id"] != exam["id"] for item in r.json()["data"])
    r = client.get(f"{settings.API_V1_STR}/exams/{exam['id']}", headers=headers_2)
    assert r.status_code == 404
    r = client.patch(
        f"{settings.API_V1_STR}/exams/{exam['id']}",
        headers=headers_2,
        json={"title": "越权改名"},
    )
    assert r.status_code == 404


def test_teacher_sharing_enabled_readonly(client: TestClient, db: Session) -> None:
    """sharing 开：同校教师可见对方考试但只读。"""
    org = _create_org(db, "学校D", sharing=True)
    t1, pw1 = _create_user(db, UserRole.TEACHER, org)
    t2, pw2 = _create_user(db, UserRole.TEACHER, org)
    headers_1 = _headers(client, t1, pw1)
    headers_2 = _headers(client, t2, pw2)

    exam = _create_exam(client, headers_1, "教师1的共享考试")

    r = client.get(f"{settings.API_V1_STR}/exams/", headers=headers_2)
    assert any(item["id"] == exam["id"] for item in r.json()["data"])
    r = client.get(f"{settings.API_V1_STR}/exams/{exam['id']}", headers=headers_2)
    assert r.status_code == 200

    # 只读：改 / 删 / 传文件均 403
    r = client.patch(
        f"{settings.API_V1_STR}/exams/{exam['id']}",
        headers=headers_2,
        json={"title": "越权改名"},
    )
    assert r.status_code == 403
    r = client.delete(f"{settings.API_V1_STR}/exams/{exam['id']}", headers=headers_2)
    assert r.status_code == 403
    r = client.post(
        f"{settings.API_V1_STR}/exams/{exam['id']}/submissions",
        headers=headers_2,
        files={"file": ("s.pdf", PDF_BYTES, "application/pdf")},
        data={"student_name": "张三", "class_name": "001班"},
    )
    assert r.status_code == 403


def test_school_owner_can_write_school_exams(client: TestClient, db: Session) -> None:
    """school_owner 可见可写本校任意考试；school_admin 可见但不可写。"""
    org = _create_org(db, "学校E")
    teacher, pw_t = _create_user(db, UserRole.TEACHER, org)
    owner, pw_o = _create_user(db, UserRole.SCHOOL_OWNER, org)
    admin, pw_a = _create_user(db, UserRole.SCHOOL_ADMIN, org)
    headers_t = _headers(client, teacher, pw_t)
    headers_o = _headers(client, owner, pw_o)
    headers_a = _headers(client, admin, pw_a)

    exam = _create_exam(client, headers_t, "教师的考试")

    # school_owner：可见 + 可改 + 可删
    r = client.get(f"{settings.API_V1_STR}/exams/", headers=headers_o)
    assert any(item["id"] == exam["id"] for item in r.json()["data"])
    r = client.patch(
        f"{settings.API_V1_STR}/exams/{exam['id']}",
        headers=headers_o,
        json={"title": "校长改名"},
    )
    assert r.status_code == 200
    assert r.json()["title"] == "校长改名"

    # school_admin：可见但不可写
    r = client.get(f"{settings.API_V1_STR}/exams/{exam['id']}", headers=headers_a)
    assert r.status_code == 200
    r = client.patch(
        f"{settings.API_V1_STR}/exams/{exam['id']}",
        headers=headers_a,
        json={"title": "管理员改名"},
    )
    assert r.status_code == 403

    r = client.delete(f"{settings.API_V1_STR}/exams/{exam['id']}", headers=headers_o)
    assert r.status_code == 200


def test_submission_resolves_to_same_org_class(client: TestClient, db: Session) -> None:
    """答卷按 (org_id, class_name) 归位：落到本校同名班，不影响他校同名班。"""
    org_a = _create_org(db, "学校F")
    org_b = _create_org(db, "学校G")
    teacher_a, pw_a = _create_user(db, UserRole.TEACHER, org_a)
    teacher_b, pw_b = _create_user(db, UserRole.TEACHER, org_b)
    headers_a = _headers(client, teacher_a, pw_a)
    headers_b = _headers(client, teacher_b, pw_b)

    class_a = _create_class(client, headers_a, "001班")
    class_b = _create_class(client, headers_b, "001班")
    exam = _create_exam(client, headers_a, "归位考试")

    r = client.post(
        f"{settings.API_V1_STR}/exams/{exam['id']}/submissions",
        headers=headers_a,
        files={"file": ("s.pdf", PDF_BYTES, "application/pdf")},
        data={"student_name": "王梓涵", "class_name": "001班"},
    )
    assert r.status_code == 200, r.text
    student_id = r.json()["student_id"]
    assert student_id

    # 学生落在 A 校 001班
    r = client.get(
        f"{settings.API_V1_STR}/classes/{class_a['id']}/students", headers=headers_a
    )
    assert [s["name"] for s in r.json()["data"]] == ["王梓涵"]
    # B 校同名班不受影响
    r = client.get(
        f"{settings.API_V1_STR}/classes/{class_b['id']}/students", headers=headers_b
    )
    assert r.json()["data"] == []

    # 直接查库确认学生挂在 A 校班级下
    class_group_a = db.get(ClassGroup, uuid.UUID(class_a["id"]))
    assert class_group_a
    assert class_group_a.org_id == org_a.id
    student_rows = db.exec(
        select(ClassGroup).where(
            ClassGroup.org_id == org_b.id, ClassGroup.name == "001班"
        )
    ).all()
    assert len(student_rows) == 1


def test_platform_superuser_cannot_access_school_exam_business(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """卖方平台账号不能读取或代建学校考试。"""
    org_a = _create_org(db, "学校H")
    teacher, pw = _create_user(db, UserRole.TEACHER, org_a)
    headers = _headers(client, teacher, pw)
    _create_exam(client, headers, "平台可见性考试")

    r = client.get(f"{settings.API_V1_STR}/exams/", headers=superuser_token_headers)
    assert r.status_code == 403

    r = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "缺学校"},
    )
    assert r.status_code == 403

    r = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "平台代建", "org_id": str(org_a.id)},
    )
    assert r.status_code == 403
