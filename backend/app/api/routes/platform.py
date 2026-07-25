"""平台管理端点（多租户阶段 3）：学校（组织）的创建、查询、停用与 owner 账号管理。

权限模型：
- 读（列表 / 详情）：platform_superuser + platform_support（运营只读）。
- 写（新建 / 修改 / 追加 owner）：仅 platform_superuser。
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col, func, select

from app import crud
from app.api.deps import SessionDep, require_roles
from app.core.security import get_password_hash
from app.models import (
    ClassGroup,
    Exam,
    Organization,
    PlatformOrgCreate,
    PlatformOrgDetail,
    PlatformOrgListItem,
    PlatformOrgOwnerCreate,
    PlatformOrgsPublic,
    PlatformOrgUpdate,
    PlatformOrgUserItem,
    Student,
    SystemConfigPublic,
    SystemConfigUpdate,
    User,
    UserRole,
)
from app.services import system_config as system_config_service

router = APIRouter(prefix="/platform", tags=["platform"])

TEACHER_ROLES = (UserRole.SCHOOL_OWNER, UserRole.SCHOOL_ADMIN, UserRole.TEACHER)

PlatformReader = Annotated[
    User,
    Depends(require_roles(UserRole.PLATFORM_SUPERUSER, UserRole.PLATFORM_SUPPORT)),
]
PlatformAdmin = Annotated[
    User, Depends(require_roles(UserRole.PLATFORM_SUPERUSER))
]


def _get_org_or_404(session: SessionDep, org_id: uuid.UUID) -> Organization:
    org = session.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


def _org_stats(session: SessionDep, org_id: uuid.UUID) -> dict[str, int]:
    exam_count = session.exec(
        select(func.count()).select_from(Exam).where(Exam.org_id == org_id)
    ).one()
    student_count = session.exec(
        select(func.count())
        .select_from(Student)
        .join(ClassGroup, col(Student.class_id) == ClassGroup.id)
        .where(ClassGroup.org_id == org_id)
    ).one()
    teacher_count = session.exec(
        select(func.count())
        .select_from(User)
        .where(User.org_id == org_id, col(User.role).in_(TEACHER_ROLES))
    ).one()
    return {
        "exam_count": exam_count,
        "student_count": student_count,
        "teacher_count": teacher_count,
    }


def _create_owner_user(
    session: SessionDep, org: Organization, owner_in
) -> User:
    existing = crud.get_user_by_email(session=session, email=owner_in.email)
    if existing:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system.",
        )
    user = User(
        email=owner_in.email,
        full_name=owner_in.full_name,
        hashed_password=get_password_hash(owner_in.password),
        role=UserRole.SCHOOL_OWNER,
        org_id=org.id,
    )
    session.add(user)
    return user


@router.get("/orgs", response_model=PlatformOrgsPublic)
def list_orgs(session: SessionDep, current_user: PlatformReader) -> Any:
    """学校列表（含考试 / 学生 / 老师数）。运营角色只读可用。"""
    orgs = session.exec(select(Organization).order_by(col(Organization.created_at))).all()
    data = [
        PlatformOrgListItem(
            id=org.id,
            name=org.name,
            code=org.code,
            status=org.status,
            created_at=org.created_at,
            **_org_stats(session, org.id),
        )
        for org in orgs
    ]
    return PlatformOrgsPublic(data=data, count=len(data))


@router.post("/orgs", response_model=PlatformOrgDetail)
def create_org(
    session: SessionDep, current_user: PlatformAdmin, org_in: PlatformOrgCreate
) -> Any:
    """新建学校，可同时创建首个 school_owner 账号（同一事务）。"""
    existing = session.exec(
        select(Organization).where(Organization.code == org_in.code)
    ).first()
    if existing:
        raise HTTPException(
            status_code=409, detail="Organization with this code already exists"
        )
    org = Organization(
        name=org_in.name, code=org_in.code, contact_name=org_in.contact_name
    )
    session.add(org)
    owner_user = None
    if org_in.owner:
        owner_user = _create_owner_user(session, org, org_in.owner)
    session.commit()
    session.refresh(org)
    users = [owner_user] if owner_user else []
    return PlatformOrgDetail(
        id=org.id,
        name=org.name,
        code=org.code,
        status=org.status,
        exam_sharing_enabled=org.exam_sharing_enabled,
        contact_name=org.contact_name,
        created_at=org.created_at,
        **_org_stats(session, org.id),
        users=[PlatformOrgUserItem.model_validate(u) for u in users],
    )


@router.get("/orgs/{org_id}", response_model=PlatformOrgDetail)
def read_org(session: SessionDep, current_user: PlatformReader, org_id: uuid.UUID) -> Any:
    """学校详情 + 账号列表 + 使用统计。"""
    org = _get_org_or_404(session, org_id)
    users = session.exec(
        select(User).where(User.org_id == org.id).order_by(col(User.created_at))
    ).all()
    return PlatformOrgDetail(
        id=org.id,
        name=org.name,
        code=org.code,
        status=org.status,
        exam_sharing_enabled=org.exam_sharing_enabled,
        contact_name=org.contact_name,
        created_at=org.created_at,
        **_org_stats(session, org.id),
        users=[PlatformOrgUserItem.model_validate(u) for u in users],
    )


@router.patch("/orgs/{org_id}", response_model=PlatformOrgDetail)
def update_org(
    session: SessionDep,
    current_user: PlatformAdmin,
    org_id: uuid.UUID,
    org_in: PlatformOrgUpdate,
) -> Any:
    """修改学校信息 / 状态（active / suspended）。"""
    org = _get_org_or_404(session, org_id)
    if org_in.code and org_in.code != org.code:
        existing = session.exec(
            select(Organization).where(Organization.code == org_in.code)
        ).first()
        if existing:
            raise HTTPException(
                status_code=409, detail="Organization with this code already exists"
            )
    org.sqlmodel_update(org_in.model_dump(exclude_unset=True))
    session.add(org)
    session.commit()
    session.refresh(org)
    users = session.exec(
        select(User).where(User.org_id == org.id).order_by(col(User.created_at))
    ).all()
    return PlatformOrgDetail(
        id=org.id,
        name=org.name,
        code=org.code,
        status=org.status,
        exam_sharing_enabled=org.exam_sharing_enabled,
        contact_name=org.contact_name,
        created_at=org.created_at,
        **_org_stats(session, org.id),
        users=[PlatformOrgUserItem.model_validate(u) for u in users],
    )


@router.post("/orgs/{org_id}/owners", response_model=PlatformOrgUserItem)
def add_org_owner(
    session: SessionDep,
    current_user: PlatformAdmin,
    org_id: uuid.UUID,
    owner_in: PlatformOrgOwnerCreate,
) -> Any:
    """给学校追加一个 school_owner 账号。"""
    org = _get_org_or_404(session, org_id)
    user = _create_owner_user(session, org, owner_in)
    session.commit()
    session.refresh(user)
    return PlatformOrgUserItem.model_validate(user)


# ---------- 系统设置：模型与批改默认值（仅平台超管） ----------


def _system_config_public(session: SessionDep) -> SystemConfigPublic:
    defaults = system_config_service.get_grading_defaults(session)
    return SystemConfigPublic(
        **defaults, providers=system_config_service.provider_statuses()
    )


@router.get("/system-config", response_model=SystemConfigPublic)
def read_system_config(session: SessionDep, current_user: PlatformAdmin) -> Any:
    """读取模型与批改默认值（DB 无值回落 env）+ 各 provider 配置状态。"""
    return _system_config_public(session)


@router.patch("/system-config", response_model=SystemConfigPublic)
def update_system_config(
    session: SessionDep, current_user: PlatformAdmin, config_in: SystemConfigUpdate
) -> Any:
    """部分更新默认值；校验 provider/model 组合合法后生效于之后的新批次。"""
    updates = config_in.model_dump(exclude_unset=True)
    if not updates:
        return _system_config_public(session)
    merged = system_config_service.get_grading_defaults(session) | updates
    for prefix in ("vision", "grading", "region", "recognition"):
        error = system_config_service.validate_provider_model(
            merged[f"{prefix}_provider"], merged[f"{prefix}_model"]
        )
        if error:
            raise HTTPException(status_code=422, detail=error)
    system_config_service.save_grading_defaults(session, updates)
    session.commit()
    return _system_config_public(session)
