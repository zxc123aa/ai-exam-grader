"""Add practice sheet attempts (photo-graded variant answers).

Revision ID: e3f5a7b9d1c4
Revises: d2e4f6a8c1b3
Create Date: 2026-08-17 09:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e3f5a7b9d1c4"
down_revision = "d2e4f6a8c1b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    verdict = postgresql.ENUM(
        "correct", "partial", "wrong", name="practiceverdict", create_type=False
    )
    verdict.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "practicesheetattempt",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sheet_id", sa.Uuid(), nullable=False),
        sa.Column("learner_id", sa.Uuid(), nullable=False),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("stored_file_id", sa.Uuid(), nullable=True),
        sa.Column("verdict", verdict, nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("comment", sa.String(length=2000), nullable=False),
        sa.Column("student_answer_text", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["learner_id"], ["learnerprofile.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["sheet_id"], ["practicesheet.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["stored_file_id"], ["storedfile.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sheet_id", "item_index", name="uq_practicesheetattempt_item"
        ),
    )
    op.create_index(
        "ix_practicesheetattempt_sheet_id", "practicesheetattempt", ["sheet_id"]
    )
    op.create_index(
        "ix_practicesheetattempt_learner_id", "practicesheetattempt", ["learner_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_practicesheetattempt_learner_id", table_name="practicesheetattempt"
    )
    op.drop_index("ix_practicesheetattempt_sheet_id", table_name="practicesheetattempt")
    op.drop_table("practicesheetattempt")
    postgresql.ENUM(name="practiceverdict").drop(op.get_bind(), checkfirst=True)
