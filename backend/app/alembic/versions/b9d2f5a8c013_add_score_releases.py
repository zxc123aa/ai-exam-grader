"""Add immutable teacher-published score snapshots.

Revision ID: b9d2f5a8c013
Revises: a8c1e4f7b902
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b9d2f5a8c013"
down_revision = "a8c1e4f7b902"
branch_labels = None
depends_on = None


def upgrade() -> None:
    status = postgresql.ENUM(
        "published", "superseded", name="scorereleasestatus", create_type=False
    )
    status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "scorerelease",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exam_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", status, nullable=False),
        sa.Column("published_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exam.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["published_by_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("exam_id", "version", name="uq_score_release_exam_version"),
    )
    op.create_index("ix_scorerelease_exam_id", "scorerelease", ["exam_id"])
    op.create_index("ix_scorerelease_published_at", "scorerelease", ["published_at"])
    op.create_table(
        "scorereleaseitem",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("release_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("annotation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("max_score", sa.Float(), nullable=True),
        sa.Column("comment", sa.String(length=2000), nullable=True),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.ForeignKeyConstraint(["release_id"], ["scorerelease.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submission_id"], ["studentsubmission.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["annotation_id"], ["submissionannotation.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("release_id", "submission_id", "label", name="uq_score_release_item"),
    )
    op.create_index("ix_scorereleaseitem_release_id", "scorereleaseitem", ["release_id"])
    op.create_index("ix_scorereleaseitem_submission_id", "scorereleaseitem", ["submission_id"])


def downgrade() -> None:
    op.drop_table("scorereleaseitem")
    op.drop_table("scorerelease")
    postgresql.ENUM(name="scorereleasestatus").drop(op.get_bind(), checkfirst=True)
