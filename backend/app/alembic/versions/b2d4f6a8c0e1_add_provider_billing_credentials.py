"""Add dedicated provider billing credentials.

Revision ID: b2d4f6a8c0e1
Revises: a1c3e5f7b9d2
Create Date: 2026-07-27 19:20:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "b2d4f6a8c0e1"
down_revision = "a1c3e5f7b9d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "providercredential", sa.Column("billing_ciphertext", sa.Text(), nullable=True)
    )
    op.add_column(
        "providercredential",
        sa.Column("billing_nonce", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "providercredential",
        sa.Column(
            "billing_key_version", sa.Integer(), server_default="1", nullable=False
        ),
    )
    op.add_column(
        "providercredential",
        sa.Column("billing_fingerprint", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "providercredential",
        sa.Column("billing_last_four", sa.String(length=4), nullable=True),
    )
    op.add_column(
        "providercredential", sa.Column("billing_user_id", sa.Integer(), nullable=True)
    )
    op.create_check_constraint(
        "ck_providercredential_billing_user_id_positive",
        "providercredential",
        "billing_user_id IS NULL OR billing_user_id >= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_providercredential_billing_user_id_positive",
        "providercredential",
        type_="check",
    )
    for name in (
        "billing_user_id",
        "billing_last_four",
        "billing_fingerprint",
        "billing_key_version",
        "billing_nonce",
        "billing_ciphertext",
    ):
        op.drop_column("providercredential", name)
