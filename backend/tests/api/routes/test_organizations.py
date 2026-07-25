from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import Organization, User, UserCreate, UserRole
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string

DEFAULT_ORG_CODE = "default"

# 模块在 collection 阶段导入，早于任何测试创建数据；
# 早于该时间点的用户即为迁移时存在的存量用户。
COLLECTED_AT = datetime.now(UTC)


def test_default_organization_exists(db: Session) -> None:
    # 迁移会创建默认学校，作为存量学校用户的归属组织
    org = db.exec(
        select(Organization).where(Organization.code == DEFAULT_ORG_CODE)
    ).first()
    assert org
    assert org.name == "默认学校"
    assert org.status == "active"
    assert org.exam_sharing_enabled is False


def test_first_superuser_is_platform_superuser_without_org(db: Session) -> None:
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user
    assert user.role == UserRole.PLATFORM_SUPERUSER
    assert user.org_id is None


def test_user_me_includes_org_id_and_org_name(client: TestClient, db: Session) -> None:
    org = db.exec(
        select(Organization).where(Organization.code == DEFAULT_ORG_CODE)
    ).one()
    password = random_lower_string()
    user_in = UserCreate(
        email=random_email(),
        password=password,
        role=UserRole.TEACHER,
        org_id=org.id,
    )
    user = crud.create_user(session=db, user_create=user_in)
    headers = user_authentication_headers(
        client=client, email=user.email, password=password
    )
    r = client.get(f"{settings.API_V1_STR}/users/me", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["org_id"] == str(org.id)
    assert data["org_name"] == "默认学校"


def test_platform_user_me_has_null_org(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.get(
        f"{settings.API_V1_STR}/users/me", headers=superuser_token_headers
    )
    assert r.status_code == 200
    data = r.json()
    assert data["role"] == UserRole.PLATFORM_SUPERUSER
    assert data["org_id"] is None
    assert data["org_name"] is None


def test_school_users_backfilled_with_default_org(db: Session) -> None:
    # 迁移回填：非平台角色的存量用户（迁移时已存在）都必须有 org_id（默认学校）。
    # 测试运行期间新建的用户不属于迁移回填范围，按创建时间排除。
    org = db.exec(
        select(Organization).where(Organization.code == DEFAULT_ORG_CODE)
    ).one()
    users = db.exec(select(User)).all()
    platform_roles = (UserRole.PLATFORM_SUPERUSER, UserRole.PLATFORM_SUPPORT)
    legacy_users = [
        user
        for user in users
        if user.created_at is None
        or user.created_at.replace(tzinfo=UTC) <= COLLECTED_AT
    ]
    for user in legacy_users:
        if user.role in platform_roles:
            assert user.org_id is None
        else:
            assert user.org_id == org.id
