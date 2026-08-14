"""Index wrongbook ownership and knowledge point lookups.

Revision ID: f8b0d2e4a6c9
Revises: e7a9c1d3f5b8
Create Date: 2026-08-13 07:10:00.000000
"""

from alembic import op

revision = "f8b0d2e4a6c9"
down_revision = "e7a9c1d3f5b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 归属过滤是 OR(student_id, student_user_id)，此前只有后者有索引
    op.create_index(
        op.f("ix_wrongquestionentry_student_id"),
        "wrongquestionentry",
        ["student_id"],
        unique=False,
    )
    # 知识点筛选用 JSONB 包含查询（@>）
    op.create_index(
        "ix_wrongquestionsource_knowledge_points_gin",
        "wrongquestionsource",
        ["knowledge_point_names"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_wrongquestionsource_knowledge_points_gin",
        table_name="wrongquestionsource",
    )
    op.drop_index(
        op.f("ix_wrongquestionentry_student_id"), table_name="wrongquestionentry"
    )
