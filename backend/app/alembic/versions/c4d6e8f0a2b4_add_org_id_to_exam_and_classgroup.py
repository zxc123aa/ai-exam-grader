"""Add org_id to exam and classgroup (multi-tenant isolation)

阶段 2 多租户数据隔离：exam / classgroup 增加 org_id 列（FK organization.id），
存量数据回填默认学校后置为 NOT NULL；classgroup 唯一约束从
(owner_id, name) 改为 (org_id, name)，班级名变为学校内唯一、跨校可重名。

Revision ID: c4d6e8f0a2b4
Revises: a7b8c9d0e1f2
Create Date: 2026-07-23 19:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "c4d6e8f0a2b4"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None

# 默认学校的固定 UUID（与 a7b8c9d0e1f2 迁移一致）
DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001"


def upgrade():
    # 1. exam.org_id：加列 -> 回填默认学校 -> NOT NULL -> 索引 + FK
    op.add_column("exam", sa.Column("org_id", sa.Uuid(), nullable=True))
    op.execute(f"UPDATE exam SET org_id = '{DEFAULT_ORG_ID}'")
    op.alter_column("exam", "org_id", nullable=False)
    op.create_index("ix_exam_org_id", "exam", ["org_id"], unique=False)
    op.create_foreign_key(
        "fk_exam_org_id_organization",
        "exam",
        "organization",
        ["org_id"],
        ["id"],
    )

    # 2. classgroup.org_id：同上
    op.add_column("classgroup", sa.Column("org_id", sa.Uuid(), nullable=True))
    op.execute(f"UPDATE classgroup SET org_id = '{DEFAULT_ORG_ID}'")
    op.alter_column("classgroup", "org_id", nullable=False)
    op.create_index("ix_classgroup_org_id", "classgroup", ["org_id"], unique=False)
    op.create_foreign_key(
        "fk_classgroup_org_id_organization",
        "classgroup",
        "organization",
        ["org_id"],
        ["id"],
    )

    # 3. 班级唯一约束：(owner_id, name) -> (org_id, name)
    op.drop_constraint("uq_classgroup_owner_name", "classgroup", type_="unique")
    op.create_unique_constraint(
        "uq_classgroup_org_name", "classgroup", ["org_id", "name"]
    )


def downgrade():
    op.drop_constraint("uq_classgroup_org_name", "classgroup", type_="unique")
    op.create_unique_constraint(
        "uq_classgroup_owner_name", "classgroup", ["owner_id", "name"]
    )
    op.drop_constraint(
        "fk_classgroup_org_id_organization", "classgroup", type_="foreignkey"
    )
    op.drop_index("ix_classgroup_org_id", table_name="classgroup")
    op.drop_column("classgroup", "org_id")
    op.drop_constraint("fk_exam_org_id_organization", "exam", type_="foreignkey")
    op.drop_index("ix_exam_org_id", table_name="exam")
    op.drop_column("exam", "org_id")
