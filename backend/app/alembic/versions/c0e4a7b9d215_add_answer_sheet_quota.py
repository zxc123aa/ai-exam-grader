"""Add customer-facing answer-sheet quota ledger.

Revision ID: c0e4a7b9d215
Revises: b9d2f5a8c013
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c0e4a7b9d215"
down_revision = "b9d2f5a8c013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    grant_source = postgresql.ENUM(
        "subscription",
        "top_up",
        "adjustment",
        name="creditgrantsource",
        create_type=False,
    )
    reservation_status = postgresql.ENUM(
        "active",
        "settled",
        "released",
        name="creditreservationstatus",
        create_type=False,
    )
    op.create_table(
        "answerquotagrant",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", grant_source, nullable=False),
        sa.Column("total_answers", sa.Integer(), nullable=False),
        sa.Column("reserved_answers", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consumed_answers", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["subscription_id"], ["organizationsubscription.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_answerquotagrant_org_id", "answerquotagrant", ["org_id"])
    op.create_index(
        "ix_answerquotagrant_subscription_id",
        "answerquotagrant",
        ["subscription_id"],
    )
    op.create_table(
        "answerquotareservation",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exam_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("grading_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("reserved_answers", sa.Integer(), nullable=False),
        sa.Column("settled_answers", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", reservation_status, nullable=False),
        sa.Column(
            "identities", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["exam_id"], ["exam.id"]),
        sa.ForeignKeyConstraint(["grading_run_id"], ["gradingrun.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("grading_run_id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    for column in ("org_id", "exam_id", "grading_run_id", "idempotency_key"):
        op.create_index(
            f"ix_answerquotareservation_{column}",
            "answerquotareservation",
            [column],
            unique=column in {"grading_run_id", "idempotency_key"},
        )
    op.create_table(
        "answerquotaallocation",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reservation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("grant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reserved_answers", sa.Integer(), nullable=False),
        sa.Column("consumed_answers", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["reservation_id"], ["answerquotareservation.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["grant_id"], ["answerquotagrant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reservation_id", "grant_id", name="uq_answer_quota_reservation_grant"
        ),
    )
    op.create_index(
        "ix_answerquotaallocation_reservation_id",
        "answerquotaallocation",
        ["reservation_id"],
    )
    op.create_index(
        "ix_answerquotaallocation_grant_id",
        "answerquotaallocation",
        ["grant_id"],
    )
    op.create_table(
        "billableanswersheet",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exam_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("grading_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reservation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("billing_identity", sa.String(length=255), nullable=False),
        sa.Column("student_name", sa.String(length=100), nullable=True),
        sa.Column("class_name", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["exam_id"], ["exam.id"]),
        sa.ForeignKeyConstraint(["grading_run_id"], ["gradingrun.id"]),
        sa.ForeignKeyConstraint(["reservation_id"], ["answerquotareservation.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_id",
            "exam_id",
            "billing_identity",
            name="uq_billable_answer_sheet_identity",
        ),
    )
    for column in ("org_id", "exam_id", "grading_run_id", "reservation_id", "created_at"):
        op.create_index(
            f"ix_billableanswersheet_{column}", "billableanswersheet", [column]
        )


def downgrade() -> None:
    op.drop_table("billableanswersheet")
    op.drop_table("answerquotaallocation")
    op.drop_table("answerquotareservation")
    op.drop_table("answerquotagrant")
