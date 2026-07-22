"""add document preprocessing metadata

Revision ID: e2f4a6c8b013
Revises: d1e3f5a7b901
Create Date: 2026-07-15 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e2f4a6c8b013"
down_revision: str | None = "d1e3f5a7b901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "examdocument",
        sa.Column("original_stored_file_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "examdocument",
        sa.Column(
            "preprocessing_status",
            sa.String(length=50),
            server_default="not_required",
            nullable=False,
        ),
    )
    op.add_column(
        "examdocument",
        sa.Column("preprocessing_quality", sa.Float(), nullable=True),
    )
    op.add_column(
        "examdocument",
        sa.Column("preprocessing_metadata", postgresql.JSONB(), nullable=True),
    )
    op.create_foreign_key(
        "fk_examdocument_original_stored_file",
        "examdocument",
        "storedfile",
        ["original_stored_file_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "studentsubmission",
        sa.Column("original_stored_file_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_studentsubmission_original_stored_file",
        "studentsubmission",
        "storedfile",
        ["original_stored_file_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_studentsubmission_original_stored_file",
        "studentsubmission",
        type_="foreignkey",
    )
    op.drop_column("studentsubmission", "original_stored_file_id")
    op.drop_constraint(
        "fk_examdocument_original_stored_file",
        "examdocument",
        type_="foreignkey",
    )
    op.drop_column("examdocument", "preprocessing_metadata")
    op.drop_column("examdocument", "preprocessing_quality")
    op.drop_column("examdocument", "preprocessing_status")
    op.drop_column("examdocument", "original_stored_file_id")
