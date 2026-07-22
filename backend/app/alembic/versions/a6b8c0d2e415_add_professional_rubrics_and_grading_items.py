"""add professional rubrics and grading items

Revision ID: a6b8c0d2e415
Revises: f5a7b9c1d203
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a6b8c0d2e415"
down_revision = "f5a7b9c1d203"
branch_labels = None
depends_on = None


def upgrade() -> None:
    item_status = postgresql.ENUM(
        "queued", "extracting", "grading", "completed", "needs_review", "failed",
        name="gradingitemstatus",
    )
    item_status.create(op.get_bind(), checkfirst=True)
    op.add_column("standardanswer", sa.Column("question_text", sa.String(12000), nullable=True))
    op.add_column("standardanswer", sa.Column("question_type", sa.String(50), nullable=True))
    op.add_column("standardanswer", sa.Column("rubric_config", postgresql.JSONB(), server_default="{}", nullable=False))
    op.add_column("standardanswer", sa.Column("validation_report", postgresql.JSONB(), server_default="{}", nullable=False))
    for name in (
        "total_items", "completed_items", "extracted_items", "objective_items",
        "subjective_items", "current_concurrency", "throttle_count",
    ):
        op.add_column("gradingrun", sa.Column(name, sa.Integer(), server_default="0", nullable=False))
    table_status = postgresql.ENUM(
        "queued", "extracting", "grading", "completed", "needs_review", "failed",
        name="gradingitemstatus", create_type=False,
    )
    op.create_table(
        "gradingitem",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("grading_run_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("exam_region_id", sa.Uuid(), nullable=False),
        sa.Column("annotation_id", sa.Uuid(), nullable=True),
        sa.Column("status", table_status, server_default="queued", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("extraction_result", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("grading_result", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("error_message", sa.String(2000), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["grading_run_id"], ["gradingrun.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submission_id"], ["studentsubmission.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["exam_region_id"], ["examregion.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["annotation_id"], ["submissionannotation.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("grading_run_id", "submission_id", "exam_region_id", name="uq_gradingitem_run_submission_region"),
    )
    op.create_index("ix_gradingitem_grading_run_id", "gradingitem", ["grading_run_id"])
    op.create_index("ix_gradingitem_submission_id", "gradingitem", ["submission_id"])


def downgrade() -> None:
    op.drop_table("gradingitem")
    for name in (
        "throttle_count", "current_concurrency", "subjective_items", "objective_items",
        "extracted_items", "completed_items", "total_items",
    ):
        op.drop_column("gradingrun", name)
    for name in ("validation_report", "rubric_config", "question_type", "question_text"):
        op.drop_column("standardanswer", name)
    postgresql.ENUM(name="gradingitemstatus").drop(op.get_bind(), checkfirst=True)
