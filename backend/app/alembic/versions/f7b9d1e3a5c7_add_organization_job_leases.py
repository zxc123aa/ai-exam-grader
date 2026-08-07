"""Add PostgreSQL-backed organization job leases.

Revision ID: f7b9d1e3a5c7
Revises: e6a8c0d2f4b1
Create Date: 2026-07-26 20:00:00.000000
"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision = "f7b9d1e3a5c7"
down_revision = "e6a8c0d2f4b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizationjoblease",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("task_type", sqlmodel.sql.sqltypes.AutoString(50), nullable=False),
        sa.Column("resource_id", sqlmodel.sql.sqltypes.AutoString(100), nullable=False),
        sa.Column("lease_token", sa.Uuid(), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lease_token"),
        sa.UniqueConstraint("task_type", "resource_id", name="uq_org_job_resource"),
    )
    op.create_index(
        "ix_organizationjoblease_org_id", "organizationjoblease", ["org_id"]
    )
    op.create_index(
        "ix_organizationjoblease_lease_token",
        "organizationjoblease",
        ["lease_token"],
        unique=True,
    )
    op.create_index(
        "ix_organizationjoblease_expires_at",
        "organizationjoblease",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_table("organizationjoblease")
