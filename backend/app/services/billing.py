from __future__ import annotations

import hashlib
import logging
import math
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, func, select

from app.core.config import settings
from app.core.db import engine
from app.models import (
    AnswerQuotaAllocation,
    AnswerQuotaGrant,
    AnswerQuotaReservation,
    BillableAnswerSheet,
    BillingRateVersion,
    BillingSubscriptionPublic,
    BillingSummaryPublic,
    CreditGrant,
    CreditGrantSource,
    CreditLedgerEntry,
    CreditReservation,
    CreditReservationAllocation,
    CreditReservationStatus,
    ModelUsageEvent,
    ModelUsageStatus,
    OfferingRateVersion,
    OrganizationModelSelection,
    OrganizationRiskState,
    OrganizationSubscription,
    OrganizationUsagePolicy,
    PlatformModelOffering,
    ProviderInternalRateVersion,
    SchoolModelScope,
    StudentSubmission,
    SubscriptionStatus,
    get_datetime_utc,
)

MICROCREDITS_PER_CREDIT = 1_000_000
_missing_usage_lock = threading.Lock()
_missing_usage_streaks: dict[tuple[str, str], int] = {}
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelCallContext:
    org_id: uuid.UUID
    workflow_purpose: str
    resource_id: str
    billing_key: str
    exam_id: uuid.UUID | None = None
    grading_run_id: uuid.UUID | None = None
    reservation_id: uuid.UUID | None = None
    org_concurrency_limit: int = 8


def effective_org_concurrency(org_id: uuid.UUID, requested: int) -> int:
    with Session(engine) as session:
        policy = session.exec(
            select(OrganizationUsagePolicy).where(
                OrganizationUsagePolicy.org_id == org_id
            )
        ).first()
        if not policy:
            return max(1, requested)
        if policy.risk_state == OrganizationRiskState.THROTTLED:
            return 1
        return max(1, min(requested, policy.max_model_concurrency))


def effective_org_calls_per_minute(org_id: uuid.UUID) -> int:
    with Session(engine) as session:
        policy = session.exec(
            select(OrganizationUsagePolicy).where(
                OrganizationUsagePolicy.org_id == org_id
            )
        ).first()
        if not policy:
            return 120
        if policy.risk_state == OrganizationRiskState.THROTTLED:
            return min(10, policy.calls_per_minute)
        return max(1, policy.calls_per_minute)


def credits_to_microcredits(credits: float | Decimal) -> int:
    return int(
        (Decimal(str(credits)) * MICROCREDITS_PER_CREDIT).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def microcredits_to_credits(value: int) -> float:
    return float(Decimal(value) / MICROCREDITS_PER_CREDIT)


def _billing_advisory_key(org_id: uuid.UUID) -> int:
    digest = hashlib.sha256(f"dianfan:billing:{org_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF


def _billing_advisory_key_for_reservation(
    session: Session, reservation_id: uuid.UUID
) -> int:
    org_id = session.exec(
        select(CreditReservation.org_id).where(CreditReservation.id == reservation_id)
    ).first()
    # A missing reservation will fail closed later; use a stable key meanwhile.
    return _billing_advisory_key(org_id or uuid.UUID(int=0))


def _succeeded_usage_since(session: Session, org_id: uuid.UUID, since: datetime) -> int:
    return int(
        session.exec(
            select(
                func.coalesce(func.sum(ModelUsageEvent.customer_microcredits), 0)
            ).where(
                ModelUsageEvent.org_id == org_id,
                ModelUsageEvent.status == ModelUsageStatus.SUCCEEDED,
                ModelUsageEvent.created_at >= since,
            )
        ).one()
    )


def _active_subscription(
    session: Session, org_id: uuid.UUID, *, at: datetime | None = None
) -> OrganizationSubscription | None:
    now = at or datetime.now(UTC)
    return session.exec(
        select(OrganizationSubscription)
        .where(
            OrganizationSubscription.org_id == org_id,
            OrganizationSubscription.status == SubscriptionStatus.ACTIVE,
            OrganizationSubscription.starts_at <= now,
            OrganizationSubscription.ends_at > now,
        )
        .order_by(col(OrganizationSubscription.ends_at).desc())
    ).first()


def _latest_subscription(
    session: Session, org_id: uuid.UUID
) -> OrganizationSubscription | None:
    return session.exec(
        select(OrganizationSubscription)
        .where(OrganizationSubscription.org_id == org_id)
        .order_by(col(OrganizationSubscription.ends_at).desc())
    ).first()


def _available_microcredits(session: Session, org_id: uuid.UUID) -> int:
    now = datetime.now(UTC)
    grants = session.exec(
        select(CreditGrant).where(
            CreditGrant.org_id == org_id, CreditGrant.expires_at > now
        )
    ).all()
    return sum(
        max(
            0,
            grant.total_microcredits
            - grant.reserved_microcredits
            - grant.consumed_microcredits,
        )
        for grant in grants
    )


def _available_answers(session: Session, org_id: uuid.UUID) -> int:
    now = datetime.now(UTC)
    grants = session.exec(
        select(AnswerQuotaGrant).where(
            AnswerQuotaGrant.org_id == org_id,
            AnswerQuotaGrant.expires_at > now,
        )
    ).all()
    return sum(
        max(
            0,
            grant.total_answers - grant.reserved_answers - grant.consumed_answers,
        )
        for grant in grants
    )


def submission_billing_identity(submission: StudentSubmission) -> str:
    if submission.student_id:
        return f"student:{submission.student_id}"
    class_name = (submission.class_name or "").strip()
    student_name = (submission.student_name or "").strip()
    if student_name:
        digest = hashlib.sha256(f"{class_name}\x00{student_name}".encode()).hexdigest()[
            :32
        ]
        return f"identity:{digest}"
    return f"submission:{submission.id}"


def entitlement(session: Session, org_id: uuid.UUID) -> str:
    latest = _latest_subscription(session, org_id)
    if latest is None:
        return "not_configured"
    if _active_subscription(session, org_id) is None:
        return "expired"
    return "available" if _available_answers(session, org_id) > 0 else "insufficient"


def require_model_entitlement(session: Session, org_id: uuid.UUID) -> None:
    policy = session.exec(
        select(OrganizationUsagePolicy).where(OrganizationUsagePolicy.org_id == org_id)
    ).first()
    if policy and policy.risk_state in {
        OrganizationRiskState.BLOCKED,
        OrganizationRiskState.FROZEN,
    }:
        detail = (
            "学校模型服务已冻结，请联系点凡阅卷客服"
            if policy.risk_state == OrganizationRiskState.FROZEN
            else "学校新任务已暂停，请联系管理员"
        )
        raise HTTPException(status_code=403, detail=detail)
    if not settings.BILLING_ENFORCEMENT_ENABLED:
        return
    latest = _latest_subscription(session, org_id)
    if latest is not None and _active_subscription(session, org_id) is not None:
        return
    detail = (
        "学校尚未开通点凡阅卷服务"
        if latest is None
        else "学校服务已到期，可查看历史数据；续费后可继续新建任务"
    )
    raise HTTPException(status_code=402, detail=detail)


def grant_answer_quota(
    session: Session,
    *,
    org_id: uuid.UUID,
    answers: int,
    source: CreditGrantSource,
    actor_id: uuid.UUID | None,
    note: str | None,
    order_id: uuid.UUID | None = None,
) -> AnswerQuotaGrant:
    if answers <= 0:
        raise HTTPException(status_code=422, detail="答卷额度必须大于 0")
    subscription = _active_subscription(session, org_id)
    if not subscription:
        raise HTTPException(status_code=409, detail="请先启用学校合同")
    grant = AnswerQuotaGrant(
        org_id=org_id,
        subscription_id=subscription.id,
        order_id=order_id,
        source=source,
        total_answers=answers,
        expires_at=subscription.ends_at,
        note=note,
        created_by_id=actor_id,
    )
    session.add(grant)
    session.flush()
    return grant


def reserve_answer_quota(
    session: Session,
    *,
    org_id: uuid.UUID,
    exam_id: uuid.UUID,
    grading_run_id: uuid.UUID,
    submissions: list[StudentSubmission],
    idempotency_key: str | None = None,
) -> AnswerQuotaReservation | None:
    idempotency_key = idempotency_key or (
        f"{org_id}:grading-run:{grading_run_id}:answers:v1"
    )
    existing = session.exec(
        select(AnswerQuotaReservation).where(
            AnswerQuotaReservation.idempotency_key == idempotency_key
        )
    ).first()
    if existing:
        return existing
    if not settings.BILLING_ENFORCEMENT_ENABLED:
        return None
    require_model_entitlement(session, org_id)
    session.exec(
        text("SELECT pg_advisory_xact_lock(:key)").bindparams(
            key=_billing_advisory_key(org_id)
        )
    )
    identities = sorted({submission_billing_identity(item) for item in submissions})
    already_billed = set(
        session.exec(
            select(BillableAnswerSheet.billing_identity).where(
                BillableAnswerSheet.org_id == org_id,
                BillableAnswerSheet.exam_id == exam_id,
                col(BillableAnswerSheet.billing_identity).in_(identities),
            )
        ).all()
    )
    active_reserved: set[str] = set()
    for reserved in session.exec(
        select(AnswerQuotaReservation.identities).where(
            AnswerQuotaReservation.org_id == org_id,
            AnswerQuotaReservation.exam_id == exam_id,
            AnswerQuotaReservation.status == CreditReservationStatus.ACTIVE,
        )
    ).all():
        active_reserved.update(reserved or [])
    overlap = set(identities) & active_reserved
    if overlap:
        raise HTTPException(
            status_code=409,
            detail="这些答卷已有批改批次正在处理，请等待完成后再试",
        )
    chargeable = [
        identity
        for identity in identities
        if identity not in already_billed and identity not in active_reserved
    ]
    required = len(chargeable)
    reservation = AnswerQuotaReservation(
        org_id=org_id,
        exam_id=exam_id,
        grading_run_id=grading_run_id,
        idempotency_key=idempotency_key,
        reserved_answers=required,
        status=CreditReservationStatus.ACTIVE,
        identities=chargeable,
    )
    session.add(reservation)
    session.flush()
    if required == 0:
        return reservation
    now = datetime.now(UTC)
    grants = list(
        session.exec(
            select(AnswerQuotaGrant)
            .where(
                AnswerQuotaGrant.org_id == org_id,
                AnswerQuotaGrant.expires_at > now,
            )
            .order_by(AnswerQuotaGrant.expires_at, AnswerQuotaGrant.created_at)
            .with_for_update()
        ).all()
    )
    available = sum(
        max(0, row.total_answers - row.reserved_answers - row.consumed_answers)
        for row in grants
    )
    if available < required:
        session.delete(reservation)
        session.flush()
        return None
    remaining = required
    for grant in grants:
        free = max(
            0, grant.total_answers - grant.reserved_answers - grant.consumed_answers
        )
        amount = min(free, remaining)
        if not amount:
            continue
        grant.reserved_answers += amount
        session.add(grant)
        session.add(
            AnswerQuotaAllocation(
                reservation_id=reservation.id,
                grant_id=grant.id,
                reserved_answers=amount,
            )
        )
        remaining -= amount
        if remaining == 0:
            break
    return reservation


def settle_answer_quota(
    session: Session,
    *,
    reservation_id: uuid.UUID,
    completed_submissions: list[StudentSubmission],
) -> int:
    reservation = session.exec(
        select(AnswerQuotaReservation)
        .where(AnswerQuotaReservation.id == reservation_id)
        .with_for_update()
    ).first()
    if not reservation or reservation.status != CreditReservationStatus.ACTIVE:
        return reservation.settled_answers if reservation else 0
    completed_by_identity = {
        submission_billing_identity(item): item for item in completed_submissions
    }
    chargeable = [
        identity
        for identity in reservation.identities
        if identity in completed_by_identity
    ]
    existing = set(
        session.exec(
            select(BillableAnswerSheet.billing_identity).where(
                BillableAnswerSheet.org_id == reservation.org_id,
                BillableAnswerSheet.exam_id == reservation.exam_id,
                col(BillableAnswerSheet.billing_identity).in_(chargeable),
            )
        ).all()
    )
    chargeable = [identity for identity in chargeable if identity not in existing]
    charged = len(chargeable)
    remaining = charged
    allocations = list(
        session.exec(
            select(AnswerQuotaAllocation)
            .where(AnswerQuotaAllocation.reservation_id == reservation.id)
            .with_for_update()
        ).all()
    )
    for allocation in allocations:
        grant = session.get(AnswerQuotaGrant, allocation.grant_id)
        if not grant:
            continue
        consumed = min(allocation.reserved_answers, remaining)
        allocation.consumed_answers = consumed
        grant.reserved_answers -= allocation.reserved_answers
        grant.consumed_answers += consumed
        session.add_all([allocation, grant])
        remaining -= consumed
    for identity in chargeable:
        submission = completed_by_identity[identity]
        session.add(
            BillableAnswerSheet(
                org_id=reservation.org_id,
                exam_id=reservation.exam_id,
                grading_run_id=reservation.grading_run_id,
                reservation_id=reservation.id,
                billing_identity=identity,
                student_name=submission.student_name,
                class_name=submission.class_name,
            )
        )
    reservation.settled_answers = charged
    reservation.status = CreditReservationStatus.SETTLED
    reservation.settled_at = get_datetime_utc()
    session.add(reservation)
    return charged


def release_answer_quota(session: Session, reservation_id: uuid.UUID) -> int:
    reservation = session.exec(
        select(AnswerQuotaReservation)
        .where(AnswerQuotaReservation.id == reservation_id)
        .with_for_update()
    ).first()
    if not reservation or reservation.status != CreditReservationStatus.ACTIVE:
        return 0
    released = 0
    for allocation in session.exec(
        select(AnswerQuotaAllocation)
        .where(AnswerQuotaAllocation.reservation_id == reservation.id)
        .with_for_update()
    ).all():
        grant = session.get(AnswerQuotaGrant, allocation.grant_id)
        if grant:
            grant.reserved_answers -= allocation.reserved_answers
            released += allocation.reserved_answers
            session.add(grant)
    reservation.status = CreditReservationStatus.RELEASED
    reservation.settled_at = get_datetime_utc()
    session.add(reservation)
    return released


def current_rate(
    session: Session, org_id: uuid.UUID | None = None
) -> BillingRateVersion | None:
    subscription = _active_subscription(session, org_id) if org_id else None
    if subscription:
        return session.get(BillingRateVersion, subscription.rate_version_id)
    return session.exec(
        select(BillingRateVersion)
        .where(BillingRateVersion.effective_at <= datetime.now(UTC))
        .order_by(col(BillingRateVersion.effective_at).desc())
    ).first()


_PURPOSE_SCOPES: dict[str, SchoolModelScope] = {
    "region_detection": SchoolModelScope.VISION,
    "answer_recognition": SchoolModelScope.VISION,
    "answer_extraction": SchoolModelScope.VISION,
    "question_recognition": SchoolModelScope.REFERENCE_ANSWER,
    "score_structure_recognition": SchoolModelScope.REFERENCE_ANSWER,
    "answer_preparation": SchoolModelScope.REFERENCE_ANSWER,
    "answer_document_parsing": SchoolModelScope.REFERENCE_ANSWER,
    "rubric_question_recognition": SchoolModelScope.REFERENCE_ANSWER,
    "rubric_generation": SchoolModelScope.REFERENCE_ANSWER,
    "rubric_validation": SchoolModelScope.REFERENCE_ANSWER,
    "subjective_grading": SchoolModelScope.GRADING,
    "grading": SchoolModelScope.GRADING,
}


def current_charge_rate(
    session: Session, *, org_id: uuid.UUID, workflow_purpose: str
) -> BillingRateVersion | OfferingRateVersion | None:
    scope = _PURPOSE_SCOPES.get(workflow_purpose)
    if scope:
        selected = session.exec(
            select(OrganizationModelSelection, PlatformModelOffering)
            .join(
                PlatformModelOffering,
                OrganizationModelSelection.offering_id == PlatformModelOffering.id,
            )
            .where(
                OrganizationModelSelection.org_id == org_id,
                OrganizationModelSelection.scope == scope,
                PlatformModelOffering.published.is_(True),
            )
        ).first()
        if selected:
            _selection, offering = selected
            rate = session.exec(
                select(OfferingRateVersion)
                .where(
                    OfferingRateVersion.offering_id == offering.id,
                    OfferingRateVersion.effective_at <= datetime.now(UTC),
                )
                .order_by(col(OfferingRateVersion.effective_at).desc())
            ).first()
            if rate:
                return rate
    return current_rate(session, org_id)


def calculate_microcredits(
    rate: BillingRateVersion | OfferingRateVersion,
    *,
    input_tokens: int,
    output_tokens: int,
    image_tokens: int,
) -> tuple[int, int]:
    divisor = 1_000_000
    customer = math.ceil(
        (
            input_tokens * rate.input_microcredits_per_million
            + output_tokens * rate.output_microcredits_per_million
            + image_tokens * rate.image_microcredits_per_million
        )
        / divisor
    )
    internal = 0
    if isinstance(rate, BillingRateVersion):
        internal = math.ceil(
            (
                input_tokens * rate.internal_input_micrormb_per_million
                + output_tokens * rate.internal_output_micrormb_per_million
                + image_tokens * rate.internal_image_micrormb_per_million
            )
            / divisor
        )
    return customer, internal


def quote_microcredits(
    session: Session,
    *,
    org_id: uuid.UUID,
    workflow_purpose: str,
    expected_calls: int,
) -> int:
    since = datetime.now(UTC) - timedelta(days=30)
    samples = list(
        session.exec(
            select(ModelUsageEvent.customer_microcredits).where(
                ModelUsageEvent.org_id == org_id,
                ModelUsageEvent.workflow_purpose == workflow_purpose,
                ModelUsageEvent.status == ModelUsageStatus.SUCCEEDED,
                ModelUsageEvent.customer_microcredits > 0,
                ModelUsageEvent.created_at >= since,
            )
        ).all()
    )
    samples = [sample for sample in samples if sample > 0]
    if samples:
        samples.sort()
        p95 = samples[min(len(samples) - 1, math.ceil(len(samples) * 0.95) - 1)]
    else:
        rate = current_charge_rate(
            session, org_id=org_id, workflow_purpose=workflow_purpose
        )
        if not rate:
            return 0
        # Cold-start quote: one image request with 4k input and 1k output tokens.
        p95, _ = calculate_microcredits(
            rate, input_tokens=4000, output_tokens=1000, image_tokens=1000
        )
    return math.ceil(max(1, expected_calls) * p95 * 1.2)


def reserve_credits(
    session: Session,
    *,
    org_id: uuid.UUID,
    task_type: str,
    resource_id: str,
    idempotency_key: str,
    estimated_microcredits: int,
    grading_run_id: uuid.UUID | None = None,
) -> CreditReservation | None:
    existing = session.exec(
        select(CreditReservation).where(
            CreditReservation.idempotency_key == idempotency_key
        )
    ).first()
    if existing:
        return existing
    if not settings.TOKEN_BUDGET_ENFORCEMENT_ENABLED:
        return None
    require_model_entitlement(session, org_id)
    # Serialize every balance/cap decision for one school. Locking only grants is
    # insufficient when a school has no grant yet or two tasks inspect caps first.
    session.exec(
        text("SELECT pg_advisory_xact_lock(:key)").bindparams(
            key=_billing_advisory_key(org_id)
        )
    )
    policy = session.exec(
        select(OrganizationUsagePolicy).where(OrganizationUsagePolicy.org_id == org_id)
    ).first()
    if policy:
        if estimated_microcredits > policy.max_job_microcredits:
            raise HTTPException(
                status_code=429, detail="本次任务预计用量超过学校单任务上限"
            )
        now = datetime.now(UTC)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = day_start.replace(day=1)
        day_usage = int(
            session.exec(
                select(
                    func.coalesce(func.sum(ModelUsageEvent.customer_microcredits), 0)
                ).where(
                    ModelUsageEvent.org_id == org_id,
                    ModelUsageEvent.status == ModelUsageStatus.SUCCEEDED,
                    ModelUsageEvent.created_at >= day_start,
                )
            ).one()
        )
        month_usage = int(
            session.exec(
                select(
                    func.coalesce(func.sum(ModelUsageEvent.customer_microcredits), 0)
                ).where(
                    ModelUsageEvent.org_id == org_id,
                    ModelUsageEvent.status == ModelUsageStatus.SUCCEEDED,
                    ModelUsageEvent.created_at >= month_start,
                )
            ).one()
        )
        active_reservations = int(
            session.exec(
                select(
                    func.coalesce(func.sum(CreditReservation.estimated_microcredits), 0)
                ).where(
                    CreditReservation.org_id == org_id,
                    CreditReservation.status == CreditReservationStatus.ACTIVE,
                )
            ).one()
        )
        if (
            day_usage + active_reservations + estimated_microcredits
            > policy.daily_microcredit_cap
        ):
            raise HTTPException(status_code=429, detail="学校今日处理额度已达上限")
        if (
            month_usage + active_reservations + estimated_microcredits
            > policy.monthly_microcredit_cap
        ):
            raise HTTPException(status_code=429, detail="学校本月处理额度已达上限")
    now = datetime.now(UTC)
    grants = list(
        session.exec(
            select(CreditGrant)
            .where(CreditGrant.org_id == org_id, CreditGrant.expires_at > now)
            .order_by(CreditGrant.expires_at, CreditGrant.created_at)
            .with_for_update()
        ).all()
    )
    reservation = CreditReservation(
        org_id=org_id,
        grading_run_id=grading_run_id,
        task_type=task_type,
        resource_id=resource_id,
        idempotency_key=idempotency_key,
        estimated_microcredits=estimated_microcredits,
        status=CreditReservationStatus.ACTIVE,
    )
    session.add(reservation)
    session.flush()
    # This ledger protects the platform's upstream spend; it is not a second
    # customer wallet. Legacy internal grants are allocated when present, but
    # a school that bought answer-sheet quota must not be blocked because its
    # internal Token grant balance is zero.
    remaining = estimated_microcredits
    for grant in grants:
        free = max(
            0,
            grant.total_microcredits
            - grant.reserved_microcredits
            - grant.consumed_microcredits,
        )
        amount = min(free, remaining)
        if not amount:
            continue
        grant.reserved_microcredits += amount
        session.add(grant)
        session.add(
            CreditReservationAllocation(
                reservation_id=reservation.id,
                grant_id=grant.id,
                reserved_microcredits=amount,
            )
        )
        remaining -= amount
        if remaining == 0:
            break
    _ledger(
        session,
        org_id,
        "reserve",
        -estimated_microcredits,
        reservation_id=reservation.id,
    )
    return reservation


def extend_reservation(
    session: Session,
    *,
    reservation_id: uuid.UUID,
    additional_microcredits: int,
) -> bool:
    """Atomically extend an active reservation before another upstream call."""
    if additional_microcredits <= 0 or not settings.TOKEN_BUDGET_ENFORCEMENT_ENABLED:
        return True
    session.exec(
        text("SELECT pg_advisory_xact_lock(:key)").bindparams(
            key=_billing_advisory_key_for_reservation(session, reservation_id)
        )
    )
    reservation = session.exec(
        select(CreditReservation)
        .where(CreditReservation.id == reservation_id)
        .with_for_update()
    ).first()
    if not reservation or reservation.status != CreditReservationStatus.ACTIVE:
        return False
    policy = session.exec(
        select(OrganizationUsagePolicy).where(
            OrganizationUsagePolicy.org_id == reservation.org_id
        )
    ).first()
    if policy:
        if policy.risk_state in {
            OrganizationRiskState.BLOCKED,
            OrganizationRiskState.FROZEN,
        }:
            return False
        if (
            reservation.estimated_microcredits + additional_microcredits
            > policy.max_job_microcredits
        ):
            return False
        now = datetime.now(UTC)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = day_start.replace(day=1)
        day_usage = _succeeded_usage_since(session, reservation.org_id, day_start)
        month_usage = _succeeded_usage_since(session, reservation.org_id, month_start)
        active_reservations = int(
            session.exec(
                select(
                    func.coalesce(func.sum(CreditReservation.estimated_microcredits), 0)
                ).where(
                    CreditReservation.org_id == reservation.org_id,
                    CreditReservation.status == CreditReservationStatus.ACTIVE,
                )
            ).one()
        )
        if (
            day_usage + active_reservations + additional_microcredits
            > policy.daily_microcredit_cap
        ):
            return False
        if (
            month_usage + active_reservations + additional_microcredits
            > policy.monthly_microcredit_cap
        ):
            return False
    now = datetime.now(UTC)
    grants = list(
        session.exec(
            select(CreditGrant)
            .where(
                CreditGrant.org_id == reservation.org_id,
                CreditGrant.expires_at > now,
            )
            .order_by(CreditGrant.expires_at, CreditGrant.created_at)
            .with_for_update()
        ).all()
    )
    remaining = additional_microcredits
    allocations = {
        row.grant_id: row
        for row in session.exec(
            select(CreditReservationAllocation)
            .where(CreditReservationAllocation.reservation_id == reservation.id)
            .with_for_update()
        ).all()
    }
    for grant in grants:
        free = max(
            0,
            grant.total_microcredits
            - grant.reserved_microcredits
            - grant.consumed_microcredits,
        )
        amount = min(free, remaining)
        if not amount:
            continue
        grant.reserved_microcredits += amount
        allocation = allocations.get(grant.id)
        if allocation:
            allocation.reserved_microcredits += amount
        else:
            allocation = CreditReservationAllocation(
                reservation_id=reservation.id,
                grant_id=grant.id,
                reserved_microcredits=amount,
            )
        session.add(grant)
        session.add(allocation)
        remaining -= amount
        if remaining == 0:
            break
    reservation.estimated_microcredits += additional_microcredits
    session.add(reservation)
    _ledger(
        session,
        reservation.org_id,
        "reserve",
        -additional_microcredits,
        reservation_id=reservation.id,
        note="模型调用前追加预留",
    )
    return True


def authorize_next_model_call(context: ModelCallContext) -> None:
    """Reserve one P95 call before it can consume upstream capacity."""
    if not settings.TOKEN_BUDGET_ENFORCEMENT_ENABLED:
        return
    if not context.reservation_id:
        raise HTTPException(status_code=402, detail="当前任务缺少有效积分预留")
    with Session(engine) as session:
        require_model_entitlement(session, context.org_id)
        next_call_quote = quote_microcredits(
            session,
            org_id=context.org_id,
            workflow_purpose=context.workflow_purpose,
            expected_calls=1,
        )
        reservation = session.exec(
            select(CreditReservation)
            .where(CreditReservation.id == context.reservation_id)
            .with_for_update()
        ).first()
        if not reservation or reservation.status != CreditReservationStatus.ACTIVE:
            raise HTTPException(status_code=402, detail="当前任务的积分预留已失效")
        increment = max(
            0,
            reservation.authorized_microcredits
            + next_call_quote
            - reservation.estimated_microcredits,
        )
        if not extend_reservation(
            session,
            reservation_id=context.reservation_id,
            additional_microcredits=increment,
        ):
            session.rollback()
            raise HTTPException(
                status_code=402,
                detail="积分不足，剩余处理已暂停；充值后可继续",
            )
        reservation.authorized_microcredits += next_call_quote
        session.add(reservation)
        session.commit()


def reserve_task_or_raise(
    session: Session,
    *,
    org_id: uuid.UUID,
    task_type: str,
    resource_id: str,
    idempotency_key: str,
    expected_calls: int,
    grading_run_id: uuid.UUID | None = None,
) -> CreditReservation | None:
    estimate = quote_microcredits(
        session,
        org_id=org_id,
        workflow_purpose=task_type,
        expected_calls=expected_calls,
    )
    reservation = reserve_credits(
        session,
        org_id=org_id,
        task_type=task_type,
        resource_id=resource_id,
        idempotency_key=idempotency_key,
        estimated_microcredits=estimate,
        grading_run_id=grading_run_id,
    )
    if settings.TOKEN_BUDGET_ENFORCEMENT_ENABLED and reservation is None:
        raise HTTPException(
            status_code=402,
            detail="学校可用积分不足，充值后可继续创建任务",
        )
    return reservation


def settle_reservation(session: Session, reservation_id: uuid.UUID) -> int:
    reservation = session.exec(
        select(CreditReservation)
        .where(CreditReservation.id == reservation_id)
        .with_for_update()
    ).first()
    if not reservation or reservation.status != CreditReservationStatus.ACTIVE:
        return reservation.settled_microcredits if reservation else 0
    actual = session.exec(
        select(func.coalesce(func.sum(ModelUsageEvent.customer_microcredits), 0)).where(
            ModelUsageEvent.reservation_id == reservation.id,
            ModelUsageEvent.status == ModelUsageStatus.SUCCEEDED,
        )
    ).one()
    charged = int(actual)
    if charged > reservation.estimated_microcredits:
        if not extend_reservation(
            session,
            reservation_id=reservation.id,
            additional_microcredits=charged - reservation.estimated_microcredits,
        ):
            raise RuntimeError("积分预留不足：上游调用前授权未覆盖实际用量")
        session.flush()
        session.refresh(reservation)
    remaining = charged
    allocations = list(
        session.exec(
            select(CreditReservationAllocation)
            .where(CreditReservationAllocation.reservation_id == reservation.id)
            .with_for_update()
        ).all()
    )
    for allocation in allocations:
        grant = session.get(CreditGrant, allocation.grant_id)
        if not grant:
            continue
        consumed = min(allocation.reserved_microcredits, remaining)
        allocation.consumed_microcredits = consumed
        grant.reserved_microcredits -= allocation.reserved_microcredits
        grant.consumed_microcredits += consumed
        session.add(allocation)
        session.add(grant)
        remaining -= consumed
    released = reservation.estimated_microcredits - charged
    reservation.settled_microcredits = charged
    reservation.status = CreditReservationStatus.SETTLED
    reservation.settled_at = get_datetime_utc()
    session.add(reservation)
    if charged:
        _ledger(
            session,
            reservation.org_id,
            "consume",
            -charged,
            reservation_id=reservation.id,
        )
    if released:
        _ledger(
            session,
            reservation.org_id,
            "release",
            released,
            reservation_id=reservation.id,
        )
    return charged


def release_reservation(
    session: Session, reservation_id: uuid.UUID, *, note: str
) -> int:
    reservation = session.exec(
        select(CreditReservation)
        .where(CreditReservation.id == reservation_id)
        .with_for_update()
    ).first()
    if not reservation or reservation.status != CreditReservationStatus.ACTIVE:
        return 0
    allocations = session.exec(
        select(CreditReservationAllocation)
        .where(CreditReservationAllocation.reservation_id == reservation.id)
        .with_for_update()
    ).all()
    released = 0
    for allocation in allocations:
        grant = session.get(CreditGrant, allocation.grant_id)
        if grant:
            grant.reserved_microcredits -= allocation.reserved_microcredits
            released += allocation.reserved_microcredits
            session.add(grant)
    reservation.status = CreditReservationStatus.RELEASED
    reservation.settled_at = get_datetime_utc()
    session.add(reservation)
    if released:
        _ledger(
            session,
            reservation.org_id,
            "release",
            released,
            reservation_id=reservation.id,
            note=note,
        )
    return released


def reconcile_stale_reservations(
    session: Session, *, older_than_hours: int = 24
) -> int:
    cutoff = datetime.now(UTC) - timedelta(hours=max(1, older_than_hours))
    stale_credits = list(
        session.exec(
            select(CreditReservation).where(
                CreditReservation.status == CreditReservationStatus.ACTIVE,
                CreditReservation.created_at < cutoff,
            )
        ).all()
    )
    for reservation in stale_credits:
        release_reservation(
            session,
            reservation.id,
            note="超时任务自动释放内部成本预留",
        )
    stale_answers = list(
        session.exec(
            select(AnswerQuotaReservation).where(
                AnswerQuotaReservation.status == CreditReservationStatus.ACTIVE,
                AnswerQuotaReservation.created_at < cutoff,
            )
        ).all()
    )
    for reservation in stale_answers:
        release_answer_quota(session, reservation.id)
    return len(stale_credits) + len(stale_answers)


def _ledger(
    session: Session,
    org_id: uuid.UUID,
    entry_type: str,
    amount: int,
    *,
    grant_id: uuid.UUID | None = None,
    reservation_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    note: str | None = None,
) -> CreditLedgerEntry:
    row = CreditLedgerEntry(
        org_id=org_id,
        grant_id=grant_id,
        reservation_id=reservation_id,
        entry_type=entry_type,
        amount_microcredits=amount,
        balance_after_microcredits=_available_microcredits(session, org_id),
        actor_id=actor_id,
        note=note,
    )
    session.add(row)
    return row


def grant_credits(
    session: Session,
    *,
    org_id: uuid.UUID,
    credits: float,
    source: CreditGrantSource,
    actor_id: uuid.UUID | None,
    note: str | None,
) -> CreditGrant:
    subscription = _active_subscription(session, org_id)
    if not subscription:
        raise HTTPException(status_code=409, detail="请先启用有效合同，再发放积分")
    amount = credits_to_microcredits(credits)
    grant = CreditGrant(
        org_id=org_id,
        subscription_id=subscription.id,
        source=source,
        total_microcredits=amount,
        expires_at=subscription.ends_at,
        created_by_id=actor_id,
        note=note,
    )
    session.add(grant)
    session.flush()
    _ledger(
        session,
        org_id,
        "grant",
        amount,
        grant_id=grant.id,
        actor_id=actor_id,
        note=note,
    )
    return grant


def normalize_usage(usage: dict[str, Any]) -> tuple[int, int, int, int]:
    input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    output_tokens = int(
        usage.get("completion_tokens") or usage.get("output_tokens") or 0
    )
    details = (
        usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    )
    image_tokens = int(
        usage.get("image_tokens")
        or (details.get("image_tokens") if isinstance(details, dict) else 0)
        or 0
    )
    total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens)
    return input_tokens, output_tokens, image_tokens, total_tokens


def _usage_detail_tokens(usage: dict[str, Any]) -> tuple[int, int]:
    input_details = (
        usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    )
    output_details = (
        usage.get("completion_tokens_details")
        or usage.get("output_tokens_details")
        or {}
    )
    cached = int(
        usage.get("cached_input_tokens")
        or (
            input_details.get("cached_tokens") if isinstance(input_details, dict) else 0
        )
        or 0
    )
    reasoning = int(
        usage.get("reasoning_tokens")
        or (
            output_details.get("reasoning_tokens")
            if isinstance(output_details, dict)
            else 0
        )
        or 0
    )
    return max(0, cached), max(0, reasoning)


def _internal_rate(
    session: Session,
    *,
    channel_id: uuid.UUID | None,
    canonical_model: str,
) -> ProviderInternalRateVersion | None:
    if channel_id is None:
        return None
    return session.exec(
        select(ProviderInternalRateVersion)
        .where(
            ProviderInternalRateVersion.channel_id == channel_id,
            ProviderInternalRateVersion.canonical_model == canonical_model,
            ProviderInternalRateVersion.effective_at <= datetime.now(UTC),
        )
        .order_by(col(ProviderInternalRateVersion.effective_at).desc())
    ).first()


def _calculate_internal_cost(
    rate: ProviderInternalRateVersion,
    *,
    input_tokens: int,
    output_tokens: int,
    image_tokens: int,
    cached_input_tokens: int,
) -> int:
    billable_input = max(0, input_tokens - cached_input_tokens)
    return math.ceil(
        (
            billable_input * rate.input_micrormb_per_million
            + cached_input_tokens * rate.cached_input_micrormb_per_million
            + output_tokens * rate.output_micrormb_per_million
            + image_tokens * rate.image_micrormb_per_million
        )
        / 1_000_000
    )


def record_model_attempt(
    context: ModelCallContext,
    *,
    requested_provider: str,
    requested_model: str,
    actual_provider: str | None,
    actual_model: str | None,
    usage: dict[str, Any] | None,
    latency_ms: int,
    attempt: int,
    error_code: str | None = None,
    channel_id: uuid.UUID | None = None,
    route_policy_id: uuid.UUID | None = None,
    route_version_id: uuid.UUID | None = None,
    upstream_request_id: str | None = None,
    http_status: int | None = None,
) -> ModelUsageEvent | None:
    status = (
        ModelUsageStatus.SUCCEEDED
        if usage
        else ModelUsageStatus.FAILED
        if error_code
        else ModelUsageStatus.MISSING_USAGE
    )
    input_tokens, output_tokens, image_tokens, total_tokens = normalize_usage(
        usage or {}
    )
    cached_input_tokens, reasoning_tokens = _usage_detail_tokens(usage or {})
    route = (actual_provider or requested_provider, actual_model or requested_model)
    with _missing_usage_lock:
        if status == ModelUsageStatus.MISSING_USAGE:
            _missing_usage_streaks[route] = _missing_usage_streaks.get(route, 0) + 1
            logger.warning(
                "Model route returned no usage; call is unbillable",
                extra={"provider": route[0], "model": route[1]},
            )
        elif status == ModelUsageStatus.SUCCEEDED:
            _missing_usage_streaks[route] = 0
    with Session(engine) as session:
        rate = current_charge_rate(
            session,
            org_id=context.org_id,
            workflow_purpose=context.workflow_purpose,
        )
        internal_rate = _internal_rate(
            session,
            channel_id=channel_id,
            canonical_model=actual_model or requested_model,
        )
        customer = internal = 0
        if status == ModelUsageStatus.SUCCEEDED and rate:
            customer, internal = calculate_microcredits(
                rate,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                image_tokens=image_tokens,
            )
        if status == ModelUsageStatus.SUCCEEDED and internal_rate:
            internal = _calculate_internal_cost(
                internal_rate,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                image_tokens=image_tokens,
                cached_input_tokens=cached_input_tokens,
            )
        # Tenant identity is part of the idempotency key. Without it, two
        # schools using the same business key could suppress each other's
        # usage record and corrupt margin/accounting reports.
        raw_billing_key = (
            f"{context.org_id}:{context.billing_key}:{attempt}:"
            f"{route[0]}:{route[1]}:{channel_id or 'env'}"
        )
        event = ModelUsageEvent(
            org_id=context.org_id,
            exam_id=context.exam_id,
            grading_run_id=context.grading_run_id,
            reservation_id=context.reservation_id,
            resource_id=context.resource_id,
            workflow_purpose=context.workflow_purpose,
            requested_provider=requested_provider,
            requested_model=requested_model,
            actual_provider=actual_provider,
            actual_model=actual_model,
            channel_id=channel_id,
            route_policy_id=route_policy_id,
            route_version_id=route_version_id,
            attempt_number=attempt,
            attempt_kind="primary" if attempt == 1 else "fallback",
            upstream_request_id=upstream_request_id,
            http_status=http_status,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            image_tokens=image_tokens,
            cached_input_tokens=cached_input_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=total_tokens,
            latency_ms=max(0, latency_ms),
            status=status,
            fallback_used=bool(
                actual_provider and actual_provider != requested_provider
            ),
            error_code=error_code,
            customer_microcredits=customer,
            internal_cost_micrormb=internal,
            billing_key=(
                "model-call:"
                + hashlib.sha256(raw_billing_key.encode("utf-8")).hexdigest()
            ),
            rate_version_id=(rate.id if isinstance(rate, BillingRateVersion) else None),
            internal_rate_version_id=internal_rate.id if internal_rate else None,
            offering_rate_version_id=(
                rate.id if isinstance(rate, OfferingRateVersion) else None
            ),
        )
        try:
            session.add(event)
            session.commit()
            session.refresh(event)
            return event
        except IntegrityError:
            session.rollback()
            return None


def route_has_usage(session: Session, provider: str, model: str) -> bool:
    with _missing_usage_lock:
        if _missing_usage_streaks.get((provider, model), 0) >= 1:
            return False
    recent = list(
        session.exec(
            select(ModelUsageEvent.status)
            .where(
                ModelUsageEvent.actual_provider == provider,
                ModelUsageEvent.actual_model == model,
            )
            .order_by(col(ModelUsageEvent.created_at).desc())
            .limit(1)
        ).all()
    )
    return not (
        len(recent) == 1
        and all(item == ModelUsageStatus.MISSING_USAGE for item in recent)
    )


def route_accepts_billing(provider: str, model: str) -> bool:
    with Session(engine) as session:
        return route_has_usage(session, provider, model)


def billing_summary(session: Session, org_id: uuid.UUID) -> BillingSummaryPublic:
    subscription = _latest_subscription(session, org_id)
    grants = list(
        session.exec(select(CreditGrant).where(CreditGrant.org_id == org_id)).all()
    )
    usage = session.exec(
        select(
            func.coalesce(func.sum(ModelUsageEvent.input_tokens), 0),
            func.coalesce(func.sum(ModelUsageEvent.output_tokens), 0),
            func.coalesce(func.sum(ModelUsageEvent.image_tokens), 0),
            func.coalesce(func.sum(ModelUsageEvent.total_tokens), 0),
        ).where(ModelUsageEvent.org_id == org_id)
    ).one()
    answer_grants = list(
        session.exec(
            select(AnswerQuotaGrant).where(AnswerQuotaGrant.org_id == org_id)
        ).all()
    )
    return BillingSummaryPublic(
        entitlement=entitlement(session, org_id),
        subscription=(
            BillingSubscriptionPublic.model_validate(subscription)
            if subscription
            else None
        ),
        available_credits=microcredits_to_credits(
            _available_microcredits(session, org_id)
        ),
        reserved_credits=microcredits_to_credits(
            sum(row.reserved_microcredits for row in grants)
        ),
        consumed_credits=microcredits_to_credits(
            sum(row.consumed_microcredits for row in grants)
        ),
        input_tokens=int(usage[0]),
        output_tokens=int(usage[1]),
        image_tokens=int(usage[2]),
        total_tokens=int(usage[3]),
        available_answers=_available_answers(session, org_id),
        reserved_answers=sum(row.reserved_answers for row in answer_grants),
        consumed_answers=sum(row.consumed_answers for row in answer_grants),
    )
