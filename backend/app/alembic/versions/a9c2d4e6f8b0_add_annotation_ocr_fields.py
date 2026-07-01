"""Add annotation OCR fields

Revision ID: a9c2d4e6f8b0
Revises: f3b1d0c9a742
Create Date: 2026-07-01 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


revision = "a9c2d4e6f8b0"
down_revision = "f3b1d0c9a742"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "submissionannotation",
        sa.Column("ocr_text", sqlmodel.sql.sqltypes.AutoString(length=8000), nullable=True),
    )
    op.add_column(
        "submissionannotation",
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "submissionannotation",
        sa.Column(
            "ocr_status",
            sqlmodel.sql.sqltypes.AutoString(length=50),
            nullable=False,
            server_default="not_started",
        ),
    )
    op.add_column(
        "submissionannotation",
        sa.Column("ocr_engine", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    )
    op.alter_column("submissionannotation", "ocr_status", server_default=None)


def downgrade():
    op.drop_column("submissionannotation", "ocr_engine")
    op.drop_column("submissionannotation", "ocr_status")
    op.drop_column("submissionannotation", "ocr_confidence")
    op.drop_column("submissionannotation", "ocr_text")
