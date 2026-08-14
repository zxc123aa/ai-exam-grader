"""Add knowledge point taxonomy and question links.

Revision ID: d6f8a0c2e4b7
Revises: c3e5f7a9b1d2
Create Date: 2026-08-13 05:30:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d6f8a0c2e4b7"
down_revision = "c3e5f7a9b1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    knowledge_point_source = postgresql.ENUM(
        "curriculum",
        "custom",
        name="knowledgepointsource",
        create_type=False,
    )
    knowledge_point_source.create(op.get_bind(), checkfirst=True)
    question_knowledge_source = postgresql.ENUM(
        "ai",
        "teacher",
        name="questionknowledgesource",
        create_type=False,
    )
    question_knowledge_source.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "knowledgepoint",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.String(length=50), nullable=False),
        sa.Column("grade_band", sa.String(length=50), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column(
            "aliases",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("source", knowledge_point_source, nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["knowledgepoint.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject", "code", name="uq_knowledgepoint_subject_code"),
    )
    op.create_index(
        op.f("ix_knowledgepoint_subject"), "knowledgepoint", ["subject"], unique=False
    )

    op.create_table(
        "examquestionknowledgelink",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_point_id", sa.Uuid(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("source", question_knowledge_source, nullable=False),
        sa.Column(
            "is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["knowledge_point_id"], ["knowledgepoint.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["question_id"], ["examquestion.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "question_id",
            "knowledge_point_id",
            name="uq_examquestionknowledgelink_pair",
        ),
    )
    op.create_index(
        op.f("ix_examquestionknowledgelink_question_id"),
        "examquestionknowledgelink",
        ["question_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_examquestionknowledgelink_knowledge_point_id"),
        "examquestionknowledgelink",
        ["knowledge_point_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_examquestionknowledgelink_knowledge_point_id"),
        table_name="examquestionknowledgelink",
    )
    op.drop_index(
        op.f("ix_examquestionknowledgelink_question_id"),
        table_name="examquestionknowledgelink",
    )
    op.drop_table("examquestionknowledgelink")
    op.drop_index(op.f("ix_knowledgepoint_subject"), table_name="knowledgepoint")
    op.drop_table("knowledgepoint")
    postgresql.ENUM(name="questionknowledgesource").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="knowledgepointsource").drop(op.get_bind(), checkfirst=True)
