"""Clean legacy offerings and defaults that cross model-purpose families.

Revision ID: f0b2d4e6a8c1
Revises: e9a1c3d5f7b8
Create Date: 2026-07-27 22:30:00.000000
"""

from alembic import op

revision = "f0b2d4e6a8c1"
down_revision = "e9a1c3d5f7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing school selections are retained for audit, but invalid catalog
    # entries are unpublished so runtime resolution falls back safely.
    op.execute(
        "UPDATE platformmodeloffering "
        "SET published = false, school_selectable = false "
        "WHERE scope = 'vision' AND NOT ("
        "lower(canonical_model) LIKE 'gemini-3.6-flash%' OR "
        "lower(canonical_model) LIKE 'gemini-3.5-flash%')"
    )
    op.execute(
        "UPDATE platformmodeloffering "
        "SET published = false, school_selectable = false "
        "WHERE scope IN ('reference_answer', 'grading') AND NOT ("
        "lower(canonical_model) LIKE 'gpt-5.6-sol%' OR "
        "lower(canonical_model) LIKE 'gpt-5.6-terra%' OR "
        "lower(canonical_model) LIKE 'kimi-%')"
    )

    for prefix in ("vision", "region", "recognition"):
        op.execute(
            "DELETE FROM systemconfig "
            f"WHERE key IN ('{prefix}_provider', '{prefix}_model') "
            "AND EXISTS (SELECT 1 FROM systemconfig configured "
            f"WHERE configured.key = '{prefix}_model' AND NOT ("
            "lower(configured.value #>> '{}') LIKE 'gemini-3.6-flash%' OR "
            "lower(configured.value #>> '{}') LIKE 'gemini-3.5-flash%'))"
        )
    op.execute(
        "DELETE FROM systemconfig "
        "WHERE key IN ('grading_provider', 'grading_model') "
        "AND EXISTS (SELECT 1 FROM systemconfig configured "
        "WHERE configured.key = 'grading_model' AND NOT ("
        "lower(configured.value #>> '{}') LIKE 'gpt-5.6-sol%' OR "
        "lower(configured.value #>> '{}') LIKE 'gpt-5.6-terra%' OR "
        "lower(configured.value #>> '{}') LIKE 'kimi-%'))"
    )

    op.execute(
        "DELETE FROM systemconfig configured "
        "WHERE configured.key = 'vision_fallback_models' "
        "AND EXISTS (SELECT 1 FROM jsonb_array_elements_text(configured.value) item "
        "WHERE NOT ("
        "lower(regexp_replace(item, '^.*[/:]', '')) LIKE 'gemini-3.6-flash%' OR "
        "lower(regexp_replace(item, '^.*[/:]', '')) LIKE 'gemini-3.5-flash%'))"
    )
    op.execute(
        "DELETE FROM systemconfig configured "
        "WHERE configured.key IN ('fallback_models', 'reasoning_fallback_models') "
        "AND EXISTS (SELECT 1 FROM jsonb_array_elements_text(configured.value) item "
        "WHERE NOT ("
        "lower(regexp_replace(item, '^.*[/:]', '')) LIKE 'gpt-5.6-sol%' OR "
        "lower(regexp_replace(item, '^.*[/:]', '')) LIKE 'gpt-5.6-terra%' OR "
        "lower(regexp_replace(item, '^.*[/:]', '')) LIKE 'kimi-%'))"
    )


def downgrade() -> None:
    # Disabled catalog entries and deleted overrides require an explicit
    # operator decision; restoring unsafe values automatically would be wrong.
    pass
