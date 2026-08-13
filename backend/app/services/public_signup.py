from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import HTTPException
from redis import Redis
from redis.exceptions import RedisError
from sqlmodel import Session, delete, select

from app.core import security
from app.core.config import settings
from app.models import (
    BillingRateVersion,
    CreditGrantSource,
    Organization,
    OrganizationSignupCompleted,
    OrganizationSignupCreate,
    OrganizationSubscription,
    OrganizationUsagePolicy,
    PendingOrganizationSignup,
    SignupOrganizationPublic,
    SubscriptionStatus,
    User,
    UserRole,
)
from app.services import billing
from app.utils import generate_signup_verification_email, send_email

_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def _require_enabled() -> None:
    if not settings.PUBLIC_SIGNUP_ENABLED:
        raise HTTPException(status_code=403, detail="学校注册暂未开放")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _rate_key(scope: str, value: str) -> str:
    digest = hashlib.sha256(value.strip().lower().encode()).hexdigest()[:32]
    return f"dianfan:public-signup:{scope}:{digest}"


def _consume_rate_limit(*, scope: str, value: str, limit: int, seconds: int) -> None:
    if settings.ENVIRONMENT == "local":
        return
    client = Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=0.5,
        socket_timeout=1,
        retry_on_timeout=False,
    )
    try:
        key = _rate_key(scope, value)
        with client.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, seconds, nx=True)
            count, _ = pipe.execute()
    except RedisError:
        if settings.ENVIRONMENT == "local":
            return
        raise HTTPException(
            status_code=503, detail="注册保护服务暂时不可用，请稍后再试"
        )
    finally:
        client.close()
    if int(count) > limit:
        raise HTTPException(status_code=429, detail="操作过于频繁，请稍后再试")


def verify_turnstile(token: str, remote_ip: str) -> None:
    if settings.ENVIRONMENT == "local" and not settings.TURNSTILE_SECRET_KEY:
        if token == "local-testing-token":
            return
        raise HTTPException(status_code=422, detail="请完成人机验证")
    if not settings.TURNSTILE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="注册验证服务尚未配置")
    try:
        response = httpx.post(
            _TURNSTILE_VERIFY_URL,
            data={
                "secret": settings.TURNSTILE_SECRET_KEY,
                "response": token,
                "remoteip": remote_ip,
            },
            timeout=8,
        )
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(
            status_code=503, detail="人机验证服务暂时不可用，请稍后再试"
        )
    if not result.get("success"):
        raise HTTPException(status_code=422, detail="人机验证未通过，请重新验证")


def _send_verification(pending: PendingOrganizationSignup, raw_token: str) -> None:
    email_data = generate_signup_verification_email(
        email_to=pending.email,
        contact_name=pending.contact_name,
        organization_name=pending.organization_name,
        token=raw_token,
        valid_minutes=settings.PUBLIC_SIGNUP_TOKEN_EXPIRE_MINUTES,
    )
    send_email(
        email_to=pending.email,
        subject=email_data.subject,
        html_content=email_data.html_content,
        raise_on_error=True,
    )


def request_signup(
    session: Session,
    *,
    signup: OrganizationSignupCreate,
    remote_ip: str,
) -> PendingOrganizationSignup:
    _require_enabled()
    verify_turnstile(signup.turnstile_token, remote_ip)
    email = str(signup.email).strip().lower()
    _consume_rate_limit(scope="ip-hour", value=remote_ip, limit=5, seconds=3600)
    _consume_rate_limit(scope="email-day", value=email, limit=3, seconds=86400)
    if session.exec(select(User).where(User.email == email)).first():
        raise HTTPException(status_code=409, detail="该邮箱已经注册，请直接登录")

    now = datetime.now(UTC)
    session.exec(
        delete(PendingOrganizationSignup).where(
            PendingOrganizationSignup.expires_at < now - timedelta(days=1)
        )
    )
    raw_token = secrets.token_urlsafe(32)
    pending = session.exec(
        select(PendingOrganizationSignup)
        .where(PendingOrganizationSignup.email == email)
        .with_for_update()
    ).first()
    values = {
        "organization_type": signup.organization_type,
        "organization_name": signup.organization_name.strip(),
        "contact_name": signup.contact_name.strip(),
        "hashed_password": security.get_password_hash(signup.password),
        "token_hash": _token_hash(raw_token),
        "expires_at": now
        + timedelta(minutes=settings.PUBLIC_SIGNUP_TOKEN_EXPIRE_MINUTES),
        "last_sent_at": now,
    }
    if pending:
        pending.sqlmodel_update(values)
    else:
        pending = PendingOrganizationSignup(email=email, **values)
    session.add(pending)
    session.commit()
    session.refresh(pending)
    try:
        _send_verification(pending, raw_token)
    except Exception:
        raise HTTPException(status_code=503, detail="验证邮件发送失败，请稍后重新发送")
    return pending


def resend_signup(
    session: Session,
    *,
    email: str,
    turnstile_token: str,
    remote_ip: str,
) -> PendingOrganizationSignup:
    _require_enabled()
    verify_turnstile(turnstile_token, remote_ip)
    normalized_email = email.strip().lower()
    _consume_rate_limit(scope="resend-ip-hour", value=remote_ip, limit=5, seconds=3600)
    _consume_rate_limit(
        scope="resend-email-day", value=normalized_email, limit=5, seconds=86400
    )
    pending = session.exec(
        select(PendingOrganizationSignup)
        .where(PendingOrganizationSignup.email == normalized_email)
        .with_for_update()
    ).first()
    if not pending:
        raise HTTPException(
            status_code=404, detail="没有找到待验证的注册信息，请重新注册"
        )
    now = datetime.now(UTC)
    elapsed = (now - pending.last_sent_at).total_seconds()
    if elapsed < 60:
        raise HTTPException(
            status_code=429,
            detail=f"请在 {max(1, 60 - int(elapsed))} 秒后重新发送",
        )
    raw_token = secrets.token_urlsafe(32)
    pending.token_hash = _token_hash(raw_token)
    pending.expires_at = now + timedelta(
        minutes=settings.PUBLIC_SIGNUP_TOKEN_EXPIRE_MINUTES
    )
    pending.last_sent_at = now
    session.add(pending)
    session.commit()
    session.refresh(pending)
    try:
        _send_verification(pending, raw_token)
    except Exception:
        raise HTTPException(status_code=503, detail="验证邮件发送失败，请稍后再试")
    return pending


def _school_code(session: Session) -> str:
    for _ in range(12):
        code = "DF-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        if not session.exec(
            select(Organization.id).where(Organization.code == code)
        ).first():
            return code
    raise HTTPException(status_code=503, detail="学校 ID 生成失败，请稍后再试")


def verify_signup(session: Session, *, token: str) -> OrganizationSignupCompleted:
    _require_enabled()
    now = datetime.now(UTC)
    pending = session.exec(
        select(PendingOrganizationSignup)
        .where(PendingOrganizationSignup.token_hash == _token_hash(token))
        .with_for_update()
    ).first()
    if not pending:
        raise HTTPException(status_code=400, detail="验证链接无效或已经使用")
    if pending.expires_at <= now:
        raise HTTPException(status_code=400, detail="验证链接已过期，请重新发送")
    if session.exec(select(User.id).where(User.email == pending.email)).first():
        raise HTTPException(status_code=409, detail="该邮箱已经注册，请直接登录")
    rate = session.exec(
        select(BillingRateVersion).where(
            BillingRateVersion.version == settings.PUBLIC_SIGNUP_TRIAL_RATE_VERSION,
            BillingRateVersion.effective_at <= now,
        )
    ).first()
    if not rate:
        raise HTTPException(status_code=503, detail="试用服务暂时无法开通，请稍后再试")

    trial_ends_at = now + timedelta(days=settings.PUBLIC_SIGNUP_TRIAL_DAYS)
    org = Organization(
        name=pending.organization_name,
        code=_school_code(session),
        organization_type=pending.organization_type,
        contact_name=pending.contact_name,
    )
    session.add(org)
    session.flush()
    owner = User(
        email=pending.email,
        full_name=pending.contact_name,
        hashed_password=pending.hashed_password,
        role=UserRole.SCHOOL_OWNER,
        org_id=org.id,
        is_active=True,
        is_superuser=False,
    )
    session.add(owner)
    session.flush()
    subscription = OrganizationSubscription(
        org_id=org.id,
        contract_no=f"TRIAL-{org.code}-{uuid.uuid4().hex[:8].upper()}",
        plan_code="trial-30d",
        status=SubscriptionStatus.ACTIVE,
        starts_at=now,
        ends_at=trial_ends_at,
        rate_version_id=rate.id,
    )
    session.add(subscription)
    session.flush()
    billing.grant_answer_quota(
        session,
        org_id=org.id,
        answers=settings.PUBLIC_SIGNUP_TRIAL_ANSWER_QUOTA,
        source=CreditGrantSource.SUBSCRIPTION,
        actor_id=owner.id,
        note="公开注册自动发放内测额度",
    )
    session.add(
        OrganizationUsagePolicy(
            org_id=org.id,
            calls_per_minute=30,
            max_running_jobs=2,
            max_model_concurrency=4,
            updated_by_id=owner.id,
            reason="公开注册内测保护策略",
        )
    )
    session.delete(pending)
    session.commit()
    access_token = security.create_access_token(
        owner.id,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return OrganizationSignupCompleted(
        access_token=access_token,
        organization=SignupOrganizationPublic(
            id=org.id,
            code=org.code,
            name=org.name,
            organization_type=org.organization_type,
        ),
        trial_ends_at=trial_ends_at,
        answer_quota=settings.PUBLIC_SIGNUP_TRIAL_ANSWER_QUOTA,
    )
