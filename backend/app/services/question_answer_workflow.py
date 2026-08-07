from __future__ import annotations

import base64
import json
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any

from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.db import engine
from app.models import (
    AnswerPreparationItem,
    AnswerPreparationItemStatus,
    AnswerPreparationRun,
    AnswerPreparationSource,
    Exam,
    ExamDocument,
    ExamQuestion,
    ExamQuestionRegion,
    ExamQuestionStatus,
    ExamRegion,
    QuestionRecognitionItem,
    QuestionRecognitionItemStatus,
    QuestionRecognitionRun,
    StoredFile,
    WorkflowRunStatus,
    get_datetime_utc,
)
from app.services import billing as billing_service
from app.services.billing import ModelCallContext
from app.services.model_concurrency import distributed_model_slot
from app.services.reference_algorithm import (
    process_stored_files,
    stored_file_page_data_urls,
)
from app.services.submission_crops import crop_region_png, render_stored_file_page_image
from app.services.vision_grading import call_json_model_with_metadata


def _bounded_decimal(value: Any, *, default: str = "0") -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        result = Decimal(default)
    return max(Decimal("0"), min(Decimal("1"), result)).quantize(Decimal("0.0001"))


def _natural_key(value: str | None) -> tuple:
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", value or "")
        if part
    )


def _score_decimal(value: Any, *, default: str = "1") -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        result = Decimal(default)
    if result <= 0:
        result = Decimal(default)
    return result.quantize(Decimal("0.01"))


_UNSOLVABLE_CONCLUSION_RE = re.compile(
    r"无解|条件矛盾|无确定解|无法确定解|无法求解|无法作答"
)


def _strip_binary(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_binary(item)
            for key, item in value.items()
            if key not in {"image", "uprightImage"}
        }
    if isinstance(value, list):
        return [_strip_binary(item) for item in value]
    if isinstance(value, str) and value.startswith("data:image/"):
        return "[stored-file-reference]"
    return value


def _page_reference(page_id: str) -> tuple[uuid.UUID | None, int]:
    raw_document_id, separator, raw_page = page_id.partition(":page:")
    if not separator:
        return None, 1
    try:
        document_id = uuid.UUID(raw_document_id)
    except (TypeError, ValueError):
        document_id = None
    try:
        page_number = max(1, int(raw_page))
    except (TypeError, ValueError):
        page_number = 1
    return document_id, page_number


def _region_snapshot(block: dict, role: str, rotation: int) -> dict:
    document_id, page_number = _page_reference(str(block.get("pageId") or ""))

    def coordinate(name: str, default: float) -> float:
        try:
            return max(0.0, min(1000.0, float(block.get(name, default))))
        except (TypeError, ValueError):
            return default

    xmin = coordinate("xmin", 0)
    ymin = coordinate("ymin", 0)
    xmax = max(xmin + 1, coordinate("xmax", 1000))
    ymax = max(ymin + 1, coordinate("ymax", 1000))
    return {
        "source_block_id": str(block.get("id") or ""),
        "exam_document_id": str(document_id) if document_id else None,
        "page_number": page_number,
        "label": str(block.get("label") or block.get("questionNumber") or "题目"),
        "role": role,
        "rotation": rotation,
        "x": round(xmin / 1000, 4),
        "y": round(ymin / 1000, 4),
        "width": round(min(1000.0, xmax) / 1000 - xmin / 1000, 4),
        "height": round(min(1000.0, ymax) / 1000 - ymin / 1000, 4),
    }


def _match_region_ids(
    *,
    snapshots: list[dict],
    regions: list[ExamRegion],
    allow_legacy_document_match: bool,
) -> list[str]:
    matched: list[str] = []
    used: set[uuid.UUID] = set()
    for snapshot in snapshots:
        document_id = snapshot.get("exam_document_id")
        candidates: list[tuple[float, ExamRegion]] = []
        for region in regions:
            if region.id in used or region.page_number != snapshot["page_number"]:
                continue
            if region.exam_document_id:
                if str(region.exam_document_id) != str(document_id):
                    continue
            elif not allow_legacy_document_match:
                continue
            distance = sum(
                abs(float(getattr(region, key)) - float(snapshot[key]))
                for key in ("x", "y", "width", "height")
            )
            if distance <= 0.12:
                candidates.append((distance, region))
        candidates.sort(key=lambda pair: pair[0])
        if candidates and (
            len(candidates) == 1 or candidates[0][0] + 0.02 < candidates[1][0]
        ):
            region = candidates[0][1]
            used.add(region.id)
            matched.append(str(region.id))
    return matched


def persist_question_recognition_payload(
    *,
    session: Session,
    run: QuestionRecognitionRun,
    payload: dict,
    requested_ids: list[uuid.UUID],
    started: float,
) -> int:
    blocks = {
        str(block.get("id")): block
        for block in payload.get("blocks", [])
        if isinstance(block, dict) and block.get("id")
    }
    layout_rotations = {
        str(layout.get("pageId")): int(layout.get("rotation") or 0)
        for layout in payload.get("layouts", [])
        if isinstance(layout, dict)
    }
    regions = list(
        session.exec(select(ExamRegion).where(ExamRegion.exam_id == run.exam_id)).all()
    )
    errors = 0
    used_source_keys: set[str] = set()
    for index, result in enumerate(payload.get("results", []), start=1):
        if not isinstance(result, dict):
            continue
        raw_source_key = str(
            result.get("blockId") or result.get("id") or f"result-{index}"
        )
        source_key = raw_source_key[:240]
        suffix = 2
        while source_key in used_source_keys:
            source_key = f"{raw_source_key[:230]}-{suffix}"
            suffix += 1
        used_source_keys.add(source_key)
        block_ids = result.get("sourceBlockIds") or [raw_source_key]
        snapshots = []
        for block_index, block_id in enumerate(block_ids):
            block = blocks.get(str(block_id))
            if not block:
                continue
            snapshots.append(
                _region_snapshot(
                    block,
                    "primary" if block_index == 0 else "continuation",
                    layout_rotations.get(str(block.get("pageId") or ""), 0),
                )
            )
        region_ids = _match_region_ids(
            snapshots=snapshots,
            regions=regions,
            allow_legacy_document_match=len(requested_ids) == 1,
        )
        question_key = str(result.get("questionNumber") or source_key).strip()
        question_text = str(result.get("question") or "").strip()
        error = str(result.get("error") or "").strip()
        if error or not question_text:
            errors += 1
        session.add(
            QuestionRecognitionItem(
                run_id=run.id,
                source_item_key=source_key,
                question_key=question_key[:100] or source_key[:100],
                label=str(
                    result.get("sourceLabel")
                    or (f"第{question_key}题" if question_key else source_key)
                )[:255],
                question_text=question_text[:20000],
                student_answer_text=(
                    str(result.get("studentAnswer") or "").strip()[:12000] or None
                ),
                question_type=(
                    str(result.get("answerType") or "").strip()[:50] or None
                ),
                confidence=(
                    _bounded_decimal(result.get("confidence"))
                    if result.get("confidence") is not None
                    else None
                ),
                notes=(
                    "；".join(
                        item
                        for item in (str(result.get("notes") or "").strip(), error)
                        if item
                    )[:4000]
                    or None
                ),
                region_ids=region_ids,
                region_snapshots=snapshots,
                raw_result=_strip_binary(result),
                status=QuestionRecognitionItemStatus.DRAFT,
            )
        )
    run.timing = {
        **(payload.get("timing") or {}),
        "orchestrationMs": round((time.perf_counter() - started) * 1000),
    }
    run.raw_output = _strip_binary(payload)
    run.status = (
        WorkflowRunStatus.COMPLETED_WITH_ERRORS
        if errors
        else WorkflowRunStatus.COMPLETED
    )
    run.completed_at = get_datetime_utc()
    session.add(run)
    return errors


def execute_question_recognition(run_id: str) -> None:
    run_uuid = uuid.UUID(run_id)
    started = time.perf_counter()
    with Session(engine) as session:
        run = session.get(QuestionRecognitionRun, run_uuid)
        if not run:
            return
        run.status = WorkflowRunStatus.RUNNING
        run.started_at = get_datetime_utc()
        run.error_message = None
        reservation_id = (
            uuid.UUID(str(run.raw_output["billing_reservation_id"]))
            if (run.raw_output or {}).get("billing_reservation_id")
            else None
        )
        session.add(run)
        session.commit()
        try:
            requested_ids = [uuid.UUID(item) for item in run.document_ids]
            rows = session.exec(
                select(ExamDocument, StoredFile)
                .join(StoredFile, ExamDocument.stored_file_id == StoredFile.id)
                .where(
                    ExamDocument.exam_id == run.exam_id,
                    col(ExamDocument.id).in_(requested_ids),
                )
            ).all()
            by_id = {
                document.id: (document, stored_file) for document, stored_file in rows
            }
            documents = [by_id[item] for item in requested_ids if item in by_id]
            if len(documents) != len(requested_ids):
                raise RuntimeError("部分试卷文件不存在或不属于当前考试")

            exam = session.get(Exam, run.exam_id)
            if not exam:
                raise RuntimeError("考试不存在")
            with distributed_model_slot(org_id=exam.org_id, org_limit=8):
                payload = process_stored_files(
                    documents=documents,
                    provider=run.provider,
                    model=run.model,
                )
            if exam:
                billing_service.record_model_attempt(
                    ModelCallContext(
                        org_id=exam.org_id,
                        exam_id=run.exam_id,
                        reservation_id=reservation_id,
                        workflow_purpose="question_recognition",
                        resource_id=str(run.id),
                        billing_key=(
                            f"{exam.org_id}:question_recognition:{run.id}:pipeline-v2"
                        ),
                    ),
                    requested_provider=run.provider,
                    requested_model=run.model,
                    actual_provider=str(payload.get("provider") or run.provider),
                    actual_model=str(payload.get("model") or run.model),
                    usage=(
                        payload.get("usage")
                        if isinstance(payload.get("usage"), dict)
                        else None
                    ),
                    latency_ms=round((time.perf_counter() - started) * 1000),
                    attempt=1,
                )
            persist_question_recognition_payload(
                session=session,
                run=run,
                payload=payload,
                requested_ids=requested_ids,
                started=started,
            )
            if reservation_id:
                billing_service.settle_reservation(session, reservation_id)
            session.commit()
        except Exception as exc:
            session.rollback()
            run = session.get(QuestionRecognitionRun, run_uuid)
            if run:
                run.status = WorkflowRunStatus.FAILED
                run.error_message = str(exc)[:2000]
                run.completed_at = get_datetime_utc()
                run.timing = {
                    **(run.timing or {}),
                    "orchestrationMs": round((time.perf_counter() - started) * 1000),
                }
                session.add(run)
                session.commit()


def _normalize_scoring_points(raw: Any, max_score: Decimal) -> list[dict]:
    if not isinstance(raw, list):
        raw = []
    points: list[dict] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        description = str(
            item.get("description") or item.get("criterion") or ""
        ).strip()
        if not description:
            continue
        point_value = _score_decimal(item.get("points"), default="0")
        points.append(
            {
                **item,
                "id": str(item.get("id") or f"p{index}"),
                "description": description,
                "points": float(point_value),
                "required": bool(item.get("required", True)),
            }
        )
    if not points:
        points = [
            {
                "id": "p1",
                "description": "答案正确且过程、单位符合题目要求",
                "points": float(max_score),
                "required": True,
            }
        ]
    else:
        total = sum(Decimal(str(point["points"])) for point in points)
        if total != max_score:
            if len(points) == 1 or total <= 0:
                points[0]["points"] = float(max_score)
                points = points[:1]
            else:
                scale = max_score / total
                allocated = Decimal("0")
                for point in points[:-1]:
                    value = (Decimal(str(point["points"])) * scale).quantize(
                        Decimal("0.01")
                    )
                    point["points"] = float(value)
                    allocated += value
                points[-1]["points"] = float(max_score - allocated)
    return points


def _declared_question_scores(text: str) -> dict[str, Decimal]:
    scores: dict[str, Decimal] = {}
    for question_key, raw_score in re.findall(
        r"(?<!\d)(\d{1,3})\s*题\s*(\d+(?:\.\d+)?)\s*分", text or ""
    ):
        scores[question_key] = _score_decimal(raw_score, default="1")
    return scores


def _leading_question_score(text: str) -> tuple[Decimal, str] | None:
    """Extract an explicit score printed at the start of one question."""
    match = re.match(
        r"^\s*(?:第?\s*\d{1,3}\s*(?:题|[.、])\s*)?[（(]\s*"
        r"(\d+(?:\.\d+)?)\s*分\s*[）)]",
        text or "",
    )
    if not match:
        return None
    return _score_decimal(match.group(1), default="1"), match.group(0).strip()


_SECTION_KIND_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("multiple_choice", ("多项选择", "多选")),
    ("single_choice", ("单项选择", "单选")),
    ("true_false", ("判断",)),
    ("fill_blank", ("填空",)),
    ("experiment", ("实验",)),
    ("calculation", ("计算",)),
)
_CANONICAL_QUESTION_TYPES = {kind for kind, _ in _SECTION_KIND_PATTERNS}
_SECTION_POINTS_RE = re.compile(r"每\s*(?:小)?题\s*(\d+(?:\.\d+)?)\s*分")
_SECTION_COUNT_RE = re.compile(r"(?:本题)?共\s*(\d+)\s*(?:小)?题")
_SECTION_LINE_HINT_RE = re.compile(
    r"(?:共\s*\d+\s*(?:小)?题|选择|填空|实验|计算|判断|作图)"
)
_EVIDENCE_START_RE = re.compile(
    r"[一二三四五六七八九十]+[、.．]|本题共|每\s*(?:小)?题\s*\d"
)
_EVIDENCE_ANSWER_RE = re.compile(r"正确选项|正确答案|答案为|答案是|本题选|故选|应选")
_EVIDENCE_ZERO_POINTS_RE = re.compile(r"得\s*0\s*分")
_EVIDENCE_GRADING_SENTENCE_RE = re.compile(
    r"得\s*\d+(?:\.\d+)?\s*分|少选|选对|选错|错选"
)


def _trim_score_rule_evidence(line: str) -> str:
    """Keep only the score-related span of a quoted score-rule line.

    The quoted line may continue into answer-specific conclusions
    ("本题正确选项为B、C……"). Those belong to the anchor question only and
    must never leak into other questions' prompts or match reasons, so the
    evidence span ends at the "得0分" tail (or the first sentence end) and is
    always cut before any answer-specific marker.
    """
    text = str(line or "").strip().strip("\"“”'‘’")
    points_match = _SECTION_POINTS_RE.search(text)
    if not points_match:
        return ""
    starts = [
        match.start()
        for match in _EVIDENCE_START_RE.finditer(text)
        if match.start() <= points_match.start()
    ]
    segment = text[min(starts) if starts else points_match.start() :]
    answer_match = _EVIDENCE_ANSWER_RE.search(segment)
    if answer_match:
        segment = segment[: answer_match.start()]
    zero_match = _EVIDENCE_ZERO_POINTS_RE.search(segment)
    if zero_match:
        tail = segment[zero_match.end() :]
        segment = segment[: zero_match.end()] + ("。" if tail.startswith("。") else "")
    else:
        # Keep the score sentence plus the grading-rule sentences that
        # directly follow it ("全部选对得4分，少选得2分。"); stop at the first
        # sentence that is not a grading rule.
        sentences = re.split(r"(?<=[。；;])", segment)
        kept: list[str] = []
        for sentence in sentences:
            if kept and not _EVIDENCE_GRADING_SENTENCE_RE.search(sentence):
                break
            kept.append(sentence)
        segment = "".join(kept)
    return segment.strip().strip("\"“”'‘’，,、：:").strip()


def _section_kind_from_text(text: str) -> str:
    for kind, keywords in _SECTION_KIND_PATTERNS:
        if any(keyword in text for keyword in keywords):
            return kind
    return "unknown"


def _canonical_question_type(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "unknown"
    lowered = text.casefold()
    if lowered in _CANONICAL_QUESTION_TYPES:
        return lowered
    return _section_kind_from_text(text)


def _numeric_question_key(value: Any) -> int | None:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else None


def _rule_covers_key(rule: dict, question_key: str) -> bool:
    anchor = _numeric_question_key(rule.get("anchor_question_key"))
    target = _numeric_question_key(question_key)
    count = rule.get("question_count")
    if anchor is None or target is None or not count:
        return False
    return anchor <= target < anchor + int(count)


def _section_score_rules_from_question_texts(questions: list[dict]) -> list[dict]:
    """Collect section-level printed score rules found inside any question text.

    The OCR keeps lines like "二、多项选择题：本题共5小题，每小题4分，共20分，
    少选得2分" inside the first question of a section, so one question's text can
    carry the score evidence for the whole section.
    """
    rules: list[dict] = []
    seen: set[tuple] = set()
    for question in questions:
        anchor_key = str(question.get("question_key") or "").strip()
        for raw_line in str(question.get("question_text") or "").splitlines():
            line = raw_line.strip()
            points_match = _SECTION_POINTS_RE.search(line)
            if not points_match or not _SECTION_LINE_HINT_RE.search(line):
                continue
            evidence = _trim_score_rule_evidence(line)
            if not evidence or not _SECTION_POINTS_RE.search(evidence):
                continue
            count_match = _SECTION_COUNT_RE.search(evidence)
            rule = {
                "section_type": _section_kind_from_text(evidence),
                "points_each": _score_decimal(points_match.group(1), default="1"),
                "grading_rule_text": evidence,
                "evidence_text": evidence,
                # The section heading sits at the top of its first question's
                # crop, so the anchor question is treated as the section start.
                "anchor_question_key": anchor_key,
                "question_count": (int(count_match.group(1)) if count_match else None),
                "source": "question_text_section_rule",
            }
            signature = (
                rule["section_type"],
                str(rule["points_each"]),
                rule["anchor_question_key"],
                rule["question_count"],
                rule["grading_rule_text"],
            )
            if signature not in seen:
                seen.add(signature)
                rules.append(rule)
    return rules


def _collect_exam_section_score_rules(
    questions: list[dict], declared_allocations: dict[str, dict]
) -> list[dict]:
    rules = _section_score_rules_from_question_texts(questions)
    seen = {
        (
            rule["section_type"],
            str(rule["points_each"]),
            rule.get("anchor_question_key"),
            rule.get("question_count"),
        )
        for rule in rules
    }
    for allocation in declared_allocations.values():
        if allocation.get("source") != "section_score_rule":
            continue
        signature = (
            str(allocation.get("section_type") or "unknown"),
            str(allocation["max_score"]),
            allocation.get("section_first_question_key"),
            allocation.get("section_question_count"),
        )
        if signature in seen:
            continue
        seen.add(signature)
        rules.append(
            {
                "section_type": str(allocation.get("section_type") or "unknown"),
                "points_each": allocation["max_score"],
                "grading_rule_text": allocation["grading_rule_text"],
                "evidence_text": allocation["evidence_text"],
                "anchor_question_key": allocation.get("section_first_question_key"),
                "question_count": allocation.get("section_question_count"),
                "source": "page_header_section_rule",
            }
        )
    return rules


def _propagate_section_score_rules(
    questions: list[dict],
    declared_allocations: dict[str, dict],
    rules: list[dict] | None = None,
) -> list[dict]:
    """Fill missing per-question scores from exam-wide section score rules.

    A question without its own printed score adopts a section rule when exactly
    one distinct score matches it — by question-number range first, otherwise by
    question type. Conflicting or ambiguous matches keep the existing fallback.
    When ``rules`` is given it is used as-is (e.g. rules harvested from solved
    items mid-batch); otherwise rules are collected from question texts and
    page-header allocations.
    """
    if rules is None:
        rules = _collect_exam_section_score_rules(questions, declared_allocations)
    for question in questions:
        key = str(question.get("question_key") or "").strip()
        if not key or key in declared_allocations:
            continue
        ranged = [rule for rule in rules if _rule_covers_key(rule, key)]
        if ranged:
            pool = ranged
        else:
            question_kind = _canonical_question_type(question.get("question_type"))
            pool = [
                rule
                for rule in rules
                if rule["section_type"] != "unknown"
                and rule["section_type"] == question_kind
                and not (rule.get("anchor_question_key") and rule.get("question_count"))
            ]
        distinct_scores = {rule["points_each"] for rule in pool}
        if not pool or len(distinct_scores) != 1:
            continue
        rule = pool[0]
        declared_allocations[key] = {
            "max_score": rule["points_each"],
            "evidence_text": rule["evidence_text"],
            "grading_rule_text": rule["grading_rule_text"],
            "source": (
                "batch_harvest"
                if rule.get("source") == "batch_harvest"
                else "section_shared"
            ),
            "anchor_question_key": rule.get("anchor_question_key"),
        }
    return rules


def _exam_score_rules_summary(rules: list[dict]) -> str:
    lines: list[str] = []
    seen: set[tuple] = set()
    for rule in rules:
        signature = (
            rule["section_type"],
            str(rule["points_each"]),
            rule["grading_rule_text"],
        )
        if signature in seen:
            continue
        seen.add(signature)
        anchor = _numeric_question_key(rule.get("anchor_question_key"))
        count = rule.get("question_count")
        if anchor is not None and count:
            scope = f"第{anchor}-{anchor + int(count) - 1}题"
        elif anchor is not None:
            scope = f"自第{anchor}题起"
        else:
            scope = "范围未标明"
        lines.append(
            f"- {scope}：每小题{rule['points_each'].normalize():f}分；计分规则原文：{rule['grading_rule_text']}"
        )
    return "\n".join(lines)


_HARVEST_FEATURE_RE = re.compile(
    r"共\s*\d+\s*(?:小)?题|选择|填空|实验|计算|少选|选对但不全"
)
_HARVEST_REJECT_RE = re.compile(
    r"卷面未标注分值|待教师确认|按.{0,8}分设定|建议分值|估分"
)


def _harvest_section_rules_from_results(results: list[dict]) -> list[dict]:
    """Harvest printed section score rules the solver actually saw on crops.

    During a batch, one question's crop may contain the section header line
    (e.g. "二、多项选择题：本题共5小题，每小题4分，共20分，选对但不全的得2分")
    that other questions' crops lack. The solver quotes that line in its
    rubric/answer; harvest those quoted lines as batch-shared evidence.
    Each quoted line is trimmed to its score-rule span
    (`_trim_score_rule_evidence`): answer-specific conclusions of the anchor
    question ("本题正确选项为B、C……") never leak into the shared evidence.
    Self-declared fallback lines ("卷面未标注分值，按 X 分设定（待教师确认）")
    are explicitly rejected.
    """
    rules: list[dict] = []
    seen: set[tuple] = set()
    for result in results:
        anchor = str(result.get("question_key") or "").strip()
        if not anchor:
            continue
        texts = [result.get("rubric_text"), result.get("answer_text")]
        raw = result.get("raw_result")
        if isinstance(raw, dict):
            texts.extend(value for value in raw.values() if isinstance(value, str))
        for text in texts:
            for raw_line in str(text or "").splitlines():
                line = raw_line.strip().strip('"“”')
                if not _SECTION_POINTS_RE.search(line):
                    continue
                if not _HARVEST_FEATURE_RE.search(line):
                    continue
                if _HARVEST_REJECT_RE.search(line):
                    continue
                evidence = _trim_score_rule_evidence(line)
                if not evidence or not _SECTION_POINTS_RE.search(evidence):
                    continue
                count_match = _SECTION_COUNT_RE.search(evidence)
                rule = {
                    "section_type": _section_kind_from_text(evidence),
                    "points_each": _score_decimal(
                        _SECTION_POINTS_RE.search(evidence).group(1), default="1"
                    ),
                    "grading_rule_text": evidence,
                    "evidence_text": evidence,
                    "anchor_question_key": anchor,
                    "question_count": (
                        int(count_match.group(1)) if count_match else None
                    ),
                    "source": "batch_harvest",
                }
                signature = (
                    rule["section_type"],
                    str(rule["points_each"]),
                    rule["anchor_question_key"],
                    rule["question_count"],
                    rule["grading_rule_text"],
                )
                if signature not in seen:
                    seen.add(signature)
                    rules.append(rule)
    return rules


def _score_hints_from_header_payload(
    parsed: dict, *, first_question_key: str
) -> dict[str, Decimal]:
    return {
        key: allocation["max_score"]
        for key, allocation in _score_allocations_from_header_payload(
            parsed, first_question_key=first_question_key
        ).items()
    }


def _score_allocations_from_header_payload(
    parsed: dict, *, first_question_key: str
) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for item in parsed.get("scores", []):
        if not isinstance(item, dict):
            continue
        key = str(item.get("question_key") or "").strip()
        evidence = str(item.get("evidence_text") or "").strip()
        if key and evidence:
            result[key] = {
                "max_score": _score_decimal(item.get("max_score"), default="1"),
                "evidence_text": evidence,
                "grading_rule_text": str(
                    item.get("grading_rule_text") or evidence
                ).strip(),
                "source": "explicit_question_score",
            }
    for rule in parsed.get("section_rules", []):
        if not isinstance(rule, dict):
            continue
        try:
            start = int(str(rule.get("first_question_key") or first_question_key))
            count = int(rule.get("question_count"))
            points_each = _score_decimal(rule.get("points_each"), default="1")
            total = Decimal(str(rule.get("total_score")))
        except (InvalidOperation, TypeError, ValueError):
            continue
        evidence = str(rule.get("evidence_text") or "").strip()
        if count < 1 or count > 200 or points_each * count != total or not evidence:
            continue
        grading_rule_text = str(rule.get("grading_rule_text") or evidence).strip()
        for question_number in range(start, start + count):
            result.setdefault(
                str(question_number),
                {
                    "max_score": points_each,
                    "evidence_text": evidence,
                    "grading_rule_text": grading_rule_text,
                    "section_total_score": total,
                    "section_first_question_key": str(start),
                    "section_question_count": count,
                    "section_type": str(rule.get("section_type") or "unknown"),
                    "source": "section_score_rule",
                },
            )
    return result


def _page_header_score_hints(
    *,
    stored_file: StoredFile,
    page_number: int,
    first_y: float,
    first_question_key: str,
    provider: str,
    model: str,
    fallback_models: list[str],
    billing_context: ModelCallContext | None = None,
) -> dict[str, dict]:
    """Read printed question-score allocations from the page header, not from OCR text."""
    image = render_stored_file_page_image(
        stored_file=stored_file, page_number=page_number
    )
    try:
        width, height = image.size
        # Include the section title immediately above the first question, while
        # avoiding the rest of a student-filled page.
        bottom = max(1, min(height, round(height * min(0.34, first_y + 0.06))))
        header = image.crop((0, 0, width, bottom))
        try:
            buffer = BytesIO()
            header.save(buffer, format="PNG")
            image_url = "data:image/png;base64," + base64.b64encode(
                buffer.getvalue()
            ).decode("ascii")
        finally:
            header.close()
    finally:
        image.close()
    prompt = f"""你是试卷赋分结构提取器，只提取图片中印刷的赋分事实，不解题、不估分、不采用常识补全。
当前页面最上方识别到的第一道题号是 {first_question_key}。
必须区分印刷文字和手写内容，忽略学生答案、得分、草稿、批改符号。

提取规则：
1. 逐题分值，例如“21题10分”，写入 scores，并逐字抄录 evidence_text。
2. 大题统一分值，例如“本题共8小题，每小题3分，共24分”，写入 section_rules。如果标题没有明确起始题号，first_question_key 使用当前页第一题号 {first_question_key}。
3. 选择题通常在同一大题内同分，但这只能用于检查，不能作为赋分证据。只有卷面明确写出某题例外时，才能在 scores 中覆盖大题规则。
4. 多选题要抄录完整计分规则，例如“全部选对得4分，选对但不全得2分，有选错得0分”，写入 grading_rule_text；不得自行创造少选分。
5. 提取大题总分和试卷总分，并抄录对应原文证据。大题规则必须满足 question_count × points_each = total_score，否则不要返回。
6. 看不清、信息不完整或只能推测时不要填数字，放入 warnings。

只返回 JSON：
{{
  "scores":[{{"question_key":"21","max_score":10,"evidence_text":"21题10分","grading_rule_text":"21题10分"}}],
  "section_rules":[{{"section_type":"single_choice","first_question_key":"1","question_count":8,"points_each":3,"total_score":24,"evidence_text":"一、单项选择题：本题共8小题，每小题3分，共24分","grading_rule_text":"每题只有一个正确选项，选对得3分，未选或错选得0分"}}],
  "exam_total_score":100,
  "exam_total_evidence_text":"满分100分",
  "warnings":[]
}}。
没有证据时对应数组为空、数值为 null。"""
    parsed, _model, _elapsed, _usage = call_json_model_with_metadata(
        provider=provider,
        model=model,
        fallback_models=fallback_models,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
        billing_context=billing_context,
    )
    return _score_allocations_from_header_payload(
        parsed, first_question_key=first_question_key
    )


def _solve_question(
    question: dict,
    provider: str,
    model: str,
    fallback_models: list[str] | None = None,
    billing_context: ModelCallContext | None = None,
) -> dict:
    declared_score = question.get("declared_max_score")
    score_evidence = str(question.get("score_evidence_text") or "").strip()
    grading_rule = str(question.get("declared_grading_rule") or "").strip()
    score_evidence_source = str(question.get("score_evidence_source") or "").strip()
    score_evidence_anchor = str(question.get("score_evidence_anchor") or "").strip()
    exam_rules_text = str(question.get("exam_score_rules_text") or "").strip()
    exam_rules_block = (
        f"全卷大题赋分规则汇总（跨题共享证据）：\n{exam_rules_text}\n"
        "若本题题型、题号属于上述某个大题，必须采用该大题的分值与计分规则，即使本题题干和裁图中没有直接证据；多个大题规则冲突或无法归属时，才允许按“卷面未标注分值”处理。\n"
        if exam_rules_text
        else ""
    )
    is_choice_question = question.get("question_type") in {
        "single_choice",
        "multiple_choice",
        "true_false",
    }
    if declared_score is not None:
        if score_evidence_source == "batch_harvest":
            origin_note = f"（赋分证据来自第{score_evidence_anchor}题裁图，批次内共享）"
        elif score_evidence_source == "section_shared":
            origin_note = "（赋分证据来自大题说明，跨题共享）"
        else:
            origin_note = ""
        declared_score_text = f"赋分提取器已从卷面确定本题满分为 {declared_score} 分{origin_note}，证据原文：{score_evidence}。max_score 必须严格为该值。卷面计分规则：{grading_rule or '按满分规则评分'}。"
    else:
        declared_score_text = "赋分提取器没有找到本题明确分值。必须先从题目全文和裁图中解析印刷分值（题号后的“（X分）”、大题说明行的“每小题X分，共X分”），解析到就作为 max_score 并在 rubric_text 中引用证据原文；确实解析不到才视为卷面未标注。"
    prompt = f"""你是资深的中文学科教师。请独立解答题目，并生成可直接执行的专业评分准则。AI 结果只是教师待确认草稿。
题目标识：{question["question_key"]}
题目类型：{question.get("question_type") or "未知"}
题目全文：
{question["question_text"]}

{exam_rules_block}下方附有题目原始裁图。图中的仪器读数、图表、选项、题面分值与公式都是题目事实，必须逐项读取，不能仅依据上方文本猜测。{declared_score_text}
分值规则：若已有赋分证据或能从题面文本、裁图中解析到印刷分值，max_score 必须使用该分值，禁止自行编造分值；rubric_text 和 scoring_points 必须忠实执行卷面印刷的计分规则。卷面确实未标注分值时，必须在 rubric_text 开头显式写明“卷面未标注分值，按……设定（待教师确认）”，且 confidence 不得高于 0.5。多选题默认遵循“全部选对得满分、少选得部分分、错选得0分”；卷面写明具体少选分值（如“少选得2分”）时按卷面执行，未写明时按默认规则给部分分并注明“少选分值待教师确认”。
存疑处理：题干疑似不完整、条件看似矛盾或缺少必要图表信息时，禁止把“无解”“条件矛盾”“无法确定”作为标准答案结论。必须写明你采用的合理假设，在假设下照常推导出完整的尝试性解答，并在 rubric_text 开头写“【需人工复核】缺失/存疑信息：……”，confidence 不得高于 0.4。
评分点分值之和必须等于 max_score。只返回 JSON：
{{"question_key":"{question["question_key"]}","answer_text":"完整标准答案","max_score":5,"rubric_text":"总体评分规则、等价答案、单位和容差规则","scoring_points":[{{"id":"p1","description":"可判定的得分条件","points":1,"required":true,"accepted_evidence":["等价表述"]}}],"confidence":0.0}}"""
    content: list[dict] = [{"type": "text", "text": prompt}]
    for index, image_bytes in enumerate(question.get("image_bytes") or [], start=1):
        content.append({"type": "text", "text": f"题目原始裁图 {index}"})
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": "data:image/png;base64,"
                    + base64.b64encode(image_bytes).decode("ascii")
                },
            }
        )
    parsed, used_model, elapsed_ms, usage = call_json_model_with_metadata(
        provider=provider,
        model=model,
        fallback_models=fallback_models or [],
        messages=[{"role": "user", "content": content}],
        billing_context=billing_context,
    )
    used_provider = str(usage.pop("_used_provider", provider))
    score_requires_review = declared_score is None and is_choice_question
    max_score = (
        _score_decimal(declared_score)
        if declared_score is not None
        else (
            Decimal("1.00")
            if score_requires_review
            else _score_decimal(parsed.get("max_score"), default="1")
        )
    )
    answer_text = str(
        parsed.get("answer_text") or parsed.get("canonical_answer") or ""
    ).strip()
    rubric_text = str(parsed.get("rubric_text") or "").strip()
    confidence = _bounded_decimal(parsed.get("confidence"))
    solution_requires_review = bool(
        answer_text and _UNSOLVABLE_CONCLUSION_RE.search(answer_text)
    )
    if solution_requires_review:
        confidence = min(confidence, Decimal("0.4"))
        if "【需人工复核】" not in rubric_text:
            rubric_text = (
                "【需人工复核】模型判定题面存疑（题干不完整、缺图或条件矛盾），"
                "答案仅为尝试性结论，需教师核对原卷后确认。\n" + rubric_text
            )
    return {
        "question_id": question["id"],
        "question_key": question["question_key"],
        "answer_text": answer_text,
        "max_score": max_score,
        "rubric_text": rubric_text,
        "scoring_points": _normalize_scoring_points(
            parsed.get("scoring_points"), max_score
        ),
        "confidence": confidence,
        "raw_result": {
            **parsed,
            "_used_provider": used_provider,
            "_used_model": used_model,
        },
        "used_provider": used_provider,
        "used_model": used_model,
        "elapsed_ms": elapsed_ms,
        "usage": usage,
        "score_requires_review": score_requires_review,
        "solution_requires_review": solution_requires_review,
        "score_evidence_text": score_evidence,
        "score_evidence_source": score_evidence_source,
        "score_evidence_anchor": score_evidence_anchor,
        "declared_grading_rule": grading_rule,
    }


def _answer_item_fields(result: dict) -> dict:
    """Column values for an AnswerPreparationItem built from a solve result."""
    evidence = result["score_evidence_text"]
    source = result.get("score_evidence_source")
    if not evidence:
        match_reason = "按已确认题目直接解题；题面未提取到明确赋分证据"
    elif source == "batch_harvest":
        match_reason = (
            f"按已确认题目直接解题；赋分证据来自第"
            f"{result.get('score_evidence_anchor') or '?'}题裁图"
            f"（批次内共享）：{evidence}"
        )
    elif source == "section_shared":
        match_reason = (
            f"按已确认题目直接解题；赋分证据来自大题说明（跨题共享）：{evidence}"
        )
    else:
        match_reason = f"按已确认题目直接解题；赋分证据：{evidence}"
    return {
        "answer_text": result["answer_text"][:20000],
        "max_score": result["max_score"],
        "rubric_text": result["rubric_text"][:12000] or None,
        "scoring_points": result["scoring_points"],
        "confidence": result["confidence"],
        "match_reason": match_reason[:2000],
        "raw_result": _strip_binary(
            {
                **result["raw_result"],
                "scoreEvidenceText": result["score_evidence_text"],
                "scoreEvidenceSource": result["score_evidence_source"],
                "scoreEvidenceAnchor": result.get("score_evidence_anchor") or "",
                "declaredGradingRule": result["declared_grading_rule"],
                "scoreRequiresReview": result["score_requires_review"],
                "solutionRequiresReview": result["solution_requires_review"],
            }
        ),
        "status": (
            AnswerPreparationItemStatus.CONFLICT
            if (result["score_requires_review"] or result["solution_requires_review"])
            else (
                AnswerPreparationItemStatus.MATCHED
                if result["answer_text"]
                else AnswerPreparationItemStatus.FAILED
            )
        ),
        "error_message": (
            "题面未识别到明确分值，请教师填写满分并保存草稿"
            if result["score_requires_review"]
            else (
                "题目疑似不完整、缺图或条件矛盾，已生成尝试性解答，请教师复核"
                if result["solution_requires_review"]
                else (None if result["answer_text"] else "模型未返回标准答案")
            )
        ),
    }


def _parse_answer_documents(
    *,
    questions: list[dict],
    documents: list[tuple[ExamDocument, StoredFile]],
    provider: str,
    model: str,
    fallback_models: list[str] | None = None,
    billing_context: ModelCallContext | None = None,
) -> tuple[dict, str, int, dict]:
    question_catalog = [
        {
            "question_key": item["question_key"],
            "label": item["label"],
            "question_text": item["question_text"],
        }
        for item in questions
    ]
    content: list[dict] = [
        {
            "type": "text",
            "text": f"""你是标准答案文档整理员。图片是教师上传的答案文档，题目目录如下：
{json.dumps(question_catalog, ensure_ascii=False)}
请忠实读取答案文档，按 question_key 精确匹配并整理评分准则。不能在文档没有对应答案时自行解题补全。无法唯一匹配的条目仍要返回原始 source_question_key，confidence 降低。评分点合计必须等于 max_score。只返回 JSON：
{{"answers":[{{"source_question_key":"文档原题号","question_key":"目录中的精确题目标识或空字符串","answer_text":"标准答案","max_score":5,"rubric_text":"评分规则","scoring_points":[{{"id":"p1","description":"得分条件","points":1,"required":true}}],"confidence":0.0,"match_reason":"匹配依据"}}]}}""",
        }
    ]
    for _document, stored_file in documents:
        for page_number, image_url in enumerate(
            stored_file_page_data_urls(stored_file=stored_file), start=1
        ):
            content.append(
                {
                    "type": "text",
                    "text": f"答案文件 {stored_file.original_filename}，第 {page_number} 页",
                }
            )
            content.append({"type": "image_url", "image_url": {"url": image_url}})
    return call_json_model_with_metadata(
        provider=provider,
        model=model,
        fallback_models=fallback_models or [],
        messages=[{"role": "user", "content": content}],
        billing_context=billing_context,
    )


def execute_answer_preparation(run_id: str) -> None:
    run_uuid = uuid.UUID(run_id)
    started = time.perf_counter()
    with Session(engine) as session:
        run = session.get(AnswerPreparationRun, run_uuid)
        if not run:
            return
        run.status = WorkflowRunStatus.RUNNING
        run.started_at = get_datetime_utc()
        run.error_message = None
        reservation_id = (
            uuid.UUID(str(run.raw_output["billing_reservation_id"]))
            if (run.raw_output or {}).get("billing_reservation_id")
            else None
        )
        session.add(run)
        session.commit()
        try:
            from app.services.system_config import get_grading_defaults

            exam = session.get(Exam, run.exam_id)
            if not exam:
                raise RuntimeError("考试不存在")
            defaults = get_grading_defaults(session, exam.org_id)
            vision_fallback_models = [
                str(item) for item in defaults["vision_fallback_models"]
            ]
            reasoning_fallback_models = [
                str(item) for item in defaults["reasoning_fallback_models"]
            ]
            questions = [
                {
                    "id": question.id,
                    "question_key": question.question_key,
                    "label": question.label,
                    "question_text": question.question_text,
                    "question_type": question.question_type,
                }
                for question in session.exec(
                    select(ExamQuestion)
                    .where(
                        ExamQuestion.exam_id == run.exam_id,
                        ExamQuestion.status == ExamQuestionStatus.CONFIRMED,
                    )
                    .order_by(ExamQuestion.question_key)
                ).all()
            ]
            questions.sort(key=lambda question: _natural_key(question["question_key"]))
            if not questions:
                raise RuntimeError("请先确认至少一道题目")
            declared_allocations: dict[str, dict] = {}
            for question in questions:
                leading_score = _leading_question_score(question["question_text"])
                if leading_score is not None:
                    score, evidence = leading_score
                    declared_allocations[question["question_key"]] = {
                        "max_score": score,
                        "evidence_text": evidence,
                        "grading_rule_text": evidence,
                        "source": "question_text_prefix",
                    }
                for key, score in _declared_question_scores(
                    question["question_text"]
                ).items():
                    declared_allocations[key] = {
                        "max_score": score,
                        "evidence_text": question["question_text"],
                        "grading_rule_text": question["question_text"],
                        "source": "question_text",
                    }
            question_by_id = {question["id"]: question for question in questions}
            question_ids = list(question_by_id)
            if question_ids:
                page_headers: dict[
                    tuple[uuid.UUID, int], tuple[StoredFile, float, str]
                ] = {}
                region_rows = session.exec(
                    select(ExamQuestionRegion, ExamRegion, ExamDocument, StoredFile)
                    .join(
                        ExamRegion,
                        ExamQuestionRegion.exam_region_id == ExamRegion.id,
                    )
                    .join(
                        ExamDocument,
                        ExamRegion.exam_document_id == ExamDocument.id,
                    )
                    .join(StoredFile, ExamDocument.stored_file_id == StoredFile.id)
                    .where(ExamQuestionRegion.question_id.in_(question_ids))
                    .order_by(ExamQuestionRegion.sequence)
                ).all()
                for link, region, _document, stored_file in region_rows:
                    question = question_by_id.get(link.question_id)
                    if not question:
                        continue
                    question.setdefault("image_bytes", []).append(
                        crop_region_png(stored_file=stored_file, region=region)
                    )
                    page_key = (stored_file.id, region.page_number)
                    current = page_headers.get(page_key)
                    if current is None or region.y < current[1]:
                        page_headers[page_key] = (
                            stored_file,
                            region.y,
                            question["question_key"],
                        )
                for (_stored_file_id, page_number), (
                    stored_file,
                    first_y,
                    first_question_key,
                ) in page_headers.items():
                    try:
                        page_allocations = _page_header_score_hints(
                            stored_file=stored_file,
                            page_number=page_number,
                            first_y=first_y,
                            first_question_key=first_question_key,
                            provider=str(defaults["recognition_provider"]),
                            model=str(defaults["recognition_model"]),
                            fallback_models=vision_fallback_models,
                            billing_context=ModelCallContext(
                                org_id=exam.org_id,
                                exam_id=run.exam_id,
                                reservation_id=reservation_id,
                                workflow_purpose="score_structure_recognition",
                                resource_id=f"{run.id}:{stored_file.id}:{page_number}",
                                billing_key=(
                                    f"{exam.org_id}:score_structure:{run.id}:"
                                    f"{stored_file.id}:{page_number}:pipeline-v2"
                                ),
                            ),
                        )
                    except Exception:
                        page_allocations = {}
                    for key, allocation in page_allocations.items():
                        declared_allocations.setdefault(key, allocation)
            section_rules = _propagate_section_score_rules(
                questions, declared_allocations
            )
            exam_score_rules_text = _exam_score_rules_summary(section_rules)
            for question in questions:
                question["exam_score_rules_text"] = exam_score_rules_text
                allocation = declared_allocations.get(question["question_key"])
                if allocation is not None:
                    question["declared_max_score"] = allocation["max_score"]
                    question["score_evidence_text"] = allocation["evidence_text"]
                    question["declared_grading_rule"] = allocation["grading_rule_text"]
                    question["score_evidence_source"] = str(
                        allocation.get("source") or ""
                    )
            failures = 0
            model_elapsed_ms = 0
            used_models: set[str] = set()
            used_providers: set[str] = set()
            usage_totals: dict[str, int] = {}
            if run.source_type == AnswerPreparationSource.MODEL:
                solved_items: list[tuple[dict, dict, AnswerPreparationItem]] = []
                with ThreadPoolExecutor(
                    max_workers=min(settings.VISION_MAX_CONCURRENCY, len(questions))
                ) as pool:
                    futures = {
                        pool.submit(
                            _solve_question,
                            question,
                            run.provider,
                            run.model,
                            reasoning_fallback_models,
                            ModelCallContext(
                                org_id=exam.org_id,
                                exam_id=run.exam_id,
                                reservation_id=reservation_id,
                                workflow_purpose="answer_preparation",
                                resource_id=str(question["id"]),
                                billing_key=(
                                    f"{exam.org_id}:answer_preparation:"
                                    f"{question['id']}:pipeline-v2"
                                ),
                            ),
                        ): question
                        for question in questions
                    }
                    for future in as_completed(futures):
                        question = futures[future]
                        try:
                            result = future.result()
                            model_elapsed_ms += result["elapsed_ms"]
                            used_providers.add(result["used_provider"])
                            used_models.add(result["used_model"])
                            for key, value in (result.get("usage") or {}).items():
                                if isinstance(value, int | float):
                                    usage_totals[key] = usage_totals.get(key, 0) + int(
                                        value
                                    )
                            item = AnswerPreparationItem(
                                run_id=run.id,
                                question_id=result["question_id"],
                                source_item_key=str(result["question_id"]),
                                source_question_key=result["question_key"],
                                **_answer_item_fields(result),
                            )
                            solved_items.append((question, result, item))
                        except Exception as exc:
                            failures += 1
                            declared_score = question.get("declared_max_score")
                            score_evidence = str(
                                question.get("score_evidence_text") or ""
                            ).strip()
                            item = AnswerPreparationItem(
                                run_id=run.id,
                                question_id=question["id"],
                                source_item_key=str(question["id"]),
                                source_question_key=question["question_key"],
                                max_score=(
                                    _score_decimal(declared_score)
                                    if declared_score is not None
                                    else Decimal("1.00")
                                ),
                                match_reason=(
                                    f"答案生成失败；已保留卷面赋分证据：{score_evidence}"
                                    if score_evidence
                                    else "答案生成失败；题面未提取到明确赋分证据"
                                )[:2000],
                                raw_result={
                                    "scoreEvidenceText": score_evidence,
                                    "declaredGradingRule": str(
                                        question.get("declared_grading_rule") or ""
                                    ),
                                    "scoreRequiresReview": declared_score is None,
                                },
                                status=AnswerPreparationItemStatus.FAILED,
                                error_message=str(exc)[:2000],
                            )
                        session.add(item)
                # Second round: harvest section score rules the solver quoted
                # from its own crop, then re-solve only the items that fell
                # back to a fabricated score for lack of printed evidence.
                harvested_rules = _harvest_section_rules_from_results(
                    [result for _question, result, _item in solved_items]
                )
                if harvested_rules:
                    missing_keys = {
                        str(question["question_key"])
                        for question in questions
                        if str(question["question_key"]) not in declared_allocations
                    }
                    combined_rules = section_rules + harvested_rules
                    _propagate_section_score_rules(
                        questions, declared_allocations, rules=combined_rules
                    )
                    resolved = []
                    for question, result, item in solved_items:
                        key = str(question["question_key"])
                        if key not in missing_keys or result["score_evidence_text"]:
                            continue
                        allocation = declared_allocations.get(key)
                        if (
                            not allocation
                            or allocation.get("source") != "batch_harvest"
                        ):
                            continue
                        # Re-solve only items still on a fallback score:
                        # flagged for review, low confidence, or a fabricated
                        # max_score that disagrees with the harvested evidence.
                        if not (
                            result["score_requires_review"]
                            or result["confidence"] <= Decimal("0.5")
                            or result["max_score"] != allocation["max_score"]
                        ):
                            continue
                        resolved.append((question, item))
                    if resolved:
                        shared_summary = _exam_score_rules_summary(combined_rules)
                        for question, _item in resolved:
                            allocation = declared_allocations[
                                str(question["question_key"])
                            ]
                            question["declared_max_score"] = allocation["max_score"]
                            question["score_evidence_text"] = allocation[
                                "evidence_text"
                            ]
                            question["declared_grading_rule"] = allocation[
                                "grading_rule_text"
                            ]
                            question["score_evidence_source"] = "batch_harvest"
                            question["score_evidence_anchor"] = str(
                                allocation.get("anchor_question_key") or ""
                            )
                            question["exam_score_rules_text"] = shared_summary
                        with ThreadPoolExecutor(
                            max_workers=min(
                                settings.VISION_MAX_CONCURRENCY, len(resolved)
                            )
                        ) as pool:
                            retry_futures = {
                                pool.submit(
                                    _solve_question,
                                    question,
                                    run.provider,
                                    run.model,
                                    reasoning_fallback_models,
                                    ModelCallContext(
                                        org_id=exam.org_id,
                                        exam_id=run.exam_id,
                                        reservation_id=reservation_id,
                                        workflow_purpose="answer_preparation",
                                        resource_id=str(question["id"]),
                                        billing_key=(
                                            f"{exam.org_id}:answer_preparation:"
                                            f"{question['id']}:pipeline-v2"
                                        ),
                                    ),
                                ): item
                                for question, item in resolved
                            }
                            for future in as_completed(retry_futures):
                                item = retry_futures[future]
                                try:
                                    result = future.result()
                                except Exception:
                                    # Keep the round-1 fallback item on failure.
                                    continue
                                model_elapsed_ms += result["elapsed_ms"]
                                used_providers.add(result["used_provider"])
                                used_models.add(result["used_model"])
                                for key, value in (result.get("usage") or {}).items():
                                    if isinstance(value, int | float):
                                        usage_totals[key] = usage_totals.get(
                                            key, 0
                                        ) + int(value)
                                for field, value in _answer_item_fields(result).items():
                                    setattr(item, field, value)
                                session.add(item)
            else:
                requested_ids = [uuid.UUID(item) for item in run.document_ids]
                rows = session.exec(
                    select(ExamDocument, StoredFile)
                    .join(StoredFile, ExamDocument.stored_file_id == StoredFile.id)
                    .where(
                        ExamDocument.exam_id == run.exam_id,
                        col(ExamDocument.id).in_(requested_ids),
                    )
                ).all()
                by_id = {
                    document.id: (document, stored_file)
                    for document, stored_file in rows
                }
                documents = [by_id[item] for item in requested_ids if item in by_id]
                if len(documents) != len(requested_ids):
                    raise RuntimeError("部分答案文件不存在或不属于当前考试")
                if not documents:
                    raise RuntimeError("答案文档模式至少需要一个答案文件")
                parsed, used_model, model_elapsed_ms, usage = _parse_answer_documents(
                    questions=questions,
                    documents=documents,
                    provider=run.provider,
                    model=run.model,
                    fallback_models=vision_fallback_models,
                    billing_context=ModelCallContext(
                        org_id=exam.org_id,
                        exam_id=run.exam_id,
                        reservation_id=reservation_id,
                        workflow_purpose="answer_document_parsing",
                        resource_id=str(run.id),
                        billing_key=(
                            f"{exam.org_id}:answer_document_parsing:{run.id}:pipeline-v2"
                        ),
                    ),
                )
                used_models.add(used_model)
                used_providers.add(str(usage.get("_used_provider", run.provider)))
                for key, value in usage.items():
                    if isinstance(value, int | float):
                        usage_totals[key] = usage_totals.get(key, 0) + int(value)
                raw_answers = parsed.get("answers")
                answer_rows = raw_answers if isinstance(raw_answers, list) else []
                by_key: dict[str, list[dict]] = {}
                for answer in answer_rows:
                    if not isinstance(answer, dict):
                        continue
                    key = str(answer.get("question_key") or "").strip()
                    if key:
                        by_key.setdefault(key, []).append(answer)
                matched_indexes: set[int] = set()
                for question in questions:
                    candidates = by_key.get(question["question_key"], [])
                    candidate = candidates[0] if candidates else {}
                    if len(candidates) > 1:
                        status = AnswerPreparationItemStatus.CONFLICT
                        reason = "答案文档中有多个条目匹配同一题目"
                    elif not candidates:
                        status = AnswerPreparationItemStatus.UNMATCHED
                        reason = "答案文档未返回该题目的精确匹配"
                    else:
                        status = AnswerPreparationItemStatus.MATCHED
                        reason = str(candidate.get("match_reason") or "题号精确匹配")
                        for index, row in enumerate(answer_rows):
                            if row is candidate:
                                matched_indexes.add(index)
                    max_score = _score_decimal(candidate.get("max_score"), default="1")
                    session.add(
                        AnswerPreparationItem(
                            run_id=run.id,
                            question_id=question["id"],
                            source_item_key=str(question["id"]),
                            source_question_key=str(
                                candidate.get("source_question_key")
                                or question["question_key"]
                            )[:100],
                            answer_text=str(candidate.get("answer_text") or "")[:20000],
                            max_score=max_score,
                            rubric_text=(
                                str(candidate.get("rubric_text") or "")[:12000] or None
                            ),
                            scoring_points=_normalize_scoring_points(
                                candidate.get("scoring_points"), max_score
                            ),
                            confidence=(
                                _bounded_decimal(candidate.get("confidence"))
                                if candidate
                                else None
                            ),
                            match_reason=reason[:2000],
                            raw_result=_strip_binary(candidate),
                            status=status,
                        )
                    )
                for index, answer in enumerate(answer_rows):
                    if index in matched_indexes or not isinstance(answer, dict):
                        continue
                    max_score = _score_decimal(answer.get("max_score"), default="1")
                    session.add(
                        AnswerPreparationItem(
                            run_id=run.id,
                            source_item_key=f"unmatched-{index + 1}",
                            source_question_key=(
                                str(answer.get("source_question_key") or "")[:100]
                                or None
                            ),
                            answer_text=str(answer.get("answer_text") or "")[:20000],
                            max_score=max_score,
                            rubric_text=(
                                str(answer.get("rubric_text") or "")[:12000] or None
                            ),
                            scoring_points=_normalize_scoring_points(
                                answer.get("scoring_points"), max_score
                            ),
                            confidence=_bounded_decimal(answer.get("confidence")),
                            match_reason="文档条目未能匹配已确认题目",
                            raw_result=_strip_binary(answer),
                            status=AnswerPreparationItemStatus.UNMATCHED,
                        )
                    )
                run.raw_output = _strip_binary(parsed)
            run.timing = {
                "modelMs": model_elapsed_ms,
                "totalElapsedMs": round((time.perf_counter() - started) * 1000),
                "requestedProvider": run.provider,
                "requestedModel": run.model,
                "usedProviders": sorted(used_providers),
                "usedModels": sorted(used_models),
                "fallbackUsed": bool(
                    used_providers - {run.provider} or used_models - {run.model}
                ),
                "tokenUsage": usage_totals,
            }
            run.status = (
                WorkflowRunStatus.COMPLETED_WITH_ERRORS
                if failures
                else WorkflowRunStatus.COMPLETED
            )
            run.error_message = (
                f"{failures} 道题未能生成答案，请重试失败项或人工补充"
                if failures
                else None
            )
            run.completed_at = get_datetime_utc()
            if reservation_id:
                billing_service.settle_reservation(session, reservation_id)
            session.add(run)
            session.commit()
        except Exception as exc:
            session.rollback()
            run = session.get(AnswerPreparationRun, run_uuid)
            if run:
                run.status = WorkflowRunStatus.FAILED
                run.error_message = str(exc)[:2000]
                run.completed_at = get_datetime_utc()
                run.timing = {
                    **(run.timing or {}),
                    "totalElapsedMs": round((time.perf_counter() - started) * 1000),
                }
                session.add(run)
                session.commit()
