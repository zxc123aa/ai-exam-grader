"""Add standard answers

Revision ID: b2c7d8e9f012
Revises: a9c2d4e6f8b0
Create Date: 2026-07-08 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel.sql.sqltypes


revision = "b2c7d8e9f012"
down_revision = "a9c2d4e6f8b0"
branch_labels = None
depends_on = None


def upgrade():
    answer_status = postgresql.ENUM(
        "draft",
        "ready",
        name="standardanswerstatus",
        create_type=False,
    )
    postgresql.ENUM(
        "draft",
        "ready",
        name="standardanswerstatus",
    ).create(op.get_bind(), checkfirst=True)
    op.create_table(
        "standardanswer",
        sa.Column(
            "answer_text",
            sqlmodel.sql.sqltypes.AutoString(length=12000),
            nullable=False,
        ),
        sa.Column("max_score", sa.Float(), nullable=False),
        sa.Column(
            "rubric_text",
            sqlmodel.sql.sqltypes.AutoString(length=8000),
            nullable=True,
        ),
        sa.Column("scoring_points", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", answer_status, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exam_id", sa.Uuid(), nullable=False),
        sa.Column("exam_region_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exam.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["exam_region_id"], ["examregion.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("exam_region_id", name="uq_standardanswer_exam_region_id"),
    )


def downgrade():
    op.drop_table("standardanswer")
    op.execute("DROP TYPE IF EXISTS standardanswerstatus")
