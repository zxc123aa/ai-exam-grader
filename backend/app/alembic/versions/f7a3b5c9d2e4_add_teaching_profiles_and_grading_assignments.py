"""Add teaching profiles and grading assignments

协作批卷（阶段 1+2）：
- user.subjects：任教学科标签（JSONB 字符串数组，默认 []）
- teacherclasslink：教师任教班级关联（联合主键）
- exam.shared_grading_enabled：大考共享批卷开关（默认 false，行为不变）
- gradingassignment：考试按班级分配批卷老师，exam_id+class_id 唯一

Revision ID: f7a3b5c9d2e4
Revises: d5e7f9a1b3c5
Create Date: 2026-07-24 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "f7a3b5c9d2e4"
down_revision = "d5e7f9a1b3c5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user",
        sa.Column(
            "subjects",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )
    op.add_column(
        "exam",
        sa.Column(
            "shared_grading_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.create_table(
        "teacherclasslink",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("class_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["class_id"], ["classgroup.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "class_id"),
    )
    op.create_table(
        "gradingassignment",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("exam_id", sa.Uuid(), nullable=False),
        sa.Column("class_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["class_id"], ["classgroup.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["exam_id"], ["exam.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "exam_id", "class_id", name="uq_gradingassignment_exam_class"
        ),
    )
    op.create_index(
        op.f("ix_gradingassignment_exam_id"),
        "gradingassignment",
        ["exam_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        op.f("ix_gradingassignment_exam_id"), table_name="gradingassignment"
    )
    op.drop_table("gradingassignment")
    op.drop_table("teacherclasslink")
    op.drop_column("exam", "shared_grading_enabled")
    op.drop_column("user", "subjects")
