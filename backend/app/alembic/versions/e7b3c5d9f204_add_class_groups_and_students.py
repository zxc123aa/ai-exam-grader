"""Add class groups and students

Revision ID: e7b3c5d9f204
Revises: c8e2f4a6b105
Create Date: 2026-07-23 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel.sql.sqltypes


revision = "e7b3c5d9f204"
down_revision = "c8e2f4a6b105"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "classgroup",
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column(
            "grade_level", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "name", name="uq_classgroup_owner_name"),
    )
    op.create_table(
        "student",
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column(
            "student_no", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("class_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["class_id"], ["classgroup.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("class_id", "name", name="uq_student_class_name"),
    )
    op.create_table(
        "examclasslink",
        sa.Column("exam_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("class_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["class_id"], ["classgroup.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["exam_id"], ["exam.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("exam_id", "class_id"),
    )
    op.add_column(
        "studentsubmission",
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_studentsubmission_student_id", "studentsubmission", ["student_id"]
    )
    op.create_foreign_key(
        "fk_studentsubmission_student_id",
        "studentsubmission",
        "student",
        ["student_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint(
        "fk_studentsubmission_student_id", "studentsubmission", type_="foreignkey"
    )
    op.drop_index("ix_studentsubmission_student_id", table_name="studentsubmission")
    op.drop_column("studentsubmission", "student_id")
    op.drop_table("examclasslink")
    op.drop_table("student")
    op.drop_table("classgroup")
