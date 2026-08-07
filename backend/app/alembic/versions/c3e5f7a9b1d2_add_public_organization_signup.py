"""Add public organization signup.

Revision ID: c3e5f7a9b1d2
Revises: b2d4f6a8c0e1
Create Date: 2026-07-28 12:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c3e5f7a9b1d2"
down_revision = "b2d4f6a8c0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    organization_type = postgresql.ENUM(
        "school",
        "training",
        "other",
        name="organizationtype",
        create_type=False,
    )
    postgresql.ENUM(
        "school", "training", "other", name="organizationtype"
    ).create(op.get_bind(), checkfirst=True)
    op.add_column(
        "organization",
        sa.Column(
            "organization_type",
            organization_type,
            server_default="school",
            nullable=False,
        ),
    )
    op.create_table(
        "pendingorganizationsignup",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_type", organization_type, nullable=False),
        sa.Column("organization_name", sa.String(length=200), nullable=False),
        sa.Column("contact_name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pendingorganizationsignup_email",
        "pendingorganizationsignup",
        ["email"],
        unique=True,
    )
    op.create_index(
        "ix_pendingorganizationsignup_token_hash",
        "pendingorganizationsignup",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pendingorganizationsignup_token_hash",
        table_name="pendingorganizationsignup",
    )
    op.drop_index(
        "ix_pendingorganizationsignup_email",
        table_name="pendingorganizationsignup",
    )
    op.drop_table("pendingorganizationsignup")
    op.drop_column("organization", "organization_type")
    sa.Enum(name="organizationtype").drop(op.get_bind(), checkfirst=True)
