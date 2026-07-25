"""Add user role

Revision ID: c8e2f4a6b105
Revises: e5f7a9c1d304
Create Date: 2026-07-23 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "c8e2f4a6b105"
down_revision = "e5f7a9c1d304"
branch_labels = None
depends_on = None


userrole = sa.Enum("superuser", "admin", "teacher", "student", name="userrole")


def upgrade():
    userrole.create(op.get_bind(), checkfirst=True)
    op.add_column("user", sa.Column("role", userrole, nullable=True))
    # 回填：原有超级管理员 -> superuser，其余 -> teacher
    op.execute('UPDATE "user" SET role = \'superuser\' WHERE is_superuser')
    op.execute('UPDATE "user" SET role = \'teacher\' WHERE role IS NULL')
    op.alter_column("user", "role", nullable=False)


def downgrade():
    op.drop_column("user", "role")
    userrole.drop(op.get_bind(), checkfirst=True)
