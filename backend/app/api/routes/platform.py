"""平台管理端点（多租户阶段 3）：学校（组织）的创建、查询、停用与 owner 账号管理。

权限模型：
- 读（列表 / 详情）：全部平台角色。
- 写（学校、计费）：platform_superuser + platform_admin。
- 模型与中转基础设施：仅 platform_superuser。
- 平台账号本身仍仅 platform_superuser 可维护。
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, case, cast, literal, or_, union_all
from sqlmodel import col, func, select

from app import crud
from app.api.deps import SessionDep, require_roles
from app.core.security import get_password_hash
from app.models import (
    AnswerQuotaGrantCreate,
    BillingRateVersion,
    BillingRateVersionCreate,
    BillingSummaryPublic,
    ClassGroup,
    CreditGrantCreate,
    CreditLedgerEntry,
    CreditLedgerItemPublic,
    CreditLedgerPublic,
    Exam,
    ModelUsageEvent,
    ModelUsageStatus,
    Organization,
    OrganizationRiskState,
    OrganizationSubscription,
    OrganizationUsagePolicy,
    OrganizationUsagePolicyPublic,
    OrganizationUsagePolicyUpdate,
    PlatformDirectoryItem,
    PlatformDirectoryPublic,
    PlatformModelUsageBreakdownItem,
    PlatformModelUsageEventPublic,
    PlatformModelUsageEventsPublic,
    PlatformModelUsageOverviewPublic,
    PlatformModelUsageSummaryPublic,
    PlatformOrgCreate,
    PlatformOrgDetail,
    PlatformOrgListItem,
    PlatformOrgOwnerCreate,
    PlatformOrgsPublic,
    PlatformOrgUpdate,
    PlatformOrgUserItem,
    ProviderChannel,
    Student,
    SubscriptionUpsert,
    SystemConfigPublic,
    SystemConfigUpdate,
    TeacherClassLink,
    User,
    UserRole,
)
from app.services import billing as billing_service
from app.services import system_config as system_config_service
from app.services.model_purpose_policy import model_allowed_for_purpose

router = APIRouter(prefix="/platform", tags=["platform"])

TEACHER_ROLES = (UserRole.SCHOOL_OWNER, UserRole.SCHOOL_ADMIN, UserRole.TEACHER)

PlatformReader = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.PLATFORM_SUPERUSER,
            UserRole.PLATFORM_ADMIN,
            UserRole.PLATFORM_SUPPORT,
        )
    ),
]
PlatformAdmin = Annotated[
    User,
    Depends(require_roles(UserRole.PLATFORM_SUPERUSER, UserRole.PLATFORM_ADMIN)),
]
PlatformSuperuser = Annotated[User, Depends(require_roles(UserRole.PLATFORM_SUPERUSER))]

MODEL_USAGE_PURPOSE_LABELS = {
    "region_detection": "版面分析",
    "question_recognition": "题目识别",
    "score_structure_recognition": "分值结构识别",
    "answer_document_parsing": "答案文档识别",
    "rubric_question_recognition": "题目转录",
    "answer_preparation": "参考答案解题",
    "rubric_generation": "参考答案生成",
    "rubric_validation": "参考答案复核",
    "answer_recognition": "答题预览",
    "answer_extraction": "答题识别",
    "subjective_grading": "主观题判分",
}


def _purpose_label(purpose: str) -> str:
    return MODEL_USAGE_PURPOSE_LABELS.get(purpose, purpose)


def _usage_summary(row: Any) -> PlatformModelUsageSummaryPublic:
    calls = int(row.calls or 0)
    succeeded = int(row.succeeded_calls or 0)
    reconciled_calls = int(row.reconciled_calls or 0)
    upstream_cost = int(row.upstream_cost_micrormb or 0)
    reconciled_internal_cost = int(row.reconciled_internal_cost_micrormb or 0)
    return PlatformModelUsageSummaryPublic(
        calls=calls,
        succeeded_calls=succeeded,
        failed_calls=int(row.failed_calls or 0),
        missing_usage_calls=int(row.missing_usage_calls or 0),
        success_rate=round(succeeded / calls, 4) if calls else 0,
        input_tokens=int(row.input_tokens or 0),
        output_tokens=int(row.output_tokens or 0),
        image_tokens=int(row.image_tokens or 0),
        reasoning_tokens=int(row.reasoning_tokens or 0),
        total_tokens=int(row.total_tokens or 0),
        customer_credits=billing_service.microcredits_to_credits(
            int(row.customer_microcredits or 0)
        ),
        internal_cost_rmb=float(
            Decimal(int(row.internal_cost_micrormb or 0)) / Decimal(1_000_000)
        ),
        upstream_cost_rmb=float(Decimal(upstream_cost) / Decimal(1_000_000)),
        reconciled_internal_cost_rmb=float(
            Decimal(reconciled_internal_cost) / Decimal(1_000_000)
        ),
        cost_variance_rmb=float(
            Decimal(upstream_cost - reconciled_internal_cost) / Decimal(1_000_000)
        ),
        reconciled_calls=reconciled_calls,
        unreconciled_calls=max(0, calls - reconciled_calls),
        average_latency_ms=round(float(row.average_latency_ms or 0), 1),
        fallback_calls=int(row.fallback_calls or 0),
    )


def _usage_breakdown_item(
    *, key: str, label: str, row: Any, org_id: uuid.UUID | None = None
) -> PlatformModelUsageBreakdownItem:
    return PlatformModelUsageBreakdownItem(
        key=key,
        label=label,
        org_id=org_id,
        calls=int(row.calls or 0),
        failed_calls=int(row.failed_calls or 0),
        total_tokens=int(row.total_tokens or 0),
        customer_credits=billing_service.microcredits_to_credits(
            int(row.customer_microcredits or 0)
        ),
        internal_cost_rmb=float(
            Decimal(int(row.internal_cost_micrormb or 0)) / Decimal(1_000_000)
        ),
        upstream_cost_rmb=float(
            Decimal(int(row.upstream_cost_micrormb or 0)) / Decimal(1_000_000)
        ),
        reconciled_calls=int(row.reconciled_calls or 0),
        average_latency_ms=round(float(row.average_latency_ms or 0), 1),
    )


def _usage_aggregate_columns() -> tuple[Any, ...]:
    return (
        func.count().label("calls"),
        func.sum(
            case((ModelUsageEvent.status == ModelUsageStatus.FAILED, 1), else_=0)
        ).label("failed_calls"),
        func.sum(ModelUsageEvent.total_tokens).label("total_tokens"),
        func.sum(ModelUsageEvent.customer_microcredits).label("customer_microcredits"),
        func.sum(ModelUsageEvent.internal_cost_micrormb).label(
            "internal_cost_micrormb"
        ),
        func.sum(ModelUsageEvent.upstream_cost_micrormb).label(
            "upstream_cost_micrormb"
        ),
        func.sum(
            case(
                (
                    ModelUsageEvent.upstream_cost_micrormb.is_not(None),
                    ModelUsageEvent.internal_cost_micrormb,
                ),
                else_=0,
            )
        ).label("reconciled_internal_cost_micrormb"),
        func.sum(
            case((ModelUsageEvent.upstream_cost_micrormb.is_not(None), 1), else_=0)
        ).label("reconciled_calls"),
        func.avg(ModelUsageEvent.latency_ms).label("average_latency_ms"),
    )


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
    class_count = session.exec(
        select(func.count()).select_from(ClassGroup).where(ClassGroup.org_id == org_id)
    ).one()
    account_count = session.exec(
        select(func.count()).select_from(User).where(User.org_id == org_id)
    ).one()
    unbound_student_count = session.exec(
        select(func.count())
        .select_from(Student)
        .join(ClassGroup, col(Student.class_id) == ClassGroup.id)
        .where(ClassGroup.org_id == org_id, Student.user_id.is_(None))
    ).one()
    return {
        "exam_count": exam_count,
        "student_count": student_count,
        "teacher_count": teacher_count,
        "class_count": class_count,
        "account_count": account_count,
        "unbound_student_count": unbound_student_count,
    }


def _org_owner_summary(
    session: SessionDep, org_id: uuid.UUID
) -> tuple[str | None, str | None]:
    owner = session.exec(
        select(User)
        .where(User.org_id == org_id, User.role == UserRole.SCHOOL_OWNER)
        .order_by(col(User.created_at))
    ).first()
    if not owner:
        return None, None
    return owner.full_name, owner.email


def _usage_policy_public(
    policy: OrganizationUsagePolicy,
) -> OrganizationUsagePolicyPublic:
    return OrganizationUsagePolicyPublic(
        org_id=policy.org_id,
        risk_state=policy.risk_state,
        calls_per_minute=policy.calls_per_minute,
        max_running_jobs=policy.max_running_jobs,
        max_model_concurrency=policy.max_model_concurrency,
        max_job_credits=billing_service.microcredits_to_credits(
            policy.max_job_microcredits
        ),
        daily_credit_cap=billing_service.microcredits_to_credits(
            policy.daily_microcredit_cap
        ),
        monthly_credit_cap=billing_service.microcredits_to_credits(
            policy.monthly_microcredit_cap
        ),
        reason=policy.reason,
        updated_at=policy.updated_at,
    )


def _create_owner_user(session: SessionDep, org: Organization, owner_in) -> User:
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


@router.get("/model-usage/overview", response_model=PlatformModelUsageOverviewPublic)
def read_model_usage_overview(
    session: SessionDep,
    _current_user: PlatformReader,
    days: int = 30,
    org_id: uuid.UUID | None = None,
) -> Any:
    """平台模型调用总览；可收窄到单个学校。"""
    if not 1 <= days <= 365:
        raise HTTPException(status_code=422, detail="days must be between 1 and 365")
    if org_id is not None:
        _get_org_or_404(session, org_id)
    since = datetime.now(UTC) - timedelta(days=days)
    conditions = [ModelUsageEvent.created_at >= since]
    if org_id is not None:
        conditions.append(ModelUsageEvent.org_id == org_id)

    summary_row = session.exec(
        select(
            func.count().label("calls"),
            func.sum(
                case((ModelUsageEvent.status == ModelUsageStatus.SUCCEEDED, 1), else_=0)
            ).label("succeeded_calls"),
            func.sum(
                case((ModelUsageEvent.status == ModelUsageStatus.FAILED, 1), else_=0)
            ).label("failed_calls"),
            func.sum(
                case(
                    (
                        ModelUsageEvent.status == ModelUsageStatus.MISSING_USAGE,
                        1,
                    ),
                    else_=0,
                )
            ).label("missing_usage_calls"),
            func.sum(ModelUsageEvent.input_tokens).label("input_tokens"),
            func.sum(ModelUsageEvent.output_tokens).label("output_tokens"),
            func.sum(ModelUsageEvent.image_tokens).label("image_tokens"),
            func.sum(ModelUsageEvent.reasoning_tokens).label("reasoning_tokens"),
            func.sum(ModelUsageEvent.total_tokens).label("total_tokens"),
            func.sum(ModelUsageEvent.customer_microcredits).label(
                "customer_microcredits"
            ),
            func.sum(ModelUsageEvent.internal_cost_micrormb).label(
                "internal_cost_micrormb"
            ),
            func.sum(ModelUsageEvent.upstream_cost_micrormb).label(
                "upstream_cost_micrormb"
            ),
            func.sum(
                case(
                    (
                        ModelUsageEvent.upstream_cost_micrormb.is_not(None),
                        ModelUsageEvent.internal_cost_micrormb,
                    ),
                    else_=0,
                )
            ).label("reconciled_internal_cost_micrormb"),
            func.sum(
                case(
                    (ModelUsageEvent.upstream_cost_micrormb.is_not(None), 1),
                    else_=0,
                )
            ).label("reconciled_calls"),
            func.avg(ModelUsageEvent.latency_ms).label("average_latency_ms"),
            func.sum(case((ModelUsageEvent.fallback_used.is_(True), 1), else_=0)).label(
                "fallback_calls"
            ),
        ).where(*conditions)
    ).one()

    organization_rows = session.exec(
        select(
            Organization.id,
            Organization.name,
            *_usage_aggregate_columns(),
        )
        .join(ModelUsageEvent, ModelUsageEvent.org_id == Organization.id)
        .where(*conditions)
        .group_by(Organization.id, Organization.name)
        .order_by(func.count().desc())
    ).all()
    purpose_rows = session.exec(
        select(ModelUsageEvent.workflow_purpose, *_usage_aggregate_columns())
        .where(*conditions)
        .group_by(ModelUsageEvent.workflow_purpose)
        .order_by(func.count().desc())
    ).all()
    model_rows = session.exec(
        select(
            ModelUsageEvent.actual_provider,
            ModelUsageEvent.actual_model,
            *_usage_aggregate_columns(),
        )
        .where(*conditions)
        .group_by(ModelUsageEvent.actual_provider, ModelUsageEvent.actual_model)
        .order_by(func.count().desc())
    ).all()
    usage_date = func.date(ModelUsageEvent.created_at)
    daily_rows = session.exec(
        select(usage_date.label("usage_date"), *_usage_aggregate_columns())
        .where(*conditions)
        .group_by(usage_date)
        .order_by(usage_date)
    ).all()

    return PlatformModelUsageOverviewPublic(
        days=days,
        since=since,
        summary=_usage_summary(summary_row),
        organizations=[
            _usage_breakdown_item(
                key=str(row.id), label=row.name, org_id=row.id, row=row
            )
            for row in organization_rows
        ],
        purposes=[
            _usage_breakdown_item(
                key=row.workflow_purpose,
                label=_purpose_label(row.workflow_purpose),
                row=row,
            )
            for row in purpose_rows
        ],
        models=[
            _usage_breakdown_item(
                key=f"{row.actual_provider or 'unknown'}:{row.actual_model or 'unknown'}",
                label=" / ".join(
                    part for part in (row.actual_provider, row.actual_model) if part
                )
                or "未记录",
                row=row,
            )
            for row in model_rows
        ],
        daily=[
            _usage_breakdown_item(
                key=str(row.usage_date), label=str(row.usage_date), row=row
            )
            for row in daily_rows
        ],
    )


@router.get("/model-usage", response_model=PlatformModelUsageEventsPublic)
def list_model_usage_events(
    session: SessionDep,
    _current_user: PlatformReader,
    org_id: uuid.UUID | None = None,
    purpose: str | None = None,
    status: ModelUsageStatus | None = None,
    days: int = 30,
    offset: int = 0,
    limit: int = 50,
) -> Any:
    """跨学校调用明细，供运营排障和成本核对。"""
    if not 1 <= days <= 365:
        raise HTTPException(status_code=422, detail="days must be between 1 and 365")
    if org_id is not None:
        _get_org_or_404(session, org_id)
    offset = max(offset, 0)
    limit = min(max(limit, 1), 200)
    since = datetime.now(UTC) - timedelta(days=days)
    conditions = [ModelUsageEvent.created_at >= since]
    if org_id is not None:
        conditions.append(ModelUsageEvent.org_id == org_id)
    if purpose:
        conditions.append(ModelUsageEvent.workflow_purpose == purpose)
    if status is not None:
        conditions.append(ModelUsageEvent.status == status)

    count = session.exec(
        select(func.count()).select_from(ModelUsageEvent).where(*conditions)
    ).one()
    rows = session.exec(
        select(ModelUsageEvent, Organization, ProviderChannel)
        .join(Organization, Organization.id == ModelUsageEvent.org_id)
        .join(
            ProviderChannel,
            ProviderChannel.id == ModelUsageEvent.channel_id,
            isouter=True,
        )
        .where(*conditions)
        .order_by(col(ModelUsageEvent.created_at).desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return PlatformModelUsageEventsPublic(
        data=[
            PlatformModelUsageEventPublic(
                id=event.id,
                org_id=event.org_id,
                org_name=org.name,
                exam_id=event.exam_id,
                grading_run_id=event.grading_run_id,
                resource_id=event.resource_id,
                workflow_purpose=event.workflow_purpose,
                purpose_label=_purpose_label(event.workflow_purpose),
                requested_provider=event.requested_provider,
                requested_model=event.requested_model,
                actual_provider=event.actual_provider,
                actual_model=event.actual_model,
                channel_id=event.channel_id,
                channel_name=channel.display_name if channel else None,
                attempt_number=event.attempt_number,
                attempt_kind=event.attempt_kind,
                fallback_used=event.fallback_used,
                http_status=event.http_status,
                error_code=event.error_code,
                input_tokens=event.input_tokens,
                output_tokens=event.output_tokens,
                image_tokens=event.image_tokens,
                cached_input_tokens=event.cached_input_tokens,
                reasoning_tokens=event.reasoning_tokens,
                total_tokens=event.total_tokens,
                latency_ms=event.latency_ms,
                status=event.status,
                customer_credits=billing_service.microcredits_to_credits(
                    event.customer_microcredits
                ),
                internal_cost_rmb=float(
                    Decimal(event.internal_cost_micrormb) / Decimal(1_000_000)
                ),
                upstream_cost_rmb=(
                    float(Decimal(event.upstream_cost_micrormb) / Decimal(1_000_000))
                    if event.upstream_cost_micrormb is not None
                    else None
                ),
                cost_variance_rmb=(
                    float(
                        Decimal(
                            event.upstream_cost_micrormb - event.internal_cost_micrormb
                        )
                        / Decimal(1_000_000)
                    )
                    if event.upstream_cost_micrormb is not None
                    else None
                ),
                reconciliation_status=event.reconciliation_status,
                created_at=event.created_at,
            )
            for event, org, channel in rows
        ],
        count=count,
    )


@router.get("/directory", response_model=PlatformDirectoryPublic)
def read_platform_directory(
    session: SessionDep,
    _current_user: PlatformReader,
    q: str | None = Query(default=None, max_length=100),
    org_id: uuid.UUID | None = None,
    class_id: uuid.UUID | None = None,
    category: str = Query(
        default="all", pattern="^(all|admins|teachers|students|unlinked)$"
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
) -> Any:
    """跨学校人员目录，统一返回教职工账号、学生名册和绑定状态。"""
    normalized_q = q.strip() if q else ""
    uuid_type = User.__table__.c.id.type
    datetime_type = User.__table__.c.created_at.type

    linked_student = select(Student.id).where(Student.user_id == User.id).exists()
    teaching_class = (
        select(TeacherClassLink.user_id)
        .join(ClassGroup, ClassGroup.id == TeacherClassLink.class_id)
        .where(TeacherClassLink.user_id == User.id)
    )
    account_conditions = [
        User.org_id.is_not(None),
        or_(User.role != UserRole.STUDENT, ~linked_student),
    ]
    student_conditions = []
    if org_id:
        account_conditions.append(User.org_id == org_id)
        student_conditions.append(ClassGroup.org_id == org_id)
    if class_id:
        account_conditions.append(
            teaching_class.where(ClassGroup.id == class_id).exists()
        )
        student_conditions.append(Student.class_id == class_id)
    if normalized_q:
        pattern = f"%{normalized_q}%"
        account_conditions.append(
            or_(
                User.full_name.ilike(pattern),
                User.email.ilike(pattern),
                User.employee_no.ilike(pattern),
                Organization.name.ilike(pattern),
                teaching_class.where(ClassGroup.name.ilike(pattern)).exists(),
            )
        )
        student_conditions.append(
            or_(
                Student.name.ilike(pattern),
                Student.student_no.ilike(pattern),
                User.email.ilike(pattern),
                Organization.name.ilike(pattern),
                ClassGroup.name.ilike(pattern),
            )
        )

    if category == "admins":
        account_conditions.append(
            col(User.role).in_((UserRole.SCHOOL_OWNER, UserRole.SCHOOL_ADMIN))
        )
        student_conditions.append(literal(False))
    elif category == "teachers":
        account_conditions.append(User.role == UserRole.TEACHER)
        student_conditions.append(literal(False))
    elif category in ("students", "unlinked"):
        account_conditions.append(User.role == UserRole.STUDENT)
        if category == "unlinked":
            student_conditions.append(Student.user_id.is_(None))

    account_rows = (
        select(
            literal("account").label("record_type"),
            User.id.label("record_id"),
            User.id.label("user_id"),
            cast(literal(None), uuid_type).label("student_id"),
            func.coalesce(func.nullif(func.trim(User.full_name), ""), User.email).label(
                "name"
            ),
            cast(User.role, String).label("role"),
            User.email.label("email"),
            User.employee_no.label("person_no"),
            User.org_id.label("org_id"),
            Organization.name.label("org_name"),
            cast(literal(None), uuid_type).label("class_id"),
            cast(literal(None), String).label("class_name"),
            case(
                (User.role == UserRole.STUDENT, "no_roster"),
                else_="not_applicable",
            ).label("link_status"),
            User.is_active.label("is_active"),
            User.created_at.label("created_at"),
        )
        .join(Organization, Organization.id == User.org_id)
        .where(*account_conditions)
    )
    student_rows = (
        select(
            literal("student").label("record_type"),
            Student.id.label("record_id"),
            Student.user_id.label("user_id"),
            Student.id.label("student_id"),
            Student.name.label("name"),
            literal(UserRole.STUDENT.value).label("role"),
            User.email.label("email"),
            Student.student_no.label("person_no"),
            ClassGroup.org_id.label("org_id"),
            Organization.name.label("org_name"),
            ClassGroup.id.label("class_id"),
            ClassGroup.name.label("class_name"),
            case(
                (Student.user_id.is_(None), "no_account"), else_="bound"
            ).label("link_status"),
            User.is_active.label("is_active"),
            cast(Student.created_at, datetime_type).label("created_at"),
        )
        .join(ClassGroup, ClassGroup.id == Student.class_id)
        .join(Organization, Organization.id == ClassGroup.org_id)
        .outerjoin(User, User.id == Student.user_id)
        .where(*student_conditions)
    )
    directory = union_all(account_rows, student_rows).subquery()
    count = session.exec(select(func.count()).select_from(directory)).one()
    rows = session.exec(
        select(*directory.c)
        .order_by(
            func.lower(directory.c.org_name),
            func.lower(directory.c.name),
            directory.c.record_id,
        )
        .offset(offset)
        .limit(limit)
    ).all()

    account_ids = {
        row.user_id for row in rows if row.record_type == "account" and row.user_id
    }
    classes_by_user: dict[uuid.UUID, list[str]] = {}
    if account_ids:
        class_rows = session.exec(
            select(TeacherClassLink.user_id, ClassGroup.name)
            .join(ClassGroup, ClassGroup.id == TeacherClassLink.class_id)
            .where(col(TeacherClassLink.user_id).in_(account_ids))
            .order_by(col(ClassGroup.name))
        ).all()
        for user_id, class_name in class_rows:
            classes_by_user.setdefault(user_id, []).append(class_name)

    return PlatformDirectoryPublic(
        data=[
            PlatformDirectoryItem(
                record_type=row.record_type,
                record_id=row.record_id,
                user_id=row.user_id,
                student_id=row.student_id,
                name=(
                    row.name.split("@", 1)[0]
                    if row.record_type == "account" and row.name == row.email
                    else row.name
                ),
                role=UserRole(row.role),
                email=row.email,
                person_no=row.person_no,
                org_id=row.org_id,
                org_name=row.org_name,
                class_id=row.class_id,
                class_name=row.class_name,
                class_names=(
                    [row.class_name]
                    if row.class_name
                    else classes_by_user.get(row.user_id, [])
                ),
                link_status=row.link_status,
                is_active=row.is_active,
                created_at=row.created_at,
            )
            for row in rows
        ],
        count=count,
    )


@router.get("/orgs", response_model=PlatformOrgsPublic)
def list_orgs(session: SessionDep, _current_user: PlatformReader) -> Any:
    """学校列表（含考试 / 学生 / 老师数）。运营角色只读可用。"""
    orgs = session.exec(
        select(Organization).order_by(col(Organization.created_at))
    ).all()
    data = []
    for org in orgs:
        owner_name, owner_email = _org_owner_summary(session, org.id)
        data.append(
            PlatformOrgListItem(
                id=org.id,
                name=org.name,
                code=org.code,
                status=org.status,
                contact_name=org.contact_name,
                owner_name=owner_name,
                owner_email=owner_email,
                created_at=org.created_at,
                **_org_stats(session, org.id),
            )
        )
    return PlatformOrgsPublic(data=data, count=len(data))


@router.post("/orgs", response_model=PlatformOrgDetail)
def create_org(
    session: SessionDep, _current_user: PlatformAdmin, org_in: PlatformOrgCreate
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
def read_org(
    session: SessionDep, _current_user: PlatformReader, org_id: uuid.UUID
) -> Any:
    """学校详情 + 账号列表 + 使用统计。"""
    org = _get_org_or_404(session, org_id)
    users = session.exec(
        select(User)
        .where(User.org_id == org.id, User.role == UserRole.SCHOOL_OWNER)
        .order_by(col(User.created_at))
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
    _current_user: PlatformAdmin,
    org_id: uuid.UUID,
    org_in: PlatformOrgUpdate,
) -> Any:
    """修改学校信息和服务状态。"""
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
        select(User)
        .where(User.org_id == org.id, User.role == UserRole.SCHOOL_OWNER)
        .order_by(col(User.created_at))
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
    _current_user: PlatformAdmin,
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
        **defaults, providers=system_config_service.provider_statuses(session)
    )


@router.get("/system-config", response_model=SystemConfigPublic)
def read_system_config(session: SessionDep, _current_user: PlatformSuperuser) -> Any:
    """读取模型与批改默认值（DB 无值回落 env）+ 各 provider 配置状态。"""
    return _system_config_public(session)


@router.patch("/system-config", response_model=SystemConfigPublic)
def update_system_config(
    session: SessionDep,
    _current_user: PlatformSuperuser,
    config_in: SystemConfigUpdate,
) -> Any:
    """部分更新默认值；校验 provider/model 组合合法后生效于之后的新批次。"""
    updates = config_in.model_dump(exclude_unset=True)
    if not updates:
        return _system_config_public(session)
    if "fallback_models" in updates and "reasoning_fallback_models" not in updates:
        updates["reasoning_fallback_models"] = updates["fallback_models"]
    if "reasoning_fallback_models" in updates:
        updates["fallback_models"] = updates["reasoning_fallback_models"]
    merged = system_config_service.get_grading_defaults(session) | updates
    for prefix in ("vision", "grading", "region", "recognition"):
        provider = merged.get(f"{prefix}_provider")
        model = merged.get(f"{prefix}_model")
        if not isinstance(provider, str) or not provider.strip():
            raise HTTPException(status_code=422, detail="模型提供者不能为空")
        if not isinstance(model, str) or not model.strip():
            raise HTTPException(status_code=422, detail="模型不能为空")
        error = system_config_service.validate_provider_model(provider, model, session)
        if error:
            raise HTTPException(status_code=422, detail=error)
        purpose = "subjective_grading" if prefix == "grading" else "region_detection"
        if not model_allowed_for_purpose(
            purpose=purpose,
            canonical_model=model,
        ):
            detail = (
                "纯视觉功能只允许使用 Gemini 3.6/3.5 Flash"
                if prefix != "grading"
                else "推理解题功能只允许使用 GPT-5.6 Sol、GPT-5.6 Terra 或 Kimi"
            )
            raise HTTPException(status_code=422, detail=detail)
    for key, purpose in (
        ("vision_fallback_models", "region_detection"),
        ("reasoning_fallback_models", "subjective_grading"),
    ):
        configured_fallbacks = merged.get(key)
        if not isinstance(configured_fallbacks, list):
            raise HTTPException(status_code=422, detail=f"{key} 必须是模型列表")
        invalid = [
            model
            for model in configured_fallbacks
            if not model_allowed_for_purpose(
                purpose=purpose,
                canonical_model=str(model),
            )
        ]
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=f"{key} 包含不适用于该任务的模型：{'、'.join(invalid)}",
            )
    system_config_service.save_grading_defaults(session, updates)
    session.commit()
    return _system_config_public(session)


# ---------- 合同、费率与积分（仅平台超管可写） ----------


@router.get("/billing/rates", response_model=list[BillingRateVersion])
def list_billing_rates(session: SessionDep, _current_user: PlatformAdmin) -> Any:
    return list(
        session.exec(
            select(BillingRateVersion).order_by(
                col(BillingRateVersion.effective_at).desc()
            )
        ).all()
    )


@router.post("/billing/rates", response_model=BillingRateVersion)
def create_billing_rate(
    session: SessionDep,
    _current_user: PlatformAdmin,
    rate_in: BillingRateVersionCreate,
) -> Any:
    if session.exec(
        select(BillingRateVersion).where(BillingRateVersion.version == rate_in.version)
    ).first():
        raise HTTPException(status_code=409, detail="费率版本已存在")

    def credits(value: float) -> int:
        return billing_service.credits_to_microcredits(value)

    def micrormb(value: float) -> int:
        return int(
            (Decimal(str(value)) * 1_000_000).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )

    rate = BillingRateVersion(
        version=rate_in.version,
        effective_at=rate_in.effective_at,
        input_microcredits_per_million=credits(rate_in.input_credits_per_million),
        output_microcredits_per_million=credits(rate_in.output_credits_per_million),
        image_microcredits_per_million=credits(rate_in.image_credits_per_million),
        internal_input_micrormb_per_million=micrormb(
            rate_in.internal_input_rmb_per_million
        ),
        internal_output_micrormb_per_million=micrormb(
            rate_in.internal_output_rmb_per_million
        ),
        internal_image_micrormb_per_million=micrormb(
            rate_in.internal_image_rmb_per_million
        ),
    )
    session.add(rate)
    session.commit()
    session.refresh(rate)
    return rate


@router.put("/orgs/{org_id}/subscription", response_model=BillingSummaryPublic)
def upsert_org_subscription(
    session: SessionDep,
    _current_user: PlatformAdmin,
    org_id: uuid.UUID,
    subscription_in: SubscriptionUpsert,
) -> Any:
    _get_org_or_404(session, org_id)
    if subscription_in.ends_at <= subscription_in.starts_at:
        raise HTTPException(status_code=422, detail="合同结束时间必须晚于开始时间")
    if not session.get(BillingRateVersion, subscription_in.rate_version_id):
        raise HTTPException(status_code=422, detail="费率版本不存在")
    subscription = session.exec(
        select(OrganizationSubscription).where(
            OrganizationSubscription.contract_no == subscription_in.contract_no
        )
    ).first()
    values = subscription_in.model_dump()
    if subscription:
        if subscription.org_id != org_id:
            raise HTTPException(status_code=409, detail="合同编号已被其他学校使用")
        subscription.sqlmodel_update(values)
        subscription.updated_at = datetime.now(UTC)
    else:
        subscription = OrganizationSubscription(org_id=org_id, **values)
    session.add(subscription)
    session.commit()
    return billing_service.billing_summary(session, org_id)


@router.post("/orgs/{org_id}/credits", response_model=BillingSummaryPublic)
def grant_org_credits(
    session: SessionDep,
    current_user: PlatformAdmin,
    org_id: uuid.UUID,
    grant_in: CreditGrantCreate,
) -> Any:
    _get_org_or_404(session, org_id)
    billing_service.grant_credits(
        session,
        org_id=org_id,
        credits=grant_in.credits,
        source=grant_in.source,
        actor_id=current_user.id,
        note=grant_in.note,
    )
    session.commit()
    return billing_service.billing_summary(session, org_id)


@router.post("/orgs/{org_id}/answer-quota", response_model=BillingSummaryPublic)
def grant_org_answer_quota(
    session: SessionDep,
    current_user: PlatformAdmin,
    org_id: uuid.UUID,
    grant_in: AnswerQuotaGrantCreate,
) -> Any:
    _get_org_or_404(session, org_id)
    billing_service.grant_answer_quota(
        session,
        org_id=org_id,
        answers=grant_in.answers,
        source=grant_in.source,
        actor_id=current_user.id,
        note=grant_in.note,
    )
    session.commit()
    return billing_service.billing_summary(session, org_id)


@router.get("/orgs/{org_id}/billing", response_model=BillingSummaryPublic)
def read_org_billing(
    session: SessionDep, _current_user: PlatformReader, org_id: uuid.UUID
) -> Any:
    _get_org_or_404(session, org_id)
    return billing_service.billing_summary(session, org_id)


@router.get("/orgs/{org_id}/billing/ledger", response_model=CreditLedgerPublic)
def read_org_billing_ledger(
    session: SessionDep,
    _current_user: PlatformReader,
    org_id: uuid.UUID,
    offset: int = 0,
    limit: int = 50,
) -> Any:
    _get_org_or_404(session, org_id)
    limit = min(max(limit, 1), 200)
    statement = select(CreditLedgerEntry).where(CreditLedgerEntry.org_id == org_id)
    count = session.exec(
        select(func.count())
        .select_from(CreditLedgerEntry)
        .where(CreditLedgerEntry.org_id == org_id)
    ).one()
    rows = session.exec(
        statement.order_by(col(CreditLedgerEntry.created_at).desc())
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


@router.get("/orgs/{org_id}/usage-policy", response_model=OrganizationUsagePolicyPublic)
def read_org_usage_policy(
    session: SessionDep,
    _current_user: PlatformReader,
    org_id: uuid.UUID,
) -> Any:
    _get_org_or_404(session, org_id)
    policy = session.exec(
        select(OrganizationUsagePolicy).where(OrganizationUsagePolicy.org_id == org_id)
    ).first()
    if not policy:
        policy = OrganizationUsagePolicy(org_id=org_id)
        session.add(policy)
        session.commit()
        session.refresh(policy)
    return _usage_policy_public(policy)


@router.put("/orgs/{org_id}/usage-policy", response_model=OrganizationUsagePolicyPublic)
def update_org_usage_policy(
    session: SessionDep,
    current_user: PlatformAdmin,
    org_id: uuid.UUID,
    policy_in: OrganizationUsagePolicyUpdate,
) -> Any:
    _get_org_or_404(session, org_id)
    policy = session.exec(
        select(OrganizationUsagePolicy)
        .where(OrganizationUsagePolicy.org_id == org_id)
        .with_for_update()
    ).first()
    if not policy:
        policy = OrganizationUsagePolicy(org_id=org_id)
    updates = policy_in.model_dump(
        exclude_unset=True,
        exclude={"max_job_credits", "daily_credit_cap", "monthly_credit_cap"},
    )
    policy.sqlmodel_update(updates)
    if policy_in.max_job_credits is not None:
        policy.max_job_microcredits = billing_service.credits_to_microcredits(
            policy_in.max_job_credits
        )
    if policy_in.daily_credit_cap is not None:
        policy.daily_microcredit_cap = billing_service.credits_to_microcredits(
            policy_in.daily_credit_cap
        )
    if policy_in.monthly_credit_cap is not None:
        policy.monthly_microcredit_cap = billing_service.credits_to_microcredits(
            policy_in.monthly_credit_cap
        )
    if policy.risk_state != OrganizationRiskState.NORMAL and not policy.reason:
        raise HTTPException(status_code=422, detail="限制学校用量时必须填写原因")
    policy.updated_by_id = current_user.id
    policy.updated_at = datetime.now(UTC)
    session.add(policy)
    session.commit()
    session.refresh(policy)
    return _usage_policy_public(policy)
