"""add snaprecord

Revision ID: 8939283db86c
Revises: f4a6b8c0d2e5
Create Date: 2026-08-19 00:18:26.708391

拍题答疑/拍照批改的历史记录表（只留本表，autogenerate 带出的无关漂移已剔除）。
"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "8939283db86c"
down_revision = "f4a6b8c0d2e5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "snaprecord",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column(
            "title", sqlmodel.sql.sqltypes.AutoString(length=120), nullable=False
        ),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_snaprecord_created_at"), "snaprecord", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_snaprecord_user_id"), "snaprecord", ["user_id"], unique=False
    )


def downgrade():
    op.drop_index(op.f("ix_snaprecord_user_id"), table_name="snaprecord")
    op.drop_index(op.f("ix_snaprecord_created_at"), table_name="snaprecord")
    op.drop_table("snaprecord")
