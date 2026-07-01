import uuid

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.models import (
    ExamRegion,
    ProcessingTask,
    ProcessingTaskStatus,
    StoredFile,
    StudentSubmission,
    SubmissionAnnotation,
    SubmissionAnnotationStatus,
    get_datetime_utc,
)
from app.services.ocr import extract_ocr_draft
from app.services.submission_crops import save_region_crop

redis_broker = RedisBroker(url=settings.REDIS_URL)
dramatiq.set_broker(redis_broker)


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
            for region in regions:
                crop = save_region_crop(
                    stored_file=stored_file,
                    region=region,
                    owner_id=stored_file.uploaded_by_id,
                    submission_id=submission.id,
                    upload_dir=settings.LOCAL_UPLOAD_DIR,
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
                    "grading": "not_started",
                },
                "region_count": len(regions),
                "region_crops": region_crops,
                "ocr_results": ocr_results,
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
