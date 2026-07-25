from collections.abc import Generator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session

from app.core import security
from app.core.config import settings
from app.core.db import engine
from app.models import TokenPayload, User, UserRole

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)


def get_db() -> Generator[Session]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]
TokenDep = Annotated[str, Depends(reusable_oauth2)]


def get_current_user(session: SessionDep, token: TokenDep) -> User:
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
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def is_platform_superuser(user: User) -> bool:
    """平台超管。role 优先，同时兼容旧的 is_superuser 标志位。"""
    return user.role == UserRole.PLATFORM_SUPERUSER or user.is_superuser


def is_platform_user(user: User) -> bool:
    """平台侧角色（超管 + 运营），跨校数据可见。"""
    return user.role in (
        UserRole.PLATFORM_SUPERUSER,
        UserRole.PLATFORM_SUPPORT,
    ) or user.is_superuser


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
    """业务端点入口：学生账号一律 403，其余角色（教师/学校管理/平台）放行。"""
    if current_user.role == UserRole.STUDENT and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="学生账号仅可访问我的成绩")
    return current_user


CurrentTeacherUser = Annotated[User, Depends(get_current_teacher_user)]
