"""Add error reason annotation to wrongbook entries.

Revision ID: c1d3e5f7a9b2
Revises: b0d2f4a6c8e1
Create Date: 2026-08-15 14:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c1d3e5f7a9b2"
down_revision = "b0d2f4a6c8e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    error_reason = postgresql.ENUM(
        "concept",
        "calculation",
        "reading",
        "unknown_knowledge",
        name="wrongquestionerrorreason",
        create_type=False,
    )
    error_reason.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "wrongquestionentry",
        sa.Column("error_reason", error_reason, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("wrongquestionentry", "error_reason")
    postgresql.ENUM(name="wrongquestionerrorreason").drop(
        op.get_bind(), checkfirst=True
    )
