"""Add exam documents

Revision ID: b7d4c6e8f901
Revises: 6c4f0f6a0e11
Create Date: 2026-06-30 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "b7d4c6e8f901"
down_revision = "6c4f0f6a0e11"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "examdocument",
        sa.Column(
            "document_type",
            sa.Enum("blank_exam", "answer_key", name="examdocumenttype"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exam_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stored_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exam.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["stored_file_id"], ["storedfile.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("examdocument")
    op.execute("DROP TYPE IF EXISTS examdocumenttype")
