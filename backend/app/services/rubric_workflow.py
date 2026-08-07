from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.models import (
    Exam,
    ExamDocument,
    ExamDocumentType,
    ExamRegion,
    ProcessingTask,
    ProcessingTaskStatus,
    StandardAnswer,
    StoredFile,
    get_datetime_utc,
)
from app.services import billing as billing_service
from app.services.rubric_generation import generate_and_validate_rubric
from app.services.submission_crops import crop_region_png


def _generate_one(
    answer_id: uuid.UUID, reservation_id: uuid.UUID | None = None
) -> dict:
    with Session(engine, expire_on_commit=False) as session:
        answer = session.get(StandardAnswer, answer_id)
        if not answer:
            return {
                "answer_id": str(answer_id),
                "valid": False,
                "error": "标准答案不存在",
            }
        region = session.get(ExamRegion, answer.exam_region_id)
        # 必须按题区所属文档取源文件：多文件拼成的整卷里，
        # 错用第一个文档会把其他题的页面裁进来
        if region and region.exam_document_id:
            row = session.exec(
                select(ExamDocument, StoredFile)
                .join(StoredFile, ExamDocument.stored_file_id == StoredFile.id)
                .where(ExamDocument.id == region.exam_document_id)
            ).first()
        else:
            row = session.exec(
                select(ExamDocument, StoredFile)
                .join(StoredFile, ExamDocument.stored_file_id == StoredFile.id)
                .where(
                    ExamDocument.exam_id == answer.exam_id,
                    ExamDocument.document_type == ExamDocumentType.BLANK_EXAM,
                )
            ).first()
        if not region or not row:
            return {
                "answer_id": str(answer_id),
                "valid": False,
                "error": "缺少题区或空白卷",
            }
        _document, stored_file = row
        try:
            from app.models import SchoolModelScope
            from app.services.system_config import (
                get_grading_defaults,
                get_school_model_target,
            )

            exam = session.get(Exam, answer.exam_id)
            defaults = get_grading_defaults(session, exam.org_id if exam else None)
            answer_provider, answer_model = get_school_model_target(
                session,
                org_id=exam.org_id if exam else None,
                scope=SchoolModelScope.REFERENCE_ANSWER,
                fallback_provider=str(defaults["grading_provider"]),
                fallback_model=str(defaults["grading_model"]),
            )
            generated = generate_and_validate_rubric(
                image_bytes=crop_region_png(stored_file=stored_file, region=region),
                answer=answer,
                question_label=region.label,
                vision_provider=str(defaults["recognition_provider"]),
                vision_model=str(defaults["recognition_model"]),
                answer_provider=answer_provider,
                answer_model=answer_model,
                vision_fallback_models=[
                    str(item) for item in defaults["vision_fallback_models"]
                ],
                reasoning_fallback_models=[
                    str(item) for item in defaults["reasoning_fallback_models"]
                ],
                org_id=exam.org_id if exam else None,
                reservation_id=reservation_id,
            )
            session.add(generated)
            session.commit()
            return {
                "answer_id": str(answer.id),
                "label": region.label,
                "valid": generated.validation_report.get("valid") is True,
                "issues": generated.validation_report.get("issues", []),
            }
        except Exception as exc:
            session.rollback()
            return {
                "answer_id": str(answer_id),
                "label": region.label,
                "valid": False,
                "error": str(exc)[:1000],
            }


def execute_rubric_generation(task_id: str, exam_id: str) -> None:
    task_uuid, exam_uuid = uuid.UUID(task_id), uuid.UUID(exam_id)
    with Session(engine) as session:
        task = session.get(ProcessingTask, task_uuid)
        if not task:
            return
        reservation_id = (
            uuid.UUID(str(task.input_ref["billing_reservation_id"]))
            if (task.input_ref or {}).get("billing_reservation_id")
            else None
        )
        task.status, task.progress, task.updated_at = (
            ProcessingTaskStatus.RUNNING,
            0,
            get_datetime_utc(),
        )
        session.add(task)
        session.commit()
        answer_ids = list(
            session.exec(
                select(StandardAnswer.id).where(StandardAnswer.exam_id == exam_uuid)
            ).all()
        )
    reports: list[dict] = []
    try:
        concurrency = min(4, settings.VISION_MAX_CONCURRENCY)
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [
                pool.submit(_generate_one, answer_id, reservation_id)
                for answer_id in answer_ids
            ]
            for index, future in enumerate(as_completed(futures), start=1):
                reports.append(future.result())
                with Session(engine) as session:
                    task = session.get(ProcessingTask, task_uuid)
                    if task:
                        task.progress = round(index / max(1, len(answer_ids)) * 100)
                        task.output_ref = {"reports": reports}
                        task.updated_at = get_datetime_utc()
                        session.add(task)
                        session.commit()
        with Session(engine) as session:
            task = session.get(ProcessingTask, task_uuid)
            if task:
                failures = [item for item in reports if not item.get("valid")]
                task.status = (
                    ProcessingTaskStatus.SUCCEEDED
                    if not failures
                    else ProcessingTaskStatus.FAILED
                )
                task.error_message = (
                    f"{len(failures)} 道题的评分准则未通过校验" if failures else None
                )
                task.progress, task.output_ref, task.updated_at = (
                    100,
                    {"reports": reports},
                    get_datetime_utc(),
                )
                if reservation_id:
                    billing_service.settle_reservation(session, reservation_id)
                session.add(task)
                session.commit()
    except Exception as exc:
        with Session(engine) as session:
            task = session.get(ProcessingTask, task_uuid)
            if task:
                task.status, task.error_message, task.updated_at = (
                    ProcessingTaskStatus.FAILED,
                    str(exc)[:1000],
                    get_datetime_utc(),
                )
                session.add(task)
                session.commit()
