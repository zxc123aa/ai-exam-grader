"""add stable ordering for exam document source files

Revision ID: d1e3f5a7b901
Revises: c7d9e1f3a526
"""

import sqlalchemy as sa
from alembic import op

revision = "d1e3f5a7b901"
down_revision = "c7d9e1f3a526"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "examdocument",
        sa.Column("sort_order", sa.Integer(), server_default="1", nullable=False),
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY exam_id, document_type
                    ORDER BY created_at ASC NULLS LAST, id ASC
                ) AS next_order
            FROM examdocument
        )
        UPDATE examdocument AS document
        SET sort_order = ranked.next_order
        FROM ranked
        WHERE document.id = ranked.id
        """
    )
    op.create_index(
        "ix_examdocument_exam_type_sort_order",
        "examdocument",
        ["exam_id", "document_type", "sort_order"],
    )


def downgrade() -> None:
    op.drop_index("ix_examdocument_exam_type_sort_order", table_name="examdocument")
    op.drop_column("examdocument", "sort_order")
