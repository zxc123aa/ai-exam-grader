"""add mapping protocol

Revision ID: e5f7a9b1c3d5
Revises: d46386b83e50
Create Date: 2026-08-20 10:30:00.000000

ProviderModelMapping.protocol：映射级协议覆盖（gemini_native 走原生 generateContent）。
"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision = "e5f7a9b1c3d5"
down_revision = "d46386b83e50"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "providermodelmapping",
        sa.Column(
            "protocol", sqlmodel.sql.sqltypes.AutoString(length=30), nullable=True
        ),
    )


def downgrade():
    op.drop_column("providermodelmapping", "protocol")
