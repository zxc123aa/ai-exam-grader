"""Add wrongbook review scheduling and knowledge point mastery.

Revision ID: a9c1e3f5b7d0
Revises: f8b0d2e4a6c9
Create Date: 2026-08-13 07:40:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a9c1e3f5b7d0"
down_revision = "f8b0d2e4a6c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    review_result = postgresql.ENUM(
        "again",
        "hard",
        "good",
        "easy",
        name="wrongquestionreviewresult",
        create_type=False,
    )
    review_result.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "wrongquestionreview",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("entry_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result", review_result, nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("interval_days", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["entry_id"], ["wrongquestionentry.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entry_id", name="uq_wrongquestionreview_entry"),
    )
    op.create_index(
        op.f("ix_wrongquestionreview_entry_id"),
        "wrongquestionreview",
        ["entry_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wrongquestionreview_owner_user_id"),
        "wrongquestionreview",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wrongquestionreview_next_due_at"),
        "wrongquestionreview",
        ["next_due_at"],
        unique=False,
    )

    op.create_table(
        "learnermastery",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_key", sa.String(length=100), nullable=False),
        sa.Column("subject", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("knowledge_point_name", sa.String(length=100), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wrong_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_wrong_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_key", "subject", "knowledge_point_name", name="uq_learnermastery_key"
        ),
    )
    op.create_index(
        op.f("ix_learnermastery_owner_key"),
        "learnermastery",
        ["owner_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_learnermastery_owner_key"), table_name="learnermastery")
    op.drop_table("learnermastery")
    op.drop_index(
        op.f("ix_wrongquestionreview_next_due_at"), table_name="wrongquestionreview"
    )
    op.drop_index(
        op.f("ix_wrongquestionreview_owner_user_id"), table_name="wrongquestionreview"
    )
    op.drop_index(
        op.f("ix_wrongquestionreview_entry_id"), table_name="wrongquestionreview"
    )
    op.drop_table("wrongquestionreview")
    postgresql.ENUM(name="wrongquestionreviewresult").drop(
        op.get_bind(), checkfirst=True
    )
