"""Add auto_confirmed to submission registration status enum

Revision ID: b4e6c8d0a213
Revises: a3f5b7c9d102
Create Date: 2026-07-21 01:30:00.000000

"""

from alembic import op


revision = "b4e6c8d0a213"
down_revision = "a3f5b7c9d102"
branch_labels = None
depends_on = None


def upgrade():
    # ALTER TYPE ... ADD VALUE 不能在事务块内执行，需要 autocommit。
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE submissionregistrationstatus "
            "ADD VALUE IF NOT EXISTS 'auto_confirmed'"
        )


def downgrade():
    # Postgres 不支持删除枚举值，留空。
    pass
