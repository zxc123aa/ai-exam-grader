"""Add exam regions

Revision ID: c2a8e1b4d903
Revises: b7d4c6e8f901
Create Date: 2026-06-30 17:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel.sql.sqltypes


revision = "c2a8e1b4d903"
down_revision = "b7d4c6e8f901"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "examregion",
        sa.Column("label", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column(
            "region_type",
            sa.Enum("question", "answer_area", "header", "other", name="examregiontype"),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column("width", sa.Float(), nullable=False),
        sa.Column("height", sa.Float(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exam_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exam.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("examregion")
    op.execute("DROP TYPE IF EXISTS examregiontype")
