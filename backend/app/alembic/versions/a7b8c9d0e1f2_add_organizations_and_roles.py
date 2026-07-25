"""Add organizations and multi-tenant user roles

阶段 1 多租户：新增 organization 表、user.org_id，并把 userrole 枚举
从 4 值（superuser/admin/teacher/student）迁移到 6 值
（platform_superuser/platform_support/school_owner/school_admin/teacher/student）。

Postgres 枚举不能删除值，因此采用「只加不删」方案：
ALTER TYPE ... ADD VALUE 追加 4 个新值后 UPDATE 映射旧值
（superuser -> platform_superuser, admin -> school_owner，teacher/student 不变），
旧值 superuser/admin 保留在枚举类型中但不再被使用。

Revision ID: a7b8c9d0e1f2
Revises: f1a2b3c4d5e6
Create Date: 2026-07-23 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "a7b8c9d0e1f2"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None

# 默认学校的固定 UUID，便于在数据回填中引用
DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001"

NEW_ROLE_VALUES = (
    "platform_superuser",
    "platform_support",
    "school_owner",
    "school_admin",
)


def upgrade():
    # 1. organization 表 + 默认学校
    op.create_table(
        "organization",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("exam_sharing_enabled", sa.Boolean(), nullable=False),
        sa.Column("contact_name", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_organization_code", "organization", ["code"], unique=True)
    op.execute(
        "INSERT INTO organization (id, name, code, status, exam_sharing_enabled)"
        f" VALUES ('{DEFAULT_ORG_ID}', '默认学校', 'default', 'active', false)"
    )

    # 2. user.org_id（学校角色指向组织，平台角色为 NULL）
    op.add_column("user", sa.Column("org_id", sa.Uuid(), nullable=True))
    op.create_index("ix_user_org_id", "user", ["org_id"], unique=False)
    op.create_foreign_key(
        "fk_user_org_id_organization",
        "user",
        "organization",
        ["org_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 3. userrole 枚举迁移。ADD VALUE 必须在独立提交的事务里执行，
    # 否则同一事务内无法使用新枚举值（PG >= 12 的限制）。
    with op.get_context().autocommit_block():
        for value in NEW_ROLE_VALUES:
            op.execute(f"ALTER TYPE userrole ADD VALUE IF NOT EXISTS '{value}'")
    op.execute(
        "UPDATE \"user\" SET role = 'platform_superuser' WHERE role = 'superuser'"
    )
    op.execute("UPDATE \"user\" SET role = 'school_owner' WHERE role = 'admin'")

    # 4. org_id 回填：学校角色 -> 默认学校，平台角色 -> NULL
    op.execute(
        f"UPDATE \"user\" SET org_id = '{DEFAULT_ORG_ID}'"
        " WHERE role NOT IN ('platform_superuser', 'platform_support')"
    )
    op.execute(
        "UPDATE \"user\" SET org_id = NULL"
        " WHERE role IN ('platform_superuser', 'platform_support')"
    )


def downgrade():
    # 角色映射回旧值（旧枚举值仍存在于 userrole 类型中，可直接写回）
    op.execute(
        "UPDATE \"user\" SET role = 'superuser' WHERE role = 'platform_superuser'"
    )
    op.execute(
        "UPDATE \"user\" SET role = 'admin'"
        " WHERE role IN ('platform_support', 'school_owner', 'school_admin')"
    )
    op.drop_constraint("fk_user_org_id_organization", "user", type_="foreignkey")
    op.drop_index("ix_user_org_id", table_name="user")
    op.drop_column("user", "org_id")
    op.drop_index("ix_organization_code", table_name="organization")
    op.drop_table("organization")
    # 注意：新增的 4 个 userrole 枚举值无法删除（Postgres 限制），降级后保留。
