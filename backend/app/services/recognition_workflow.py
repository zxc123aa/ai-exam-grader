from __future__ import annotations

import time
import uuid
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass

from sqlmodel import Session, select

from app.core.db import engine
from app.models import (
    ExamRegion,
    ExamRegionType,
    GradingItem,
    GradingItemStatus,
    GradingRun,
    GradingRunStatus,
    StoredFile,
    StudentSubmission,
    get_datetime_utc,
)
from app.services.reference_algorithm import process_stored_file
from app.services.question_text_normalization import (
    normalize_recognized_question_text_with_audit,
)
from app.services.submission_crops import (
    crop_region_png,
    resolve_exam_region_paper_page,
)
from app.services.vision_grading import extract_answer_image


@dataclass(frozen=True)
class RecognitionPayload:
    item_id: uuid.UUID
    stored_file: StoredFile
    region: ExamRegion
    provider: str
    model: str
    # Global paper page; regions store document-local pages while the
    # submission is a single multi-page file.
    page_number: int | None = None


def _recognize(payload: RecognitionPayload) -> tuple[RecognitionPayload, dict | None, str | None]:
    try:
        result = extract_answer_image(
            image_bytes=crop_region_png(
                stored_file=payload.stored_file,
                region=payload.region,
                page_number=payload.page_number,
            ),
            provider=payload.provider,
            model=payload.model,
            question_label=payload.region.label,
        )
        question_audit = normalize_recognized_question_text_with_audit(
            result.question_text,
            question_key=payload.region.label,
        )
        question_text = str(question_audit["text"])
        return payload, {
            "question_text": question_text,
            **(
                {"raw_question_text": result.question_text}
                if question_text != result.question_text.strip()
                else {}
            ),
            **(
                {"question_normalization": {
                    key: value
                    for key, value in question_audit.items()
                    if key != "text"
                }}
                if question_audit.get("changed")
                else {}
            ),
            "student_answer": result.student_answer,
            "final_answer": result.final_answer,
            "answer_type": result.answer_type,
            "confidence": result.confidence,
            "notes": result.notes,
            "provider": result.provider,
            "model": result.model,
            "elapsed_ms": result.elapsed_ms,
        }, None
    except Exception as exc:
        return payload, None, str(exc)[:1000]


def _needs_graphical_supplement(extracted: dict) -> bool:
    question = str(extracted.get("question") or "")
    return any(
        marker in question
        for marker in ("作图", "画出", "示意图", "绕法", "连线", "图中画")
    )


def execute_recognition_run(run_id: str) -> None:
    started_perf = time.perf_counter()
    with Session(engine, expire_on_commit=False) as session:
        run = session.get(GradingRun, uuid.UUID(run_id))
        if not run:
            return
        run.status = GradingRunStatus.RUNNING
        run.started_at = get_datetime_utc()
        run.config_snapshot = {
            **run.config_snapshot,
            "timing": {"layout_ms": 0, "crop_ms": 0, "ocr_ms": 0, "total_elapsed_ms": 0},
        }
        submission_id = uuid.UUID(run.config_snapshot["submission_id"])
        submission = session.get(StudentSubmission, submission_id)
        stored_file = session.get(StoredFile, submission.stored_file_id) if submission else None
        regions = list(session.exec(select(ExamRegion).where(
            ExamRegion.exam_id == run.exam_id,
            ExamRegion.region_type == ExamRegionType.QUESTION,
        ).order_by(ExamRegion.page_number, ExamRegion.y)).all())
        if not submission or not stored_file:
            run.status = GradingRunStatus.FAILED
            run.error_message = "答卷文件不存在"
            run.completed_at = get_datetime_utc()
            session.add(run)
            session.commit()
            return
        reference_payload = None
        try:
            reference_payload = process_stored_file(
                stored_file=stored_file,
                verification_mode=str(
                    run.config_snapshot.get("verification_mode") or "evidence"
                ),
            )
        except Exception:
            # Keep existing queued runs resumable while the Node sidecar is unavailable.
            reference_payload = None
        if reference_payload and reference_payload.get("results"):
            results = reference_payload["results"]
            pairs = list(zip(regions, results, strict=False))
            graphical_started = time.perf_counter()
            graphical_supplements: dict[int, dict] = {}
            graphical_targets = [
                (index, region)
                for index, (region, extracted) in enumerate(pairs)
                if _needs_graphical_supplement(extracted)
            ]
            if graphical_targets:
                max_workers = min(
                    len(graphical_targets),
                    min(
                        8,
                        max(
                            1,
                            int(run.config_snapshot.get("max_concurrency", 8)),
                        ),
                    ),
                )
                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    futures = {
                        pool.submit(
                            _recognize,
                            RecognitionPayload(
                                item_id=uuid.uuid4(),
                                stored_file=stored_file,
                                region=region,
                                provider=run.provider,
                                model=run.model,
                                page_number=resolve_exam_region_paper_page(
                                    session, region
                                ),
                            ),
                        ): index
                        for index, region in graphical_targets
                    }
                    for future in futures:
                        _payload, supplement, error = future.result()
                        index = futures[future]
                        if not error and supplement and str(
                            supplement.get("student_answer") or ""
                        ).strip():
                            graphical_supplements[index] = supplement
            graphical_ms = round(
                (time.perf_counter() - graphical_started) * 1000
            )
            reference_timing = dict(reference_payload.get("timing", {}))
            if graphical_targets:
                reference_timing["graphicalFallbackMs"] = graphical_ms
                reference_timing["graphicalFallbackCount"] = len(
                    graphical_supplements
                )
                reference_timing["totalElapsedMs"] = int(
                    reference_timing.get("totalElapsedMs") or 0
                ) + graphical_ms
            run.total_submissions = 1
            run.total_items = min(len(results), len(regions))
            run.completed_items = run.total_items
            run.extracted_items = run.total_items
            run.current_concurrency = int(reference_payload.get("concurrency") or 0)
            run.config_snapshot = {
                **run.config_snapshot,
                "algorithm": "reference-node",
                "timing": reference_timing,
            }
            for index, (region, extracted) in enumerate(pairs):
                question_audit = normalize_recognized_question_text_with_audit(
                    str(extracted.get("question") or ""),
                    question_key=str(extracted.get("questionNumber") or region.label or ""),
                )
                question_text = str(question_audit["text"])
                extraction_result = {
                    "question_text": question_text,
                    **(
                        {"raw_question_text": extracted.get("question", "")}
                        if question_text != str(extracted.get("question") or "").strip()
                        else {}
                    ),
                    **(
                        {"question_normalization": {
                            key: value
                            for key, value in question_audit.items()
                            if key != "text"
                        }}
                        if question_audit.get("changed")
                        else {}
                    ),
                    "student_answer": extracted.get("studentAnswer", ""),
                    "final_answer": extracted.get("studentAnswer", ""),
                    "answer_type": extracted.get("answerType", "未知"),
                    "confidence": extracted.get("confidence", 0),
                    "notes": [extracted.get("notes", "")],
                    "printed_question_marks": extracted.get(
                        "printedQuestionMarks", []
                    ),
                    "answer_entries": extracted.get("answerEntries", []),
                    "unassigned_evidence": extracted.get(
                        "unassignedEvidence", []
                    ),
                    "grading_answer": extracted.get("gradingAnswer", ""),
                    "grading_eligible": bool(
                        extracted.get("gradingEligible", False)
                    ),
                    "answer_structure": extracted.get("answerStructure", {}),
                    "answer_verification": extracted.get(
                        "answerVerification", {}
                    ),
                    "provider": run.provider,
                    "model": run.model,
                    "elapsed_ms": extracted.get("elapsedMs", 0),
                }
                supplement = graphical_supplements.get(index)
                if supplement and len(
                    str(supplement.get("student_answer") or "").strip()
                ) > len(str(extracted.get("studentAnswer") or "").strip()):
                    extraction_result = {
                        **supplement,
                        "notes": [
                            "作图题已在首轮并发 OCR 后使用 Gemini 整块视觉补充；"
                            "补充结果仍需教师对照原图确认。",
                            *list(supplement.get("notes") or []),
                        ],
                        "elapsed_ms": int(
                            supplement.get("elapsed_ms") or 0
                        )
                        + int(extracted.get("elapsedMs") or 0),
                    }
                item = GradingItem(
                    grading_run_id=run.id,
                    submission_id=submission.id,
                    exam_region_id=region.id,
                    status=GradingItemStatus.COMPLETED,
                    extraction_result=extraction_result,
                    completed_at=get_datetime_utc(),
                )
                session.add(item)
            run.status = GradingRunStatus.COMPLETED
            run.completed_at = get_datetime_utc()
            session.add(run)
            session.commit()
            return
        items = []
        for region in regions:
            item = session.exec(select(GradingItem).where(
                GradingItem.grading_run_id == run.id,
                GradingItem.submission_id == submission.id,
                GradingItem.exam_region_id == region.id,
            )).first()
            if not item:
                item = GradingItem(grading_run_id=run.id, submission_id=submission.id, exam_region_id=region.id)
                session.add(item)
                session.flush()
            items.append((item, region))
        run.total_submissions = 1
        run.total_items = len(items)
        session.add(run)
        session.commit()
        payloads = [RecognitionPayload(item_id=item.id, stored_file=stored_file, region=region,
                    provider=run.provider, model=run.model,
                    page_number=resolve_exam_region_paper_page(session, region))
                    for item, region in items
                    if item.status not in {GradingItemStatus.COMPLETED, GradingItemStatus.NEEDS_REVIEW}]
        max_workers = min(8, max(1, int(run.config_snapshot.get("max_concurrency", 8))))
        futures: dict[Future, RecognitionPayload] = {}
        pending = list(payloads)
        try:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                while pending or futures:
                    while pending and len(futures) < max_workers:
                        payload = pending.pop(0)
                        item = session.get(GradingItem, payload.item_id)
                        item.status = GradingItemStatus.EXTRACTING
                        item.started_at = get_datetime_utc()
                        session.add(item)
                        futures[pool.submit(_recognize, payload)] = payload
                    session.commit()
                    done, _ = wait(futures, return_when=FIRST_COMPLETED)
                    for future in done:
                        payload, extraction, error = future.result()
                        futures.pop(future)
                        item = session.get(GradingItem, payload.item_id)
                        if error:
                            item.status = GradingItemStatus.FAILED
                            item.error_message = error
                        else:
                            item.status = GradingItemStatus.COMPLETED
                            item.extraction_result = extraction or {}
                            item.error_message = None
                            item.completed_at = get_datetime_utc()
                        item.attempts += 1
                        session.add(item)
                        session.commit()
            items_now = list(session.exec(select(GradingItem).where(GradingItem.grading_run_id == run.id)).all())
            run.completed_items = sum(item.status in {GradingItemStatus.COMPLETED, GradingItemStatus.NEEDS_REVIEW, GradingItemStatus.FAILED} for item in items_now)
            run.extracted_items = sum(bool(item.extraction_result) for item in items_now)
            run.failed_count = sum(item.status == GradingItemStatus.FAILED for item in items_now)
            run.review_count = sum(item.status in {GradingItemStatus.NEEDS_REVIEW, GradingItemStatus.FAILED} for item in items_now)
            run.current_concurrency = 0
            run.status = GradingRunStatus.COMPLETED_WITH_ERRORS if run.failed_count else GradingRunStatus.COMPLETED
        except Exception as exc:
            run.status = GradingRunStatus.FAILED
            run.error_message = str(exc)[:2000]
        run.completed_at = get_datetime_utc()
        total_ms = round((time.perf_counter() - started_perf) * 1000)
        timing = dict((run.config_snapshot or {}).get("timing", {}))
        timing["ocr_ms"] = total_ms
        timing["total_elapsed_ms"] = total_ms
        timing["item_elapsed_ms"] = sum(
            int((item.extraction_result or {}).get("elapsed_ms") or 0)
            for item in items_now
        ) if 'items_now' in locals() else 0
        run.config_snapshot = {**run.config_snapshot, "timing": timing}
        session.add(run)
        session.commit()
