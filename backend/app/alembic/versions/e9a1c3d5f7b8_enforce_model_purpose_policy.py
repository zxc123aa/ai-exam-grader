"""Enforce visual, reasoning, and traditional-processing model boundaries.

Revision ID: e9a1c3d5f7b8
Revises: d5f7a9c1e3b6
Create Date: 2026-07-27 22:00:00.000000
"""

from alembic import op

revision = "e9a1c3d5f7b8"
down_revision = "d5f7a9c1e3b6"
branch_labels = None
depends_on = None

_TRADITIONAL = ("photo_preprocessing", "scan_preprocessing")
_VISION = (
    "region_detection",
    "question_recognition",
    "score_structure_recognition",
    "answer_document_parsing",
    "rubric_question_recognition",
    "answer_recognition",
    "answer_extraction",
)
_REASONING = (
    "answer_preparation",
    "rubric_generation",
    "rubric_validation",
    "subjective_grading",
)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    traditional = _quoted(_TRADITIONAL)
    vision = _quoted(_VISION)
    reasoning = _quoted(_REASONING)

    # Page straightening/cropping is an OpenCV pipeline. Historical route
    # versions remain untouched for audit, but they can no longer receive work.
    op.execute(
        f"UPDATE modelroutepolicy SET enabled = false WHERE purpose IN ({traditional})"
    )
    op.execute(f"DELETE FROM functionmodelassignment WHERE purpose IN ({traditional})")

    op.execute(
        f"UPDATE modelroutepolicy SET enabled = false "
        f"WHERE purpose IN ({vision}) AND NOT ("
        "lower(canonical_model) LIKE 'gemini-3.6-flash%' OR "
        "lower(canonical_model) LIKE 'gemini-3.5-flash%')"
    )
    op.execute(
        f"UPDATE modelroutepolicy SET enabled = false "
        f"WHERE purpose IN ({reasoning}) AND NOT ("
        "lower(canonical_model) LIKE 'gpt-5.6-sol%' OR "
        "lower(canonical_model) LIKE 'gpt-5.6-terra%' OR "
        "lower(canonical_model) LIKE 'kimi-%')"
    )

    # Drop defaults that no longer point to an enabled, published route.
    op.execute(
        f"DELETE FROM functionmodelassignment a "
        f"WHERE a.purpose IN ({vision}, {reasoning}) "
        "AND NOT EXISTS ("
        "SELECT 1 FROM modelroutepolicy p "
        "JOIN modelrouteversion v ON v.policy_id = p.id "
        "WHERE p.purpose = a.purpose "
        "AND p.canonical_model = a.default_canonical_model "
        "AND p.enabled = true AND v.status = 'published')"
    )

    # Pick a deterministic default for every function that still has a valid
    # published route. Visual work prefers Gemini 3.6 then 3.5; reasoning work
    # prefers Sol, then Terra, then Kimi.
    op.execute(
        f"INSERT INTO functionmodelassignment "
        "(purpose, default_canonical_model, updated_at) "
        "SELECT DISTINCT ON (p.purpose) p.purpose, p.canonical_model, now() "
        "FROM modelroutepolicy p "
        "WHERE p.enabled = true "
        f"AND p.purpose IN ({vision}) "
        "AND EXISTS (SELECT 1 FROM modelrouteversion v "
        "WHERE v.policy_id = p.id AND v.status = 'published') "
        "ORDER BY p.purpose, CASE "
        "WHEN lower(p.canonical_model) LIKE 'gemini-3.6-flash%' THEN 1 "
        "WHEN lower(p.canonical_model) LIKE 'gemini-3.5-flash%' THEN 2 "
        "ELSE 99 END, p.updated_at DESC "
        "ON CONFLICT (purpose) DO UPDATE SET "
        "default_canonical_model = EXCLUDED.default_canonical_model, "
        "updated_by_id = NULL, updated_at = EXCLUDED.updated_at"
    )
    op.execute(
        f"INSERT INTO functionmodelassignment "
        "(purpose, default_canonical_model, updated_at) "
        "SELECT DISTINCT ON (p.purpose) p.purpose, p.canonical_model, now() "
        "FROM modelroutepolicy p "
        "WHERE p.enabled = true "
        f"AND p.purpose IN ({reasoning}) "
        "AND EXISTS (SELECT 1 FROM modelrouteversion v "
        "WHERE v.policy_id = p.id AND v.status = 'published') "
        "ORDER BY p.purpose, CASE "
        "WHEN lower(p.canonical_model) LIKE 'gpt-5.6-sol%' THEN 1 "
        "WHEN lower(p.canonical_model) LIKE 'gpt-5.6-terra%' THEN 2 "
        "WHEN lower(p.canonical_model) LIKE 'kimi-k2.7-code%' THEN 3 "
        "WHEN lower(p.canonical_model) LIKE 'kimi-k3%' THEN 4 "
        "WHEN lower(p.canonical_model) LIKE 'kimi-%' THEN 5 "
        "ELSE 99 END, p.updated_at DESC "
        "ON CONFLICT (purpose) DO UPDATE SET "
        "default_canonical_model = EXCLUDED.default_canonical_model, "
        "updated_by_id = NULL, updated_at = EXCLUDED.updated_at"
    )


def downgrade() -> None:
    # This migration corrects live configuration. Historical route versions are
    # retained, so an operator can explicitly republish an old route if needed.
    pass
