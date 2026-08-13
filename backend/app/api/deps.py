from collections.abc import Generator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session

from app.core import security
from app.core.config import settings
from app.core.db import engine
from app.models import (
    Organization,
    OrganizationServiceState,
    TokenPayload,
    User,
    UserRole,
)

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)


def get_db() -> Generator[Session]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]
TokenDep = Annotated[str, Depends(reusable_oauth2)]


def get_user_from_authorization_header(
    *, session: Session, authorization: str | None = None
) -> User:
    """从 Authorization 头解析用户，供图片等由 `<img>`/fetch 直接取的端点使用。

    这些端点不能走标准依赖注入的 OAuth2 流程，但同样不接受 URL 里的 token。
    """
    token = None
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value:
            token = value
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    user = session.get(User, token_data.sub)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


def assert_organization_access(
    session: SessionDep, user: User, *, method: str = "GET"
) -> None:
    """Apply the school's service state to every authenticated request."""
    if user.org_id is None:
        return
    if user.role == UserRole.STUDENT:
        # 学生身份与学校租户解耦（D-029）：学校欠费冻结不该让学生打不开自己的
        # 学习记录。学生本来就被角色门禁挡在所有学校业务接口之外，只能访问
        # /students/me/*，因此豁免不会扩大暴露面。
        return
    organization = session.get(Organization, user.org_id)
    if not organization or organization.status in {
        OrganizationServiceState.FROZEN,
        OrganizationServiceState.DELETING,
    }:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="学校服务已冻结，请联系点凡阅卷客服",
        )
    if (
        organization.status == OrganizationServiceState.READ_ONLY
        and method.upper() not in {"GET", "HEAD", "OPTIONS"}
    ):
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="学校当前处于只读导出期，不能修改数据或创建新任务",
        )


def get_current_user(session: SessionDep, token: TokenDep, request: Request) -> User:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    user = session.get(User, token_data.sub)
    if not user:
        # A token whose subject no longer exists is an invalid credential,
        # not a missing resource. Returning 401 lets clients discard it and
        # send the user back through login after a database reset/deletion.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    assert_organization_access(session, user, method=request.method)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def is_platform_superuser(user: User) -> bool:
    """平台超管。role 优先，同时兼容旧的 is_superuser 标志位。"""
    return user.role == UserRole.PLATFORM_SUPERUSER or user.is_superuser


def is_platform_user(user: User) -> bool:
    """平台侧角色（超管 + 管理员 + 运营），仅访问卖方控制面。"""
    return (
        user.role
        in (
            UserRole.PLATFORM_SUPERUSER,
            UserRole.PLATFORM_ADMIN,
            UserRole.PLATFORM_SUPPORT,
        )
        or user.is_superuser
    )


def is_school_manager(user: User) -> bool:
    """学校侧管理角色（总管理员 / 管理员），本校数据可见。"""
    return user.role in (UserRole.SCHOOL_OWNER, UserRole.SCHOOL_ADMIN)


def is_superuser(user: User) -> bool:
    """兼容别名：等价于 is_platform_superuser。"""
    return is_platform_superuser(user)


def is_admin_or_superuser(user: User) -> bool:
    """“跨数据可见”语义（阶段 1）：平台角色或学校管理者。

    阶段 2 会按 org 维度细化平台与学校角色的数据范围。
    """
    return is_platform_user(user) or is_school_manager(user)


def get_current_active_superuser(current_user: CurrentUser) -> User:
    if not is_superuser(current_user):
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    return current_user


def require_roles(*roles: UserRole):
    """依赖工厂：当前用户 role 不在允许列表内时返回 403。

    允许列表包含 PLATFORM_SUPERUSER 时，旧的 is_superuser 标志位同样放行。
    """

    def role_checker(current_user: CurrentUser) -> User:
        if current_user.role in roles:
            return current_user
        if UserRole.PLATFORM_SUPERUSER in roles and current_user.is_superuser:
            return current_user
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )

    return role_checker


def get_current_teacher_user(current_user: CurrentUser) -> User:
    """学校业务入口：仅学校管理者与教师可访问。"""
    if current_user.role == UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="学生账号仅可访问我的成绩")
    if current_user.role not in (
        UserRole.SCHOOL_OWNER,
        UserRole.SCHOOL_ADMIN,
        UserRole.TEACHER,
    ):
        raise HTTPException(status_code=403, detail="平台账号无权访问学校业务")
    return current_user


CurrentTeacherUser = Annotated[User, Depends(get_current_teacher_user)]
