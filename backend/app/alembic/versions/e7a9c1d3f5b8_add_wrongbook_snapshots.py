"""Add student wrongbook snapshot tables.

Revision ID: e7a9c1d3f5b8
Revises: d6f8a0c2e4b7
Create Date: 2026-08-13 06:10:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e7a9c1d3f5b8"
down_revision = "d6f8a0c2e4b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    entry_status = postgresql.ENUM(
        "active",
        "superseded",
        name="wrongquestionentrystatus",
        create_type=False,
    )
    entry_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "wrongquestionsource",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("exam_id", sa.Uuid(), nullable=True),
        sa.Column("question_id", sa.Uuid(), nullable=True),
        sa.Column("release_id", sa.Uuid(), nullable=True),
        sa.Column("release_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("exam_title", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=100), nullable=True),
        sa.Column("grade_level", sa.String(length=100), nullable=True),
        sa.Column("exam_date", sa.Date(), nullable=True),
        sa.Column("question_label", sa.String(length=100), nullable=False),
        sa.Column("question_text", sa.String(length=20000), nullable=True),
        sa.Column("question_type", sa.String(length=50), nullable=True),
        sa.Column("max_score", sa.Float(), nullable=True),
        sa.Column("standard_answer_text", sa.String(length=20000), nullable=True),
        sa.Column(
            "scoring_points",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "knowledge_point_names",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exam.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["question_id"], ["examquestion.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["release_id"], ["scorerelease.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "release_id", "question_label", name="uq_wrongquestionsource_release_label"
        ),
    )
    op.create_index(
        op.f("ix_wrongquestionsource_subject"),
        "wrongquestionsource",
        ["subject"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wrongquestionsource_released_at"),
        "wrongquestionsource",
        ["released_at"],
        unique=False,
    )

    op.create_table(
        "wrongquestionentry",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=True),
        sa.Column("student_user_id", sa.Uuid(), nullable=True),
        sa.Column("student_name", sa.String(length=255), nullable=True),
        sa.Column("class_name_at_time", sa.String(length=100), nullable=True),
        sa.Column("submission_id", sa.Uuid(), nullable=True),
        sa.Column("annotation_id", sa.Uuid(), nullable=True),
        sa.Column("release_id", sa.Uuid(), nullable=True),
        sa.Column("release_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("question_label", sa.String(length=100), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("max_score", sa.Float(), nullable=True),
        sa.Column(
            "is_wrong", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("student_answer_text", sa.String(length=12000), nullable=True),
        sa.Column(
            "missed_points",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("teacher_comment", sa.String(length=2000), nullable=True),
        sa.Column("score_source", sa.String(length=30), nullable=True),
        sa.Column("image_storage_key", sa.String(length=1024), nullable=True),
        sa.Column("status", entry_status, nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["annotation_id"], ["submissionannotation.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["release_id"], ["scorerelease.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["wrongquestionsource.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["student_id"], ["student.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["student_user_id"], ["user.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"], ["studentsubmission.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "release_id",
            "submission_id",
            "question_label",
            name="uq_wrongquestionentry_release_submission_label",
        ),
    )
    op.create_index(
        op.f("ix_wrongquestionentry_source_id"),
        "wrongquestionentry",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wrongquestionentry_student_user_id"),
        "wrongquestionentry",
        ["student_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wrongquestionentry_is_wrong"),
        "wrongquestionentry",
        ["is_wrong"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wrongquestionentry_released_at"),
        "wrongquestionentry",
        ["released_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_wrongquestionentry_released_at"), table_name="wrongquestionentry"
    )
    op.drop_index(
        op.f("ix_wrongquestionentry_is_wrong"), table_name="wrongquestionentry"
    )
    op.drop_index(
        op.f("ix_wrongquestionentry_student_user_id"), table_name="wrongquestionentry"
    )
    op.drop_index(
        op.f("ix_wrongquestionentry_source_id"), table_name="wrongquestionentry"
    )
    op.drop_table("wrongquestionentry")
    op.drop_index(
        op.f("ix_wrongquestionsource_released_at"), table_name="wrongquestionsource"
    )
    op.drop_index(
        op.f("ix_wrongquestionsource_subject"), table_name="wrongquestionsource"
    )
    op.drop_table("wrongquestionsource")
    postgresql.ENUM(name="wrongquestionentrystatus").drop(
        op.get_bind(), checkfirst=True
    )
