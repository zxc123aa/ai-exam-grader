import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.core.security import verify_password
from app.models import (
    AnswerQuotaGrant,
    BillingRateVersion,
    Organization,
    OrganizationSubscription,
    OrganizationUsagePolicy,
    PendingOrganizationSignup,
    SubscriptionStatus,
    UserRole,
)
from app.services import public_signup
from tests.utils.utils import random_email

URL = f"{settings.API_V1_STR}/users/signup"


def _signup_payload(
    email: str, organization_name: str = "启明内测机构"
) -> dict[str, str]:
    return {
        "organization_type": "training",
        "organization_name": organization_name,
        "contact_name": "周老师",
        "email": email,
        "password": "Dianfan-Test-2026",
        "turnstile_token": "test-turnstile-token",
    }


def _rate(db: Session, version: str) -> BillingRateVersion:
    rate = BillingRateVersion(
        version=version,
        effective_at=datetime.now(UTC) - timedelta(minutes=1),
        input_microcredits_per_million=1_000_000,
        output_microcredits_per_million=2_000_000,
        image_microcredits_per_million=1_000_000,
    )
    db.add(rate)
    db.commit()
    db.refresh(rate)
    return rate


def test_public_signup_verifies_and_opens_trial_atomically(
    client: TestClient, db: Session, monkeypatch
) -> None:
    email = random_email()
    rate_version = f"signup-{uuid.uuid4().hex[:10]}"
    rate = _rate(db, rate_version)
    tokens: list[str] = []
    monkeypatch.setattr(settings, "PUBLIC_SIGNUP_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLIC_SIGNUP_TRIAL_RATE_VERSION", rate_version)
    monkeypatch.setattr(public_signup, "verify_turnstile", lambda *_args: None)
    monkeypatch.setattr(public_signup, "_consume_rate_limit", lambda **_kwargs: None)
    monkeypatch.setattr(
        public_signup,
        "_send_verification",
        lambda _pending, token: tokens.append(token),
    )

    requested = client.post(URL, json=_signup_payload(email))
    assert requested.status_code == 202, requested.text
    assert tokens
    assert crud.get_user_by_email(session=db, email=email) is None
    pending = db.exec(
        select(PendingOrganizationSignup).where(
            PendingOrganizationSignup.email == email
        )
    ).first()
    assert pending is not None

    verified = client.post(f"{URL}/verify", json={"token": tokens[-1]})
    assert verified.status_code == 200, verified.text
    result = verified.json()
    assert result["access_token"]
    assert result["organization"]["code"].startswith("DF-")
    assert result["organization"]["organization_type"] == "training"
    assert result["answer_quota"] == 200
    onboarding = client.get(
        f"{settings.API_V1_STR}/org/onboarding",
        headers={"Authorization": f"Bearer {result['access_token']}"},
    )
    assert onboarding.status_code == 200, onboarding.text
    assert onboarding.json() == {
        "class_count": 0,
        "teacher_count": 0,
        "student_count": 0,
        "teacher_exam_count": 0,
    }

    db.expire_all()
    owner = crud.get_user_by_email(session=db, email=email)
    assert owner is not None
    assert owner.role == UserRole.SCHOOL_OWNER
    assert verify_password("Dianfan-Test-2026", owner.hashed_password)[0]
    org = db.get(Organization, owner.org_id)
    assert org is not None
    assert org.name == "启明内测机构"
    subscription = db.exec(
        select(OrganizationSubscription).where(
            OrganizationSubscription.org_id == org.id
        )
    ).one()
    assert subscription.status == SubscriptionStatus.ACTIVE
    assert subscription.rate_version_id == rate.id
    grant = db.exec(
        select(AnswerQuotaGrant).where(AnswerQuotaGrant.org_id == org.id)
    ).one()
    assert grant.total_answers == 200
    policy = db.exec(
        select(OrganizationUsagePolicy).where(
            OrganizationUsagePolicy.org_id == org.id
        )
    ).one()
    assert policy.calls_per_minute == 30
    assert policy.max_running_jobs == 2
    assert policy.max_model_concurrency == 4
    assert db.exec(
        select(PendingOrganizationSignup).where(
            PendingOrganizationSignup.email == email
        )
    ).first() is None

    reused = client.post(f"{URL}/verify", json={"token": tokens[-1]})
    assert reused.status_code == 400
    assert reused.json()["detail"] == "验证链接无效或已经使用"
    duplicate = client.post(URL, json=_signup_payload(email))
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "该邮箱已经注册，请直接登录"


def test_public_signup_resend_invalidates_previous_link(
    client: TestClient, db: Session, monkeypatch
) -> None:
    email = random_email()
    rate_version = f"signup-{uuid.uuid4().hex[:10]}"
    _rate(db, rate_version)
    tokens: list[str] = []
    monkeypatch.setattr(settings, "PUBLIC_SIGNUP_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLIC_SIGNUP_TRIAL_RATE_VERSION", rate_version)
    monkeypatch.setattr(public_signup, "verify_turnstile", lambda *_args: None)
    monkeypatch.setattr(public_signup, "_consume_rate_limit", lambda **_kwargs: None)
    monkeypatch.setattr(
        public_signup,
        "_send_verification",
        lambda _pending, token: tokens.append(token),
    )
    requested = client.post(URL, json=_signup_payload(email))
    assert requested.status_code == 202
    pending = db.exec(
        select(PendingOrganizationSignup).where(
            PendingOrganizationSignup.email == email
        )
    ).one()
    pending.last_sent_at = datetime.now(UTC) - timedelta(seconds=61)
    db.add(pending)
    db.commit()

    resent = client.post(
        f"{URL}/resend",
        json={"email": email, "turnstile_token": "test-turnstile-token"},
    )
    assert resent.status_code == 202, resent.text
    assert len(tokens) == 2
    old_link = client.post(f"{URL}/verify", json={"token": tokens[0]})
    assert old_link.status_code == 400
    new_link = client.post(f"{URL}/verify", json={"token": tokens[1]})
    assert new_link.status_code == 200, new_link.text


def test_public_signup_missing_rate_does_not_create_tenant(
    client: TestClient, db: Session, monkeypatch
) -> None:
    email = random_email()
    tokens: list[str] = []
    monkeypatch.setattr(settings, "PUBLIC_SIGNUP_ENABLED", True)
    monkeypatch.setattr(
        settings, "PUBLIC_SIGNUP_TRIAL_RATE_VERSION", "missing-signup-rate"
    )
    monkeypatch.setattr(public_signup, "verify_turnstile", lambda *_args: None)
    monkeypatch.setattr(public_signup, "_consume_rate_limit", lambda **_kwargs: None)
    monkeypatch.setattr(
        public_signup,
        "_send_verification",
        lambda _pending, token: tokens.append(token),
    )

    organization_name = f"回滚测试机构-{uuid.uuid4().hex[:8]}"
    requested = client.post(URL, json=_signup_payload(email, organization_name))
    assert requested.status_code == 202
    verified = client.post(f"{URL}/verify", json={"token": tokens[-1]})
    assert verified.status_code == 503
    assert verified.json()["detail"] == "试用服务暂时无法开通，请稍后再试"
    assert crud.get_user_by_email(session=db, email=email) is None
    assert db.exec(
        select(Organization).where(Organization.name == organization_name)
    ).first() is None


def test_public_signup_rejects_invalid_turnstile(
    client: TestClient, db: Session, monkeypatch
) -> None:
    email = random_email()
    monkeypatch.setattr(settings, "PUBLIC_SIGNUP_ENABLED", True)

    response = client.post(URL, json=_signup_payload(email))

    assert response.status_code == 422
    assert response.json()["detail"] == "请完成人机验证"
    assert crud.get_user_by_email(session=db, email=email) is None
