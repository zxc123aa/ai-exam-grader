"""Enforce one invoice and one refund request per commerce order.

Revision ID: c4e6f8a0b2d5
Revises: b3d5f7a9c1e4
Create Date: 2026-07-27 15:00:00.000000
"""

from alembic import op

revision = "c4e6f8a0b2d5"
down_revision = "b3d5f7a9c1e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_invoice_application_order", "invoiceapplication", ["order_id"]
    )
    op.create_unique_constraint(
        "uq_refund_request_order", "refundrequest", ["order_id"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_refund_request_order", "refundrequest", type_="unique"
    )
    op.drop_constraint(
        "uq_invoice_application_order", "invoiceapplication", type_="unique"
    )
