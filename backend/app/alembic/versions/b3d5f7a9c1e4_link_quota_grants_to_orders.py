"""Link answer quota grants to their commerce order.

Revision ID: b3d5f7a9c1e4
Revises: a2c4e6f8b0d3
Create Date: 2026-07-27 11:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "b3d5f7a9c1e4"
down_revision = "a2c4e6f8b0d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("answerquotagrant", sa.Column("order_id", sa.Uuid(), nullable=True))
    op.create_index("ix_answerquotagrant_order_id", "answerquotagrant", ["order_id"])
    op.create_foreign_key(
        "fk_answer_quota_grant_order",
        "answerquotagrant",
        "commerceorder",
        ["order_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_answer_quota_grant_order", "answerquotagrant", type_="foreignkey"
    )
    op.drop_index("ix_answerquotagrant_order_id", table_name="answerquotagrant")
    op.drop_column("answerquotagrant", "order_id")
