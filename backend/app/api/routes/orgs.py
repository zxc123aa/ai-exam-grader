"""学校设置端点（多租户阶段 3）：本校信息查询与设置修改。

- GET /org/settings：学校侧角色（owner / admin / teacher）可读；学生 403。
- PATCH /org/settings：仅 school_owner 可改 contact_name 与 exam_sharing_enabled。
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col, func, select

from app.api.deps import SessionDep, require_roles
from app.models import (
    BillingEntitlementPublic,
    BillingSummaryPublic,
    BillingUsageItemPublic,
    BillingUsagePublic,
    ClassGroup,
    CreditLedgerEntry,
    CreditLedgerItemPublic,
    CreditLedgerPublic,
    Exam,
    ModelUsageEvent,
    Organization,
    OrganizationModelSelection,
    OrgOnboardingPublic,
    OrgSettingsPublic,
    OrgSettingsUpdate,
    PlatformModelOffering,
    SchoolModelScope,
    SchoolModelSelectionUpdate,
    SchoolModelSettingsPublic,
    Student,
    User,
    UserRole,
)
from app.services import billing as billing_service
from app.services.model_catalog import school_model_settings

router = APIRouter(prefix="/org", tags=["org"])

SchoolMember = Annotated[
    User,
    Depends(
        require_roles(UserRole.SCHOOL_OWNER, UserRole.SCHOOL_ADMIN, UserRole.TEACHER)
    ),
]
SchoolOwner = Annotated[User, Depends(require_roles(UserRole.SCHOOL_OWNER))]
SchoolManager = Annotated[
    User,
    Depends(require_roles(UserRole.SCHOOL_OWNER, UserRole.SCHOOL_ADMIN)),
]


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
        organization_type=org.organization_type,
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
        organization_type=org.organization_type,
        exam_sharing_enabled=org.exam_sharing_enabled,
        contact_name=org.contact_name,
    )


@router.get("/onboarding", response_model=OrgOnboardingPublic)
def read_org_onboarding(
    session: SessionDep, current_user: SchoolManager
) -> OrgOnboardingPublic:
    """首次开通引导使用的学校真实进度。"""
    org = _get_own_org(session, current_user)
    class_count = session.exec(
        select(func.count()).select_from(ClassGroup).where(ClassGroup.org_id == org.id)
    ).one()
    teacher_count = session.exec(
        select(func.count())
        .select_from(User)
        .where(User.org_id == org.id, User.role == UserRole.TEACHER)
    ).one()
    student_count = session.exec(
        select(func.count())
        .select_from(Student)
        .join(ClassGroup, ClassGroup.id == Student.class_id)
        .where(ClassGroup.org_id == org.id)
    ).one()
    teacher_exam_count = session.exec(
        select(func.count())
        .select_from(Exam)
        .join(User, User.id == Exam.owner_id)
        .where(Exam.org_id == org.id, User.role == UserRole.TEACHER)
    ).one()
    return OrgOnboardingPublic(
        class_count=class_count,
        teacher_count=teacher_count,
        student_count=student_count,
        teacher_exam_count=teacher_exam_count,
    )


@router.get("/model-settings", response_model=SchoolModelSettingsPublic)
def read_org_model_settings(session: SessionDep, current_user: SchoolManager) -> Any:
    org = _get_own_org(session, current_user)
    return school_model_settings(session, org.id)


@router.put("/model-settings/{scope}", response_model=SchoolModelSettingsPublic)
def update_org_model_setting(
    session: SessionDep,
    current_user: SchoolOwner,
    scope: SchoolModelScope,
    selection_in: SchoolModelSelectionUpdate,
) -> Any:
    org = _get_own_org(session, current_user)
    offering = session.get(PlatformModelOffering, selection_in.offering_id)
    if (
        not offering
        or offering.scope != scope
        or not offering.published
        or not offering.school_selectable
    ):
        raise HTTPException(status_code=422, detail="该模型方案不可供学校选择")
    selection = session.exec(
        select(OrganizationModelSelection).where(
            OrganizationModelSelection.org_id == org.id,
            OrganizationModelSelection.scope == scope,
        )
    ).first()
    if selection:
        selection.offering_id = offering.id
        selection.updated_by_id = current_user.id
    else:
        selection = OrganizationModelSelection(
            org_id=org.id,
            scope=scope,
            offering_id=offering.id,
            updated_by_id=current_user.id,
        )
    session.add(selection)
    session.commit()
    return school_model_settings(session, org.id)


@router.get("/billing/entitlement", response_model=BillingEntitlementPublic)
def read_billing_entitlement(session: SessionDep, current_user: SchoolMember) -> Any:
    org = _get_own_org(session, current_user)
    return BillingEntitlementPublic(status=billing_service.entitlement(session, org.id))


@router.get("/billing", response_model=BillingSummaryPublic)
def read_billing_summary(session: SessionDep, current_user: SchoolManager) -> Any:
    org = _get_own_org(session, current_user)
    return billing_service.billing_summary(session, org.id)


@router.get("/billing/usage", response_model=BillingUsagePublic)
def read_billing_usage(
    session: SessionDep,
    current_user: SchoolManager,
    offset: int = 0,
    limit: int = 50,
) -> Any:
    org = _get_own_org(session, current_user)
    limit = min(max(limit, 1), 200)
    count = session.exec(
        select(func.count())
        .select_from(ModelUsageEvent)
        .where(ModelUsageEvent.org_id == org.id)
    ).one()
    rows = session.exec(
        select(ModelUsageEvent)
        .where(ModelUsageEvent.org_id == org.id)
        .order_by(col(ModelUsageEvent.created_at).desc())
        .offset(max(offset, 0))
        .limit(limit)
    ).all()
    return BillingUsagePublic(
        data=[
            BillingUsageItemPublic(
                id=row.id,
                exam_id=row.exam_id,
                grading_run_id=row.grading_run_id,
                workflow_purpose=row.workflow_purpose,
                input_tokens=row.input_tokens,
                output_tokens=row.output_tokens,
                image_tokens=row.image_tokens,
                total_tokens=row.total_tokens,
                credits=billing_service.microcredits_to_credits(
                    row.customer_microcredits
                ),
                status=row.status,
                created_at=row.created_at,
            )
            for row in rows
        ],
        count=count,
    )


@router.get("/billing/ledger", response_model=CreditLedgerPublic)
def read_billing_ledger(
    session: SessionDep,
    current_user: SchoolManager,
    offset: int = 0,
    limit: int = 50,
) -> Any:
    org = _get_own_org(session, current_user)
    limit = min(max(limit, 1), 200)
    count = session.exec(
        select(func.count())
        .select_from(CreditLedgerEntry)
        .where(CreditLedgerEntry.org_id == org.id)
    ).one()
    rows = session.exec(
        select(CreditLedgerEntry)
        .where(CreditLedgerEntry.org_id == org.id)
        .order_by(col(CreditLedgerEntry.created_at).desc())
        .offset(max(offset, 0))
        .limit(limit)
    ).all()
    return CreditLedgerPublic(
        data=[
            CreditLedgerItemPublic(
                id=row.id,
                entry_type=row.entry_type,
                amount_credits=billing_service.microcredits_to_credits(
                    row.amount_microcredits
                ),
                balance_after_credits=billing_service.microcredits_to_credits(
                    row.balance_after_microcredits
                ),
                note=row.note,
                created_at=row.created_at,
            )
            for row in rows
        ],
        count=count,
    )
