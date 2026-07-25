"""Add system_config table (platform grading defaults)

平台级系统配置表：key 主键 + JSONB value，存放模型与批改默认值
（视觉/判题 provider/model、备用模型、复核阈值、并发），仅平台超管可写，
DB 无记录时回落 env 默认。

Revision ID: d5e7f9a1b3c5
Revises: c4d6e8f0a2b4
Create Date: 2026-07-23 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "d5e7f9a1b3c5"
down_revision = "c4d6e8f0a2b4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "systemconfig",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade():
    op.drop_table("systemconfig")
