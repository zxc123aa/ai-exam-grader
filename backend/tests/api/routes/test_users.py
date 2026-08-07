import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.core.security import verify_password
from app.models import TeacherClassLink, User, UserCreate, UserRole
from tests.utils.user import create_random_user, user_authentication_headers
from tests.utils.utils import random_email, random_lower_string

DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001"


def _create_school_owner(
    client: TestClient, db: Session
) -> tuple[User, dict[str, str]]:
    email = random_email()
    password = random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=email,
            password=password,
            role=UserRole.SCHOOL_OWNER,
            org_id=DEFAULT_ORG_ID,
        ),
    )
    headers = user_authentication_headers(client=client, email=email, password=password)
    return user, headers


def _create_class(client: TestClient, headers: dict[str, str], name: str) -> dict:
    r = client.post(
        f"{settings.API_V1_STR}/classes/", headers=headers, json={"name": name}
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_get_users_superuser_me(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.get(f"{settings.API_V1_STR}/users/me", headers=superuser_token_headers)
    current_user = r.json()
    assert current_user
    assert current_user["is_active"] is True
    assert current_user["is_superuser"]
    assert current_user["email"] == settings.FIRST_SUPERUSER


def test_get_users_normal_user_me(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    r = client.get(f"{settings.API_V1_STR}/users/me", headers=normal_user_token_headers)
    current_user = r.json()
    assert current_user
    assert current_user["is_active"] is True
    assert current_user["is_superuser"] is False
    assert current_user["email"] == settings.EMAIL_TEST_USER


def test_create_user_new_email(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    with (
        patch("app.utils.send_email", return_value=None),
        patch("app.core.config.settings.SMTP_HOST", "smtp.example.com"),
        patch("app.core.config.settings.SMTP_USER", "admin@example.com"),
    ):
        username = random_email()
        password = random_lower_string()
        data = {
            "email": username,
            "password": password,
            "role": "platform_support",
        }
        r = client.post(
            f"{settings.API_V1_STR}/users/",
            headers=superuser_token_headers,
            json=data,
        )
        assert 200 <= r.status_code < 300
        created_user = r.json()
        user = crud.get_user_by_email(session=db, email=username)
        assert user
        assert user.email == created_user["email"]


def test_get_existing_user_as_superuser(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(
        email=username, password=password, role=UserRole.PLATFORM_SUPPORT
    )
    user = crud.create_user(session=db, user_create=user_in)
    user_id = user.id
    r = client.get(
        f"{settings.API_V1_STR}/users/{user_id}",
        headers=superuser_token_headers,
    )
    assert 200 <= r.status_code < 300
    api_user = r.json()
    existing_user = crud.get_user_by_email(session=db, email=username)
    assert existing_user
    assert existing_user.email == api_user["email"]


def test_get_non_existing_user_as_superuser(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.get(
        f"{settings.API_V1_STR}/users/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 404
    assert r.json() == {"detail": "User not found"}


def test_get_existing_user_current_user(client: TestClient, db: Session) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(
        email=username, password=password, role=UserRole.PLATFORM_SUPPORT
    )
    user = crud.create_user(session=db, user_create=user_in)
    user_id = user.id

    login_data = {
        "username": username,
        "password": password,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    tokens = r.json()
    a_token = tokens["access_token"]
    headers = {"Authorization": f"Bearer {a_token}"}

    r = client.get(
        f"{settings.API_V1_STR}/users/{user_id}",
        headers=headers,
    )
    assert 200 <= r.status_code < 300
    api_user = r.json()
    existing_user = crud.get_user_by_email(session=db, email=username)
    assert existing_user
    assert existing_user.email == api_user["email"]


def test_get_existing_user_permissions_error(
    db: Session,
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    user = create_random_user(db)

    r = client.get(
        f"{settings.API_V1_STR}/users/{user.id}",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 403
    assert r.json() == {"detail": "The user doesn't have enough privileges"}


def test_get_non_existing_user_permissions_error(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    user_id = uuid.uuid4()

    r = client.get(
        f"{settings.API_V1_STR}/users/{user_id}",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 403
    assert r.json() == {"detail": "The user doesn't have enough privileges"}


def test_create_user_existing_username(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    # username = email
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    crud.create_user(session=db, user_create=user_in)
    data = {
        "email": username,
        "password": password,
        "role": "platform_support",
    }
    r = client.post(
        f"{settings.API_V1_STR}/users/",
        headers=superuser_token_headers,
        json=data,
    )
    created_user = r.json()
    assert r.status_code == 400
    assert "_id" not in created_user


def test_create_user_by_normal_user(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    username = random_email()
    password = random_lower_string()
    data = {"email": username, "password": password}
    r = client.post(
        f"{settings.API_V1_STR}/users/",
        headers=normal_user_token_headers,
        json=data,
    )
    assert r.status_code == 403


def test_retrieve_users(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    crud.create_user(session=db, user_create=user_in)

    username2 = random_email()
    password2 = random_lower_string()
    user_in2 = UserCreate(email=username2, password=password2)
    crud.create_user(session=db, user_create=user_in2)

    r = client.get(f"{settings.API_V1_STR}/users/", headers=superuser_token_headers)
    all_users = r.json()

    assert len(all_users["data"]) > 1
    assert "count" in all_users
    for item in all_users["data"]:
        assert "email" in item


def test_update_user_me(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    full_name = "Updated Name"
    email = random_email()
    data = {"full_name": full_name, "email": email}
    r = client.patch(
        f"{settings.API_V1_STR}/users/me",
        headers=normal_user_token_headers,
        json=data,
    )
    assert r.status_code == 200
    updated_user = r.json()
    assert updated_user["email"] == email
    assert updated_user["full_name"] == full_name

    user_query = select(User).where(User.email == email)
    user_db = db.exec(user_query).first()
    assert user_db
    assert user_db.email == email
    assert user_db.full_name == full_name


def test_update_password_me(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    new_password = random_lower_string()
    data = {
        "current_password": settings.FIRST_SUPERUSER_PASSWORD,
        "new_password": new_password,
    }
    r = client.patch(
        f"{settings.API_V1_STR}/users/me/password",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 200
    updated_user = r.json()
    assert updated_user["message"] == "Password updated successfully"

    user_query = select(User).where(User.email == settings.FIRST_SUPERUSER)
    user_db = db.exec(user_query).first()
    assert user_db
    assert user_db.email == settings.FIRST_SUPERUSER
    verified, _ = verify_password(new_password, user_db.hashed_password)
    assert verified

    # Revert to the old password to keep consistency in test
    old_data = {
        "current_password": new_password,
        "new_password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.patch(
        f"{settings.API_V1_STR}/users/me/password",
        headers=superuser_token_headers,
        json=old_data,
    )
    db.refresh(user_db)

    assert r.status_code == 200
    verified, _ = verify_password(
        settings.FIRST_SUPERUSER_PASSWORD, user_db.hashed_password
    )
    assert verified


def test_update_password_me_incorrect_password(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    new_password = random_lower_string()
    data = {"current_password": new_password, "new_password": new_password}
    r = client.patch(
        f"{settings.API_V1_STR}/users/me/password",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 400
    updated_user = r.json()
    assert updated_user["detail"] == "Incorrect password"


def test_update_user_me_email_exists(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = crud.create_user(session=db, user_create=user_in)

    data = {"email": user.email}
    r = client.patch(
        f"{settings.API_V1_STR}/users/me",
        headers=normal_user_token_headers,
        json=data,
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "User with this email already exists"


def test_update_password_me_same_password_error(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    data = {
        "current_password": settings.FIRST_SUPERUSER_PASSWORD,
        "new_password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.patch(
        f"{settings.API_V1_STR}/users/me/password",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 400
    updated_user = r.json()
    assert (
        updated_user["detail"] == "New password cannot be the same as the current one"
    )


def test_register_user(client: TestClient, db: Session) -> None:
    # 默认开关关闭时，完整注册请求也不能创建租户。
    username = random_email()
    password = random_lower_string()
    data = {
        "organization_type": "school",
        "organization_name": "暂未开放学校",
        "contact_name": random_lower_string(),
        "email": username,
        "password": password,
        "turnstile_token": "local-testing-token",
    }
    r = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json=data,
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "学校注册暂未开放"

    user_query = select(User).where(User.email == username)
    user_db = db.exec(user_query).first()
    assert user_db is None


def test_register_user_already_exists_error(client: TestClient) -> None:
    password = random_lower_string()
    data = {
        "organization_type": "school",
        "organization_name": "暂未开放学校",
        "contact_name": "负责人",
        "email": settings.FIRST_SUPERUSER,
        "password": password,
        "turnstile_token": "local-testing-token",
    }
    r = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json=data,
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "学校注册暂未开放"


def test_update_user(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(
        email=username, password=password, role=UserRole.PLATFORM_SUPPORT
    )
    user = crud.create_user(session=db, user_create=user_in)

    data = {"full_name": "Updated_full_name"}
    r = client.patch(
        f"{settings.API_V1_STR}/users/{user.id}",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 200
    updated_user = r.json()

    assert updated_user["full_name"] == "Updated_full_name"

    user_query = select(User).where(User.email == username)
    user_db = db.exec(user_query).first()
    db.refresh(user_db)
    assert user_db
    assert user_db.full_name == "Updated_full_name"


def test_update_user_not_exists(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    data = {"full_name": "Updated_full_name"}
    r = client.patch(
        f"{settings.API_V1_STR}/users/{uuid.uuid4()}",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "The user with this id does not exist in the system"


def test_update_user_email_exists(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(
        email=username, password=password, role=UserRole.PLATFORM_SUPPORT
    )
    user = crud.create_user(session=db, user_create=user_in)

    username2 = random_email()
    password2 = random_lower_string()
    user_in2 = UserCreate(
        email=username2, password=password2, role=UserRole.PLATFORM_ADMIN
    )
    user2 = crud.create_user(session=db, user_create=user_in2)

    data = {"email": user2.email}
    r = client.patch(
        f"{settings.API_V1_STR}/users/{user.id}",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "User with this email already exists"


def test_delete_user_me(client: TestClient, db: Session) -> None:
    """自删已禁用：任何角色删除自己都应 403，且账号仍在。"""
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = crud.create_user(session=db, user_create=user_in)
    user_id = user.id

    login_data = {
        "username": username,
        "password": password,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    tokens = r.json()
    a_token = tokens["access_token"]
    headers = {"Authorization": f"Bearer {a_token}"}

    r = client.delete(
        f"{settings.API_V1_STR}/users/me",
        headers=headers,
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "账号不支持自行删除，如需停用请联系学校管理员"
    result = db.exec(select(User).where(User.id == user_id)).first()
    assert result is not None


def test_delete_user_me_as_superuser(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.delete(
        f"{settings.API_V1_STR}/users/me",
        headers=superuser_token_headers,
    )
    assert r.status_code == 403
    response = r.json()
    assert response["detail"] == "账号不支持自行删除，如需停用请联系学校管理员"


def test_delete_user_super_user(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(
        email=username, password=password, role=UserRole.PLATFORM_SUPPORT
    )
    user = crud.create_user(session=db, user_create=user_in)
    user_id = user.id
    r = client.delete(
        f"{settings.API_V1_STR}/users/{user_id}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    deleted_user = r.json()
    assert deleted_user["message"] == "User deactivated; historical data was preserved"
    db.refresh(user)
    assert user.is_active is False
    result = db.exec(select(User).where(User.id == user_id)).first()
    assert result is not None


def test_delete_user_not_found(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.delete(
        f"{settings.API_V1_STR}/users/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "User not found"


def test_delete_user_current_super_user_error(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    super_user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert super_user
    user_id = super_user.id

    r = client.delete(
        f"{settings.API_V1_STR}/users/{user_id}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "Super users are not allowed to delete themselves"


def test_delete_user_without_privileges(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = crud.create_user(session=db, user_create=user_in)

    r = client.delete(
        f"{settings.API_V1_STR}/users/{user.id}",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "The user doesn't have enough privileges"


def test_batch_import_teachers(client: TestClient, db: Session) -> None:
    _, headers = _create_school_owner(client, db)
    class_group = _create_class(client, headers, "高三1班")
    r = client.post(
        f"{settings.API_V1_STR}/users/batch",
        headers=headers,
        json={
            "rows": [
                {
                    "name": "王老师",
                    "employee_no": "T001",
                    "email": "wang@example.com",
                    "subjects": "物理,化学",
                    "class_names": "高三1班",
                },
                {"name": "李老师", "email": "li@example.com"},
            ]
        },
    )
    assert r.status_code == 200, r.text
    content = r.json()
    assert content["created"] == 2
    assert content["skipped"] == 0
    assert content["errors"] == []
    user = crud.get_user_by_email(session=db, email="wang@example.com")
    assert user is not None
    assert user.role == UserRole.TEACHER
    assert user.employee_no == "T001"
    assert user.full_name == "王老师"
    assert str(user.org_id) == DEFAULT_ORG_ID
    assert user.is_active is True
    assert user.subjects == ["物理", "化学"]
    verified, _ = verify_password("Dianfan@2026", user.hashed_password)
    assert verified
    link = db.exec(
        select(TeacherClassLink).where(TeacherClassLink.user_id == user.id)
    ).first()
    assert link is not None
    assert str(link.class_id) == class_group["id"]


def test_batch_import_teachers_dry_run(client: TestClient, db: Session) -> None:
    _, headers = _create_school_owner(client, db)
    r = client.post(
        f"{settings.API_V1_STR}/users/batch",
        headers=headers,
        json={
            "rows": [{"name": "王老师", "email": "dryrun@example.com"}],
            "dry_run": True,
        },
    )
    assert r.status_code == 200
    assert r.json()["rows"][0]["action"] == "create"
    assert crud.get_user_by_email(session=db, email="dryrun@example.com") is None


def test_batch_import_teachers_skips_existing_email(
    client: TestClient, db: Session
) -> None:
    _, headers = _create_school_owner(client, db)
    existing_email = random_email()
    crud.create_user(
        session=db, user_create=UserCreate(email=existing_email, password="password123")
    )
    r = client.post(
        f"{settings.API_V1_STR}/users/batch",
        headers=headers,
        json={
            "rows": [
                {"name": "新人", "email": existing_email},
                {"name": "赵老师", "email": "zhao@example.com"},
            ]
        },
    )
    assert r.status_code == 200
    content = r.json()
    assert content["created"] == 1
    assert content["skipped"] == 1
    rows = {row["email"]: row for row in content["rows"]}
    assert rows[existing_email]["action"] == "skip_exists"
    assert rows["zhao@example.com"]["action"] == "create"


def test_batch_import_teachers_validation_errors(
    client: TestClient, db: Session
) -> None:
    _, headers = _create_school_owner(client, db)
    _create_class(client, headers, "高三2班")
    r = client.post(
        f"{settings.API_V1_STR}/users/batch",
        headers=headers,
        json={
            "rows": [
                {"name": "缺邮箱"},
                {"name": "坏邮箱", "email": "not-an-email"},
                {
                    "name": "周老师",
                    "email": "zhou@example.com",
                    "class_names": "高三2班,不存在的班",
                },
            ]
        },
    )
    assert r.status_code == 200
    content = r.json()
    assert content["created"] == 0
    assert len(content["errors"]) == 3
    rows = content["rows"]
    assert rows[0]["message"] == "姓名和邮箱必填"
    assert rows[1]["message"] == "邮箱格式不正确"
    assert "不存在的班" in rows[2]["message"]
    assert crud.get_user_by_email(session=db, email="zhou@example.com") is None


def test_batch_import_teachers_forbidden_for_teacher(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/users/batch",
        headers=normal_user_token_headers,
        json={"rows": [{"name": "王老师", "email": "wang2@example.com"}]},
    )
    assert r.status_code == 403


def test_user_employee_no_read_write(client: TestClient, db: Session) -> None:
    _, headers = _create_school_owner(client, db)
    email = random_email()
    r = client.post(
        f"{settings.API_V1_STR}/users/",
        headers=headers,
        json={
            "email": email,
            "password": "password123",
            "full_name": "工号老师",
            "employee_no": "T100",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["employee_no"] == "T100"
    user_id = r.json()["id"]

    r = client.get(f"{settings.API_V1_STR}/users/{user_id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["employee_no"] == "T100"

    r = client.patch(
        f"{settings.API_V1_STR}/users/{user_id}",
        headers=headers,
        json={"employee_no": "T101"},
    )
    assert r.status_code == 200
    assert r.json()["employee_no"] == "T101"
    user = crud.get_user_by_email(session=db, email=email)
    assert user is not None
    assert user.employee_no == "T101"
