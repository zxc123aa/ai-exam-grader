from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.models import Organization, OrganizationJobLease, OrganizationUsagePolicy
from app.services import job_control


def test_job_lease_enforces_org_limit_and_releases(db: Session) -> None:
    org = Organization(name="任务限流学校", code="job-limit-school")
    db.add(org)
    db.flush()
    db.add(OrganizationUsagePolicy(org_id=org.id, max_running_jobs=1))
    db.commit()

    first = job_control.try_acquire_job_lease(
        org_id=org.id, task_type="grading", resource_id="run-1"
    )
    assert first is not None
    assert (
        job_control.try_acquire_job_lease(
            org_id=org.id, task_type="grading", resource_id="run-2"
        )
        is None
    )

    job_control.release_job_lease(first)
    second = job_control.try_acquire_job_lease(
        org_id=org.id, task_type="grading", resource_id="run-2"
    )
    assert second is not None
    job_control.release_job_lease(second)


def test_job_lease_reclaims_expired_slot(db: Session) -> None:
    org = Organization(name="过期租约学校", code="expired-job-lease-school")
    db.add(org)
    db.flush()
    db.add(OrganizationUsagePolicy(org_id=org.id, max_running_jobs=1))
    db.add(
        OrganizationJobLease(
            org_id=org.id,
            task_type="grading",
            resource_id="stale-run",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    db.commit()

    token = job_control.try_acquire_job_lease(
        org_id=org.id, task_type="grading", resource_id="fresh-run"
    )
    assert token is not None
    with Session(db.bind) as check:
        leases = check.exec(
            select(OrganizationJobLease).where(OrganizationJobLease.org_id == org.id)
        ).all()
        assert [item.resource_id for item in leases] == ["fresh-run"]
    job_control.release_job_lease(token)
