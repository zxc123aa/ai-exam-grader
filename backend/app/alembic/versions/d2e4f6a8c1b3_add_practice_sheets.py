"""Add practice sheets for variant-question practice.

Revision ID: d2e4f6a8c1b3
Revises: c1d3e5f7a9b2
Create Date: 2026-08-16 14:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d2e4f6a8c1b3"
down_revision = "c1d3e5f7a9b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "practicesheet",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("learner_id", sa.Uuid(), nullable=False),
        sa.Column("student_user_id", sa.Uuid(), nullable=True),
        sa.Column("subject", sa.String(length=50), nullable=False),
        sa.Column("knowledge_point", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("items", postgresql.JSONB(), nullable=False),
        sa.Column("seed_count", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["learner_id"], ["learnerprofile.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["student_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_practicesheet_learner_id", "practicesheet", ["learner_id"])


def downgrade() -> None:
    op.drop_index("ix_practicesheet_learner_id", table_name="practicesheet")
    op.drop_table("practicesheet")
