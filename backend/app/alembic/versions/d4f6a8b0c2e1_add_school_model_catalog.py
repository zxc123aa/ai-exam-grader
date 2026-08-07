"""Add school-facing model catalog and per-school selections.

Revision ID: d4f6a8b0c2e1
Revises: 8f31c0d4a7b2
Create Date: 2026-07-26 14:00:00.000000
"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d4f6a8b0c2e1"
down_revision = "8f31c0d4a7b2"
branch_labels = None
depends_on = None

school_model_scope = postgresql.ENUM(
    "vision",
    "reference_answer",
    "grading",
    name="schoolmodelscope",
    create_type=False,
)


def upgrade() -> None:
    school_model_scope.create(op.get_bind(), checkfirst=True)
    op.execute(
        "ALTER TABLE modelroutepolicy DROP CONSTRAINT IF EXISTS uq_route_purpose"
    )
    op.create_unique_constraint(
        "uq_route_purpose_model",
        "modelroutepolicy",
        ["purpose", "canonical_model"],
    )
    op.create_table(
        "platformmodeloffering",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sqlmodel.sql.sqltypes.AutoString(100), nullable=False),
        sa.Column(
            "display_name", sqlmodel.sql.sqltypes.AutoString(100), nullable=False
        ),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(300), nullable=True),
        sa.Column("scope", school_model_scope, nullable=False),
        sa.Column(
            "provider_code", sqlmodel.sql.sqltypes.AutoString(100), nullable=False
        ),
        sa.Column(
            "canonical_model", sqlmodel.sql.sqltypes.AutoString(200), nullable=False
        ),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("school_selectable", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_platformmodeloffering_code",
        "platformmodeloffering",
        ["code"],
        unique=True,
    )
    op.create_index(
        "ix_platformmodeloffering_canonical_model",
        "platformmodeloffering",
        ["canonical_model"],
    )
    op.create_table(
        "organizationmodelselection",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("scope", school_model_scope, nullable=False),
        sa.Column("offering_id", sa.Uuid(), nullable=False),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["offering_id"], ["platformmodeloffering.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["updated_by_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "scope", name="uq_org_model_selection_scope"),
    )
    op.create_index(
        "ix_organizationmodelselection_org_id",
        "organizationmodelselection",
        ["org_id"],
    )
    op.create_index(
        "ix_organizationmodelselection_offering_id",
        "organizationmodelselection",
        ["offering_id"],
    )


def downgrade() -> None:
    op.drop_table("organizationmodelselection")
    op.drop_table("platformmodeloffering")
    op.execute(
        "ALTER TABLE modelroutepolicy DROP CONSTRAINT IF EXISTS uq_route_purpose_model"
    )
    # 旧版本每个用途只能保留一条策略；降级时保留最早创建的策略。
    op.execute(
        """
        DELETE FROM modelroutepolicy newer
        USING modelroutepolicy older
        WHERE newer.purpose = older.purpose
          AND (newer.created_at, newer.id) > (older.created_at, older.id)
        """
    )
    op.create_unique_constraint("uq_route_purpose", "modelroutepolicy", ["purpose"])
    school_model_scope.drop(op.get_bind(), checkfirst=True)
