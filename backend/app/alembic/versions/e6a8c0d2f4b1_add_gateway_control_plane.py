"""Add production gateway control plane, risk limits and reconciliation.

Revision ID: e6a8c0d2f4b1
Revises: d4f6a8b0c2e1
Create Date: 2026-07-26 18:00:00.000000
"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e6a8c0d2f4b1"
down_revision = "d4f6a8b0c2e1"
branch_labels = None
depends_on = None


channel_status = postgresql.ENUM(
    "draft", "active", "draining", "disabled",
    name="providerchannelstatus", create_type=False,
)
route_version_status = postgresql.ENUM(
    "draft", "published", "retired",
    name="modelrouteversionstatus", create_type=False,
)
risk_state = postgresql.ENUM(
    "normal", "throttled", "blocked", "frozen",
    name="organizationriskstate", create_type=False,
)
reconciliation_status = postgresql.ENUM(
    "pending", "matched", "mismatch", "missing_upstream",
    name="usagereconciliationstatus", create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    channel_status.create(bind, checkfirst=True)
    route_version_status.create(bind, checkfirst=True)
    risk_state.create(bind, checkfirst=True)
    reconciliation_status.create(bind, checkfirst=True)

    op.add_column(
        "providerchannel",
        sa.Column("status", channel_status, nullable=False, server_default="draft"),
    )
    op.execute(
        "UPDATE providerchannel SET status = (CASE WHEN enabled THEN 'active' "
        "ELSE 'disabled' END)::providerchannelstatus"
    )
    op.add_column(
        "providermodelmapping",
        sa.Column("usage_metering_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "providermodelmapping",
        sa.Column("usage_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE providermodelmapping m SET usage_metering_verified = true, "
        "usage_verified_at = now() WHERE EXISTS (SELECT 1 FROM modelusageevent u "
        "WHERE u.channel_id = m.channel_id AND u.actual_model = m.canonical_model "
        "AND u.status = 'succeeded' AND u.total_tokens > 0)"
    )

    op.create_table(
        "standardmodel",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sqlmodel.sql.sqltypes.AutoString(200), nullable=False),
        sa.Column("display_name", sqlmodel.sql.sqltypes.AutoString(200), nullable=False),
        sa.Column("supports_vision", sa.Boolean(), nullable=False),
        sa.Column("supports_structured_output", sa.Boolean(), nullable=False),
        sa.Column("requires_usage", sa.Boolean(), nullable=False),
        sa.Column("production_ready", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_standardmodel_code", "standardmodel", ["code"], unique=True)
    op.execute(
        "INSERT INTO standardmodel "
        "(id, code, display_name, supports_vision, supports_structured_output, "
        "requires_usage, production_ready, created_at, updated_at) "
        "SELECT gen_random_uuid(), canonical_model, canonical_model, "
        "bool_or(supports_vision), bool_or(supports_structured_output), true, "
        "bool_or(usage_metering_verified), now(), now() "
        "FROM providermodelmapping GROUP BY canonical_model"
    )
    op.add_column("platformmodeloffering", sa.Column("standard_model_id", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_platformmodeloffering_standard_model_id",
        "platformmodeloffering", ["standard_model_id"], unique=False,
    )
    op.create_foreign_key(
        "fk_offering_standard_model", "platformmodeloffering", "standardmodel",
        ["standard_model_id"], ["id"], ondelete="RESTRICT",
    )
    op.execute(
        "UPDATE platformmodeloffering o SET standard_model_id = m.id "
        "FROM standardmodel m WHERE m.code = o.canonical_model"
    )

    op.create_table(
        "modelrouteversion",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", route_version_status, nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("sticky_scope", sqlmodel.sql.sqltypes.AutoString(50), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("published_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["policy_id"], ["modelroutepolicy.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["published_by_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("policy_id", "version", name="uq_route_policy_version"),
    )
    op.create_index("ix_modelrouteversion_policy_id", "modelrouteversion", ["policy_id"])
    op.create_table(
        "modelrouteversiontarget",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("route_version_id", sa.Uuid(), nullable=False),
        sa.Column("mapping_id", sa.Uuid(), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["route_version_id"], ["modelrouteversion.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["mapping_id"], ["providermodelmapping.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("route_version_id", "mapping_id", name="uq_route_version_mapping"),
    )
    op.create_index("ix_modelrouteversiontarget_route_version_id", "modelrouteversiontarget", ["route_version_id"])
    op.execute(
        "INSERT INTO modelrouteversion "
        "(id, policy_id, version, status, max_attempts, sticky_scope, created_at, published_at) "
        "SELECT gen_random_uuid(), id, 1, 'published'::modelrouteversionstatus, max_attempts, sticky_scope, created_at, now() "
        "FROM modelroutepolicy"
    )
    op.execute(
        "INSERT INTO modelrouteversiontarget "
        "(id, route_version_id, mapping_id, tier, weight, enabled) "
        "SELECT gen_random_uuid(), ranked.route_version_id, ranked.mapping_id, "
        "ranked.tier, ranked.weight, ranked.enabled FROM ("
        "SELECT v.id AS route_version_id, t.mapping_id, "
        "dense_rank() OVER (PARTITION BY t.policy_id ORDER BY t.priority) AS tier, "
        "t.weight, t.enabled FROM modelroutetarget t JOIN modelrouteversion v "
        "ON v.policy_id = t.policy_id AND v.version = 1) ranked"
    )

    op.create_table(
        "offeringrateversion",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("offering_id", sa.Uuid(), nullable=False),
        sa.Column("version", sqlmodel.sql.sqltypes.AutoString(50), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_microcredits_per_million", sa.BigInteger(), nullable=False),
        sa.Column("output_microcredits_per_million", sa.BigInteger(), nullable=False),
        sa.Column("image_microcredits_per_million", sa.BigInteger(), nullable=False),
        sa.Column("target_margin_bps", sa.Integer(), nullable=False),
        sa.Column("minimum_margin_bps", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["offering_id"], ["platformmodeloffering.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("offering_id", "version", name="uq_offering_rate_version"),
    )
    op.create_index("ix_offeringrateversion_offering_id", "offeringrateversion", ["offering_id"])

    op.create_table(
        "organizationusagepolicy",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("risk_state", risk_state, nullable=False),
        sa.Column("calls_per_minute", sa.Integer(), nullable=False),
        sa.Column("max_running_jobs", sa.Integer(), nullable=False),
        sa.Column("max_model_concurrency", sa.Integer(), nullable=False),
        sa.Column("max_job_microcredits", sa.BigInteger(), nullable=False),
        sa.Column("daily_microcredit_cap", sa.BigInteger(), nullable=False),
        sa.Column("monthly_microcredit_cap", sa.BigInteger(), nullable=False),
        sa.Column("reason", sqlmodel.sql.sqltypes.AutoString(500), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_organizationusagepolicy_org_id", "organizationusagepolicy", ["org_id"], unique=True)

    op.create_table(
        "providerreconciliationbatch",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(30), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("imported_by_id", sa.Uuid(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("matched_count", sa.Integer(), nullable=False),
        sa.Column("mismatch_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["providerchannel.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["imported_by_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_providerreconciliationbatch_channel_id", "providerreconciliationbatch", ["channel_id"])

    op.add_column("modelusageevent", sa.Column("route_version_id", sa.Uuid(), nullable=True))
    op.add_column("modelusageevent", sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("modelusageevent", sa.Column("attempt_kind", sqlmodel.sql.sqltypes.AutoString(30), nullable=False, server_default="primary"))
    op.add_column("modelusageevent", sa.Column("offering_rate_version_id", sa.Uuid(), nullable=True))
    op.add_column("modelusageevent", sa.Column("reconciliation_status", reconciliation_status, nullable=False, server_default="pending"))
    op.create_foreign_key("fk_usage_route_version", "modelusageevent", "modelrouteversion", ["route_version_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_usage_offering_rate", "modelusageevent", "offeringrateversion", ["offering_rate_version_id"], ["id"])
    op.create_index("ix_modelusageevent_route_version_id", "modelusageevent", ["route_version_id"])

    op.create_table(
        "providerreconciliationitem",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("usage_event_id", sa.Uuid(), nullable=True),
        sa.Column("upstream_request_id", sqlmodel.sql.sqltypes.AutoString(255), nullable=True),
        sa.Column("upstream_input_tokens", sa.Integer(), nullable=False),
        sa.Column("upstream_output_tokens", sa.Integer(), nullable=False),
        sa.Column("upstream_cost_micrormb", sa.BigInteger(), nullable=False),
        sa.Column("status", reconciliation_status, nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["providerreconciliationbatch.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["usage_event_id"], ["modelusageevent.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_providerreconciliationitem_batch_id", "providerreconciliationitem", ["batch_id"])
    op.create_index("ix_providerreconciliationitem_usage_event_id", "providerreconciliationitem", ["usage_event_id"])
    op.create_index("ix_providerreconciliationitem_upstream_request_id", "providerreconciliationitem", ["upstream_request_id"])


def downgrade() -> None:
    op.drop_table("providerreconciliationitem")
    op.drop_index("ix_modelusageevent_route_version_id", table_name="modelusageevent")
    op.drop_constraint("fk_usage_offering_rate", "modelusageevent", type_="foreignkey")
    op.drop_constraint("fk_usage_route_version", "modelusageevent", type_="foreignkey")
    for column in (
        "reconciliation_status", "offering_rate_version_id", "attempt_kind",
        "attempt_number", "route_version_id",
    ):
        op.drop_column("modelusageevent", column)
    op.drop_table("providerreconciliationbatch")
    op.drop_table("organizationusagepolicy")
    op.drop_table("offeringrateversion")
    op.drop_table("modelrouteversiontarget")
    op.drop_table("modelrouteversion")
    op.drop_constraint("fk_offering_standard_model", "platformmodeloffering", type_="foreignkey")
    op.drop_index("ix_platformmodeloffering_standard_model_id", table_name="platformmodeloffering")
    op.drop_column("platformmodeloffering", "standard_model_id")
    op.drop_table("standardmodel")
    op.drop_column("providermodelmapping", "usage_verified_at")
    op.drop_column("providermodelmapping", "usage_metering_verified")
    op.drop_column("providerchannel", "status")
    reconciliation_status.drop(op.get_bind(), checkfirst=True)
    risk_state.drop(op.get_bind(), checkfirst=True)
    route_version_status.drop(op.get_bind(), checkfirst=True)
    channel_status.drop(op.get_bind(), checkfirst=True)
