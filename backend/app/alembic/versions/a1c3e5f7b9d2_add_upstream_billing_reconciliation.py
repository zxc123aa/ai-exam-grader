"""Add upstream billing reconciliation fields.

Revision ID: a1c3e5f7b9d2
Revises: f0b2d4e6a8c1
Create Date: 2026-07-27 23:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "a1c3e5f7b9d2"
down_revision = "f0b2d4e6a8c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE usagereconciliationstatus ADD VALUE IF NOT EXISTS 'missing_local'"
    )
    op.add_column(
        "modelusageevent",
        sa.Column("upstream_cost_micrormb", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "modelusageevent",
        sa.Column("upstream_billed_at", sa.DateTime(timezone=True), nullable=True),
    )
    for name in ("fetched_count", "ignored_count"):
        op.add_column(
            "providerreconciliationbatch",
            sa.Column(name, sa.Integer(), server_default="0", nullable=False),
        )
    op.add_column(
        "providerreconciliationbatch",
        sa.Column("upstream_system_name", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "providerreconciliationbatch",
        sa.Column("upstream_version", sa.String(length=100), nullable=True),
    )
    for name in (
        "upstream_total_granted_quota",
        "upstream_total_used_quota",
        "upstream_total_available_quota",
        "upstream_total_used_micrormb",
        "quota_per_unit",
    ):
        op.add_column(
            "providerreconciliationbatch",
            sa.Column(name, sa.BigInteger(), server_default="0", nullable=False),
        )
    op.add_column(
        "providerreconciliationbatch",
        sa.Column("usd_exchange_rate", sa.Float(), server_default="0", nullable=False),
    )
    op.add_column(
        "providerreconciliationbatch",
        sa.Column(
            "unlimited_quota", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )


def downgrade() -> None:
    for name in (
        "unlimited_quota",
        "usd_exchange_rate",
        "quota_per_unit",
        "upstream_total_used_micrormb",
        "upstream_total_available_quota",
        "upstream_total_used_quota",
        "upstream_total_granted_quota",
        "upstream_version",
        "upstream_system_name",
        "ignored_count",
        "fetched_count",
    ):
        op.drop_column("providerreconciliationbatch", name)
    op.drop_column("modelusageevent", "upstream_billed_at")
    op.drop_column("modelusageevent", "upstream_cost_micrormb")
    # PostgreSQL enum values cannot be removed safely in a transactional downgrade.
