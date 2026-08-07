from __future__ import annotations

import hashlib
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, text, update
from sqlmodel import Session, func, select

from app.core.db import engine
from app.models import (
    Organization,
    OrganizationJobLease,
    OrganizationRiskState,
    OrganizationServiceState,
    OrganizationUsagePolicy,
)

LEASE_TTL = timedelta(minutes=5)
HEARTBEAT_INTERVAL_SECONDS = 60


def _advisory_key(org_id: uuid.UUID) -> int:
    digest = hashlib.sha256(f"dianfan:org-job:{org_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF


def try_acquire_job_lease(
    *, org_id: uuid.UUID, task_type: str, resource_id: str
) -> uuid.UUID | None:
    """Atomically claim one of the organization's PostgreSQL-backed job slots."""
    now = datetime.now(UTC)
    with Session(engine) as session:
        session.exec(
            text("SELECT pg_advisory_xact_lock(:key)").bindparams(
                key=_advisory_key(org_id)
            )
        )
        session.exec(
            delete(OrganizationJobLease).where(OrganizationJobLease.expires_at <= now)
        )
        organization = session.get(Organization, org_id)
        if not organization or organization.status != OrganizationServiceState.ACTIVE:
            session.commit()
            return None
        policy = session.exec(
            select(OrganizationUsagePolicy).where(
                OrganizationUsagePolicy.org_id == org_id
            )
        ).first()
        if policy and policy.risk_state in {
            OrganizationRiskState.BLOCKED,
            OrganizationRiskState.FROZEN,
        }:
            session.commit()
            return None
        limit = policy.max_running_jobs if policy else 8
        active = int(
            session.exec(
                select(func.count())
                .select_from(OrganizationJobLease)
                .where(
                    OrganizationJobLease.org_id == org_id,
                    OrganizationJobLease.expires_at > now,
                )
            ).one()
        )
        if active >= limit:
            session.commit()
            return None
        token = uuid.uuid4()
        session.add(
            OrganizationJobLease(
                org_id=org_id,
                task_type=task_type,
                resource_id=resource_id,
                lease_token=token,
                acquired_at=now,
                heartbeat_at=now,
                expires_at=now + LEASE_TTL,
            )
        )
        session.commit()
        return token


def heartbeat_job_lease(token: uuid.UUID) -> bool:
    now = datetime.now(UTC)
    with Session(engine) as session:
        result = session.exec(
            update(OrganizationJobLease)
            .where(OrganizationJobLease.lease_token == token)
            .values(heartbeat_at=now, expires_at=now + LEASE_TTL)
        )
        session.commit()
        return bool(result.rowcount)


def release_job_lease(token: uuid.UUID) -> None:
    with Session(engine) as session:
        session.exec(
            delete(OrganizationJobLease).where(
                OrganizationJobLease.lease_token == token
            )
        )
        session.commit()


@contextmanager
def organization_job_slot(
    *, org_id: uuid.UUID, task_type: str, resource_id: str
) -> Iterator[bool]:
    token = try_acquire_job_lease(
        org_id=org_id, task_type=task_type, resource_id=resource_id
    )
    if token is None:
        yield False
        return

    stopped = threading.Event()

    def keep_alive() -> None:
        while not stopped.wait(HEARTBEAT_INTERVAL_SECONDS):
            if not heartbeat_job_lease(token):
                return

    thread = threading.Thread(target=keep_alive, daemon=True)
    thread.start()
    try:
        yield True
    finally:
        stopped.set()
        thread.join(timeout=1)
        release_job_lease(token)
