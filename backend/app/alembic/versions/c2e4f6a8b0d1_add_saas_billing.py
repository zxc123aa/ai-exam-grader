"""Add SaaS subscriptions, credit ledger, reservations and model usage.

Revision ID: c2e4f6a8b0d1
Revises: b9d1e3f5a702
Create Date: 2026-07-25 10:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c2e4f6a8b0d1"
down_revision = "b9d1e3f5a702"
branch_labels = None
depends_on = None


subscription_status = postgresql.ENUM(
    "draft",
    "active",
    "expired",
    "suspended",
    name="subscriptionstatus",
    create_type=False,
)
grant_source = postgresql.ENUM(
    "subscription",
    "top_up",
    "adjustment",
    name="creditgrantsource",
    create_type=False,
)
reservation_status = postgresql.ENUM(
    "active",
    "settled",
    "released",
    name="creditreservationstatus",
    create_type=False,
)
usage_status = postgresql.ENUM(
    "succeeded",
    "failed",
    "missing_usage",
    name="modelusagestatus",
    create_type=False,
)


def upgrade():
    subscription_status.create(op.get_bind(), checkfirst=True)
    grant_source.create(op.get_bind(), checkfirst=True)
    reservation_status.create(op.get_bind(), checkfirst=True)
    usage_status.create(op.get_bind(), checkfirst=True)
    op.execute("ALTER TYPE gradingrunstatus ADD VALUE IF NOT EXISTS 'awaiting_credits'")

    op.add_column(
        "gradingrun",
        sa.Column(
            "estimated_microcredits",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "gradingrun",
        sa.Column(
            "reserved_microcredits", sa.BigInteger(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "gradingrun",
        sa.Column(
            "settled_microcredits", sa.BigInteger(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "gradingrun",
        sa.Column(
            "billing_status", sa.String(30), nullable=False, server_default="unmetered"
        ),
    )

    op.create_table(
        "billingrateversion",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_microcredits_per_million", sa.BigInteger(), nullable=False),
        sa.Column("output_microcredits_per_million", sa.BigInteger(), nullable=False),
        sa.Column("image_microcredits_per_million", sa.BigInteger(), nullable=False),
        sa.Column(
            "internal_input_micrormb_per_million",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "internal_output_micrormb_per_million",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "internal_image_micrormb_per_million",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version"),
    )
    op.create_index(
        "ix_billingrateversion_version", "billingrateversion", ["version"], unique=True
    )
    op.create_table(
        "organizationsubscription",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("contract_no", sa.String(100), nullable=False),
        sa.Column("plan_code", sa.String(50), nullable=False),
        sa.Column("status", subscription_status, nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rate_version_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["rate_version_id"], ["billingrateversion.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contract_no"),
    )
    op.create_index(
        "ix_organizationsubscription_org_id", "organizationsubscription", ["org_id"]
    )
    op.create_index(
        "ix_organizationsubscription_contract_no",
        "organizationsubscription",
        ["contract_no"],
        unique=True,
    )
    op.create_table(
        "creditgrant",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
        sa.Column("source", grant_source, nullable=False),
        sa.Column("total_microcredits", sa.BigInteger(), nullable=False),
        sa.Column(
            "reserved_microcredits", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "consumed_microcredits", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["subscription_id"], ["organizationsubscription.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_creditgrant_org_id", "creditgrant", ["org_id"])
    op.create_index(
        "ix_creditgrant_subscription_id", "creditgrant", ["subscription_id"]
    )
    op.create_table(
        "creditreservation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("grading_run_id", sa.Uuid(), nullable=True),
        sa.Column("task_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(100), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("estimated_microcredits", sa.BigInteger(), nullable=False),
        sa.Column(
            "settled_microcredits", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("status", reservation_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["grading_run_id"], ["gradingrun.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_creditreservation_org_id", "creditreservation", ["org_id"])
    op.create_index(
        "ix_creditreservation_grading_run_id", "creditreservation", ["grading_run_id"]
    )
    op.create_index(
        "ix_creditreservation_idempotency_key",
        "creditreservation",
        ["idempotency_key"],
        unique=True,
    )
    op.create_table(
        "creditreservationallocation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reservation_id", sa.Uuid(), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("reserved_microcredits", sa.BigInteger(), nullable=False),
        sa.Column(
            "consumed_microcredits", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id"], ["creditreservation.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["grant_id"], ["creditgrant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reservation_id", "grant_id", name="uq_reservation_grant"),
    )
    op.create_index(
        "ix_creditreservationallocation_reservation_id",
        "creditreservationallocation",
        ["reservation_id"],
    )
    op.create_index(
        "ix_creditreservationallocation_grant_id",
        "creditreservationallocation",
        ["grant_id"],
    )
    op.create_table(
        "creditledgerentry",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=True),
        sa.Column("reservation_id", sa.Uuid(), nullable=True),
        sa.Column("entry_type", sa.String(30), nullable=False),
        sa.Column("amount_microcredits", sa.BigInteger(), nullable=False),
        sa.Column("balance_after_microcredits", sa.BigInteger(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["grant_id"], ["creditgrant.id"]),
        sa.ForeignKeyConstraint(["reservation_id"], ["creditreservation.id"]),
        sa.ForeignKeyConstraint(["actor_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("org_id", "grant_id", "reservation_id", "entry_type", "created_at"):
        op.create_index(f"ix_creditledgerentry_{column}", "creditledgerentry", [column])
    op.create_table(
        "modelusageevent",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("exam_id", sa.Uuid(), nullable=True),
        sa.Column("grading_run_id", sa.Uuid(), nullable=True),
        sa.Column("reservation_id", sa.Uuid(), nullable=True),
        sa.Column("resource_id", sa.String(100), nullable=False),
        sa.Column("workflow_purpose", sa.String(50), nullable=False),
        sa.Column("requested_provider", sa.String(100), nullable=False),
        sa.Column("requested_model", sa.String(200), nullable=False),
        sa.Column("actual_provider", sa.String(100), nullable=True),
        sa.Column("actual_model", sa.String(200), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("image_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", usage_status, nullable=False),
        sa.Column(
            "fallback_used", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column(
            "customer_microcredits", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "internal_cost_micrormb",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("billing_key", sa.String(255), nullable=False),
        sa.Column("rate_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["exam_id"], ["exam.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["grading_run_id"], ["gradingrun.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id"], ["creditreservation.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["rate_version_id"], ["billingrateversion.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("billing_key"),
    )
    for column in (
        "org_id",
        "exam_id",
        "grading_run_id",
        "reservation_id",
        "workflow_purpose",
        "billing_key",
        "created_at",
    ):
        op.create_index(
            f"ix_modelusageevent_{column}",
            "modelusageevent",
            [column],
            unique=column == "billing_key",
        )


def downgrade():
    op.drop_table("modelusageevent")
    op.drop_table("creditledgerentry")
    op.drop_table("creditreservationallocation")
    op.drop_table("creditreservation")
    op.drop_table("creditgrant")
    op.drop_table("organizationsubscription")
    op.drop_table("billingrateversion")
    op.drop_column("gradingrun", "billing_status")
    op.drop_column("gradingrun", "settled_microcredits")
    op.drop_column("gradingrun", "reserved_microcredits")
    op.drop_column("gradingrun", "estimated_microcredits")
    usage_status.drop(op.get_bind(), checkfirst=True)
    reservation_status.drop(op.get_bind(), checkfirst=True)
    grant_source.drop(op.get_bind(), checkfirst=True)
    subscription_status.drop(op.get_bind(), checkfirst=True)
