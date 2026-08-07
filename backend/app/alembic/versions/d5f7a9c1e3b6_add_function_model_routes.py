"""Add multi-model function assignments and immutable route snapshots.

Revision ID: d5f7a9c1e3b6
Revises: c4e6f8a0b2d5
Create Date: 2026-07-27 18:00:00.000000
"""

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "d5f7a9c1e3b6"
down_revision = "c4e6f8a0b2d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "modelroutepolicy",
        sa.Column(
            "routing_mode",
            sqlmodel.sql.sqltypes.AutoString(20),
            server_default="balanced",
            nullable=False,
        ),
    )
    op.add_column(
        "modelrouteversion",
        sa.Column(
            "routing_mode",
            sqlmodel.sql.sqltypes.AutoString(20),
            server_default="balanced",
            nullable=False,
        ),
    )
    op.create_table(
        "functionmodelassignment",
        sa.Column("purpose", sqlmodel.sql.sqltypes.AutoString(50), nullable=False),
        sa.Column(
            "default_canonical_model",
            sqlmodel.sql.sqltypes.AutoString(200),
            nullable=False,
        ),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["updated_by_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("purpose"),
    )
    op.create_index(
        "ix_functionmodelassignment_default_canonical_model",
        "functionmodelassignment",
        ["default_canonical_model"],
    )
    op.execute(
        "INSERT INTO functionmodelassignment "
        "(purpose, default_canonical_model, updated_at) "
        "SELECT DISTINCT ON (purpose) purpose, canonical_model, updated_at "
        "FROM modelroutepolicy WHERE enabled = true "
        "ORDER BY purpose, updated_at DESC"
    )
    op.execute(
        "UPDATE functionmodelassignment a "
        "SET default_canonical_model = 'gpt-5.6-sol' "
        "WHERE a.purpose IN "
        "('rubric_generation', 'rubric_validation', 'subjective_grading') "
        "AND EXISTS (SELECT 1 FROM modelroutepolicy p "
        "WHERE p.purpose = a.purpose "
        "AND p.canonical_model = 'gpt-5.6-sol' AND p.enabled = true)"
    )

    op.add_column(
        "modelrouteversiontarget", sa.Column("channel_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "modelrouteversiontarget",
        sa.Column("channel_code", sqlmodel.sql.sqltypes.AutoString(100), nullable=True),
    )
    op.add_column(
        "modelrouteversiontarget",
        sa.Column(
            "canonical_model", sqlmodel.sql.sqltypes.AutoString(200), nullable=True
        ),
    )
    op.add_column(
        "modelrouteversiontarget",
        sa.Column(
            "upstream_model", sqlmodel.sql.sqltypes.AutoString(200), nullable=True
        ),
    )
    op.add_column(
        "modelrouteversiontarget",
        sa.Column(
            "protocol",
            sa.Enum(name="providerprotocol", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "modelrouteversiontarget",
        sa.Column("base_url", sqlmodel.sql.sqltypes.AutoString(500), nullable=True),
    )
    op.add_column(
        "modelrouteversiontarget",
        sa.Column("internal_rate_version_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "modelrouteversiontarget",
        sa.Column(
            "cost_micrormb_per_million",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE modelrouteversiontarget t SET "
        "channel_id = m.channel_id, channel_code = c.code, "
        "canonical_model = m.canonical_model, upstream_model = m.upstream_model, "
        "protocol = c.protocol, base_url = c.base_url "
        "FROM providermodelmapping m JOIN providerchannel c ON c.id = m.channel_id "
        "WHERE t.mapping_id = m.id"
    )
    for column in (
        "channel_id",
        "channel_code",
        "canonical_model",
        "upstream_model",
        "protocol",
        "base_url",
    ):
        op.alter_column("modelrouteversiontarget", column, nullable=False)
    op.drop_constraint(
        "modelrouteversiontarget_mapping_id_fkey",
        "modelrouteversiontarget",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_route_snapshot_mapping",
        "modelrouteversiontarget",
        "providermodelmapping",
        ["mapping_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_route_snapshot_channel",
        "modelrouteversiontarget",
        "providerchannel",
        ["channel_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_route_snapshot_rate",
        "modelrouteversiontarget",
        "providerinternalrateversion",
        ["internal_rate_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_modelrouteversiontarget_channel_id",
        "modelrouteversiontarget",
        ["channel_id"],
    )
    op.create_index(
        "ix_modelrouteversiontarget_canonical_model",
        "modelrouteversiontarget",
        ["canonical_model"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_modelrouteversiontarget_canonical_model",
        table_name="modelrouteversiontarget",
    )
    op.drop_index(
        "ix_modelrouteversiontarget_channel_id", table_name="modelrouteversiontarget"
    )
    op.drop_constraint(
        "fk_route_snapshot_rate", "modelrouteversiontarget", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_route_snapshot_channel", "modelrouteversiontarget", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_route_snapshot_mapping", "modelrouteversiontarget", type_="foreignkey"
    )
    op.create_foreign_key(
        "modelrouteversiontarget_mapping_id_fkey",
        "modelrouteversiontarget",
        "providermodelmapping",
        ["mapping_id"],
        ["id"],
        ondelete="CASCADE",
    )
    for column in (
        "cost_micrormb_per_million",
        "internal_rate_version_id",
        "base_url",
        "protocol",
        "upstream_model",
        "canonical_model",
        "channel_code",
        "channel_id",
    ):
        op.drop_column("modelrouteversiontarget", column)
    op.drop_index(
        "ix_functionmodelassignment_default_canonical_model",
        table_name="functionmodelassignment",
    )
    op.drop_table("functionmodelassignment")
    op.drop_column("modelrouteversion", "routing_mode")
    op.drop_column("modelroutepolicy", "routing_mode")
