"""Add exam_date and description to exam

Revision ID: f1a2b3c4d5e6
Revises: e7b3c5d9f204
Create Date: 2026-07-23 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


revision = "f1a2b3c4d5e6"
down_revision = "e7b3c5d9f204"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("exam", sa.Column("exam_date", sa.Date(), nullable=True))
    op.add_column(
        "exam",
        sa.Column(
            "description",
            sqlmodel.sql.sqltypes.AutoString(length=500),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column("exam", "description")
    op.drop_column("exam", "exam_date")
