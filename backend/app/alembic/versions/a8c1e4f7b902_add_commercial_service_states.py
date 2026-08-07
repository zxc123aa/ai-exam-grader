"""Add commercial organization service states and protect user-owned data.

Revision ID: a8c1e4f7b902
Revises: f7b9d1e3a5c7
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a8c1e4f7b902"
down_revision = "f7b9d1e3a5c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    service_state = postgresql.ENUM(
        "active",
        "read_only",
        "frozen",
        "deleting",
        name="organizationservicestate",
        create_type=False,
    )
    service_state.create(bind, checkfirst=True)
    op.execute(
        "ALTER TABLE organization ALTER COLUMN status DROP DEFAULT"
    )
    op.execute(
        "ALTER TABLE organization ALTER COLUMN status TYPE organizationservicestate "
        "USING (CASE WHEN status = 'suspended' THEN 'frozen' ELSE status END)::organizationservicestate"
    )
    op.execute(
        "ALTER TABLE organization ALTER COLUMN status SET DEFAULT 'active'::organizationservicestate"
    )
    op.add_column(
        "creditreservation",
        sa.Column(
            "authorized_microcredits",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )

    # Business records outlive the account that originally created them.
    for table, constraint in (
        ("exam", "exam_owner_id_fkey"),
        ("storedfile", "storedfile_uploaded_by_id_fkey"),
        ("processingtask", "processingtask_created_by_id_fkey"),
        ("classgroup", "classgroup_owner_id_fkey"),
    ):
        op.drop_constraint(constraint, table, type_="foreignkey")
        column = {
            "exam": "owner_id",
            "storedfile": "uploaded_by_id",
            "processingtask": "created_by_id",
            "classgroup": "owner_id",
        }[table]
        op.create_foreign_key(
            constraint, table, "user", [column], ["id"], ondelete="RESTRICT"
        )


def downgrade() -> None:
    op.drop_column("creditreservation", "authorized_microcredits")
    for table, constraint in (
        ("exam", "exam_owner_id_fkey"),
        ("storedfile", "storedfile_uploaded_by_id_fkey"),
        ("processingtask", "processingtask_created_by_id_fkey"),
        ("classgroup", "classgroup_owner_id_fkey"),
    ):
        op.drop_constraint(constraint, table, type_="foreignkey")
        column = {
            "exam": "owner_id",
            "storedfile": "uploaded_by_id",
            "processingtask": "created_by_id",
            "classgroup": "owner_id",
        }[table]
        op.create_foreign_key(
            constraint, table, "user", [column], ["id"], ondelete="CASCADE"
        )
    op.execute("ALTER TABLE organization ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TABLE organization ALTER COLUMN status TYPE VARCHAR(20) "
        "USING status::text"
    )
    op.execute("UPDATE organization SET status = 'suspended' WHERE status = 'frozen'")
    op.execute("ALTER TABLE organization ALTER COLUMN status SET DEFAULT 'active'")
    postgresql.ENUM(name="organizationservicestate").drop(
        op.get_bind(), checkfirst=True
    )
