"""学校设置端点（多租户阶段 3）：本校信息查询与设置修改。

- GET /org/settings：学校侧角色（owner / admin / teacher）可读；学生 403。
- PATCH /org/settings：仅 school_owner 可改 contact_name 与 exam_sharing_enabled。
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import SessionDep, require_roles
from app.models import (
    Organization,
    OrgSettingsPublic,
    OrgSettingsUpdate,
    User,
    UserRole,
)

router = APIRouter(prefix="/org", tags=["org"])

SchoolMember = Annotated[
    User,
    Depends(
        require_roles(UserRole.SCHOOL_OWNER, UserRole.SCHOOL_ADMIN, UserRole.TEACHER)
    ),
]
SchoolOwner = Annotated[User, Depends(require_roles(UserRole.SCHOOL_OWNER))]


def _get_own_org(session: SessionDep, current_user: User) -> Organization:
    if current_user.org_id is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    org = session.get(Organization, current_user.org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


@router.get("/settings", response_model=OrgSettingsPublic)
def read_org_settings(session: SessionDep, current_user: SchoolMember) -> Any:
    """本校信息（name / code / exam_sharing_enabled / contact_name）。"""
    org = _get_own_org(session, current_user)
    return OrgSettingsPublic(
        name=org.name,
        code=org.code,
        exam_sharing_enabled=org.exam_sharing_enabled,
        contact_name=org.contact_name,
    )


@router.patch("/settings", response_model=OrgSettingsPublic)
def update_org_settings(
    session: SessionDep, current_user: SchoolOwner, settings_in: OrgSettingsUpdate
) -> Any:
    """修改本校设置（仅 school_owner）。"""
    org = _get_own_org(session, current_user)
    org.sqlmodel_update(settings_in.model_dump(exclude_unset=True))
    session.add(org)
    session.commit()
    session.refresh(org)
    return OrgSettingsPublic(
        name=org.name,
        code=org.code,
        exam_sharing_enabled=org.exam_sharing_enabled,
        contact_name=org.contact_name,
    )
