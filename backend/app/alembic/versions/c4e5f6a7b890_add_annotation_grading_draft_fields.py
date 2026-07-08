"""Add annotation grading draft fields

Revision ID: c4e5f6a7b890
Revises: b2c7d8e9f012
Create Date: 2026-07-08 18:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "c4e5f6a7b890"
down_revision = "b2c7d8e9f012"
branch_labels = None
depends_on = None


def upgrade():
    grading_status = postgresql.ENUM(
        "not_started",
        "succeeded",
        "skipped_missing_answer",
        "needs_review",
        "stale",
        name="annotationgradingstatus",
        create_type=False,
    )
    postgresql.ENUM(
        "not_started",
        "succeeded",
        "skipped_missing_answer",
        "needs_review",
        "stale",
        name="annotationgradingstatus",
    ).create(op.get_bind(), checkfirst=True)
    op.add_column(
        "submissionannotation",
        sa.Column("suggested_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "submissionannotation",
        sa.Column("suggested_comment", sa.String(length=2000), nullable=True),
    )
    op.add_column(
        "submissionannotation",
        sa.Column("grading_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "submissionannotation",
        sa.Column(
            "grading_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "submissionannotation",
        sa.Column(
            "grading_status",
            grading_status,
            nullable=False,
            server_default="not_started",
        ),
    )
    op.add_column(
        "submissionannotation",
        sa.Column("answer_key_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column("submissionannotation", "grading_reasons", server_default=None)
    op.alter_column("submissionannotation", "grading_status", server_default=None)


def downgrade():
    op.drop_column("submissionannotation", "answer_key_updated_at")
    op.drop_column("submissionannotation", "grading_status")
    op.drop_column("submissionannotation", "grading_reasons")
    op.drop_column("submissionannotation", "grading_confidence")
    op.drop_column("submissionannotation", "suggested_comment")
    op.drop_column("submissionannotation", "suggested_score")
    op.execute("DROP TYPE IF EXISTS annotationgradingstatus")
