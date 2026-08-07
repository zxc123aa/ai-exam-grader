"""Add versioned commerce catalog, orders, payments, invoices and outbox.

Revision ID: a2c4e6f8b0d3
Revises: d1f5b8c2e904
Create Date: 2026-07-27 10:00:00.000000
"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a2c4e6f8b0d3"
down_revision = "d1f5b8c2e904"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    order_status = postgresql.ENUM(
        "pending_payment", "paid", "fulfilled", "closed", "refunding", "refunded",
        name="commerceorderstatus", create_type=False,
    )
    payment_method = postgresql.ENUM(
        "wechat_native", "bank_transfer", name="paymentmethod", create_type=False
    )
    payment_status = postgresql.ENUM(
        "pending", "succeeded", "failed", "closed", "refunded",
        name="paymentstatus", create_type=False,
    )
    invoice_status = postgresql.ENUM(
        "submitted", "approved", "issued", "rejected",
        name="invoicestatus", create_type=False,
    )
    refund_status = postgresql.ENUM(
        "requested", "approved", "processing", "succeeded", "rejected", "failed",
        name="refundstatus", create_type=False,
    )
    for enum in (order_status, payment_method, payment_status, invoice_status, refund_status):
        enum.create(bind, checkfirst=True)

    op.create_table(
        "planversion",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sqlmodel.sql.sqltypes.AutoString(50), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("display_name", sqlmodel.sql.sqltypes.AutoString(100), nullable=False),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(500), nullable=True),
        sa.Column("annual_price_cents", sa.BigInteger(), nullable=False),
        sa.Column("included_answers", sa.Integer(), nullable=False),
        sa.Column("validity_days", sa.Integer(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "version", name="uq_plan_version"),
    )
    op.create_index("ix_planversion_code", "planversion", ["code"])
    op.create_table(
        "addonsku",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sqlmodel.sql.sqltypes.AutoString(50), nullable=False),
        sa.Column("display_name", sqlmodel.sql.sqltypes.AutoString(100), nullable=False),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(500), nullable=True),
        sa.Column("answer_quota", sa.Integer(), nullable=False),
        sa.Column("price_cents", sa.BigInteger(), nullable=False),
        sa.Column("validity_days", sa.Integer(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("code"),
    )
    op.create_index("ix_addonsku_code", "addonsku", ["code"], unique=True)
    op.create_table(
        "commerceorder",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_no", sqlmodel.sql.sqltypes.AutoString(64), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("status", order_status, nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("currency", sqlmodel.sql.sqltypes.AutoString(3), nullable=False),
        sa.Column("idempotency_key", sqlmodel.sql.sqltypes.AutoString(128), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_no"), sa.UniqueConstraint("idempotency_key"),
    )
    for name in ("order_no", "org_id", "idempotency_key", "created_at"):
        op.create_index(f"ix_commerceorder_{name}", "commerceorder", [name], unique=name in {"order_no", "idempotency_key"})
    op.create_table(
        "orderitem",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("item_type", sqlmodel.sql.sqltypes.AutoString(20), nullable=False),
        sa.Column("sku_code", sqlmodel.sql.sqltypes.AutoString(50), nullable=False),
        sa.Column("display_name", sqlmodel.sql.sqltypes.AutoString(100), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_cents", sa.BigInteger(), nullable=False),
        sa.Column("answer_quota", sa.Integer(), nullable=False),
        sa.Column("validity_days", sa.Integer(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["commerceorder.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_orderitem_order_id", "orderitem", ["order_id"])
    op.create_table(
        "paymentattempt",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("method", payment_method, nullable=False),
        sa.Column("status", payment_status, nullable=False),
        sa.Column("provider_transaction_id", sqlmodel.sql.sqltypes.AutoString(128), nullable=True),
        sa.Column("request_id", sqlmodel.sql.sqltypes.AutoString(128), nullable=True),
        sa.Column("code_url", sqlmodel.sql.sqltypes.AutoString(1000), nullable=True),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("raw_response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["order_id"], ["commerceorder.id"]),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("provider_transaction_id"),
    )
    op.create_index("ix_paymentattempt_order_id", "paymentattempt", ["order_id"])
    op.create_index("ix_paymentattempt_created_at", "paymentattempt", ["created_at"])
    op.create_table(
        "paymentwebhookevent",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sqlmodel.sql.sqltypes.AutoString(128), nullable=False),
        sa.Column("provider", sqlmodel.sql.sqltypes.AutoString(30), nullable=False),
        sa.Column("event_type", sqlmodel.sql.sqltypes.AutoString(100), nullable=False),
        sa.Column("signature_verified", sa.Boolean(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_error", sqlmodel.sql.sqltypes.AutoString(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("event_id"),
    )
    op.create_index("ix_paymentwebhookevent_event_id", "paymentwebhookevent", ["event_id"], unique=True)
    op.create_index("ix_paymentwebhookevent_created_at", "paymentwebhookevent", ["created_at"])
    op.create_table(
        "invoiceapplication",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False), sa.Column("title", sqlmodel.sql.sqltypes.AutoString(200), nullable=False),
        sa.Column("tax_number", sqlmodel.sql.sqltypes.AutoString(50), nullable=False), sa.Column("email", sqlmodel.sql.sqltypes.AutoString(255), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False), sa.Column("status", invoice_status, nullable=False),
        sa.Column("invoice_no", sqlmodel.sql.sqltypes.AutoString(100), nullable=True), sa.Column("reject_reason", sqlmodel.sql.sqltypes.AutoString(500), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["commerceorder.id"]), sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["user.id"]), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invoiceapplication_order_id", "invoiceapplication", ["order_id"])
    op.create_index("ix_invoiceapplication_org_id", "invoiceapplication", ["org_id"])
    op.create_index("ix_invoiceapplication_created_at", "invoiceapplication", ["created_at"])
    op.create_table(
        "refundrequest",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("order_id", sa.Uuid(), nullable=False), sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False), sa.Column("reason", sqlmodel.sql.sqltypes.AutoString(500), nullable=False),
        sa.Column("status", refund_status, nullable=False), sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("reviewed_by_id", sa.Uuid(), nullable=True), sa.Column("review_note", sqlmodel.sql.sqltypes.AutoString(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["commerceorder.id"]), sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["requested_by_id"], ["user.id"]), sa.ForeignKeyConstraint(["reviewed_by_id"], ["user.id"]), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_refundrequest_order_id", "refundrequest", ["order_id"])
    op.create_index("ix_refundrequest_org_id", "refundrequest", ["org_id"])
    op.create_index("ix_refundrequest_created_at", "refundrequest", ["created_at"])
    op.create_table(
        "outboxevent",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("event_type", sqlmodel.sql.sqltypes.AutoString(100), nullable=False),
        sa.Column("aggregate_type", sqlmodel.sql.sqltypes.AutoString(50), nullable=False), sa.Column("aggregate_id", sqlmodel.sql.sqltypes.AutoString(100), nullable=False),
        sa.Column("idempotency_key", sqlmodel.sql.sqltypes.AutoString(200), nullable=False), sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True), sa.Column("last_error", sqlmodel.sql.sqltypes.AutoString(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_outboxevent_event_type", "outboxevent", ["event_type"])
    op.create_index("ix_outboxevent_idempotency_key", "outboxevent", ["idempotency_key"], unique=True)
    op.create_index("ix_outboxevent_available_at", "outboxevent", ["available_at"])


def downgrade() -> None:
    for table in ("outboxevent", "refundrequest", "invoiceapplication", "paymentwebhookevent", "paymentattempt", "orderitem", "commerceorder", "addonsku", "planversion"):
        op.drop_table(table)
    bind = op.get_bind()
    for name in ("refundstatus", "invoicestatus", "paymentstatus", "paymentmethod", "commerceorderstatus"):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
