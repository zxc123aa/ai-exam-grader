"""Allow a grading run to reserve answer quota again after a failed attempt.

Revision ID: d1f5b8c2e904
Revises: c0e4a7b9d215
"""

from alembic import op

revision = "d1f5b8c2e904"
down_revision = "c0e4a7b9d215"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(
        "ix_answerquotareservation_grading_run_id",
        table_name="answerquotareservation",
    )
    op.drop_constraint(
        "answerquotareservation_grading_run_id_key",
        "answerquotareservation",
        type_="unique",
    )
    op.create_index(
        "ix_answerquotareservation_grading_run_id",
        "answerquotareservation",
        ["grading_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_answerquotareservation_grading_run_id",
        table_name="answerquotareservation",
    )
    op.create_unique_constraint(
        "answerquotareservation_grading_run_id_key",
        "answerquotareservation",
        ["grading_run_id"],
    )
    op.create_index(
        "ix_answerquotareservation_grading_run_id",
        "answerquotareservation",
        ["grading_run_id"],
        unique=True,
    )
