"""Add student submissions

Revision ID: d4f9a2b7c601
Revises: c2a8e1b4d903
Create Date: 2026-06-30 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel.sql.sqltypes


revision = "d4f9a2b7c601"
down_revision = "c2a8e1b4d903"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "studentsubmission",
        sa.Column(
            "student_name",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.Column(
            "student_identifier",
            sqlmodel.sql.sqltypes.AutoString(length=100),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "uploaded",
                "registration_pending",
                "registration_failed",
                "ready_for_review",
                name="studentsubmissionstatus",
            ),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exam_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stored_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exam.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["stored_file_id"], ["storedfile.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("studentsubmission")
    op.execute("DROP TYPE IF EXISTS studentsubmissionstatus")
