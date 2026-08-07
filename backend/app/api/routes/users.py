import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import and_
from sqlmodel import col, func, select

from app import crud
from app.api.deps import (
    CurrentUser,
    SessionDep,
    is_admin_or_superuser,
    is_platform_superuser,
    is_platform_user,
    require_roles,
)
from app.core.config import settings
from app.core.security import get_password_hash, verify_password
from app.models import (
    ClassGroup,
    Message,
    Organization,
    OrganizationSignupCompleted,
    OrganizationSignupCreate,
    OrganizationSignupRequested,
    OrganizationSignupResend,
    OrganizationSignupVerify,
    TeacherBatchCreate,
    TeacherBatchResult,
    TeacherBatchRowResult,
    TeacherClassLink,
    TeachingProfilePublic,
    TeachingProfileUpdate,
    UpdatePassword,
    User,
    UserCreate,
    UserPublic,
    UserRole,
    UsersPublic,
    UserUpdate,
    UserUpdateMe,
)
from app.services import public_signup
from app.utils import generate_new_account_email, send_email

router = APIRouter(prefix="/users", tags=["users"])

PLATFORM_ROLES = (
    UserRole.PLATFORM_SUPERUSER,
    UserRole.PLATFORM_ADMIN,
    UserRole.PLATFORM_SUPPORT,
)

_email_adapter = TypeAdapter(EmailStr)

# 用户管理端点：平台超管查看全部账号，但只维护平台账号；学校管理角色维护本校账号。
CurrentAdminUser = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.PLATFORM_SUPERUSER,
            UserRole.SCHOOL_OWNER,
            UserRole.SCHOOL_ADMIN,
        )
    ),
]


def _user_in_scope(current_user: User, target: User) -> bool:
    """平台超管只维护平台账号；学校角色只能管理本校用户。

    无 org 的学校账号（仅历史/测试数据）只能管理同为无 org 的非平台账号，
    避免把平台账号纳入其范围。
    """
    if is_platform_superuser(current_user):
        return target.role in PLATFORM_ROLES and target.org_id is None
    if current_user.org_id is None:
        return target.org_id is None and target.role not in PLATFORM_ROLES
    return target.org_id == current_user.org_id


def _users_scope_filter(current_user: User):
    """平台超管维护平台账号；学校角色维护本校账号。"""
    if is_platform_superuser(current_user):
        return and_(col(User.org_id).is_(None), col(User.role).in_(PLATFORM_ROLES))
    if current_user.org_id is None:
        return and_(col(User.org_id).is_(None), col(User.role).notin_(PLATFORM_ROLES))
    return User.org_id == current_user.org_id


@router.get("/", response_model=UsersPublic)
def read_users(
    session: SessionDep,
    current_user: CurrentAdminUser,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    Retrieve users. 平台超管看平台账号，学校角色只看本校用户。
    """
    scope = _users_scope_filter(current_user)
    count_statement = select(func.count()).select_from(User).where(scope)
    count = session.exec(count_statement).one()

    statement = (
        select(User)
        .where(scope)
        .order_by(col(User.created_at).desc())
        .offset(skip)
        .limit(limit)
    )
    users = session.exec(statement).all()

    # 填充学校名称（列表页「学校」列）
    org_ids = {user.org_id for user in users if user.org_id}
    org_names = {}
    if org_ids:
        for org in session.exec(
            select(Organization).where(col(Organization.id).in_(org_ids))
        ).all():
            org_names[org.id] = org.name
    users_public = []
    for user in users:
        user_public = UserPublic.model_validate(user)
        user_public.org_name = org_names.get(user.org_id)
        users_public.append(user_public)
    return UsersPublic(data=users_public, count=count)


@router.post("/", response_model=UserPublic)
def create_user(
    *, session: SessionDep, user_in: UserCreate, current_user: CurrentAdminUser
) -> Any:
    """
    Create new user. 学校角色只能创建本校账号，且受角色上限约束。
    """
    if is_platform_superuser(current_user) and user_in.role not in PLATFORM_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Platform superusers can only create platform accounts here",
        )
    if not is_platform_user(current_user):
        # 学校角色：不能创建平台账号，账号一律归入本校
        if user_in.role in PLATFORM_ROLES:
            raise HTTPException(
                status_code=400,
                detail="Only platform superusers can create platform accounts",
            )
        if current_user.role == UserRole.SCHOOL_ADMIN and user_in.role in (
            UserRole.SCHOOL_OWNER,
            UserRole.SCHOOL_ADMIN,
        ):
            raise HTTPException(
                status_code=403,
                detail="School admins cannot create owner or admin accounts",
            )
        user_in.org_id = current_user.org_id
    user = crud.get_user_by_email(session=session, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system.",
        )

    user = crud.create_user(session=session, user_create=user_in)
    if settings.emails_enabled and user_in.email:
        email_data = generate_new_account_email(
            email_to=user_in.email, username=user_in.email, password=user_in.password
        )
        send_email(
            email_to=user_in.email,
            subject=email_data.subject,
            html_content=email_data.html_content,
        )
    return user


# 老师批量导入的统一初始密码
# TODO(v1 之后): 强制首次登录改密
TEACHER_INITIAL_PASSWORD = "Dianfan@2026"


def _split_csv_field(value: str | None) -> list[str]:
    """逗号分隔字段拆分：去空白、去空项、去重保序。"""
    if not value:
        return []
    return list(
        dict.fromkeys(item.strip() for item in value.split(",") if item.strip())
    )


@router.post("/batch", response_model=TeacherBatchResult)
def create_teachers_batch(
    *,
    session: SessionDep,
    batch_in: TeacherBatchCreate,
    current_user: CurrentAdminUser,
) -> Any:
    """老师花名册批量导入。dry_run=true 只校验不落库，逐行返回处理结果。"""
    org_id = current_user.org_id
    class_by_name: dict[str, ClassGroup] = {}
    if org_id:
        for class_group in session.exec(
            select(ClassGroup).where(ClassGroup.org_id == org_id)
        ).all():
            class_by_name[class_group.name] = class_group
    seen_emails: set[str] = set()
    row_results: list[TeacherBatchRowResult] = []
    created = skipped = 0
    for row in batch_in.rows:
        name = row.name.strip() if row.name else ""
        email = row.email.strip().lower() if row.email else ""
        if not name or not email:
            row_results.append(
                TeacherBatchRowResult(
                    name=name or None,
                    email=email or None,
                    action="error",
                    message="姓名和邮箱必填",
                )
            )
            continue
        try:
            _email_adapter.validate_python(email)
        except ValidationError:
            row_results.append(
                TeacherBatchRowResult(
                    name=name,
                    email=email,
                    action="error",
                    message="邮箱格式不正确",
                )
            )
            continue
        if email in seen_emails or crud.get_user_by_email(
            session=session, email=email
        ):
            skipped += 1
            row_results.append(
                TeacherBatchRowResult(
                    name=name,
                    email=email,
                    action="skip_exists",
                    message="邮箱已存在",
                )
            )
            continue
        class_names = _split_csv_field(row.class_names)
        missing = [cn for cn in class_names if cn not in class_by_name]
        if missing:
            row_results.append(
                TeacherBatchRowResult(
                    name=name,
                    email=email,
                    action="error",
                    message=f"班级不存在：{'、'.join(missing)}",
                )
            )
            continue
        subjects = _split_csv_field(row.subjects)
        seen_emails.add(email)
        created += 1
        row_results.append(
            TeacherBatchRowResult(name=name, email=email, action="create")
        )
        if batch_in.dry_run:
            continue
        user = User(
            email=email,
            hashed_password=get_password_hash(TEACHER_INITIAL_PASSWORD),
            full_name=name,
            role=UserRole.TEACHER,
            employee_no=row.employee_no.strip() if row.employee_no else None,
            org_id=org_id,
            is_active=True,
            subjects=subjects,
        )
        session.add(user)
        session.flush()
        for class_name in class_names:
            session.add(
                TeacherClassLink(
                    user_id=user.id, class_id=class_by_name[class_name].id
                )
            )
    if not batch_in.dry_run:
        session.commit()
    errors = [r for r in row_results if r.action == "error"]
    return TeacherBatchResult(
        created=created, skipped=skipped, rows=row_results, errors=errors
    )


@router.patch("/me", response_model=UserPublic)
def update_user_me(
    *, session: SessionDep, user_in: UserUpdateMe, current_user: CurrentUser
) -> Any:
    """
    Update own user.
    """

    if user_in.email:
        existing_user = crud.get_user_by_email(session=session, email=user_in.email)
        if existing_user and existing_user.id != current_user.id:
            raise HTTPException(
                status_code=409, detail="User with this email already exists"
            )
    user_data = user_in.model_dump(exclude_unset=True)
    current_user.sqlmodel_update(user_data)
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    return current_user


@router.patch("/me/password", response_model=Message)
def update_password_me(
    *, session: SessionDep, body: UpdatePassword, current_user: CurrentUser
) -> Any:
    """
    Update own password.
    """
    verified, _ = verify_password(body.current_password, current_user.hashed_password)
    if not verified:
        raise HTTPException(status_code=400, detail="Incorrect password")
    if body.current_password == body.new_password:
        raise HTTPException(
            status_code=400, detail="New password cannot be the same as the current one"
        )
    hashed_password = get_password_hash(body.new_password)
    current_user.hashed_password = hashed_password
    session.add(current_user)
    session.commit()
    return Message(message="Password updated successfully")


@router.get("/me", response_model=UserPublic)
def read_user_me(session: SessionDep, current_user: CurrentUser) -> Any:
    """
    Get current user.
    """
    user_public = UserPublic.model_validate(current_user)
    if current_user.org_id:
        org = session.get(Organization, current_user.org_id)
        user_public.org_name = org.name if org else None
    return user_public


@router.delete("/me", response_model=Message)
def delete_user_me(_session: SessionDep, _current_user: CurrentUser) -> Any:
    """
    Delete own user.

    多租户模式下自删会级联删除其名下的考试与数据，过于危险：
    所有角色一律禁止自删，由学校管理员或平台停用账号。
    """
    raise HTTPException(
        status_code=403,
        detail="账号不支持自行删除，如需停用请联系学校管理员",
    )


def _request_ip(request: Request) -> str:
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


@router.post(
    "/signup",
    response_model=OrganizationSignupRequested,
    status_code=status.HTTP_202_ACCEPTED,
)
def register_organization(
    request: Request, session: SessionDep, signup_in: OrganizationSignupCreate
) -> Any:
    """提交学校注册；邮箱验证前不创建正式租户。"""
    public_signup.request_signup(
        session, signup=signup_in, remote_ip=_request_ip(request)
    )
    return OrganizationSignupRequested(
        message="验证邮件已发送，请在 30 分钟内完成验证",
        expires_in_seconds=settings.PUBLIC_SIGNUP_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/signup/resend",
    response_model=OrganizationSignupRequested,
    status_code=status.HTTP_202_ACCEPTED,
)
def resend_organization_signup(
    request: Request, session: SessionDep, resend_in: OrganizationSignupResend
) -> Any:
    public_signup.resend_signup(
        session,
        email=str(resend_in.email),
        turnstile_token=resend_in.turnstile_token,
        remote_ip=_request_ip(request),
    )
    return OrganizationSignupRequested(
        message="新的验证邮件已发送",
        expires_in_seconds=settings.PUBLIC_SIGNUP_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/signup/verify", response_model=OrganizationSignupCompleted)
def verify_organization_signup(
    session: SessionDep, verify_in: OrganizationSignupVerify
) -> Any:
    """验证邮箱并原子开通学校、负责人账号和试用额度。"""
    return public_signup.verify_signup(session, token=verify_in.token)


@router.get("/{user_id}", response_model=UserPublic)
def read_user_by_id(
    user_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    """
    Get a specific user by id.
    """
    user = session.get(User, user_id)
    if user == current_user:
        return user
    if not is_admin_or_superuser(current_user):
        raise HTTPException(
            status_code=403,
            detail="The user doesn't have enough privileges",
        )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not _user_in_scope(current_user, user):
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/{user_id}/teaching", response_model=TeachingProfilePublic)
def read_teaching_profile(
    user_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    """
    任教档案（任教班级 + 学科标签）：本人或学校管理角色（owner/admin）可读。
    """
    target = session.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id != current_user.id:
        if not is_admin_or_superuser(current_user):
            raise HTTPException(
                status_code=403,
                detail="The user doesn't have enough privileges",
            )
        if not is_platform_user(current_user) and not _user_in_scope(
            current_user, target
        ):
            raise HTTPException(status_code=404, detail="User not found")
    return _build_teaching_profile(session=session, target=target)


def _build_teaching_profile(
    *, session: SessionDep, target: User
) -> TeachingProfilePublic:
    rows = session.exec(
        select(TeacherClassLink, ClassGroup)
        .join(ClassGroup, TeacherClassLink.class_id == ClassGroup.id)
        .where(TeacherClassLink.user_id == target.id)
        .order_by(col(ClassGroup.name).asc())
    ).all()
    return TeachingProfilePublic(
        class_ids=[link.class_id for link, _class_group in rows],
        class_names=[class_group.name for _link, class_group in rows],
        subjects=list(target.subjects or []),
    )


CurrentSchoolManagerUser = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.SCHOOL_OWNER,
            UserRole.SCHOOL_ADMIN,
        )
    ),
]


@router.put("/{user_id}/teaching", response_model=TeachingProfilePublic)
def update_teaching_profile(
    user_id: uuid.UUID,
    session: SessionDep,
    profile_in: TeachingProfileUpdate,
    current_user: CurrentSchoolManagerUser,
) -> Any:
    """
    整体覆盖任教档案：school_owner/school_admin（限本校）；
    目标用户角色必须是 teacher/school_admin；班级必须与目标用户同校（跨校 400）。
    """
    target = session.get(User, user_id)
    if not target or not _user_in_scope(current_user, target):
        raise HTTPException(status_code=404, detail="User not found")
    if target.role not in (UserRole.TEACHER, UserRole.SCHOOL_ADMIN):
        raise HTTPException(
            status_code=400,
            detail="只能为教师或学校管理员设置任教档案",
        )
    # 平台超管 org_id 为空，班级归属按目标用户的学校校验
    org_id = current_user.org_id or target.org_id
    unique_class_ids = list(dict.fromkeys(profile_in.class_ids))
    class_groups = (
        list(
            session.exec(
                select(ClassGroup).where(
                    col(ClassGroup.id).in_(unique_class_ids),
                    ClassGroup.org_id == org_id,
                )
            ).all()
        )
        if unique_class_ids
        else []
    )
    if len(class_groups) != len(unique_class_ids):
        raise HTTPException(
            status_code=400,
            detail="Invalid class_ids: 班级不存在或不属于本学校",
        )
    # 学科标签：去空白、去重保序
    subjects = list(
        dict.fromkeys(
            subject.strip() for subject in profile_in.subjects if subject.strip()
        )
    )
    for link in session.exec(
        select(TeacherClassLink).where(TeacherClassLink.user_id == target.id)
    ).all():
        session.delete(link)
    session.flush()
    for class_id in unique_class_ids:
        session.add(TeacherClassLink(user_id=target.id, class_id=class_id))
    target.subjects = subjects
    session.add(target)
    session.commit()
    session.refresh(target)
    return _build_teaching_profile(session=session, target=target)


@router.patch("/{user_id}", response_model=UserPublic)
def update_user(
    *,
    session: SessionDep,
    user_id: uuid.UUID,
    user_in: UserUpdate,
    current_user: CurrentAdminUser,
) -> Any:
    """
    Update a user. 学校角色只能修改本校用户，且受角色上限约束。
    """

    db_user = session.get(User, user_id)
    if not db_user:
        raise HTTPException(
            status_code=404,
            detail="The user with this id does not exist in the system",
        )
    if not is_platform_superuser(current_user) and (
        db_user.role in PLATFORM_ROLES or is_platform_superuser(db_user)
    ):
        raise HTTPException(
            status_code=400,
            detail="Only platform superusers can modify platform accounts",
        )
    if not _user_in_scope(current_user, db_user):
        raise HTTPException(
            status_code=403,
            detail="No permission to manage users of other organizations",
        )
    # 任何人不能修改自己的角色（防降级锁死）
    if user_in.role is not None and db_user.id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="Users cannot change their own role",
        )
    if not is_platform_superuser(current_user):
        if user_in.role in PLATFORM_ROLES:
            raise HTTPException(
                status_code=400,
                detail="Only platform superusers can grant platform roles",
            )
        if current_user.role == UserRole.SCHOOL_ADMIN:
            if db_user.role in (UserRole.SCHOOL_OWNER, UserRole.SCHOOL_ADMIN):
                raise HTTPException(
                    status_code=403,
                    detail="School admins cannot modify owner or admin accounts",
                )
            if user_in.role in (UserRole.SCHOOL_OWNER, UserRole.SCHOOL_ADMIN):
                raise HTTPException(
                    status_code=403,
                    detail="School admins cannot grant owner or admin roles",
                )
        if not is_platform_user(current_user):
            # 学校角色不能改动用户归属学校（强制保持本校，忽略请求值）
            user_in.org_id = current_user.org_id
    elif user_in.role is not None and user_in.role not in PLATFORM_ROLES:
        raise HTTPException(
            status_code=400,
            detail="Platform superusers can only grant platform roles",
        )
    if user_in.email:
        existing_user = crud.get_user_by_email(session=session, email=user_in.email)
        if existing_user and existing_user.id != user_id:
            raise HTTPException(
                status_code=409, detail="User with this email already exists"
            )

    db_user = crud.update_user(session=session, db_user=db_user, user_in=user_in)
    return db_user


@router.delete("/{user_id}")
def delete_user(
    session: SessionDep, current_user: CurrentAdminUser, user_id: uuid.UUID
) -> Message:
    """
    Deactivate a user. Historical school data must never follow an account deletion.
    """
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user == current_user:
        raise HTTPException(
            status_code=403, detail="Super users are not allowed to delete themselves"
        )
    if not _user_in_scope(current_user, user):
        raise HTTPException(
            status_code=403,
            detail="No permission to manage users of other organizations",
        )
    if user.role in PLATFORM_ROLES and not is_platform_superuser(current_user):
        raise HTTPException(
            status_code=400,
            detail="Only platform superusers can delete platform accounts",
        )
    user.is_active = False
    session.add(user)
    session.commit()
    return Message(message="User deactivated; historical data was preserved")
