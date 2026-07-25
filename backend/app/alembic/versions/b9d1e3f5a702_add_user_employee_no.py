"""Add employee_no to user

花名册批量导入：user.employee_no 教职工工号（可空，max 50）。

Revision ID: b9d1e3f5a702
Revises: f7a3b5c9d2e4
Create Date: 2026-07-24 16:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "b9d1e3f5a702"
down_revision = "f7a3b5c9d2e4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user",
        sa.Column("employee_no", sa.String(length=50), nullable=True),
    )


def downgrade():
    op.drop_column("user", "employee_no")
