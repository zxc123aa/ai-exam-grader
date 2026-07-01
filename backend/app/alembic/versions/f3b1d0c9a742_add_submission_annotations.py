"""Add submission annotations

Revision ID: f3b1d0c9a742
Revises: e8c3b2a1f904
Create Date: 2026-07-01 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel.sql.sqltypes


revision = "f3b1d0c9a742"
down_revision = "e8c3b2a1f904"
branch_labels = None
depends_on = None


def upgrade():
    annotation_status = postgresql.ENUM(
        "needs_review",
        "accepted",
        "rejected",
        name="submissionannotationstatus",
        create_type=False,
    )
    postgresql.ENUM(
        "needs_review",
        "accepted",
        "rejected",
        name="submissionannotationstatus",
    ).create(op.get_bind(), checkfirst=True)
    op.create_table(
        "submissionannotation",
        sa.Column("label", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column("status", annotation_status, nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column("width", sa.Float(), nullable=False),
        sa.Column("height", sa.Float(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("max_score", sa.Float(), nullable=True),
        sa.Column(
            "comment",
            sqlmodel.sql.sqltypes.AutoString(length=2000),
            nullable=True,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("exam_region_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["exam_region_id"],
            ["examregion.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["studentsubmission.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("submissionannotation")
    op.execute("DROP TYPE IF EXISTS submissionannotationstatus")
