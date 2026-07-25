"""Add knowledge point and difficulty to exam questions

Revision ID: e5f7a9c1d304
Revises: b4e6c8d0a213
Create Date: 2026-07-22 16:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "e5f7a9c1d304"
down_revision = "b4e6c8d0a213"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "examquestion",
        sa.Column("knowledge_point", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "examquestion",
        sa.Column("difficulty", sa.Integer(), nullable=True),
    )
    op.add_column(
        "questionrecognitionitem",
        sa.Column("knowledge_point", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "questionrecognitionitem",
        sa.Column("difficulty", sa.Integer(), nullable=True),
    )
    # 数字卷（重新组卷）的标准答案不关联扫描区域。
    op.alter_column(
        "standardanswer",
        "exam_region_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )


def downgrade():
    op.alter_column(
        "standardanswer",
        "exam_region_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.drop_column("questionrecognitionitem", "difficulty")
    op.drop_column("questionrecognitionitem", "knowledge_point")
    op.drop_column("examquestion", "difficulty")
    op.drop_column("examquestion", "knowledge_point")
