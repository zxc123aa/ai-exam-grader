"""Add submission registration fields

Revision ID: e8c3b2a1f904
Revises: d4f9a2b7c601
Create Date: 2026-07-01 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel.sql.sqltypes


revision = "e8c3b2a1f904"
down_revision = "d4f9a2b7c601"
branch_labels = None
depends_on = None


def upgrade():
    registration_status = sa.Enum(
        "pending",
        "manual_confirmed",
        "failed",
        name="submissionregistrationstatus",
    )
    registration_status.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "studentsubmission",
        sa.Column(
            "registration_status",
            registration_status,
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "studentsubmission",
        sa.Column("registration_quality", sa.Float(), nullable=True),
    )
    op.add_column(
        "studentsubmission",
        sa.Column(
            "registration_notes",
            sqlmodel.sql.sqltypes.AutoString(length=1000),
            nullable=True,
        ),
    )
    op.add_column(
        "studentsubmission",
        sa.Column(
            "registration_homography",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "studentsubmission",
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column("studentsubmission", "registration_status", server_default=None)


def downgrade():
    op.drop_column("studentsubmission", "registered_at")
    op.drop_column("studentsubmission", "registration_homography")
    op.drop_column("studentsubmission", "registration_notes")
    op.drop_column("studentsubmission", "registration_quality")
    op.drop_column("studentsubmission", "registration_status")
    op.execute("DROP TYPE IF EXISTS submissionregistrationstatus")
