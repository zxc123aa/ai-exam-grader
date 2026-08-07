import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    AnswerQuotaGrant,
    AnswerQuotaReservation,
    BillableAnswerSheet,
    BillingRateVersion,
    CreditGrant,
    CreditGrantSource,
    CreditReservationAllocation,
    Exam,
    GradingRun,
    ModelUsageEvent,
    ModelUsageStatus,
    Organization,
    OrganizationSubscription,
    ProviderChannel,
    ProviderChannelKind,
    ProviderInternalRateVersion,
    ProviderProtocol,
    StoredFile,
    StudentSubmission,
    SubscriptionStatus,
    User,
    UserRole,
)
from app.services.billing import (
    ModelCallContext,
    calculate_microcredits,
    credits_to_microcredits,
    grant_answer_quota,
    grant_credits,
    microcredits_to_credits,
    quote_microcredits,
    reconcile_stale_reservations,
    record_model_attempt,
    release_answer_quota,
    reserve_answer_quota,
    reserve_credits,
    settle_answer_quota,
    settle_reservation,
)


def _contract(session: Session) -> tuple[Organization, BillingRateVersion]:
    org = Organization(name="计费测试学校", code=f"billing-{uuid.uuid4().hex[:10]}")
    rate = BillingRateVersion(
        version=f"test-{uuid.uuid4().hex[:10]}",
        effective_at=datetime.now(UTC) - timedelta(days=1),
        input_microcredits_per_million=credits_to_microcredits(10),
        output_microcredits_per_million=credits_to_microcredits(20),
        image_microcredits_per_million=credits_to_microcredits(30),
    )
    session.add(org)
    session.add(rate)
    session.flush()
    session.add(
        OrganizationSubscription(
            org_id=org.id,
            contract_no=f"C-{uuid.uuid4().hex[:12]}",
            plan_code="school-standard",
            status=SubscriptionStatus.ACTIVE,
            starts_at=datetime.now(UTC) - timedelta(days=1),
            ends_at=datetime.now(UTC) + timedelta(days=365),
            rate_version_id=rate.id,
        )
    )
    session.commit()
    return org, rate


def test_credit_conversion_and_actual_token_rate(db: Session) -> None:
    org, rate = _contract(db)
    customer, internal = calculate_microcredits(
        rate, input_tokens=100_000, output_tokens=50_000, image_tokens=25_000
    )
    assert microcredits_to_credits(customer) == 2.75
    assert internal == 0
    assert org.id is not None


def _answer_submission(
    db: Session,
    *,
    exam: Exam,
    uploader_id: uuid.UUID,
    student_name: str,
) -> StudentSubmission:
    stored = StoredFile(
        original_filename=f"{student_name}.pdf",
        content_type="application/pdf",
        storage_key=f"test/{uuid.uuid4().hex}",
        size_bytes=10,
        sha256=uuid.uuid4().hex * 2,
        uploaded_by_id=uploader_id,
    )
    db.add(stored)
    db.flush()
    submission = StudentSubmission(
        exam_id=exam.id,
        stored_file_id=stored.id,
        student_name=student_name,
        class_name="001班",
    )
    db.add(submission)
    db.flush()
    return submission


def test_answer_quota_is_exactly_once_and_failed_answers_are_released(
    db: Session, monkeypatch
) -> None:
    org, _rate = _contract(db)
    owner = db.exec(select(User).where(User.org_id == org.id)).first()
    if owner is None:
        owner = User(
            email=f"quota-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="test",
            role=UserRole.SCHOOL_OWNER,
            org_id=org.id,
        )
        db.add(owner)
        db.flush()
    monkeypatch.setattr(settings, "BILLING_ENFORCEMENT_ENABLED", True)
    grant = grant_answer_quota(
        db,
        org_id=org.id,
        answers=3,
        source=CreditGrantSource.SUBSCRIPTION,
        actor_id=owner.id,
        note="合同额度",
    )
    exam = Exam(title="额度测试", owner_id=owner.id, org_id=org.id)
    db.add(exam)
    db.flush()
    first = _answer_submission(
        db, exam=exam, uploader_id=owner.id, student_name="张三"
    )
    second = _answer_submission(
        db, exam=exam, uploader_id=owner.id, student_name="李四"
    )
    run = GradingRun(
        exam_id=exam.id,
        created_by_id=owner.id,
        provider="test",
        model="test-model",
    )
    db.add(run)
    db.flush()

    reservation = reserve_answer_quota(
        db,
        org_id=org.id,
        exam_id=exam.id,
        grading_run_id=run.id,
        submissions=[first, second],
    )
    assert reservation is not None
    assert reservation.reserved_answers == 2
    assert grant.reserved_answers == 2
    charged = settle_answer_quota(
        db, reservation_id=reservation.id, completed_submissions=[first]
    )
    db.commit()
    assert charged == 1
    db.refresh(grant)
    assert grant.reserved_answers == 0
    assert grant.consumed_answers == 1
    assert db.exec(select(BillableAnswerSheet)).all()[0].student_name == "张三"

    retry_run = GradingRun(
        exam_id=exam.id,
        created_by_id=owner.id,
        provider="test",
        model="test-model",
    )
    db.add(retry_run)
    db.flush()
    retry = reserve_answer_quota(
        db,
        org_id=org.id,
        exam_id=exam.id,
        grading_run_id=retry_run.id,
        submissions=[first, second],
    )
    assert retry is not None
    assert retry.reserved_answers == 1
    assert retry.identities != reservation.identities
    assert db.exec(select(AnswerQuotaReservation)).all()
    assert db.exec(select(AnswerQuotaGrant)).all()


def test_released_answer_quota_can_be_reserved_again_for_same_run(
    db: Session, monkeypatch
) -> None:
    org, _rate = _contract(db)
    owner = User(
        email=f"retry-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="test",
        role=UserRole.SCHOOL_OWNER,
        org_id=org.id,
    )
    db.add(owner)
    db.flush()
    monkeypatch.setattr(settings, "BILLING_ENFORCEMENT_ENABLED", True)
    grant = grant_answer_quota(
        db,
        org_id=org.id,
        answers=1,
        source=CreditGrantSource.SUBSCRIPTION,
        actor_id=owner.id,
        note="重试测试",
    )
    exam = Exam(title="失败重试", owner_id=owner.id, org_id=org.id)
    db.add(exam)
    db.flush()
    submission = _answer_submission(
        db, exam=exam, uploader_id=owner.id, student_name="王五"
    )
    run = GradingRun(
        exam_id=exam.id,
        created_by_id=owner.id,
        provider="test",
        model="test-model",
    )
    db.add(run)
    db.flush()

    first = reserve_answer_quota(
        db,
        org_id=org.id,
        exam_id=exam.id,
        grading_run_id=run.id,
        submissions=[submission],
    )
    assert first is not None
    assert release_answer_quota(db, first.id) == 1
    second = reserve_answer_quota(
        db,
        org_id=org.id,
        exam_id=exam.id,
        grading_run_id=run.id,
        submissions=[submission],
        idempotency_key=f"{org.id}:retry:{uuid.uuid4()}",
    )
    assert second is not None
    assert second.id != first.id
    assert second.reserved_answers == 1
    assert grant.reserved_answers == 1


def test_stale_answer_quota_reservation_is_released(
    db: Session, monkeypatch
) -> None:
    org, _rate = _contract(db)
    owner = User(
        email=f"stale-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="test",
        role=UserRole.SCHOOL_OWNER,
        org_id=org.id,
    )
    db.add(owner)
    db.flush()
    monkeypatch.setattr(settings, "BILLING_ENFORCEMENT_ENABLED", True)
    grant = grant_answer_quota(
        db,
        org_id=org.id,
        answers=1,
        source=CreditGrantSource.SUBSCRIPTION,
        actor_id=owner.id,
        note="超时测试",
    )
    exam = Exam(title="超时释放", owner_id=owner.id, org_id=org.id)
    db.add(exam)
    db.flush()
    submission = _answer_submission(
        db, exam=exam, uploader_id=owner.id, student_name="赵六"
    )
    run = GradingRun(
        exam_id=exam.id,
        created_by_id=owner.id,
        provider="test",
        model="test-model",
    )
    db.add(run)
    db.flush()
    reservation = reserve_answer_quota(
        db,
        org_id=org.id,
        exam_id=exam.id,
        grading_run_id=run.id,
        submissions=[submission],
    )
    assert reservation is not None
    reservation.created_at = datetime.now(UTC) - timedelta(hours=25)
    db.add(reservation)
    db.commit()

    assert reconcile_stale_reservations(db) == 1
    db.commit()
    db.refresh(grant)
    db.refresh(reservation)
    assert grant.reserved_answers == 0
    assert reservation.status.value == "released"


def test_fifo_reservation_requires_full_actual_charge_and_idempotency(
    db: Session, monkeypatch
) -> None:
    org, rate = _contract(db)
    monkeypatch.setattr(settings, "BILLING_ENFORCEMENT_ENABLED", True)
    monkeypatch.setattr(settings, "TOKEN_BUDGET_ENFORCEMENT_ENABLED", True)
    first = grant_credits(
        db,
        org_id=org.id,
        credits=5,
        source=CreditGrantSource.SUBSCRIPTION,
        actor_id=None,
        note="首批",
    )
    second = grant_credits(
        db,
        org_id=org.id,
        credits=10,
        source=CreditGrantSource.TOP_UP,
        actor_id=None,
        note="续充",
    )
    # Make the first batch expire first so FIFO order is deterministic.
    first.expires_at = datetime.now(UTC) + timedelta(days=10)
    second.expires_at = datetime.now(UTC) + timedelta(days=20)
    db.add(first)
    db.add(second)
    db.commit()

    reservation = reserve_credits(
        db,
        org_id=org.id,
        task_type="grading_run",
        resource_id="run-1",
        idempotency_key=f"{org.id}:run-1",
        estimated_microcredits=credits_to_microcredits(8),
    )
    assert reservation is not None
    duplicate = reserve_credits(
        db,
        org_id=org.id,
        task_type="grading_run",
        resource_id="run-1",
        idempotency_key=f"{org.id}:run-1",
        estimated_microcredits=credits_to_microcredits(8),
    )
    assert duplicate and duplicate.id == reservation.id
    allocations = list(
        db.exec(
            select(CreditReservationAllocation).where(
                CreditReservationAllocation.reservation_id == reservation.id
            )
        ).all()
    )
    assert [row.reserved_microcredits for row in allocations] == [
        credits_to_microcredits(5),
        credits_to_microcredits(3),
    ]

    # Actual usage cannot be silently capped at the quote. Settlement extends
    # the reservation and charges all 12 credits while balance remains.
    usage_event = ModelUsageEvent(
        org_id=org.id,
        reservation_id=reservation.id,
        resource_id="item-1",
        workflow_purpose="subjective_grading",
        requested_provider="server-only",
        requested_model="server-only",
        actual_provider="server-only",
        actual_model="server-only",
        input_tokens=400_000,
        output_tokens=400_000,
        total_tokens=800_000,
        latency_ms=10,
        status=ModelUsageStatus.SUCCEEDED,
        customer_microcredits=credits_to_microcredits(12),
        billing_key=f"{org.id}:usage-1",
        rate_version_id=rate.id,
    )
    db.add(usage_event)
    db.commit()
    assert settle_reservation(db, reservation.id) == credits_to_microcredits(12)
    db.commit()
    db.refresh(first)
    db.refresh(second)
    db.refresh(usage_event)
    assert first.consumed_microcredits == credits_to_microcredits(5)
    assert second.consumed_microcredits == credits_to_microcredits(7)
    assert first.reserved_microcredits == 0
    assert second.reserved_microcredits == 0
    assert usage_event.customer_microcredits == credits_to_microcredits(12)
    assert quote_microcredits(
        db,
        org_id=org.id,
        workflow_purpose="subjective_grading",
        expected_calls=1,
    ) == credits_to_microcredits(14.4)


def test_internal_cost_reservation_does_not_require_school_token_grant(
    db: Session, monkeypatch
) -> None:
    org, _rate = _contract(db)
    monkeypatch.setattr(settings, "BILLING_ENFORCEMENT_ENABLED", True)
    monkeypatch.setattr(settings, "TOKEN_BUDGET_ENFORCEMENT_ENABLED", True)

    reservation = reserve_credits(
        db,
        org_id=org.id,
        task_type="grading_run",
        resource_id="answer-quota-funded-run",
        idempotency_key=f"{org.id}:answer-quota-funded-run",
        estimated_microcredits=credits_to_microcredits(8),
    )

    assert reservation is not None
    assert reservation.estimated_microcredits == credits_to_microcredits(8)
    assert db.exec(select(CreditGrant).where(CreditGrant.org_id == org.id)).all() == []


def test_model_usage_billing_key_is_fixed_length_and_idempotent(db: Session) -> None:
    org, _rate = _contract(db)
    context = ModelCallContext(
        org_id=org.id,
        workflow_purpose="answer_preparation",
        resource_id="resource",
        billing_key="business-revision:" + "x" * 500,
    )
    event = record_model_attempt(
        context,
        requested_provider="requested",
        requested_model="model-" + "a" * 190,
        actual_provider="actual",
        actual_model="model-" + "b" * 190,
        usage={"prompt_tokens": 100, "completion_tokens": 20},
        latency_ms=10,
        attempt=1,
    )
    duplicate = record_model_attempt(
        context,
        requested_provider="requested",
        requested_model="model-" + "a" * 190,
        actual_provider="actual",
        actual_model="model-" + "b" * 190,
        usage={"prompt_tokens": 100, "completion_tokens": 20},
        latency_ms=10,
        attempt=1,
    )

    assert event is not None
    assert len(event.billing_key) == 75
    assert duplicate is None


def test_failed_or_missing_usage_is_not_chargeable(db: Session) -> None:
    org, rate = _contract(db)
    rows = [
        ModelUsageEvent(
            org_id=org.id,
            resource_id=f"item-{status}",
            workflow_purpose="answer_recognition",
            requested_provider="server-only",
            requested_model="server-only",
            status=status,
            customer_microcredits=0,
            billing_key=f"{org.id}:{status}",
            rate_version_id=rate.id,
        )
        for status in (ModelUsageStatus.FAILED, ModelUsageStatus.MISSING_USAGE)
    ]
    db.add_all(rows)
    db.commit()
    assert all(row.customer_microcredits == 0 for row in rows)
    assert db.exec(select(CreditGrant).where(CreditGrant.org_id == org.id)).all() == []


def test_dynamic_channel_uses_separate_internal_rate_snapshot(db: Session) -> None:
    org, customer_rate = _contract(db)
    channel = ProviderChannel(
        code=f"relay-{uuid.uuid4().hex[:8]}",
        display_name="成本测试通道",
        kind=ProviderChannelKind.AUTHORIZED_RELAY,
        protocol=ProviderProtocol.OPENAI_CHAT,
        base_url="https://relay.example/v1",
    )
    db.add(channel)
    db.flush()
    internal_rate = ProviderInternalRateVersion(
        channel_id=channel.id,
        canonical_model="grader-main",
        version="cost-v1",
        effective_at=datetime.now(UTC) - timedelta(minutes=1),
        input_micrormb_per_million=2_000_000,
        output_micrormb_per_million=8_000_000,
        image_micrormb_per_million=0,
        cached_input_micrormb_per_million=500_000,
    )
    db.add(internal_rate)
    db.commit()
    context = ModelCallContext(
        org_id=org.id,
        workflow_purpose="subjective_grading",
        resource_id="item",
        billing_key=f"rate-test-{uuid.uuid4()}",
    )

    event = record_model_attempt(
        context,
        requested_provider="configured",
        requested_model="grader-main",
        actual_provider=channel.code,
        actual_model="grader-main",
        channel_id=channel.id,
        usage={
            "prompt_tokens": 1_000_000,
            "completion_tokens": 100_000,
            "prompt_tokens_details": {"cached_tokens": 200_000},
            "completion_tokens_details": {"reasoning_tokens": 20_000},
        },
        latency_ms=10,
        attempt=1,
    )

    assert event is not None
    expected_customer, _legacy_internal = calculate_microcredits(
        customer_rate,
        input_tokens=1_000_000,
        output_tokens=100_000,
        image_tokens=0,
    )
    assert event.customer_microcredits == expected_customer
    assert event.internal_cost_micrormb == 2_500_000
    assert event.cached_input_tokens == 200_000
    assert event.reasoning_tokens == 20_000
    assert event.internal_rate_version_id == internal_rate.id
