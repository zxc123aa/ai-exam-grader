import re
import uuid

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.models import (
    AnnotationGradingStatus,
    ExamRegion,
    ProcessingTask,
    ProcessingTaskStatus,
    StandardAnswer,
    StandardAnswerStatus,
    StoredFile,
    StudentSubmission,
    SubmissionAnnotation,
    SubmissionAnnotationStatus,
    get_datetime_utc,
)
from app.services.ocr import extract_ocr_draft
from app.services.submission_crops import (
    resolve_exam_region_paper_page,
    save_region_crop,
)

redis_broker = RedisBroker(url=settings.REDIS_URL)
dramatiq.set_broker(redis_broker)


def tokenize_for_grading(text: str) -> set[str]:
    tokens = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text.lower())
    return {token for token in tokens if token.strip()}


def build_grading_draft(
    *,
    annotation: SubmissionAnnotation,
    standard_answer: StandardAnswer | None,
) -> dict:
    if not standard_answer or standard_answer.status != StandardAnswerStatus.READY:
        annotation.suggested_score = None
        annotation.suggested_comment = None
        annotation.grading_confidence = None
        annotation.grading_reasons = [
            {
                "type": "missing_standard_answer",
                "message": "No ready standard answer is available for this region.",
            }
        ]
        annotation.grading_status = AnnotationGradingStatus.SKIPPED_MISSING_ANSWER
        annotation.answer_key_updated_at = None
        return {
            "region_id": str(annotation.exam_region_id),
            "label": annotation.label,
            "status": annotation.grading_status,
            "reason": "missing_ready_standard_answer",
        }

    annotation.max_score = standard_answer.max_score
    annotation.answer_key_updated_at = standard_answer.updated_at

    if annotation.ocr_status != "succeeded":
        annotation.suggested_score = None
        annotation.suggested_comment = "OCR draft is not available for automatic scoring."
        annotation.grading_confidence = 0
        annotation.grading_reasons = [
            {
                "type": "ocr_not_succeeded",
                "ocr_status": annotation.ocr_status,
                "message": "Teacher review is required before scoring.",
            }
        ]
        annotation.grading_status = AnnotationGradingStatus.NEEDS_REVIEW
        return {
            "region_id": str(annotation.exam_region_id),
            "label": annotation.label,
            "status": annotation.grading_status,
            "reason": "ocr_not_succeeded",
            "answer_key_updated_at": standard_answer.updated_at.isoformat()
            if standard_answer.updated_at
            else None,
        }

    if annotation.ocr_confidence is not None and annotation.ocr_confidence < 0.9:
        annotation.suggested_score = None
        annotation.suggested_comment = "OCR confidence is low; teacher review is required."
        annotation.grading_confidence = annotation.ocr_confidence
        annotation.grading_reasons = [
            {
                "type": "low_ocr_confidence",
                "ocr_confidence": annotation.ocr_confidence,
                "threshold": 0.9,
            }
        ]
        annotation.grading_status = AnnotationGradingStatus.NEEDS_REVIEW
        return {
            "region_id": str(annotation.exam_region_id),
            "label": annotation.label,
            "status": annotation.grading_status,
            "reason": "low_ocr_confidence",
            "answer_key_updated_at": standard_answer.updated_at.isoformat()
            if standard_answer.updated_at
            else None,
        }

    answer_tokens = tokenize_for_grading(standard_answer.answer_text)
    student_tokens = tokenize_for_grading(annotation.ocr_text or "")
    matched_tokens = sorted(answer_tokens & student_tokens)
    coverage = len(matched_tokens) / len(answer_tokens) if answer_tokens else 0
    suggested_score = round(standard_answer.max_score * coverage, 2)
    confidence = min(annotation.ocr_confidence or 0, coverage)
    annotation.suggested_score = suggested_score
    annotation.suggested_comment = (
        "Draft score based on OCR/reference-answer text overlap; teacher must confirm."
    )
    annotation.grading_confidence = round(confidence, 4)
    annotation.grading_reasons = [
        {
            "type": "text_overlap_heuristic_v0",
            "matched_token_count": len(matched_tokens),
            "reference_token_count": len(answer_tokens),
            "coverage": round(coverage, 4),
        },
        {
            "type": "scoring_points_available",
            "count": len(standard_answer.scoring_points),
        },
    ]
    annotation.grading_status = AnnotationGradingStatus.SUCCEEDED
    return {
        "region_id": str(annotation.exam_region_id),
        "label": annotation.label,
        "status": annotation.grading_status,
        "suggested_score": suggested_score,
        "max_score": standard_answer.max_score,
        "grading_confidence": annotation.grading_confidence,
        "answer_key_updated_at": standard_answer.updated_at.isoformat()
        if standard_answer.updated_at
        else None,
    }


@dramatiq.actor
def process_test_task(task_id: str) -> None:
    run_test_task(task_id)


@dramatiq.actor
def process_submission_processing_task(task_id: str) -> None:
    run_submission_processing_task(task_id)


def set_task_state(
    *,
    session: Session,
    task: ProcessingTask,
    status: ProcessingTaskStatus,
    progress: int,
    output_ref: dict | None = None,
    error_message: str | None = None,
) -> None:
    task.status = status
    task.progress = progress
    task.output_ref = output_ref
    task.error_message = error_message
    task.updated_at = get_datetime_utc()
    session.add(task)
    session.commit()


def run_test_task(task_id: str) -> None:
    with Session(engine) as session:
        task = session.get(ProcessingTask, task_id)
        if not task:
            return
        set_task_state(
            session=session,
            task=task,
            status=ProcessingTaskStatus.RUNNING,
            progress=50,
        )
        set_task_state(
            session=session,
            task=task,
            status=ProcessingTaskStatus.SUCCEEDED,
            progress=100,
            output_ref={"message": "Test task completed"},
        )


def run_submission_processing_task(task_id: str) -> None:
    with Session(engine) as session:
        task = session.get(ProcessingTask, task_id)
        if not task:
            return
        try:
            set_task_state(
                session=session,
                task=task,
                status=ProcessingTaskStatus.RUNNING,
                progress=10,
                output_ref={"stage": "loading_submission"},
            )
            input_ref = task.input_ref or {}
            exam_id = uuid.UUID(str(input_ref.get("exam_id")))
            submission_id = uuid.UUID(str(input_ref.get("submission_id")))
            submission = session.get(StudentSubmission, submission_id)
            if not submission or submission.exam_id != exam_id:
                raise ValueError("Student submission not found for processing task")
            stored_file = session.get(StoredFile, submission.stored_file_id)
            if not stored_file:
                raise ValueError("Student submission file not found")

            set_task_state(
                session=session,
                task=task,
                status=ProcessingTaskStatus.RUNNING,
                progress=35,
                output_ref={"stage": "template_regions"},
            )
            regions = session.exec(
                select(ExamRegion)
                .where(ExamRegion.exam_id == exam_id)
                .order_by(ExamRegion.page_number, ExamRegion.created_at)
            ).all()
            standard_answers = session.exec(
                select(StandardAnswer).where(StandardAnswer.exam_id == exam_id)
            ).all()
            standard_answers_by_region_id = {
                answer.exam_region_id: answer for answer in standard_answers
            }
            existing_annotations = session.exec(
                select(SubmissionAnnotation).where(
                    SubmissionAnnotation.submission_id == submission_id
                )
            ).all()
            existing_annotations_by_region_id = {
                annotation.exam_region_id: annotation
                for annotation in existing_annotations
                if annotation.exam_region_id
            }

            created_annotations = 0
            region_crops = []
            ocr_results = []
            grading_results = []
            for region in regions:
                crop = save_region_crop(
                    stored_file=stored_file,
                    region=region,
                    owner_id=stored_file.uploaded_by_id,
                    submission_id=submission.id,
                    upload_dir=settings.LOCAL_UPLOAD_DIR,
                    page_number=resolve_exam_region_paper_page(session, region),
                )
                region_crops.append(crop)
                ocr_draft = extract_ocr_draft(
                    settings.LOCAL_UPLOAD_DIR / crop["storage_key"]
                )
                ocr_results.append(
                    {
                        "region_id": str(region.id),
                        "label": region.label,
                        "status": ocr_draft.status,
                        "engine": ocr_draft.engine,
                        "confidence": ocr_draft.confidence,
                        "error": ocr_draft.error,
                    }
                )
                annotation = existing_annotations_by_region_id.get(region.id)
                if not annotation:
                    annotation = SubmissionAnnotation(
                        submission_id=submission.id,
                        exam_region_id=region.id,
                        label=region.label,
                        status=SubmissionAnnotationStatus.NEEDS_REVIEW,
                        page_number=region.page_number,
                        x=region.x,
                        y=region.y,
                        width=region.width,
                        height=region.height,
                        comment="Awaiting OCR and AI grading result.",
                    )
                    session.add(annotation)
                    created_annotations += 1
                annotation.ocr_text = ocr_draft.text
                annotation.ocr_confidence = ocr_draft.confidence
                annotation.ocr_status = ocr_draft.status
                annotation.ocr_engine = ocr_draft.engine
                grading_results.append(
                    build_grading_draft(
                        annotation=annotation,
                        standard_answer=standard_answers_by_region_id.get(region.id),
                    )
                )
                annotation.updated_at = get_datetime_utc()
            session.commit()

            ocr_statuses = {result["status"] for result in ocr_results}
            if not ocr_results:
                ocr_stage: str | dict = "skipped"
            elif ocr_statuses == {"succeeded"}:
                ocr_stage = "succeeded"
            else:
                ocr_stage = {
                    "status": "needs_configuration"
                    if "not_configured" in ocr_statuses
                    else "partial",
                    "engine": ocr_results[0]["engine"],
                }
            grading_statuses = {result["status"] for result in grading_results}
            if not grading_results:
                grading_stage: str | dict = "skipped"
            elif grading_statuses == {AnnotationGradingStatus.SUCCEEDED}:
                grading_stage = "succeeded"
            elif AnnotationGradingStatus.SKIPPED_MISSING_ANSWER in grading_statuses:
                grading_stage = {
                    "status": "skipped_missing_answer",
                    "succeeded_count": sum(
                        result["status"] == AnnotationGradingStatus.SUCCEEDED
                        for result in grading_results
                    ),
                    "total_count": len(grading_results),
                }
            else:
                grading_stage = {
                    "status": "needs_review",
                    "succeeded_count": sum(
                        result["status"] == AnnotationGradingStatus.SUCCEEDED
                        for result in grading_results
                    ),
                    "total_count": len(grading_results),
                }

            output_ref = {
                "pipeline": "submission_processing_v1",
                "submission_id": str(submission_id),
                "exam_id": str(exam_id),
                "stages": {
                    "registration": {
                        "status": "manual_confirmed"
                        if submission.registration_status == "manual_confirmed"
                        else "needs_review",
                        "source": "identity_v1",
                    },
                    "region_crops": "succeeded",
                    "ocr": ocr_stage,
                    "grading": grading_stage,
                },
                "region_count": len(regions),
                "region_crops": region_crops,
                "ocr_results": ocr_results,
                "grading_results": grading_results,
                "created_annotation_count": created_annotations,
            }
            set_task_state(
                session=session,
                task=task,
                status=ProcessingTaskStatus.SUCCEEDED,
                progress=100,
                output_ref=output_ref,
            )
        except Exception as exc:
            set_task_state(
                session=session,
                task=task,
                status=ProcessingTaskStatus.FAILED,
                progress=100,
                output_ref=task.output_ref,
                error_message=str(exc),
            )
