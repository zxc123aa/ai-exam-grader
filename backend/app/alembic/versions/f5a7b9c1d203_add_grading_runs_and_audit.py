"""add grading runs and audit

Revision ID: f5a7b9c1d203
Revises: c4e5f6a7b890
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "f5a7b9c1d203"
down_revision = "c4e5f6a7b890"
branch_labels = None
depends_on = None


def upgrade() -> None:
    grading_status = postgresql.ENUM(
        "queued", "running", "completed", "completed_with_errors", "failed",
        name="gradingrunstatus",
    )
    grading_status.create(op.get_bind(), checkfirst=True)
    op.add_column("standardanswer", sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    op.add_column("standardanswer", sa.Column("source_provider", sa.String(100), nullable=True))
    op.add_column("standardanswer", sa.Column("source_model", sa.String(200), nullable=True))
    op.add_column("standardanswer", sa.Column("generation_confidence", sa.Float(), nullable=True))
    op.add_column("standardanswer", sa.Column("answer_hash", sa.String(64), nullable=True))
    op.add_column("standardanswer", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("standardanswer", sa.Column("published_by_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_standardanswer_published_by", "standardanswer", "user", ["published_by_id"], ["id"], ondelete="SET NULL")
    op.add_column("submissionannotation", sa.Column("score_source", sa.String(50), nullable=True))
    op.add_column("submissionannotation", sa.Column("model_score", sa.Float(), nullable=True))
    op.add_column("submissionannotation", sa.Column("model_confidence", sa.Float(), nullable=True))
    op.add_column("submissionannotation", sa.Column("grading_version", sa.String(100), nullable=True))
    op.add_column("submissionannotation", sa.Column("grading_evidence", postgresql.JSONB(), server_default="[]", nullable=False))
    op.add_column("submissionannotation", sa.Column("auto_published_at", sa.DateTime(timezone=True), nullable=True))
    run_status_column = postgresql.ENUM(
        "queued", "running", "completed", "completed_with_errors", "failed",
        name="gradingrunstatus", create_type=False,
    )
    op.create_table(
        "gradingrun",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("exam_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("fallback_models", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("answer_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", run_status_column, server_default="queued", nullable=False),
        sa.Column("total_submissions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("review_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("config_snapshot", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("error_message", sa.String(2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["exam_id"], ["exam.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["user.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_gradingrun_exam_id", "gradingrun", ["exam_id"])
    op.create_table(
        "gradingauditevent",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("grading_run_id", sa.Uuid(), nullable=True),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("annotation_id", sa.Uuid(), nullable=False),
        sa.Column("operator_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("old_score", sa.Float(), nullable=True),
        sa.Column("new_score", sa.Float(), nullable=True),
        sa.Column("old_comment", sa.String(2000), nullable=True),
        sa.Column("new_comment", sa.String(2000), nullable=True),
        sa.Column("reason", sa.String(1000), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["grading_run_id"], ["gradingrun.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["submission_id"], ["studentsubmission.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["annotation_id"], ["submissionannotation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["operator_id"], ["user.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_gradingauditevent_submission_id", "gradingauditevent", ["submission_id"])
    op.create_index("ix_gradingauditevent_annotation_id", "gradingauditevent", ["annotation_id"])


def downgrade() -> None:
    op.drop_table("gradingauditevent")
    op.drop_index("ix_gradingrun_exam_id", table_name="gradingrun")
    op.drop_table("gradingrun")
    for column in ("auto_published_at", "grading_evidence", "grading_version", "model_confidence", "model_score", "score_source"):
        op.drop_column("submissionannotation", column)
    op.drop_constraint("fk_standardanswer_published_by", "standardanswer", type_="foreignkey")
    for column in ("published_by_id", "published_at", "answer_hash", "generation_confidence", "source_model", "source_provider", "version"):
        op.drop_column("standardanswer", column)
    postgresql.ENUM(name="gradingrunstatus").drop(op.get_bind(), checkfirst=True)
