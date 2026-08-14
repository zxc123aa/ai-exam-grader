from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import User, UserCreate, UserRole
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def _create_user_with_role(db: Session, role: UserRole) -> tuple[User, str]:
    email = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=email, password=password, role=role)
    user = crud.create_user(session=db, user_create=user_in)
    return user, password


def test_first_superuser_has_superuser_role(db: Session) -> None:
    # init_db 创建的初始超级管理员必须带 platform_superuser 角色
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user
    assert user.role == UserRole.PLATFORM_SUPERUSER


def test_signup_is_closed(client: TestClient, db: Session) -> None:
    # 公开注册由配置开关控制，请求不能借机指定角色。
    username = random_email()
    data = {
        "organization_type": "school",
        "organization_name": "暂未开放学校",
        "contact_name": "Student One",
        "email": username,
        "password": random_lower_string(),
        "turnstile_token": "local-testing-token",
        "role": "school_owner",
    }
    r = client.post(f"{settings.API_V1_STR}/users/signup", json=data)
    assert r.status_code == 403
    assert r.json()["detail"] == "学校注册暂未开放"
    user = crud.get_user_by_email(session=db, email=username)
    assert user is None


def test_admin_can_list_users(client: TestClient, db: Session) -> None:
    _admin, password = _create_user_with_role(db, UserRole.SCHOOL_OWNER)
    headers = user_authentication_headers(
        client=client, email=_admin.email, password=password
    )
    r = client.get(f"{settings.API_V1_STR}/users/", headers=headers)
    assert r.status_code == 200
    assert "data" in r.json()


def test_teacher_cannot_list_users(client: TestClient, db: Session) -> None:
    teacher, password = _create_user_with_role(db, UserRole.TEACHER)
    headers = user_authentication_headers(
        client=client, email=teacher.email, password=password
    )
    r = client.get(f"{settings.API_V1_STR}/users/", headers=headers)
    assert r.status_code == 403


def test_admin_cannot_create_superuser(client: TestClient, db: Session) -> None:
    admin, password = _create_user_with_role(db, UserRole.SCHOOL_OWNER)
    headers = user_authentication_headers(
        client=client, email=admin.email, password=password
    )
    data = {
        "email": random_email(),
        "password": random_lower_string(),
        "role": "platform_superuser",
    }
    r = client.post(f"{settings.API_V1_STR}/users/", headers=headers, json=data)
    assert r.status_code == 400


def test_admin_can_create_teacher(client: TestClient, db: Session) -> None:
    admin, password = _create_user_with_role(db, UserRole.SCHOOL_OWNER)
    headers = user_authentication_headers(
        client=client, email=admin.email, password=password
    )
    data = {"email": random_email(), "password": random_lower_string()}
    r = client.post(f"{settings.API_V1_STR}/users/", headers=headers, json=data)
    assert r.status_code == 200
    # 未指定 role 时默认为 teacher
    assert r.json()["role"] == UserRole.TEACHER


def test_admin_cannot_grant_superuser_role(client: TestClient, db: Session) -> None:
    admin, password = _create_user_with_role(db, UserRole.SCHOOL_OWNER)
    target, _ = _create_user_with_role(db, UserRole.TEACHER)
    headers = user_authentication_headers(
        client=client, email=admin.email, password=password
    )
    r = client.patch(
        f"{settings.API_V1_STR}/users/{target.id}",
        headers=headers,
        json={"role": "platform_superuser"},
    )
    assert r.status_code == 400


def test_admin_cannot_modify_superuser_account(client: TestClient, db: Session) -> None:
    admin, password = _create_user_with_role(db, UserRole.SCHOOL_OWNER)
    superuser = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert superuser
    headers = user_authentication_headers(
        client=client, email=admin.email, password=password
    )
    r = client.patch(
        f"{settings.API_V1_STR}/users/{superuser.id}",
        headers=headers,
        json={"full_name": "Hacked"},
    )
    assert r.status_code == 400


def test_superuser_can_manage_platform_roles(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    target, _ = _create_user_with_role(db, UserRole.PLATFORM_SUPPORT)
    r = client.patch(
        f"{settings.API_V1_STR}/users/{target.id}",
        headers=superuser_token_headers,
        json={"role": "platform_admin"},
    )
    assert r.status_code == 200
    assert r.json()["role"] == UserRole.PLATFORM_ADMIN


def test_platform_roles_forbidden_from_school_business(
    client: TestClient, db: Session
) -> None:
    for role in (
        UserRole.PLATFORM_SUPERUSER,
        UserRole.PLATFORM_ADMIN,
        UserRole.PLATFORM_SUPPORT,
    ):
        user, password = _create_user_with_role(db, role)
        headers = user_authentication_headers(
            client=client, email=user.email, password=password
        )
        for path in ("/exams/", "/classes/", "/grading/runs"):
            response = client.get(f"{settings.API_V1_STR}{path}", headers=headers)
            assert response.status_code == 403
            assert response.json()["detail"] == "平台账号无权访问学校业务"


def test_student_forbidden_from_exams(client: TestClient, db: Session) -> None:
    student, password = _create_user_with_role(db, UserRole.STUDENT)
    headers = user_authentication_headers(
        client=client, email=student.email, password=password
    )
    r = client.get(f"{settings.API_V1_STR}/exams/", headers=headers)
    assert r.status_code == 403
    assert r.json()["detail"] == "学生账号仅可访问我的成绩"


def test_teacher_can_access_exams(client: TestClient, db: Session) -> None:
    teacher, password = _create_user_with_role(db, UserRole.TEACHER)
    headers = user_authentication_headers(
        client=client, email=teacher.email, password=password
    )
    r = client.get(f"{settings.API_V1_STR}/exams/", headers=headers)
    assert r.status_code == 200


def test_student_forbidden_from_grading(client: TestClient, db: Session) -> None:
    student, password = _create_user_with_role(db, UserRole.STUDENT)
    headers = user_authentication_headers(
        client=client, email=student.email, password=password
    )
    r = client.get(
        f"{settings.API_V1_STR}/grading/runs",
        headers=headers,
        params={"exam_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "学生账号仅可访问我的成绩"
