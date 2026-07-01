import dramatiq
from dramatiq.brokers.redis import RedisBroker
import uuid

from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.models import (
    ExamRegion,
    ProcessingTask,
    ProcessingTaskStatus,
    StudentSubmission,
    SubmissionAnnotation,
    SubmissionAnnotationStatus,
    get_datetime_utc,
)

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
            existing_region_ids = {
                annotation.exam_region_id
                for annotation in existing_annotations
                if annotation.exam_region_id
            }

            created_annotations = 0
            for region in regions:
                if region.id in existing_region_ids:
                    continue
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
            session.commit()

            output_ref = {
                "pipeline": "submission_processing_v1",
                "submission_id": str(submission_id),
                "exam_id": str(exam_id),
                "stages": {
                    "registration": "placeholder",
                    "region_crops": "placeholder",
                    "ocr": "not_started",
                    "grading": "not_started",
                },
                "region_count": len(regions),
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
