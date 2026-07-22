"""add confirmed questions and immutable answer workflow

Revision ID: c7d9e1f3a526
Revises: a6b8c0d2e415
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from decimal import Decimal

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c7d9e1f3a526"
down_revision = "a6b8c0d2e415"
branch_labels = None
depends_on = None


def _enum(name: str, *values: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name)


def _enum_column(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def _question_key(label: str, used: set[str], fallback: str) -> str:
    match = re.search(r"\d+(?:[.-]\d+)*", label or "")
    base = match.group(0) if match else (label.strip() or fallback)
    base = base[:90]
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}-{suffix}"[:100]
        suffix += 1
    used.add(candidate)
    return candidate


def _content_hash(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def upgrade() -> None:
    enum_specs = (
        ("examquestionstatus", "draft", "confirmed"),
        ("questionregionrole", "primary", "continuation", "figure"),
        (
            "workflowrunstatus",
            "queued",
            "running",
            "completed",
            "completed_with_errors",
            "failed",
        ),
        ("questionrecognitionitemstatus", "draft", "confirmed", "excluded"),
        ("answerpreparationsource", "model", "document"),
        (
            "answerpreparationitemstatus",
            "queued",
            "running",
            "matched",
            "conflict",
            "unmatched",
            "failed",
            "confirmed",
        ),
        ("standardanswerrevisionstatus", "draft", "published"),
    )
    for spec in enum_specs:
        _enum(spec[0], *spec[1:]).create(op.get_bind(), checkfirst=True)

    op.add_column("examregion", sa.Column("exam_document_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_examregion_exam_document",
        "examregion",
        "examdocument",
        ["exam_document_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_examregion_exam_document_id", "examregion", ["exam_document_id"])

    op.create_table(
        "examquestion",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("exam_id", sa.Uuid(), nullable=False),
        sa.Column("question_key", sa.String(100), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("question_text", sa.String(20000), nullable=False),
        sa.Column("question_type", sa.String(50), nullable=True),
        sa.Column("recognition_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "status",
            _enum_column("examquestionstatus"),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("confirmed_by_id", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["exam_id"], ["exam.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["confirmed_by_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("exam_id", "question_key", name="uq_examquestion_exam_key"),
    )
    op.create_index("ix_examquestion_exam_id", "examquestion", ["exam_id"])

    op.add_column("standardanswer", sa.Column("question_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_standardanswer_question",
        "standardanswer",
        "examquestion",
        ["question_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_standardanswer_question_id", "standardanswer", ["question_id"])
    op.create_unique_constraint(
        "uq_standardanswer_question_id", "standardanswer", ["question_id"]
    )

    op.create_table(
        "examquestionregion",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("exam_region_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "role",
            _enum_column("questionregionrole"),
            server_default="primary",
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["question_id"], ["examquestion.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["exam_region_id"], ["examregion.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "question_id", "exam_region_id", name="uq_examquestionregion_pair"
        ),
        sa.UniqueConstraint("exam_region_id", name="uq_examquestionregion_region"),
    )
    op.create_index("ix_examquestionregion_question_id", "examquestionregion", ["question_id"])
    op.create_index(
        "ix_examquestionregion_exam_region_id", "examquestionregion", ["exam_region_id"]
    )

    op.create_table(
        "questionrecognitionrun",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("exam_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(100), server_default="fluxnode_gemini", nullable=False),
        sa.Column("model", sa.String(200), server_default="gemini-3.5-flash", nullable=False),
        sa.Column("engine", sa.String(100), server_default="reference-node", nullable=False),
        sa.Column(
            "status", _enum_column("workflowrunstatus"), server_default="queued", nullable=False
        ),
        sa.Column("document_ids", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("timing", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("raw_output", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("error_message", sa.String(2000), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["exam_id"], ["exam.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_questionrecognitionrun_exam_id", "questionrecognitionrun", ["exam_id"])

    op.create_table(
        "questionrecognitionitem",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("source_item_key", sa.String(255), nullable=False),
        sa.Column("question_key", sa.String(100), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("question_text", sa.String(20000), server_default="", nullable=False),
        sa.Column("student_answer_text", sa.String(12000), nullable=True),
        sa.Column("question_type", sa.String(50), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("notes", sa.String(4000), nullable=True),
        sa.Column("region_ids", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("region_snapshots", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("raw_result", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column(
            "status",
            _enum_column("questionrecognitionitemstatus"),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("confirmed_question_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["run_id"], ["questionrecognitionrun.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["confirmed_question_id"], ["examquestion.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id", "source_item_key", name="uq_questionrecognitionitem_run_source"
        ),
    )
    op.create_index("ix_questionrecognitionitem_run_id", "questionrecognitionitem", ["run_id"])

    op.create_table(
        "answerpreparationrun",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("exam_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", _enum_column("answerpreparationsource"), nullable=False),
        sa.Column("provider", sa.String(100), server_default="pomoai", nullable=False),
        sa.Column("model", sa.String(200), server_default="gpt-5.6-sol", nullable=False),
        sa.Column("document_ids", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column(
            "status", _enum_column("workflowrunstatus"), server_default="queued", nullable=False
        ),
        sa.Column("timing", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("raw_output", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("error_message", sa.String(2000), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["exam_id"], ["exam.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_answerpreparationrun_exam_id", "answerpreparationrun", ["exam_id"])

    op.create_table(
        "answerpreparationitem",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=True),
        sa.Column("source_item_key", sa.String(255), nullable=False),
        sa.Column("source_question_key", sa.String(100), nullable=True),
        sa.Column("answer_text", sa.String(20000), server_default="", nullable=False),
        sa.Column("max_score", sa.Numeric(8, 2), server_default="1.00", nullable=False),
        sa.Column("rubric_text", sa.String(12000), nullable=True),
        sa.Column("scoring_points", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("match_reason", sa.String(2000), nullable=True),
        sa.Column("raw_result", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column(
            "status",
            _enum_column("answerpreparationitemstatus"),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("revision_id", sa.Uuid(), nullable=True),
        sa.Column("error_message", sa.String(2000), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["run_id"], ["answerpreparationrun.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["examquestion.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id", "source_item_key", name="uq_answerpreparationitem_run_source"
        ),
    )
    op.create_index("ix_answerpreparationitem_run_id", "answerpreparationitem", ["run_id"])
    op.create_index(
        "ix_answerpreparationitem_question_id", "answerpreparationitem", ["question_id"]
    )

    op.create_table(
        "standardanswerrevision",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("standard_answer_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("question_key", sa.String(100), nullable=False),
        sa.Column("question_text", sa.String(20000), nullable=False),
        sa.Column("question_type", sa.String(50), nullable=True),
        sa.Column("answer_text", sa.String(20000), nullable=False),
        sa.Column("max_score", sa.Numeric(8, 2), nullable=False),
        sa.Column("rubric_text", sa.String(12000), nullable=True),
        sa.Column("scoring_points", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("source_provider", sa.String(100), nullable=True),
        sa.Column("source_model", sa.String(200), nullable=True),
        sa.Column("generation_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "status",
            _enum_column("standardanswerrevisionstatus"),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("published_by_id", sa.Uuid(), nullable=True),
        sa.Column("preparation_item_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["standard_answer_id"], ["standardanswer.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["question_id"], ["examquestion.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["published_by_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "standard_answer_id",
            "revision_number",
            name="uq_standardanswerrevision_answer_number",
        ),
    )
    op.create_index(
        "ix_standardanswerrevision_standard_answer_id",
        "standardanswerrevision",
        ["standard_answer_id"],
    )
    op.create_index(
        "ix_standardanswerrevision_question_id", "standardanswerrevision", ["question_id"]
    )
    op.create_foreign_key(
        "fk_answerpreparationitem_revision",
        "answerpreparationitem",
        "standardanswerrevision",
        ["revision_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_standardanswerrevision_preparation_item",
        "standardanswerrevision",
        "answerpreparationitem",
        ["preparation_item_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("standardanswer", sa.Column("current_revision_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_standardanswer_current_revision",
        "standardanswer",
        "standardanswerrevision",
        ["current_revision_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("gradingitem", sa.Column("question_id", sa.Uuid(), nullable=True))
    op.add_column("gradingitem", sa.Column("answer_revision_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_gradingitem_question",
        "gradingitem",
        "examquestion",
        ["question_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_gradingitem_answer_revision",
        "gradingitem",
        "standardanswerrevision",
        ["answer_revision_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_gradingitem_question_id", "gradingitem", ["question_id"])
    op.create_index(
        "ix_gradingitem_answer_revision_id", "gradingitem", ["answer_revision_id"]
    )

    bind = op.get_bind()
    regions = bind.execute(
        sa.text(
            """
            SELECT r.id, r.exam_id, r.label, r.created_at,
                   a.id AS answer_id, a.question_text, a.question_type,
                   a.answer_text, a.max_score, a.rubric_text, a.scoring_points,
                   a.status AS answer_status, a.source_provider, a.source_model,
                   a.generation_confidence, a.answer_hash, a.published_at,
                   a.published_by_id, e.owner_id
            FROM examregion r
            JOIN exam e ON e.id = r.exam_id
            LEFT JOIN standardanswer a ON a.exam_region_id = r.id
            WHERE r.region_type = 'question'
            ORDER BY r.exam_id, r.page_number, r.y, r.created_at
            """
        )
    ).mappings()
    used_by_exam: dict[uuid.UUID, set[str]] = {}
    now = bind.execute(sa.text("SELECT now()" )).scalar_one()
    for row in regions:
        question_id = uuid.uuid4()
        used = used_by_exam.setdefault(row["exam_id"], set())
        key = _question_key(row["label"], used, f"legacy-{row['id']}")
        question_text = (row["question_text"] or row["label"] or key).strip()
        confirmed = bool(row["question_text"])
        bind.execute(
            sa.text(
                """
                INSERT INTO examquestion
                    (id, exam_id, question_key, label, question_text, question_type,
                     status, confirmed_by_id, confirmed_at, created_at, updated_at)
                VALUES
                    (:id, :exam_id, :question_key, :label, :question_text, :question_type,
                     :status, :confirmed_by_id, :confirmed_at, :created_at, :updated_at)
                """
            ),
            {
                "id": question_id,
                "exam_id": row["exam_id"],
                "question_key": key,
                "label": row["label"],
                "question_text": question_text,
                "question_type": row["question_type"],
                "status": "confirmed" if confirmed else "draft",
                "confirmed_by_id": row["published_by_id"] if confirmed else None,
                "confirmed_at": row["published_at"] if confirmed else None,
                "created_at": row["created_at"] or now,
                "updated_at": now,
            },
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO examquestionregion
                    (id, question_id, exam_region_id, sequence, role, created_at)
                VALUES (:id, :question_id, :region_id, 1, 'primary', :created_at)
                """
            ),
            {
                "id": uuid.uuid4(),
                "question_id": question_id,
                "region_id": row["id"],
                "created_at": now,
            },
        )
        if not row["answer_id"]:
            continue
        bind.execute(
            sa.text("UPDATE standardanswer SET question_id = :question_id WHERE id = :id"),
            {"question_id": question_id, "id": row["answer_id"]},
        )
        revision_id = uuid.uuid4()
        revision_status = (
            "published"
            if str(row["answer_status"]) == "ready" or row["published_at"]
            else "draft"
        )
        scoring_points = row["scoring_points"] or []
        payload = {
            "question_text": question_text,
            "question_type": row["question_type"],
            "answer_text": row["answer_text"],
            "max_score": str(row["max_score"]),
            "rubric_text": row["rubric_text"],
            "scoring_points": scoring_points,
        }
        creator_id = row["published_by_id"] or row["owner_id"]
        bind.execute(
            sa.text(
                """
                INSERT INTO standardanswerrevision
                    (id, standard_answer_id, question_id, revision_number,
                     question_key, question_text, question_type, answer_text,
                     max_score, rubric_text, scoring_points, source_provider,
                     source_model, generation_confidence, content_hash, status,
                     created_by_id, published_by_id, created_at, published_at)
                VALUES
                    (:id, :answer_id, :question_id, 1, :question_key,
                     :question_text, :question_type, :answer_text, :max_score,
                     :rubric_text, CAST(:scoring_points AS jsonb), :source_provider,
                     :source_model, :generation_confidence, :content_hash, :status,
                     :created_by_id, :published_by_id, :created_at, :published_at)
                """
            ),
            {
                "id": revision_id,
                "answer_id": row["answer_id"],
                "question_id": question_id,
                "question_key": key,
                "question_text": question_text,
                "question_type": row["question_type"],
                "answer_text": row["answer_text"],
                "max_score": Decimal(str(row["max_score"])),
                "rubric_text": row["rubric_text"],
                "scoring_points": json.dumps(scoring_points, ensure_ascii=False),
                "source_provider": row["source_provider"],
                "source_model": row["source_model"],
                "generation_confidence": row["generation_confidence"],
                "content_hash": row["answer_hash"] or _content_hash(payload),
                "status": revision_status,
                "created_by_id": creator_id,
                "published_by_id": creator_id if revision_status == "published" else None,
                "created_at": row["created_at"] or now,
                "published_at": (
                    row["published_at"] or now
                    if revision_status == "published"
                    else None
                ),
            },
        )
        bind.execute(
            sa.text(
                "UPDATE standardanswer SET current_revision_id = :revision_id WHERE id = :id"
            ),
            {"revision_id": revision_id, "id": row["answer_id"]},
        )

    bind.execute(
        sa.text(
            """
            UPDATE gradingitem gi
            SET question_id = sa.question_id,
                answer_revision_id = sa.current_revision_id
            FROM standardanswer sa
            WHERE sa.exam_region_id = gi.exam_region_id
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_gradingitem_answer_revision_id", table_name="gradingitem")
    op.drop_index("ix_gradingitem_question_id", table_name="gradingitem")
    op.drop_constraint("fk_gradingitem_answer_revision", "gradingitem", type_="foreignkey")
    op.drop_constraint("fk_gradingitem_question", "gradingitem", type_="foreignkey")
    op.drop_column("gradingitem", "answer_revision_id")
    op.drop_column("gradingitem", "question_id")

    op.drop_constraint("fk_standardanswer_current_revision", "standardanswer", type_="foreignkey")
    op.drop_column("standardanswer", "current_revision_id")
    op.drop_constraint("fk_answerpreparationitem_revision", "answerpreparationitem", type_="foreignkey")
    op.drop_constraint(
        "fk_standardanswerrevision_preparation_item",
        "standardanswerrevision",
        type_="foreignkey",
    )
    op.drop_index("ix_standardanswerrevision_question_id", table_name="standardanswerrevision")
    op.drop_index(
        "ix_standardanswerrevision_standard_answer_id", table_name="standardanswerrevision"
    )
    op.drop_table("standardanswerrevision")
    op.drop_index("ix_answerpreparationitem_question_id", table_name="answerpreparationitem")
    op.drop_index("ix_answerpreparationitem_run_id", table_name="answerpreparationitem")
    op.drop_table("answerpreparationitem")
    op.drop_index("ix_answerpreparationrun_exam_id", table_name="answerpreparationrun")
    op.drop_table("answerpreparationrun")
    op.drop_index("ix_questionrecognitionitem_run_id", table_name="questionrecognitionitem")
    op.drop_table("questionrecognitionitem")
    op.drop_index("ix_questionrecognitionrun_exam_id", table_name="questionrecognitionrun")
    op.drop_table("questionrecognitionrun")
    op.drop_index("ix_examquestionregion_exam_region_id", table_name="examquestionregion")
    op.drop_index("ix_examquestionregion_question_id", table_name="examquestionregion")
    op.drop_table("examquestionregion")
    op.drop_constraint("uq_standardanswer_question_id", "standardanswer", type_="unique")
    op.drop_index("ix_standardanswer_question_id", table_name="standardanswer")
    op.drop_constraint("fk_standardanswer_question", "standardanswer", type_="foreignkey")
    op.drop_column("standardanswer", "question_id")
    op.drop_index("ix_examquestion_exam_id", table_name="examquestion")
    op.drop_table("examquestion")
    op.drop_index("ix_examregion_exam_document_id", table_name="examregion")
    op.drop_constraint("fk_examregion_exam_document", "examregion", type_="foreignkey")
    op.drop_column("examregion", "exam_document_id")

    for name in (
        "standardanswerrevisionstatus",
        "answerpreparationitemstatus",
        "answerpreparationsource",
        "questionrecognitionitemstatus",
        "workflowrunstatus",
        "questionregionrole",
        "examquestionstatus",
    ):
        postgresql.ENUM(name=name).drop(op.get_bind(), checkfirst=True)
