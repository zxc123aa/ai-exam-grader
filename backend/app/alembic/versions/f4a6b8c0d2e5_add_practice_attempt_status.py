"""Add async grading status to practice sheet attempts.

Revision ID: f4a6b8c0d2e5
Revises: e3f5a7b9d1c4
Create Date: 2026-08-18 09:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f4a6b8c0d2e5"
down_revision = "e3f5a7b9d1c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    status = postgresql.ENUM(
        "pending", "graded", "failed", name="practiceattemptstatus", create_type=False
    )
    status.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "practicesheetattempt",
        sa.Column("status", status, nullable=False, server_default="pending"),
    )
    # 既有记录都是同步时代已判完的
    op.execute("UPDATE practicesheetattempt SET status = 'graded'")
    op.alter_column("practicesheetattempt", "status", server_default=None)
    op.alter_column(
        "practicesheetattempt",
        "verdict",
        existing_type=postgresql.ENUM(name="practiceverdict"),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "practicesheetattempt",
        "verdict",
        existing_type=postgresql.ENUM(name="practiceverdict"),
        nullable=False,
    )
    op.drop_column("practicesheetattempt", "status")
    postgresql.ENUM(name="practiceattemptstatus").drop(op.get_bind(), checkfirst=True)
