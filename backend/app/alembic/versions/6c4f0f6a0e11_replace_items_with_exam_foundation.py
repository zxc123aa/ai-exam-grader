"""Replace items with exam foundation

Revision ID: 6c4f0f6a0e11
Revises: fe56fa70289e
Create Date: 2026-06-30 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel.sql.sqltypes


revision = "6c4f0f6a0e11"
down_revision = "fe56fa70289e"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("item")
    op.create_table(
        "exam",
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("subject", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
        sa.Column(
            "grade_level", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True
        ),
        sa.Column("status", sa.Enum("draft", "active", "archived", name="examstatus"), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "storedfile",
        sa.Column(
            "original_filename",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column(
            "content_type", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True
        ),
        sa.Column(
            "storage_key", sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False
        ),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uploaded_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["uploaded_by_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index(op.f("ix_storedfile_sha256"), "storedfile", ["sha256"], unique=False)
    op.create_table(
        "processingtask",
        sa.Column("task_type", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column(
            "status",
            sa.Enum("queued", "running", "succeeded", "failed", name="processingtaskstatus"),
            nullable=False,
        ),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column(
            "error_message", sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=True
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_ref", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("output_ref", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("processingtask")
    op.drop_index(op.f("ix_storedfile_sha256"), table_name="storedfile")
    op.drop_table("storedfile")
    op.drop_table("exam")
    op.create_table(
        "item",
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
