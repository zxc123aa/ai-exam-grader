import re
import uuid
from collections.abc import Callable

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from sqlalchemy import text
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
from app.services.object_storage import materialize_storage_key
from app.services.ocr import extract_ocr_draft
from app.services.submission_crops import (
    resolve_exam_region_paper_page,
    save_region_crop,
)

redis_broker = RedisBroker(url=settings.REDIS_URL)
dramatiq.set_broker(redis_broker)

SCAN_PREPROCESSING_LOCK_ID = "00000000-0000-0000-0000-000000005ca0"


def _run_once(resource_id: str, callback: Callable[..., None], *args: str) -> bool:
    """Hold a PostgreSQL advisory lock for the full worker operation."""
    lock_key = uuid.UUID(resource_id).int & 0x7FFF_FFFF_FFFF_FFFF
    with Session(engine) as lock_session:
        locked = lock_session.exec(
            text("SELECT pg_try_advisory_lock(:key)").bindparams(key=lock_key)
        ).one()[0]
        if not locked:
            return False
        try:
            callback(*args)
        finally:
            lock_session.exec(
                text("SELECT pg_advisory_unlock(:key)").bindparams(key=lock_key)
            )
        return True


def _run_org_job_once(
    resource_id: str,
    org_id: uuid.UUID,
    task_type: str,
    callback: Callable[..., None],
    *args: str,
) -> bool:
    from app.services.job_control import organization_job_slot

    with organization_job_slot(
        org_id=org_id, task_type=task_type, resource_id=resource_id
    ) as acquired:
        if not acquired:
            return False
        _run_once(resource_id, callback, *args)
        return True


@dramatiq.actor(max_retries=0)
def process_grading_run(run_id: str) -> None:
    from app.models import Exam, GradingRun, GradingRunStatus
    from app.services.grading_workflow import execute_grading_run

    with Session(engine) as session:
        run = session.get(GradingRun, uuid.UUID(run_id))
        if not run or run.status in {
            GradingRunStatus.RUNNING,
            GradingRunStatus.COMPLETED,
        }:
            return
        exam = session.get(Exam, run.exam_id)
        if not exam:
            return

    if not _run_org_job_once(
        run_id, exam.org_id, "grading", execute_grading_run, run_id
    ):
        process_grading_run.send_with_options(args=(run_id,), delay=5000)


def run_wrongbook_snapshot(release_id: str) -> None:
    from app.services.wrongbook import snapshot_release

    with Session(engine) as session:
        snapshot_release(session, uuid.UUID(release_id))


@dramatiq.actor(max_retries=3, min_backoff=5_000)
def process_wrongbook_snapshot(release_id: str) -> None:
    """成绩发布后把学生逐题结果快照进错题本。

    重裁题区要渲染 PDF，属于 CPU 密集操作，因此占用学校任务槽；抢不到槽就延迟重排。
    """
    from app.models import Exam, ScoreRelease

    with Session(engine) as session:
        release = session.get(ScoreRelease, uuid.UUID(release_id))
        if not release:
            return
        exam = session.get(Exam, release.exam_id)
        if not exam:
            return

    if not _run_org_job_once(
        release_id,
        exam.org_id,
        "wrongbook_snapshot",
        run_wrongbook_snapshot,
        release_id,
    ):
        process_wrongbook_snapshot.send_with_options(args=(release_id,), delay=5000)


@dramatiq.actor(max_retries=0)
def process_recognition_run(run_id: str) -> None:
    from app.models import Exam, GradingRun, GradingRunStatus
    from app.services.recognition_workflow import execute_recognition_run

    with Session(engine) as session:
        run = session.get(GradingRun, uuid.UUID(run_id))
        if not run or run.status in {
            GradingRunStatus.RUNNING,
            GradingRunStatus.COMPLETED,
        }:
            return
        exam = session.get(Exam, run.exam_id)
        if not exam:
            return

    if not _run_org_job_once(
        run_id, exam.org_id, "recognition", execute_recognition_run, run_id
    ):
        process_recognition_run.send_with_options(args=(run_id,), delay=5000)


@dramatiq.actor(max_retries=0)
def process_rubric_generation(task_id: str, exam_id: str) -> None:
    from app.models import Exam, ProcessingTask, ProcessingTaskStatus
    from app.services.rubric_workflow import execute_rubric_generation

    with Session(engine) as session:
        task = session.get(ProcessingTask, uuid.UUID(task_id))
        if not task or task.status in {
            ProcessingTaskStatus.RUNNING,
            ProcessingTaskStatus.SUCCEEDED,
        }:
            return
        exam = session.get(Exam, uuid.UUID(exam_id))
        if not exam:
            return

    if not _run_org_job_once(
        task_id,
        exam.org_id,
        "rubric_generation",
        execute_rubric_generation,
        task_id,
        exam_id,
    ):
        process_rubric_generation.send_with_options(args=(task_id, exam_id), delay=5000)


@dramatiq.actor(max_retries=0)
def process_question_recognition_run(run_id: str) -> None:
    from app.models import Exam, QuestionRecognitionRun, WorkflowRunStatus
    from app.services.question_answer_workflow import execute_question_recognition

    with Session(engine) as session:
        run = session.get(QuestionRecognitionRun, uuid.UUID(run_id))
        if not run or run.status in {
            WorkflowRunStatus.RUNNING,
            WorkflowRunStatus.COMPLETED,
        }:
            return
        exam = session.get(Exam, run.exam_id)
        if not exam:
            return

    if not _run_org_job_once(
        run_id,
        exam.org_id,
        "question_recognition",
        execute_question_recognition,
        run_id,
    ):
        process_question_recognition_run.send_with_options(args=(run_id,), delay=5000)


@dramatiq.actor(max_retries=0)
def process_answer_preparation_run(run_id: str) -> None:
    from app.models import AnswerPreparationRun, Exam, WorkflowRunStatus
    from app.services.question_answer_workflow import execute_answer_preparation

    with Session(engine) as session:
        run = session.get(AnswerPreparationRun, uuid.UUID(run_id))
        if not run or run.status in {
            WorkflowRunStatus.RUNNING,
            WorkflowRunStatus.COMPLETED,
        }:
            return
        exam = session.get(Exam, run.exam_id)
        if not exam:
            return

    if not _run_org_job_once(
        run_id,
        exam.org_id,
        "answer_preparation",
        execute_answer_preparation,
        run_id,
    ):
        process_answer_preparation_run.send_with_options(args=(run_id,), delay=5000)


@dramatiq.actor(max_retries=0)
def reconcile_billing_reservations() -> None:
    from app.services.billing import reconcile_stale_reservations

    with Session(engine) as session:
        reconcile_stale_reservations(session)
        session.commit()


@dramatiq.actor(max_retries=5, min_backoff=5_000, max_backoff=300_000)
def dispatch_outbox_events() -> None:
    from app.services.outbox import dispatch_pending_events

    with Session(engine) as session:
        dispatch_pending_events(session)
        session.commit()


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
        annotation.suggested_comment = (
            "OCR draft is not available for automatic scoring."
        )
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
        annotation.suggested_comment = (
            "OCR confidence is low; teacher review is required."
        )
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


@dramatiq.actor(max_retries=0)
def process_exam_document_preprocessing(document_id: str) -> None:
    if not _run_once(
        SCAN_PREPROCESSING_LOCK_ID,
        run_exam_document_preprocessing,
        document_id,
    ):
        process_exam_document_preprocessing.send_with_options(
            args=(document_id,), delay=5000
        )


def run_exam_document_preprocessing(document_id: str) -> None:
    from app.api.routes.exams import auto_rectify_exam_document_record
    from app.models import ExamDocument

    with Session(engine) as session:
        document = session.get(ExamDocument, uuid.UUID(document_id))
        if not document or document.preprocessing_status in {"ready", "review"}:
            return
        if document.preprocessing_status not in {"queued", "running"}:
            return
        stored_file = session.get(StoredFile, document.stored_file_id)
        if not stored_file:
            document.preprocessing_status = "failed"
            document.preprocessing_quality = 0.0
            document.preprocessing_metadata = {
                "source": "async_scan_preprocessing_v1",
                "error": {
                    "code": "source_file_missing",
                    "message": "Original uploaded file was not found",
                },
            }
            session.add(document)
            session.commit()
            return

        document.preprocessing_status = "running"
        session.add(document)
        session.commit()
        try:
            auto_rectify_exam_document_record(
                session=session,
                exam_document=document,
                stored_file=stored_file,
            )
            session.commit()
        except Exception as exc:
            session.rollback()
            document = session.get(ExamDocument, uuid.UUID(document_id))
            if not document:
                return
            document.preprocessing_status = "failed"
            document.preprocessing_quality = 0.0
            document.preprocessing_metadata = {
                "source": "async_scan_preprocessing_v1",
                "scan_engine": settings.SCAN_ENGINE,
                "error": {
                    "code": "preprocessing_failed",
                    "message": (str(exc).strip() or exc.__class__.__name__)[:500],
                },
            }
            session.add(document)
            session.commit()


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
                    page_number=resolve_exam_region_paper_page(session, region),
                )
                region_crops.append(crop)
                ocr_draft = extract_ocr_draft(
                    materialize_storage_key(crop["storage_key"])
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
