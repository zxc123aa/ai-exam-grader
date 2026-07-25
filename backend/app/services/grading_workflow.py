from __future__ import annotations

import random
import time
import uuid
from collections.abc import Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, select

from app.core.db import engine
from app.models import (
    AnnotationGradingStatus,
    ExamQuestion,
    ExamQuestionRegion,
    ExamQuestionStatus,
    ExamRegion,
    GradingAuditEvent,
    GradingItem,
    GradingItemStatus,
    GradingRun,
    GradingRunStatus,
    StandardAnswer,
    StandardAnswerRevision,
    StandardAnswerRevisionStatus,
    StandardAnswerStatus,
    StoredFile,
    StudentSubmission,
    SubmissionAnnotation,
    SubmissionAnnotationStatus,
    SubmissionRegistrationStatus,
    get_datetime_utc,
)
from app.services.grading_rules import (
    enforce_scoring_points,
    grade_objective,
    is_objective,
    validate_rubric,
)
from app.services.submission_crops import (
    crop_region_png,
    resolve_exam_region_paper_page,
)
from app.services.vision_grading import extract_answer_images, grade_answer_text

MAX_TOTAL_CONCURRENCY = 32


def publish_standard_answers(session: Session, run: GradingRun) -> list[StandardAnswer]:
    """Compatibility read: grading may only use explicitly published revisions."""
    return list(
        session.exec(
            select(StandardAnswer).where(
                StandardAnswer.exam_id == run.exam_id,
                StandardAnswer.status == StandardAnswerStatus.READY,
                StandardAnswer.current_revision_id.is_not(None),
            )
        ).all()
    )


def _answer_snapshot(
    answer: StandardAnswer, revision: StandardAnswerRevision
) -> StandardAnswer:
    return StandardAnswer(
        id=answer.id,
        exam_id=answer.exam_id,
        exam_region_id=answer.exam_region_id,
        question_id=revision.question_id,
        current_revision_id=revision.id,
        answer_text=revision.answer_text,
        max_score=float(revision.max_score),
        rubric_text=revision.rubric_text,
        scoring_points=revision.scoring_points,
        status=StandardAnswerStatus.READY,
        version=revision.revision_number,
        source_provider=revision.source_provider,
        source_model=revision.source_model,
        generation_confidence=(
            float(revision.generation_confidence)
            if revision.generation_confidence is not None
            else None
        ),
        answer_hash=revision.content_hash,
        question_text=revision.question_text,
        question_type=revision.question_type,
        rubric_config={"schema_version": "confirmed-answer-revision-v1"},
        validation_report={
            "valid": True,
            "human_confirmed": True,
            "published": True,
        },
    )


def _annotation(
    session: Session, submission: StudentSubmission, region: ExamRegion
) -> SubmissionAnnotation:
    item = session.exec(
        select(SubmissionAnnotation).where(
            SubmissionAnnotation.submission_id == submission.id,
            SubmissionAnnotation.exam_region_id == region.id,
        )
    ).first()
    if item:
        return item
    item = SubmissionAnnotation(
        submission_id=submission.id,
        exam_region_id=region.id,
        label=region.label,
        page_number=region.page_number,
        x=region.x,
        y=region.y,
        width=region.width,
        height=region.height,
    )
    session.add(item)
    session.flush()
    return item


@dataclass(frozen=True)
class WorkPayload:
    item_id: uuid.UUID
    submission: StudentSubmission
    stored_file: StoredFile
    region: ExamRegion
    regions: tuple[ExamRegion, ...]
    answer: StandardAnswer
    vision_provider: str
    vision_model: str
    grading_provider: str
    grading_model: str
    fallback_models: list[str]
    attempt: int
    extraction_override: dict | None = None
    # Global paper page per region id; regions store document-local pages while
    # the submission is a single multi-page file.
    page_numbers: dict[uuid.UUID, int] | None = None


@dataclass(frozen=True)
class WorkResult:
    payload: WorkPayload
    extraction: dict | None = None
    grading: dict | None = None
    objective: bool = False
    error: str | None = None
    transient: bool = False


@dataclass
class AdaptiveConcurrency:
    maximum: int
    current: int = 0
    success_streak: int = 0
    throttle_count: int = 0

    def __post_init__(self) -> None:
        self.maximum = min(MAX_TOTAL_CONCURRENCY, max(1, self.maximum))
        self.current = self.maximum

    def record(self, *, transient: bool, failed: bool) -> None:
        if transient:
            self.current = max(1, self.current // 2)
            self.throttle_count += 1
            self.success_streak = 0
        elif not failed:
            self.success_streak += 1
            if self.success_streak >= 20 and self.current < self.maximum:
                self.current += 1
                self.success_streak = 0


def next_schedulable_payload_index(
    pending: list[WorkPayload],
    active: Iterable[WorkPayload],
    *,
    max_parallel_submissions: int,
    max_concurrency_per_submission: int,
) -> int | None:
    """Pick the next item without exceeding answer-level or per-answer limits."""
    active_counts: dict[uuid.UUID, int] = {}
    for payload in active:
        submission_id = payload.submission.id
        active_counts[submission_id] = active_counts.get(submission_id, 0) + 1
    active_submissions = set(active_counts)
    for index, payload in enumerate(pending):
        submission_id = payload.submission.id
        if active_counts.get(submission_id, 0) >= max_concurrency_per_submission:
            continue
        if (
            submission_id not in active_submissions
            and len(active_submissions) >= max_parallel_submissions
        ):
            continue
        return index
    return None


def answer_text_for_grading(extraction_data: dict[str, Any]) -> str:
    if "grading_answer" in extraction_data:
        return str(extraction_data.get("grading_answer") or "")
    return str(
        extraction_data.get("final_answer")
        or extraction_data.get("student_answer")
        or ""
    )


def extraction_requires_manual_confirmation(
    extraction_data: dict[str, Any],
) -> bool:
    return extraction_data.get("grading_eligible") is False


def _process_item(payload: WorkPayload) -> WorkResult:
    if payload.attempt > 1:
        time.sleep(min(4, 0.5 * (2 ** (payload.attempt - 2))) + random.random() * 0.25)
    try:
        if payload.extraction_override:
            extraction_data = dict(payload.extraction_override)
        else:
            extraction = extract_answer_images(
                image_bytes_list=[
                    crop_region_png(
                        stored_file=payload.stored_file,
                        region=region,
                        page_number=(payload.page_numbers or {}).get(region.id),
                    )
                    for region in payload.regions
                ],
                provider=payload.vision_provider,
                model=payload.vision_model,
                question_label=payload.region.label,
                fallback_models=payload.fallback_models,
            )
            extraction_data = {
                "question_text": extraction.question_text,
                "student_answer": extraction.student_answer,
                "final_answer": extraction.final_answer,
                "answer_type": extraction.answer_type,
                "confidence": extraction.confidence,
                "notes": extraction.notes,
                "provider": extraction.provider,
                "model": extraction.model,
                "elapsed_ms": extraction.elapsed_ms,
            }
        if extraction_requires_manual_confirmation(extraction_data):
            return WorkResult(
                payload=payload,
                extraction=extraction_data,
                grading={
                    "blocked": True,
                    "score": None,
                    "confidence": 0.0,
                    "comment": "识别证据尚未确认，已阻止自动判分",
                    "evidence": [],
                    "provider": "safety-gate",
                    "model": "answer-evidence-gate-v1",
                    "elapsed_ms": 0,
                },
            )
        grading_answer = answer_text_for_grading(extraction_data)
        if is_objective(payload.answer):
            grade = grade_objective(
                student_answer=str(grading_answer),
                answer=payload.answer,
                extraction_confidence=float(extraction_data.get("confidence") or 0),
            )
            grading_data = {
                "score": grade.score,
                "confidence": grade.confidence,
                "comment": grade.comment,
                "evidence": grade.evidence,
                "provider": "rules",
                "model": "objective-rules-v1",
                "elapsed_ms": 0,
            }
            return WorkResult(
                payload=payload,
                extraction=extraction_data,
                grading=grading_data,
                objective=True,
            )
        grade = grade_answer_text(
            student_answer=str(grading_answer),
            standard_answer=payload.answer,
            provider=payload.grading_provider,
            model=payload.grading_model,
            fallback_models=payload.fallback_models,
        )
        score = enforce_scoring_points(
            grade.score, grade.evidence, payload.answer.max_score
        )
        grading_data = {
            "score": score,
            "confidence": grade.confidence,
            "comment": grade.comment,
            "evidence": grade.evidence,
            "provider": grade.provider,
            "model": grade.model,
            "elapsed_ms": grade.elapsed_ms,
        }
        return WorkResult(
            payload=payload, extraction=extraction_data, grading=grading_data
        )
    except Exception as exc:
        message = str(exc)[:1000]
        transient = any(
            token in message.lower()
            for token in (
                "429",
                "timeout",
                "timed out",
                "500",
                "502",
                "503",
                "504",
                "暂不可用",
                "额度已用完",
                "请求较多",
                "ssl",
                "connection",
                "disconnected",
                "eof",
            )
        )
        return WorkResult(payload=payload, error=message, transient=transient)


def _save_result(
    session: Session, run: GradingRun, result: WorkResult, threshold: float
) -> None:
    item = session.get(GradingItem, result.payload.item_id)
    if not item:
        return
    submission, region, answer = (
        result.payload.submission,
        result.payload.region,
        result.payload.answer,
    )
    annotation = _annotation(session, submission, region)
    old_score, old_comment = annotation.score, annotation.comment
    item.attempts = result.payload.attempt
    if result.error:
        item.error_message = result.error
        if item.attempts >= 3:
            item.status = GradingItemStatus.FAILED
            item.completed_at = get_datetime_utc()
            annotation.status = SubmissionAnnotationStatus.NEEDS_REVIEW
            annotation.grading_status = AnnotationGradingStatus.NEEDS_REVIEW
            annotation.grading_reasons = [
                {"type": "model_failure", "message": result.error}
            ]
            session.add(annotation)
            session.flush()
            item.annotation_id = annotation.id
            session.add(
                GradingAuditEvent(
                    grading_run_id=run.id,
                    submission_id=submission.id,
                    annotation_id=annotation.id,
                    source="auto_error",
                    old_score=old_score,
                    new_score=annotation.score,
                    old_comment=old_comment,
                    new_comment=annotation.comment,
                    reason="题块处理失败，转人工复核",
                    metadata_json={"error": result.error, "attempts": item.attempts},
                )
            )
        else:
            item.status = GradingItemStatus.QUEUED
        session.add(item)
        return
    extraction, grading = result.extraction or {}, result.grading or {}
    if grading.get("blocked"):
        item.status = GradingItemStatus.NEEDS_REVIEW
        item.extraction_result = extraction
        item.grading_result = grading
        item.error_message = None
        item.annotation_id = annotation.id
        item.completed_at = get_datetime_utc()
        annotation.ocr_text = str(extraction.get("student_answer", ""))
        annotation.ocr_confidence = float(extraction.get("confidence") or 0)
        annotation.ocr_status = "needs_review"
        annotation.ocr_engine = (
            f"{extraction.get('provider', 'unknown')}:"
            f"{extraction.get('model', 'unknown')}"
        )
        annotation.suggested_score = None
        annotation.suggested_comment = str(grading["comment"])
        annotation.grading_confidence = 0
        annotation.model_score = None
        annotation.model_confidence = 0
        annotation.max_score = answer.max_score
        annotation.status = SubmissionAnnotationStatus.NEEDS_REVIEW
        annotation.grading_status = AnnotationGradingStatus.NEEDS_REVIEW
        annotation.grading_reasons = [
            {
                "type": "unconfirmed_answer_evidence",
                "message": "识别证据存在分歧、缺失或低置信度，未调用自动判分模型",
            }
        ]
        annotation.grading_evidence = [
            {"stage": "vision_extraction", **extraction},
            {
                "stage": "grading_gate",
                "provider": grading["provider"],
                "model": grading["model"],
                "blocked": True,
            },
        ]
        session.add_all([item, annotation])
        session.flush()
        session.add(
            GradingAuditEvent(
                grading_run_id=run.id,
                submission_id=submission.id,
                annotation_id=annotation.id,
                source="auto_blocked",
                old_score=old_score,
                new_score=annotation.score,
                old_comment=old_comment,
                new_comment=annotation.comment,
                reason="识别证据未确认，安全门阻止自动判分",
                metadata_json={
                    "extraction": extraction,
                    "grading_gate": grading,
                },
            )
        )
        return
    combined = min(float(extraction["confidence"]), float(grading["confidence"]))
    extracted_text = str(extraction.get("student_answer", ""))
    answer_count_mismatch = (
        answer.question_type == "fill_blank"
        and len(answer.scoring_points) > 1
        and len([line for line in extracted_text.splitlines() if line.strip()])
        < len(answer.scoring_points)
    )
    needs_review = (
        combined < threshold
        or "[看不清]" in extracted_text
        or "[无法辨认]" in extracted_text
        or answer_count_mismatch
    )
    item.status = (
        GradingItemStatus.NEEDS_REVIEW if needs_review else GradingItemStatus.COMPLETED
    )
    item.extraction_result = extraction
    item.grading_result = grading
    item.error_message = None
    item.annotation_id = annotation.id
    item.completed_at = get_datetime_utc()
    annotation.ocr_text = str(extraction.get("student_answer", ""))
    annotation.ocr_confidence = float(extraction["confidence"])
    annotation.ocr_status = "succeeded"
    annotation.ocr_engine = f"{extraction['provider']}:{extraction['model']}"
    annotation.suggested_score = float(grading["score"])
    annotation.suggested_comment = str(grading["comment"])
    annotation.grading_confidence = combined
    annotation.model_score = float(grading["score"])
    annotation.model_confidence = combined
    annotation.score = float(grading["score"])
    annotation.max_score = answer.max_score
    annotation.comment = str(grading["comment"])
    annotation.score_source = "auto"
    annotation.status = SubmissionAnnotationStatus.ACCEPTED
    annotation.grading_status = (
        AnnotationGradingStatus.NEEDS_REVIEW
        if needs_review
        else AnnotationGradingStatus.SUCCEEDED
    )
    annotation.grading_version = (
        f"answer-revision:{item.answer_revision_id}"
        if item.answer_revision_id
        else f"answer-v{answer.version}"
    )
    annotation.answer_key_updated_at = answer.updated_at
    annotation.auto_published_at = get_datetime_utc()
    annotation.grading_evidence = [
        {"stage": "vision_extraction", **extraction},
        *grading.get("evidence", []),
        {
            "stage": "grading",
            "provider": grading["provider"],
            "model": grading["model"],
            "elapsed_ms": grading["elapsed_ms"],
        },
        {
            "stage": "answer_revision",
            "question_id": str(item.question_id) if item.question_id else None,
            "answer_revision_id": (
                str(item.answer_revision_id) if item.answer_revision_id else None
            ),
        },
    ]
    annotation.grading_reasons = []
    if combined < threshold:
        annotation.grading_reasons.append(
            {"type": "low_confidence", "message": "提取或判题置信度低于阈值"}
        )
    if "[看不清]" in extracted_text or "[无法辨认]" in extracted_text:
        annotation.grading_reasons.append(
            {"type": "unreadable", "message": "识别结果包含看不清内容"}
        )
    if answer_count_mismatch:
        annotation.grading_reasons.append(
            {
                "type": "answer_count_mismatch",
                "message": "多空题识别答案项数少于评分点数",
            }
        )
    session.add_all([item, annotation])
    session.flush()
    session.add(
        GradingAuditEvent(
            grading_run_id=run.id,
            submission_id=submission.id,
            annotation_id=annotation.id,
            source="auto",
            old_score=old_score,
            new_score=annotation.score,
            old_comment=old_comment,
            new_comment=annotation.comment,
            reason="题块高并发流水线自动评分并发布",
            metadata_json={
                "extraction": extraction,
                "grading": grading,
                "combined_confidence": combined,
                "question_id": str(item.question_id) if item.question_id else None,
                "answer_revision_id": (
                    str(item.answer_revision_id) if item.answer_revision_id else None
                ),
            },
        )
    )


def execute_grading_run(run_id: str) -> None:
    started_perf = time.perf_counter()
    recognition_timing: dict = {}
    with Session(engine, expire_on_commit=False) as session:
        run = session.get(GradingRun, uuid.UUID(run_id))
        if not run:
            return
        run.status, run.started_at, run.error_message = (
            GradingRunStatus.RUNNING,
            get_datetime_utc(),
            None,
        )
        session.add(run)
        session.commit()
        try:
            questions = list(
                session.exec(
                    select(ExamQuestion).where(
                        ExamQuestion.exam_id == run.exam_id,
                        ExamQuestion.status == ExamQuestionStatus.CONFIRMED,
                    )
                ).all()
            )
            question_ids = [question.id for question in questions]
            region_rows = list(
                session.exec(
                    select(ExamQuestionRegion, ExamRegion)
                    .join(
                        ExamRegion,
                        ExamQuestionRegion.exam_region_id == ExamRegion.id,
                    )
                    .where(ExamQuestionRegion.question_id.in_(question_ids))
                    .order_by(
                        ExamQuestionRegion.question_id,
                        ExamQuestionRegion.sequence,
                    )
                ).all()
            )
            regions_by_question: dict[uuid.UUID, list[ExamRegion]] = {
                question_id: [] for question_id in question_ids
            }
            for link, region in region_rows:
                regions_by_question.setdefault(link.question_id, []).append(region)

            locked_revision_ids = {
                uuid.UUID(str(question_id)): uuid.UUID(str(revision_id))
                for question_id, revision_id in (
                    run.config_snapshot.get("answer_revision_ids") or {}
                ).items()
            }
            targets: dict[
                uuid.UUID,
                tuple[
                    ExamQuestion,
                    tuple[ExamRegion, ...],
                    StandardAnswer,
                    StandardAnswerRevision,
                ],
            ] = {}
            invalid: dict[str, list[str]] = {}
            for question in questions:
                answer = session.exec(
                    select(StandardAnswer).where(
                        StandardAnswer.exam_id == run.exam_id,
                        StandardAnswer.question_id == question.id,
                    )
                ).first()
                revision_id = locked_revision_ids.get(question.id)
                if not revision_id and answer and answer.current_revision_id:
                    # Compatibility for runs created before revision locking was introduced.
                    revision_id = answer.current_revision_id
                revision = (
                    session.get(StandardAnswerRevision, revision_id)
                    if revision_id
                    else None
                )
                question_regions = tuple(regions_by_question.get(question.id, []))
                if (
                    not answer
                    or not revision
                    or revision.question_id != question.id
                    or revision.status != StandardAnswerRevisionStatus.PUBLISHED
                    or not question_regions
                ):
                    invalid[question.question_key] = ["缺少已发布答案版本或题目区域"]
                    continue
                snapshot = _answer_snapshot(answer, revision)
                rubric_errors = validate_rubric(snapshot)
                if rubric_errors:
                    invalid[question.question_key] = rubric_errors
                    continue
                targets[question_regions[0].id] = (
                    question,
                    question_regions,
                    snapshot,
                    revision,
                )
            if invalid or len(targets) != len(questions):
                summary = "；".join(
                    f"{key}: {', '.join(errors)}"
                    for key, errors in list(invalid.items())[:10]
                )
                raise RuntimeError(
                    f"{len(invalid)} 道题缺少可用的已发布评分版本：{summary}"
                )
            regions = [target[1][0] for target in targets.values()]
            region_page_numbers = {
                region.id: resolve_exam_region_paper_page(session, region)
                for target in targets.values()
                for region in target[1]
            }
            ids = [
                uuid.UUID(value)
                for value in run.config_snapshot.get("submission_ids", [])
            ]
            query = select(StudentSubmission).where(
                StudentSubmission.exam_id == run.exam_id
            )
            if ids:
                query = query.where(StudentSubmission.id.in_(ids))
            submissions = list(session.exec(query).all())
            stored_files = {
                submission.id: session.get(StoredFile, submission.stored_file_id)
                for submission in submissions
            }
            recognition_items: dict[tuple[uuid.UUID, uuid.UUID], dict] = {}
            recognition_run_id = run.config_snapshot.get("recognition_run_id")
            if recognition_run_id:
                recognition_run = session.get(
                    GradingRun, uuid.UUID(str(recognition_run_id))
                )
                recognition_timing = (
                    dict((recognition_run.config_snapshot or {}).get("timing", {}))
                    if recognition_run
                    else {}
                )
                for recognition_item in session.exec(
                    select(GradingItem).where(
                        GradingItem.grading_run_id
                        == uuid.UUID(str(recognition_run_id)),
                        GradingItem.status == GradingItemStatus.COMPLETED,
                    )
                ).all():
                    recognition_items[
                        (
                            recognition_item.submission_id,
                            recognition_item.exam_region_id,
                        )
                    ] = dict(recognition_item.extraction_result or {})
            existing = {
                (item.submission_id, item.exam_region_id): item
                for item in session.exec(
                    select(GradingItem).where(GradingItem.grading_run_id == run.id)
                ).all()
            }
            for submission in submissions:
                for region in regions:
                    if (submission.id, region.id) not in existing:
                        question, _question_regions, _answer, revision = targets[
                            region.id
                        ]
                        item = GradingItem(
                            grading_run_id=run.id,
                            submission_id=submission.id,
                            exam_region_id=region.id,
                            question_id=question.id,
                            answer_revision_id=revision.id,
                        )
                        session.add(item)
                        session.flush()
                        existing[(submission.id, region.id)] = item
            run.total_submissions = len(submissions)
            run.total_items = len(existing)
            session.add(run)
            session.commit()
            pending: list[WorkPayload] = []
            for (submission_id, region_id), item in existing.items():
                if item.status in {
                    GradingItemStatus.COMPLETED,
                    GradingItemStatus.NEEDS_REVIEW,
                }:
                    continue
                submission = next(
                    value for value in submissions if value.id == submission_id
                )
                region = next(value for value in regions if value.id == region_id)
                stored = stored_files.get(submission_id)
                target = targets.get(region_id)
                if not stored or not target or item.attempts >= 3:
                    continue
                question, question_regions, answer, revision = target
                if item.question_id is None:
                    item.question_id = question.id
                if item.answer_revision_id is None:
                    item.answer_revision_id = revision.id
                if item.answer_revision_id != revision.id:
                    locked_revision = session.get(
                        StandardAnswerRevision, item.answer_revision_id
                    )
                    standard_answer = session.exec(
                        select(StandardAnswer).where(
                            StandardAnswer.question_id == item.question_id
                        )
                    ).first()
                    if not locked_revision or not standard_answer:
                        continue
                    answer = _answer_snapshot(standard_answer, locked_revision)
                session.add(item)
                pending.append(
                    WorkPayload(
                        item_id=item.id,
                        submission=submission,
                        stored_file=stored,
                        region=region,
                        regions=question_regions,
                        answer=answer,
                        vision_provider=str(run.config_snapshot["vision_provider"]),
                        vision_model=str(run.config_snapshot["vision_model"]),
                        grading_provider=run.provider,
                        grading_model=run.model,
                        fallback_models=run.fallback_models,
                        attempt=item.attempts + 1,
                        extraction_override=recognition_items.get(
                            (submission_id, region_id)
                        ),
                        page_numbers=region_page_numbers,
                    )
                )
            max_concurrency = min(
                MAX_TOTAL_CONCURRENCY,
                max(1, int(run.config_snapshot.get("max_concurrency", 8))),
            )
            max_parallel_submissions = min(
                8,
                max(
                    1,
                    int(run.config_snapshot.get("max_parallel_submissions", 8)),
                ),
            )
            max_concurrency_per_submission = min(
                8,
                max(
                    1,
                    int(run.config_snapshot.get("max_concurrency_per_submission", 4)),
                ),
            )
            adaptive = AdaptiveConcurrency(max_concurrency)
            futures: dict[Future[WorkResult], WorkPayload] = {}
            with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
                while pending or futures:
                    while pending and len(futures) < adaptive.current:
                        next_index = next_schedulable_payload_index(
                            pending,
                            futures.values(),
                            max_parallel_submissions=max_parallel_submissions,
                            max_concurrency_per_submission=(
                                max_concurrency_per_submission
                            ),
                        )
                        if next_index is None:
                            break
                        payload = pending.pop(next_index)
                        item = session.get(GradingItem, payload.item_id)
                        if item:
                            item.status, item.started_at = (
                                GradingItemStatus.EXTRACTING,
                                get_datetime_utc(),
                            )
                            session.add(item)
                        futures[pool.submit(_process_item, payload)] = payload
                    run.current_concurrency = len(futures)
                    session.add(run)
                    session.commit()
                    done, _ = wait(futures, return_when=FIRST_COMPLETED)
                    for future in done:
                        payload = futures.pop(future)
                        result = future.result()
                        _save_result(
                            session,
                            run,
                            result,
                            float(run.config_snapshot.get("review_threshold", 0.8)),
                        )
                        if result.error and payload.attempt < 3:
                            pending.append(
                                WorkPayload(
                                    **{
                                        **payload.__dict__,
                                        "attempt": payload.attempt + 1,
                                    }
                                )
                            )
                        adaptive.record(
                            transient=result.transient, failed=result.error is not None
                        )
                        run.throttle_count = adaptive.throttle_count
                        session.commit()
                    items = list(
                        session.exec(
                            select(GradingItem).where(
                                GradingItem.grading_run_id == run.id
                            )
                        ).all()
                    )
                    run.completed_items = sum(
                        item.status
                        in {
                            GradingItemStatus.COMPLETED,
                            GradingItemStatus.NEEDS_REVIEW,
                            GradingItemStatus.FAILED,
                        }
                        for item in items
                    )
                    run.extracted_items = sum(
                        bool(item.extraction_result) for item in items
                    )
                    run.objective_items = sum(
                        item.grading_result.get("provider") == "rules" for item in items
                    )
                    run.subjective_items = sum(
                        bool(item.grading_result)
                        and item.grading_result.get("provider") != "rules"
                        for item in items
                    )
                    run.failed_count = sum(
                        item.status == GradingItemStatus.FAILED for item in items
                    )
                    run.review_count = len(
                        {
                            item.submission_id
                            for item in items
                            if item.status
                            in {
                                GradingItemStatus.NEEDS_REVIEW,
                                GradingItemStatus.FAILED,
                            }
                        }
                    )
                    session.add(run)
                    session.commit()
            run.completed_count = len(submissions)
            # 批改成功处理的答卷视为已自动配准：配准（对齐模板区域）已在
            # 裁切/评分流程中实际生效，不再要求人工逐份确认。
            graded_submission_ids = {
                item.submission_id
                for item in items
                if item.status
                in {GradingItemStatus.COMPLETED, GradingItemStatus.NEEDS_REVIEW}
            }
            for submission in submissions:
                if (
                    submission.id in graded_submission_ids
                    and submission.registration_status
                    == SubmissionRegistrationStatus.PENDING
                ):
                    submission.registration_status = (
                        SubmissionRegistrationStatus.AUTO_CONFIRMED
                    )
                    submission.updated_at = get_datetime_utc()
                    session.add(submission)
            session.commit()
            run.current_concurrency = 0
            run.status = (
                GradingRunStatus.COMPLETED_WITH_ERRORS
                if run.failed_count
                else GradingRunStatus.COMPLETED
            )
        except Exception as exc:
            run.status, run.error_message = GradingRunStatus.FAILED, str(exc)[:2000]
        grading_wall_ms = round((time.perf_counter() - started_perf) * 1000)
        timing_items = list(
            session.exec(
                select(GradingItem).where(GradingItem.grading_run_id == run.id)
            ).all()
        )
        extraction_item_ms = sum(
            int((item.extraction_result or {}).get("elapsed_ms") or 0)
            for item in timing_items
        )
        grading_item_ms = sum(
            int((item.grading_result or {}).get("elapsed_ms") or 0)
            for item in timing_items
        )
        used_routes = sorted(
            {
                f"{result.get('provider')}:{result.get('model')}"
                for item in timing_items
                for result in (item.extraction_result or {}, item.grading_result or {})
                if result.get("provider") and result.get("model")
            }
        )
        recognition_total_ms = int(
            recognition_timing.get("total_elapsed_ms")
            or recognition_timing.get("totalElapsedMs")
            or 0
        )
        run.config_snapshot = {
            **(run.config_snapshot or {}),
            "timing": {
                "orientation_ms": int(
                    recognition_timing.get("orientation_ms")
                    or recognition_timing.get("orientationMs")
                    or 0
                ),
                "layout_ms": int(
                    recognition_timing.get("layout_ms")
                    or recognition_timing.get("layoutMs")
                    or 0
                ),
                "crop_ms": int(
                    recognition_timing.get("crop_ms")
                    or recognition_timing.get("cropMs")
                    or 0
                ),
                "ocr_ms": int(
                    recognition_timing.get("ocr_ms")
                    or recognition_timing.get("ocrMs")
                    or extraction_item_ms
                ),
                "recognition_total_ms": recognition_total_ms,
                "grading_ms": grading_wall_ms,
                "extraction_item_ms": extraction_item_ms,
                "grading_item_ms": grading_item_ms,
                "item_elapsed_ms": extraction_item_ms + grading_item_ms,
                "used_routes": used_routes,
                "fallback_used": any(
                    route
                    not in {
                        f"{run.config_snapshot.get('vision_provider')}:{run.config_snapshot.get('vision_model')}",
                        f"{run.provider}:{run.model}",
                        "rules:objective-rules-v1",
                        "safety-gate:answer-evidence-gate-v1",
                    }
                    for route in used_routes
                ),
                "total_elapsed_ms": (
                    recognition_total_ms + grading_wall_ms
                    if recognition_total_ms
                    else grading_wall_ms
                ),
            },
        }
        run.completed_at = get_datetime_utc()
        session.add(run)
        session.commit()
