"""Add class_name to student submissions

Revision ID: a3f5b7c9d102
Revises: e2f4a6c8b013
Create Date: 2026-07-21 12:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "a3f5b7c9d102"
down_revision = "e2f4a6c8b013"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "studentsubmission",
        sa.Column("class_name", sa.String(length=100), nullable=True),
    )


def downgrade():
    op.drop_column("studentsubmission", "class_name")
