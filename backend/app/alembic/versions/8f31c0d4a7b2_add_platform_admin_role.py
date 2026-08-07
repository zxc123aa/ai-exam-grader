"""Add the writable platform administrator role.

Revision ID: 8f31c0d4a7b2
Revises: 24301a6c50ac
Create Date: 2026-07-26 10:00:00.000000
"""

from alembic import op


revision = "8f31c0d4a7b2"
down_revision = "24301a6c50ac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'platform_admin'")


def downgrade() -> None:
    op.execute(
        "UPDATE \"user\" SET role = 'platform_support'"
        " WHERE role = 'platform_admin'"
    )
    # PostgreSQL enum values cannot be removed without rebuilding the type.
