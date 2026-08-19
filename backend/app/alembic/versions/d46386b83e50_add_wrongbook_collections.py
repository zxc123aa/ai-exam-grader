"""add wrongbook collections

Revision ID: d46386b83e50
Revises: 8939283db86c
Create Date: 2026-08-19 18:59:15.204660

"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "d46386b83e50"
down_revision = "8939283db86c"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "wrongbookcollection",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("learner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=60), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["learner_id"], ["learnerprofile.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("learner_id", "name", name="uq_wrongbookcollection_name"),
    )
    op.create_index(
        op.f("ix_wrongbookcollection_learner_id"),
        "wrongbookcollection",
        ["learner_id"],
        unique=False,
    )
    op.create_table(
        "wrongbookcollectionitem",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("entry_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["wrongbookcollection.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["entry_id"], ["wrongquestionentry.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "collection_id", "entry_id", name="uq_wrongbookcollectionitem_pair"
        ),
    )
    op.create_index(
        op.f("ix_wrongbookcollectionitem_collection_id"),
        "wrongbookcollectionitem",
        ["collection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wrongbookcollectionitem_entry_id"),
        "wrongbookcollectionitem",
        ["entry_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        op.f("ix_wrongbookcollectionitem_entry_id"),
        table_name="wrongbookcollectionitem",
    )
    op.drop_index(
        op.f("ix_wrongbookcollectionitem_collection_id"),
        table_name="wrongbookcollectionitem",
    )
    op.drop_table("wrongbookcollectionitem")
    op.drop_index(
        op.f("ix_wrongbookcollection_learner_id"), table_name="wrongbookcollection"
    )
    op.drop_table("wrongbookcollection")
    # ### end Alembic commands ###
