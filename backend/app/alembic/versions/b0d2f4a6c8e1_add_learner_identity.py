"""Add lifelong learner identity and attach wrongbook to it.

Revision ID: b0d2f4a6c8e1
Revises: a9c1e3f5b7d0
Create Date: 2026-08-13 08:10:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "b0d2f4a6c8e1"
down_revision = "a9c1e3f5b7d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learnerprofile",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("grade_band", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_learnerprofile_user"),
    )

    op.create_table(
        "learnerenrollment",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("learner_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("student_id", sa.Uuid(), nullable=True),
        sa.Column("org_name_at_time", sa.String(length=255), nullable=True),
        sa.Column("class_name_at_time", sa.String(length=100), nullable=True),
        sa.Column("student_name_at_time", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["learner_id"], ["learnerprofile.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["student_id"], ["student.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "learner_id", "student_id", name="uq_learnerenrollment_pair"
        ),
    )
    op.create_index(
        op.f("ix_learnerenrollment_learner_id"),
        "learnerenrollment",
        ["learner_id"],
        unique=False,
    )

    op.add_column(
        "wrongquestionentry", sa.Column("learner_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "wrongquestionentry_learner_id_fkey",
        "wrongquestionentry",
        "learnerprofile",
        ["learner_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_wrongquestionentry_learner_id"),
        "wrongquestionentry",
        ["learner_id"],
        unique=False,
    )

    op.add_column(
        "wrongquestionreview", sa.Column("learner_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "wrongquestionreview_learner_id_fkey",
        "wrongquestionreview",
        "learnerprofile",
        ["learner_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_wrongquestionreview_learner_id"),
        "wrongquestionreview",
        ["learner_id"],
        unique=False,
    )

    # 回填：每个已绑定登录账号的学生档案生成一个终身身份与一条在校经历，
    # 并把已有错题条目和复习记录挂过去。未绑账号的学生等首次登录时再认领。
    op.execute(
        """
        INSERT INTO learnerprofile (id, user_id, display_name, created_at, updated_at)
        SELECT gen_random_uuid(), s.user_id, s.name, now(), now()
        FROM student s
        WHERE s.user_id IS NOT NULL
        ON CONFLICT (user_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO learnerenrollment (
            id, learner_id, org_id, student_id, org_name_at_time,
            class_name_at_time, student_name_at_time, started_at
        )
        SELECT gen_random_uuid(), lp.id, c.org_id, s.id, o.name, c.name, s.name, now()
        FROM student s
        JOIN learnerprofile lp ON lp.user_id = s.user_id
        JOIN classgroup c ON c.id = s.class_id
        LEFT JOIN organization o ON o.id = c.org_id
        WHERE s.user_id IS NOT NULL
        ON CONFLICT (learner_id, student_id) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE wrongquestionentry e
        SET learner_id = lp.id
        FROM learnerprofile lp
        WHERE e.learner_id IS NULL
          AND (
            e.student_user_id = lp.user_id
            OR e.student_id IN (
                SELECT en.student_id FROM learnerenrollment en WHERE en.learner_id = lp.id
            )
          )
        """
    )
    op.execute(
        """
        UPDATE wrongquestionreview r
        SET learner_id = lp.id
        FROM learnerprofile lp
        WHERE r.learner_id IS NULL AND r.owner_user_id = lp.user_id
        """
    )
    # 掌握度是派生数据，归属键从 user:/student: 改为 learner:，直接清掉重算
    op.execute("DELETE FROM learnermastery")


def downgrade() -> None:
    op.drop_index(
        op.f("ix_wrongquestionreview_learner_id"), table_name="wrongquestionreview"
    )
    op.drop_constraint(
        "wrongquestionreview_learner_id_fkey", "wrongquestionreview", type_="foreignkey"
    )
    op.drop_column("wrongquestionreview", "learner_id")
    op.drop_index(
        op.f("ix_wrongquestionentry_learner_id"), table_name="wrongquestionentry"
    )
    op.drop_constraint(
        "wrongquestionentry_learner_id_fkey", "wrongquestionentry", type_="foreignkey"
    )
    op.drop_column("wrongquestionentry", "learner_id")
    op.drop_index(
        op.f("ix_learnerenrollment_learner_id"), table_name="learnerenrollment"
    )
    op.drop_table("learnerenrollment")
    op.drop_table("learnerprofile")
    op.execute("DELETE FROM learnermastery")
