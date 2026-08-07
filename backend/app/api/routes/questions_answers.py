from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_teacher_user,
)
from app.models import (
    AnswerPreparationItem,
    AnswerPreparationItemPublic,
    AnswerPreparationItemStatus,
    AnswerPreparationItemUpdate,
    AnswerPreparationRun,
    AnswerPreparationRunCreate,
    AnswerPreparationRunPublic,
    AnswerPreparationRunsPublic,
    AnswerPreparationSource,
    Exam,
    ExamDocument,
    ExamDocumentType,
    ExamQuestion,
    ExamQuestionPublic,
    ExamQuestionRegion,
    ExamQuestionsPublic,
    ExamQuestionStatus,
    ExamRegion,
    ExamRegionType,
    MarkingRecognitionImport,
    QuestionRecognitionItem,
    QuestionRecognitionItemPublic,
    QuestionRecognitionItemStatus,
    QuestionRecognitionItemUpdate,
    QuestionRecognitionRun,
    QuestionRecognitionRunCreate,
    QuestionRecognitionRunPublic,
    QuestionRecognitionRunsPublic,
    QuestionRegionRole,
    SchoolModelScope,
    StandardAnswer,
    StandardAnswerPublishRequest,
    StandardAnswerRevision,
    StandardAnswerRevisionPublic,
    StandardAnswerRevisionsPublic,
    StandardAnswerRevisionStatus,
    StandardAnswerStatus,
    StoredFile,
    WorkflowRunStatus,
    get_datetime_utc,
)
from app.services import billing as billing_service
from app.services.file_storage import get_stored_file_path
from app.services.org_scope import can_see_exam, can_write_exam
from app.services.pdf_rendering import get_pdf_page_count
from app.services.question_answer_workflow import (
    persist_question_recognition_payload,
)
from app.services.system_config import get_grading_defaults, get_school_model_target
from app.worker import (
    process_answer_preparation_run,
    process_question_recognition_run,
)

router = APIRouter(
    prefix="/exams",
    tags=["question-answer-workflow"],
    dependencies=[Depends(get_current_teacher_user)],
)


def _natural_key(value: str | None) -> tuple:
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", value or "")
        if part
    )


def _owned_exam(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    *,
    require_write: bool = False,
) -> Exam:
    exam = session.get(Exam, exam_id)
    if not exam or not can_see_exam(session, current_user, exam):
        raise HTTPException(status_code=404, detail="考试不存在")
    if require_write and not can_write_exam(current_user, exam):
        raise HTTPException(status_code=403, detail="无权修改该考试")
    return exam


def _question_run(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    require_write: bool = False,
) -> QuestionRecognitionRun:
    _owned_exam(session, current_user, exam_id, require_write=require_write)
    run = session.get(QuestionRecognitionRun, run_id)
    if not run or run.exam_id != exam_id:
        raise HTTPException(status_code=404, detail="题目识别任务不存在")
    return run


def _answer_run(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    require_write: bool = False,
) -> AnswerPreparationRun:
    _owned_exam(session, current_user, exam_id, require_write=require_write)
    run = session.get(AnswerPreparationRun, run_id)
    if not run or run.exam_id != exam_id:
        raise HTTPException(status_code=404, detail="答案准备任务不存在")
    return run


def _question_public(session: SessionDep, question: ExamQuestion) -> ExamQuestionPublic:
    region_ids = list(
        session.exec(
            select(ExamQuestionRegion.exam_region_id)
            .where(ExamQuestionRegion.question_id == question.id)
            .order_by(ExamQuestionRegion.sequence)
        ).all()
    )
    return ExamQuestionPublic.model_validate(
        question, update={"region_ids": region_ids}
    )


def _question_run_public(
    session: SessionDep, run: QuestionRecognitionRun
) -> QuestionRecognitionRunPublic:
    count = session.exec(
        select(func.count())
        .select_from(QuestionRecognitionItem)
        .where(QuestionRecognitionItem.run_id == run.id)
    ).one()
    return QuestionRecognitionRunPublic.model_validate(
        run, update={"item_count": count}
    )


def _answer_run_public(
    session: SessionDep, run: AnswerPreparationRun
) -> AnswerPreparationRunPublic:
    count = session.exec(
        select(func.count())
        .select_from(AnswerPreparationItem)
        .where(AnswerPreparationItem.run_id == run.id)
    ).one()
    return AnswerPreparationRunPublic.model_validate(run, update={"item_count": count})


@router.get("/{exam_id}/questions", response_model=ExamQuestionsPublic)
def list_exam_questions(
    session: SessionDep, current_user: CurrentUser, exam_id: uuid.UUID
) -> ExamQuestionsPublic:
    _owned_exam(session, current_user, exam_id)
    questions = list(
        session.exec(select(ExamQuestion).where(ExamQuestion.exam_id == exam_id)).all()
    )
    questions.sort(key=lambda question: _natural_key(question.question_key))
    return ExamQuestionsPublic(
        data=[_question_public(session, question) for question in questions],
        count=len(questions),
    )


@router.post(
    "/{exam_id}/question-recognition-runs",
    response_model=QuestionRecognitionRunPublic,
)
def create_question_recognition_run(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    run_in: QuestionRecognitionRunCreate,
) -> QuestionRecognitionRunPublic:
    exam = _owned_exam(session, current_user, exam_id, require_write=True)
    billing_service.require_model_entitlement(session, exam.org_id)
    document_ids = list(dict.fromkeys(run_in.document_ids))
    documents = list(
        session.exec(
            select(ExamDocument).where(
                ExamDocument.exam_id == exam_id,
                col(ExamDocument.id).in_(document_ids),
            )
        ).all()
    )
    if len(documents) != len(document_ids):
        raise HTTPException(status_code=422, detail="部分试卷文件不存在")
    if any(item.document_type != ExamDocumentType.BLANK_EXAM for item in documents):
        raise HTTPException(
            status_code=422,
            detail="题目识别只能选择题目源页面：可以是空白卷，也可以是一份代表学生卷；答案文档请在标准答案页面导入",
        )
    defaults = get_grading_defaults(session, exam.org_id)
    run = QuestionRecognitionRun(
        exam_id=exam_id,
        created_by_id=current_user.id,
        provider=str(defaults["recognition_provider"]),
        model=str(defaults["recognition_model"]),
        engine="reference-node",
        document_ids=[str(item) for item in document_ids],
    )
    session.add(run)
    session.flush()
    reservation = billing_service.reserve_task_or_raise(
        session,
        org_id=exam.org_id,
        task_type="question_recognition",
        resource_id=str(run.id),
        idempotency_key=f"{exam.org_id}:question_recognition:{run.id}:v1",
        expected_calls=max(1, len(document_ids)),
    )
    if reservation:
        run.raw_output = {"billing_reservation_id": str(reservation.id)}
        session.add(run)
    session.commit()
    session.refresh(run)
    process_question_recognition_run.send(str(run.id))
    return _question_run_public(session, run)


@router.post(
    "/{exam_id}/question-recognition-runs/from-marking",
    response_model=QuestionRecognitionRunPublic,
)
def import_marking_recognition_run(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    import_in: MarkingRecognitionImport,
) -> QuestionRecognitionRunPublic:
    _owned_exam(session, current_user, exam_id, require_write=True)
    document_ids = list(dict.fromkeys(import_in.document_ids))
    rows = session.exec(
        select(ExamDocument, StoredFile)
        .join(StoredFile, ExamDocument.stored_file_id == StoredFile.id)
        .where(
            ExamDocument.exam_id == exam_id,
            col(ExamDocument.id).in_(document_ids),
        )
    ).all()
    by_id = {document.id: (document, stored_file) for document, stored_file in rows}
    if len(by_id) != len(document_ids):
        raise HTTPException(status_code=422, detail="部分试卷文件不存在")
    documents = [by_id[document_id] for document_id in document_ids]
    if any(
        document.document_type != ExamDocumentType.BLANK_EXAM
        for document, _stored_file in documents
    ):
        raise HTTPException(status_code=422, detail="只能导入题目源页面的标定结果")

    expected_page_ids: set[str] = set()
    for document, stored_file in documents:
        page_count = (
            get_pdf_page_count(get_stored_file_path(stored_file))
            if stored_file.content_type == "application/pdf"
            else 1
        )
        expected_page_ids.update(
            f"{document.id}:page:{page_number}"
            for page_number in range(1, page_count + 1)
        )
    covered_page_ids = set(import_in.covered_page_ids)
    if covered_page_ids != expected_page_ids:
        missing = sorted(expected_page_ids - covered_page_ids)
        extra = sorted(covered_page_ids - expected_page_ids)
        detail = "标定结果尚未覆盖全部卷面页"
        if extra:
            detail = "标定结果包含不属于所选试卷的页面"
        raise HTTPException(
            status_code=422,
            detail=f"{detail}（缺少 {len(missing)} 页，多出 {len(extra)} 页）",
        )

    allowed_block_fields = {
        "id",
        "pageId",
        "label",
        "questionNumber",
        "xmin",
        "ymin",
        "xmax",
        "ymax",
    }
    blocks = []
    block_ids: set[str] = set()
    for raw_block in import_in.blocks:
        block = {
            key: raw_block.get(key) for key in allowed_block_fields if key in raw_block
        }
        block_id = str(block.get("id") or "")
        page_id = str(block.get("pageId") or "")
        if not block_id or page_id not in expected_page_ids or block_id in block_ids:
            raise HTTPException(status_code=422, detail="题块标识或所属页面无效")
        try:
            xmin = float(block.get("xmin", 0))
            ymin = float(block.get("ymin", 0))
            xmax = float(block.get("xmax", 1000))
            ymax = float(block.get("ymax", 1000))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="题块坐标无效") from exc
        if not (0 <= xmin < xmax <= 1000 and 0 <= ymin < ymax <= 1000):
            raise HTTPException(status_code=422, detail="题块坐标超出页面范围")
        block.update({"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax})
        blocks.append(block)
        block_ids.add(block_id)

    results = []
    allowed_result_fields = {
        "id",
        "blockId",
        "sourceBlockIds",
        "sourceLabel",
        "questionNumber",
        "question",
        "studentAnswer",
        "answerType",
        "confidence",
        "notes",
        "error",
        "elapsedMs",
    }
    for raw_result in import_in.results:
        result = {
            key: raw_result.get(key)
            for key in allowed_result_fields
            if key in raw_result
        }
        source_ids = result.get("sourceBlockIds") or [
            result.get("blockId") or result.get("id")
        ]
        if not source_ids or any(
            str(source_id) not in block_ids for source_id in source_ids
        ):
            raise HTTPException(status_code=422, detail="识别结果引用了不存在的题块")
        result["sourceBlockIds"] = [str(source_id) for source_id in source_ids]
        results.append(result)
    if not results:
        raise HTTPException(status_code=422, detail="没有可导入的题目识别结果")

    now = get_datetime_utc()
    run = QuestionRecognitionRun(
        exam_id=exam_id,
        created_by_id=current_user.id,
        provider="marking-result",
        model="reused",
        engine="reference-node-marking-import",
        status=WorkflowRunStatus.RUNNING,
        document_ids=[str(document_id) for document_id in document_ids],
        started_at=now,
    )
    session.add(run)
    session.flush()
    persist_question_recognition_payload(
        session=session,
        run=run,
        payload={
            "results": results,
            "blocks": blocks,
            "layouts": import_in.layouts,
            "timing": import_in.timing,
            "source": "marking-result",
        },
        requested_ids=document_ids,
        started=time.perf_counter(),
    )
    session.commit()
    session.refresh(run)
    return _question_run_public(session, run)


@router.get(
    "/{exam_id}/question-recognition-runs",
    response_model=QuestionRecognitionRunsPublic,
)
def list_question_recognition_runs(
    session: SessionDep, current_user: CurrentUser, exam_id: uuid.UUID
) -> QuestionRecognitionRunsPublic:
    _owned_exam(session, current_user, exam_id)
    runs = list(
        session.exec(
            select(QuestionRecognitionRun)
            .where(QuestionRecognitionRun.exam_id == exam_id)
            .order_by(col(QuestionRecognitionRun.created_at).desc())
        ).all()
    )
    return QuestionRecognitionRunsPublic(
        data=[_question_run_public(session, run) for run in runs], count=len(runs)
    )


@router.get(
    "/{exam_id}/question-recognition-runs/{run_id}",
    response_model=QuestionRecognitionRunPublic,
)
def get_question_recognition_run(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    run_id: uuid.UUID,
) -> QuestionRecognitionRunPublic:
    return _question_run_public(
        session, _question_run(session, current_user, exam_id, run_id)
    )


@router.get(
    "/{exam_id}/question-recognition-runs/{run_id}/items",
    response_model=list[QuestionRecognitionItemPublic],
)
def list_question_recognition_items(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    run_id: uuid.UUID,
) -> list[QuestionRecognitionItemPublic]:
    _question_run(session, current_user, exam_id, run_id)
    items = list(
        session.exec(
            select(QuestionRecognitionItem).where(
                QuestionRecognitionItem.run_id == run_id
            )
        ).all()
    )
    items.sort(key=lambda item: _natural_key(item.question_key))
    return [QuestionRecognitionItemPublic.model_validate(item) for item in items]


@router.patch(
    "/{exam_id}/question-recognition-items/{item_id}",
    response_model=QuestionRecognitionItemPublic,
)
def update_question_recognition_item(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    item_id: uuid.UUID,
    item_in: QuestionRecognitionItemUpdate,
) -> QuestionRecognitionItemPublic:
    item = session.get(QuestionRecognitionItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="题目识别项不存在")
    run = _question_run(session, current_user, exam_id, item.run_id, require_write=True)
    if run.confirmed_at:
        raise HTTPException(status_code=409, detail="识别任务已确认，不能再修改")
    update = item_in.model_dump(exclude_unset=True)
    if "region_ids" in update and update["region_ids"] is not None:
        region_ids = update["region_ids"]
        regions = list(
            session.exec(
                select(ExamRegion).where(
                    ExamRegion.exam_id == exam_id,
                    col(ExamRegion.id).in_(region_ids),
                )
            ).all()
        )
        if len(regions) != len(set(region_ids)):
            raise HTTPException(status_code=422, detail="存在不属于当前考试的题目区域")
        update["region_ids"] = [str(region_id) for region_id in region_ids]
    if update.get("status") == QuestionRecognitionItemStatus.CONFIRMED:
        raise HTTPException(status_code=422, detail="请通过任务确认接口确认题目")
    item.sqlmodel_update(update)
    item.updated_at = get_datetime_utc()
    session.add(item)
    session.commit()
    session.refresh(item)
    return QuestionRecognitionItemPublic.model_validate(item)


def _create_region_from_snapshot(
    *, session: SessionDep, exam_id: uuid.UUID, snapshot: dict
) -> ExamRegion:
    try:
        document_id = uuid.UUID(str(snapshot["exam_document_id"]))
        page_number = int(snapshot["page_number"])
        x = float(snapshot["x"])
        y = float(snapshot["y"])
        width = float(snapshot["width"])
        height = float(snapshot["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="识别区域坐标无效") from exc
    document = session.get(ExamDocument, document_id)
    if not document or document.exam_id != exam_id:
        raise HTTPException(status_code=422, detail="识别区域引用了无效试卷文件")
    if (
        width <= 0
        or height <= 0
        or x < 0
        or y < 0
        or x + width > 1.001
        or y + height > 1.001
    ):
        raise HTTPException(status_code=422, detail="识别区域超出页面范围")
    region = ExamRegion(
        exam_id=exam_id,
        exam_document_id=document_id,
        label=str(snapshot.get("label") or "题目")[:100],
        region_type=ExamRegionType.QUESTION,
        page_number=page_number,
        x=x,
        y=y,
        width=min(width, 1 - x),
        height=min(height, 1 - y),
    )
    session.add(region)
    session.flush()
    return region


@router.post(
    "/{exam_id}/question-recognition-runs/{run_id}/confirm",
    response_model=QuestionRecognitionRunPublic,
)
def confirm_question_recognition_run(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    run_id: uuid.UUID,
) -> QuestionRecognitionRunPublic:
    run = _question_run(session, current_user, exam_id, run_id, require_write=True)
    if run.confirmed_at:
        return _question_run_public(session, run)
    if run.status not in {
        WorkflowRunStatus.COMPLETED,
        WorkflowRunStatus.COMPLETED_WITH_ERRORS,
    }:
        raise HTTPException(status_code=409, detail="识别任务尚未完成")
    items = list(
        session.exec(
            select(QuestionRecognitionItem)
            .where(QuestionRecognitionItem.run_id == run.id)
            .order_by(QuestionRecognitionItem.created_at)
        ).all()
    )
    included = [
        item for item in items if item.status != QuestionRecognitionItemStatus.EXCLUDED
    ]
    if not included:
        raise HTTPException(status_code=409, detail="没有可确认的题目")
    keys = [item.question_key.strip() for item in included]
    if any(not item.question_text.strip() for item in included):
        raise HTTPException(status_code=409, detail="所有保留题目都必须有题干")
    if len(keys) != len(set(keys)):
        raise HTTPException(status_code=409, detail="题目标识重复，请修订或排除重复项")

    try:
        now = get_datetime_utc()
        for item in included:
            question = session.exec(
                select(ExamQuestion).where(
                    ExamQuestion.exam_id == exam_id,
                    ExamQuestion.question_key == item.question_key.strip(),
                )
            ).first()
            if not question:
                question = ExamQuestion(
                    exam_id=exam_id,
                    question_key=item.question_key.strip(),
                    label=item.label.strip(),
                    question_text=item.question_text.strip(),
                    question_type=item.question_type,
                    recognition_confidence=item.confidence,
                )
            question.label = item.label.strip()
            question.question_text = item.question_text.strip()
            question.question_type = item.question_type
            question.knowledge_point = item.knowledge_point
            question.difficulty = item.difficulty
            question.recognition_confidence = item.confidence
            question.status = ExamQuestionStatus.CONFIRMED
            question.confirmed_by_id = current_user.id
            question.confirmed_at = now
            question.updated_at = now
            session.add(question)
            session.flush()

            region_ids = [uuid.UUID(value) for value in item.region_ids]
            if not region_ids:
                region_ids = [
                    _create_region_from_snapshot(
                        session=session, exam_id=exam_id, snapshot=snapshot
                    ).id
                    for snapshot in item.region_snapshots
                ]
            regions = list(
                session.exec(
                    select(ExamRegion).where(
                        ExamRegion.exam_id == exam_id,
                        col(ExamRegion.id).in_(region_ids),
                    )
                ).all()
            )
            if not regions or len(regions) != len(set(region_ids)):
                raise HTTPException(
                    status_code=409, detail=f"{item.label} 缺少有效题目区域"
                )
            old_links = list(
                session.exec(
                    select(ExamQuestionRegion).where(
                        ExamQuestionRegion.question_id == question.id
                    )
                ).all()
            )
            for link in old_links:
                session.delete(link)
            session.flush()
            for sequence, region_id in enumerate(region_ids, start=1):
                occupied = session.exec(
                    select(ExamQuestionRegion).where(
                        ExamQuestionRegion.exam_region_id == region_id
                    )
                ).first()
                if occupied and occupied.question_id != question.id:
                    raise HTTPException(
                        status_code=409, detail=f"{item.label} 的区域已属于其他题目"
                    )
                snapshot = (
                    item.region_snapshots[sequence - 1]
                    if sequence <= len(item.region_snapshots)
                    else {}
                )
                role_value = str(snapshot.get("role") or "primary")
                role = (
                    QuestionRegionRole.CONTINUATION
                    if role_value == "continuation"
                    else QuestionRegionRole.PRIMARY
                )
                session.add(
                    ExamQuestionRegion(
                        question_id=question.id,
                        exam_region_id=region_id,
                        sequence=sequence,
                        role=role,
                    )
                )
            item.status = QuestionRecognitionItemStatus.CONFIRMED
            item.confirmed_question_id = question.id
            item.updated_at = now
            session.add(item)
        run.confirmed_at = now
        session.add(run)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="题目标识或区域关联发生冲突"
        ) from exc
    session.refresh(run)
    return _question_run_public(session, run)


@router.post(
    "/{exam_id}/answer-preparation-runs",
    response_model=AnswerPreparationRunPublic,
)
def create_answer_preparation_run(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    run_in: AnswerPreparationRunCreate,
) -> AnswerPreparationRunPublic:
    exam = _owned_exam(session, current_user, exam_id, require_write=True)
    billing_service.require_model_entitlement(session, exam.org_id)
    confirmed_count = session.exec(
        select(func.count())
        .select_from(ExamQuestion)
        .where(
            ExamQuestion.exam_id == exam_id,
            ExamQuestion.status == ExamQuestionStatus.CONFIRMED,
        )
    ).one()
    if not confirmed_count:
        raise HTTPException(status_code=409, detail="请先识别并确认题目")
    document_ids = list(dict.fromkeys(run_in.document_ids))
    if run_in.source_type == AnswerPreparationSource.DOCUMENT:
        if not document_ids:
            raise HTTPException(status_code=422, detail="请选择至少一个答案文件")
        documents = list(
            session.exec(
                select(ExamDocument).where(
                    ExamDocument.exam_id == exam_id,
                    col(ExamDocument.id).in_(document_ids),
                )
            ).all()
        )
        if len(documents) != len(document_ids):
            raise HTTPException(status_code=422, detail="部分答案文件不存在")
        if any(item.document_type != ExamDocumentType.ANSWER_KEY for item in documents):
            raise HTTPException(status_code=422, detail="答案文档模式只能选择答案文件")
    elif document_ids:
        raise HTTPException(status_code=422, detail="模型解题模式不需要答案文件")
    defaults = get_grading_defaults(session, exam.org_id)
    answer_provider, answer_model = get_school_model_target(
        session,
        org_id=exam.org_id,
        scope=SchoolModelScope.REFERENCE_ANSWER,
        fallback_provider=str(defaults["grading_provider"]),
        fallback_model=str(defaults["grading_model"]),
    )
    run = AnswerPreparationRun(
        exam_id=exam_id,
        created_by_id=current_user.id,
        source_type=run_in.source_type,
        provider=(
            str(defaults["recognition_provider"])
            if run_in.source_type == AnswerPreparationSource.DOCUMENT
            else answer_provider
        ),
        model=(
            str(defaults["recognition_model"])
            if run_in.source_type == AnswerPreparationSource.DOCUMENT
            else answer_model
        ),
        document_ids=[str(item) for item in document_ids],
    )
    session.add(run)
    session.flush()
    reservation = billing_service.reserve_task_or_raise(
        session,
        org_id=exam.org_id,
        task_type="answer_preparation",
        resource_id=str(run.id),
        idempotency_key=f"{exam.org_id}:answer_preparation:{run.id}:v1",
        expected_calls=max(1, confirmed_count),
    )
    if reservation:
        run.raw_output = {"billing_reservation_id": str(reservation.id)}
        session.add(run)
    session.commit()
    session.refresh(run)
    process_answer_preparation_run.send(str(run.id))
    return _answer_run_public(session, run)


@router.get(
    "/{exam_id}/answer-preparation-runs",
    response_model=AnswerPreparationRunsPublic,
)
def list_answer_preparation_runs(
    session: SessionDep, current_user: CurrentUser, exam_id: uuid.UUID
) -> AnswerPreparationRunsPublic:
    _owned_exam(session, current_user, exam_id)
    runs = list(
        session.exec(
            select(AnswerPreparationRun)
            .where(AnswerPreparationRun.exam_id == exam_id)
            .order_by(col(AnswerPreparationRun.created_at).desc())
        ).all()
    )
    return AnswerPreparationRunsPublic(
        data=[_answer_run_public(session, run) for run in runs], count=len(runs)
    )


@router.get(
    "/{exam_id}/answer-preparation-runs/{run_id}",
    response_model=AnswerPreparationRunPublic,
)
def get_answer_preparation_run(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    run_id: uuid.UUID,
) -> AnswerPreparationRunPublic:
    return _answer_run_public(
        session, _answer_run(session, current_user, exam_id, run_id)
    )


@router.get(
    "/{exam_id}/answer-preparation-runs/{run_id}/items",
    response_model=list[AnswerPreparationItemPublic],
)
def list_answer_preparation_items(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    run_id: uuid.UUID,
) -> list[AnswerPreparationItemPublic]:
    _answer_run(session, current_user, exam_id, run_id)
    items = list(
        session.exec(
            select(AnswerPreparationItem).where(AnswerPreparationItem.run_id == run_id)
        ).all()
    )
    question_keys = {
        question.id: question.question_key
        for question in session.exec(
            select(ExamQuestion).where(ExamQuestion.exam_id == exam_id)
        ).all()
    }
    items.sort(
        key=lambda item: (
            item.question_id is None,
            _natural_key(question_keys.get(item.question_id)),
            item.created_at,
        )
    )
    return [AnswerPreparationItemPublic.model_validate(item) for item in items]


@router.patch(
    "/{exam_id}/answer-preparation-items/{item_id}",
    response_model=AnswerPreparationItemPublic,
)
def update_answer_preparation_item(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    item_id: uuid.UUID,
    item_in: AnswerPreparationItemUpdate,
) -> AnswerPreparationItemPublic:
    item = session.get(AnswerPreparationItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="答案准备项不存在")
    run = _answer_run(session, current_user, exam_id, item.run_id, require_write=True)
    if run.confirmed_at or item.revision_id:
        raise HTTPException(status_code=409, detail="答案已确认，不能修改历史快照")
    update = item_in.model_dump(exclude_unset=True)
    question_id = update.get("question_id")
    if question_id:
        question = session.get(ExamQuestion, question_id)
        if (
            not question
            or question.exam_id != exam_id
            or question.status != ExamQuestionStatus.CONFIRMED
        ):
            raise HTTPException(status_code=422, detail="目标题目无效或尚未确认")
        item.source_question_key = question.question_key
    if update.get("status") in {
        AnswerPreparationItemStatus.CONFIRMED,
        AnswerPreparationItemStatus.QUEUED,
        AnswerPreparationItemStatus.RUNNING,
    }:
        raise HTTPException(status_code=422, detail="不能手工设置该答案状态")
    item.sqlmodel_update(update)
    item.updated_at = get_datetime_utc()
    session.add(item)
    session.commit()
    session.refresh(item)
    return AnswerPreparationItemPublic.model_validate(item)


def _validate_answer_item(item: AnswerPreparationItem) -> None:
    if not item.answer_text.strip():
        raise HTTPException(status_code=409, detail="标准答案不能为空")
    if not item.rubric_text or not item.rubric_text.strip():
        raise HTTPException(status_code=409, detail="每道题都必须确认总体评分规则")
    if not item.scoring_points:
        raise HTTPException(status_code=409, detail="每道题都必须确认至少一个评分点")
    total = Decimal("0")
    for index, point in enumerate(item.scoring_points, start=1):
        if (
            not isinstance(point, dict)
            or not str(point.get("description") or "").strip()
        ):
            raise HTTPException(status_code=409, detail=f"第 {index} 个评分点不完整")
        try:
            total += Decimal(str(point.get("points")))
        except Exception as exc:
            raise HTTPException(
                status_code=409, detail=f"第 {index} 个评分点分值无效"
            ) from exc
    if abs(total - item.max_score) > Decimal("0.01"):
        raise HTTPException(
            status_code=409,
            detail=f"评分点合计 {total} 与满分 {item.max_score} 不一致",
        )


def _revision_hash(*, question: ExamQuestion, item: AnswerPreparationItem) -> str:
    payload = {
        "question_key": question.question_key,
        "question_text": question.question_text,
        "question_type": question.question_type,
        "answer_text": item.answer_text,
        "max_score": str(item.max_score),
        "rubric_text": item.rubric_text,
        "scoring_points": item.scoring_points,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@router.post(
    "/{exam_id}/answer-preparation-runs/{run_id}/confirm",
    response_model=AnswerPreparationRunPublic,
)
def confirm_answer_preparation_run(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    run_id: uuid.UUID,
) -> AnswerPreparationRunPublic:
    run = _answer_run(session, current_user, exam_id, run_id, require_write=True)
    if run.confirmed_at:
        return _answer_run_public(session, run)
    if run.status not in {
        WorkflowRunStatus.COMPLETED,
        WorkflowRunStatus.COMPLETED_WITH_ERRORS,
    }:
        raise HTTPException(status_code=409, detail="答案准备任务尚未完成")
    questions = list(
        session.exec(
            select(ExamQuestion).where(
                ExamQuestion.exam_id == exam_id,
                ExamQuestion.status == ExamQuestionStatus.CONFIRMED,
            )
        ).all()
    )
    items = list(
        session.exec(
            select(AnswerPreparationItem).where(AnswerPreparationItem.run_id == run.id)
        ).all()
    )
    selected: dict[uuid.UUID, AnswerPreparationItem] = {}
    for item in items:
        if not item.question_id:
            continue
        if item.status != AnswerPreparationItemStatus.MATCHED:
            raise HTTPException(
                status_code=409,
                detail="所有已匹配题目都必须先处理冲突并设为已匹配",
            )
        if item.question_id in selected:
            raise HTTPException(status_code=409, detail="同一道题存在多个答案候选")
        selected[item.question_id] = item
    missing = [
        question.question_key for question in questions if question.id not in selected
    ]
    if missing:
        raise HTTPException(
            status_code=409,
            detail=f"以下题目缺少已确认答案：{', '.join(missing[:10])}",
        )

    now = get_datetime_utc()
    try:
        for question in questions:
            item = selected[question.id]
            _validate_answer_item(item)
            source_provider = str(item.raw_result.get("_used_provider") or run.provider)
            source_model = str(item.raw_result.get("_used_model") or run.model)
            answer = session.exec(
                select(StandardAnswer).where(
                    StandardAnswer.exam_id == exam_id,
                    StandardAnswer.question_id == question.id,
                )
            ).first()
            if not answer:
                link = session.exec(
                    select(ExamQuestionRegion)
                    .where(ExamQuestionRegion.question_id == question.id)
                    .order_by(ExamQuestionRegion.sequence)
                ).first()
                if not link:
                    raise HTTPException(
                        status_code=409,
                        detail=f"题目 {question.question_key} 没有题目区域",
                    )
                answer = StandardAnswer(
                    exam_id=exam_id,
                    exam_region_id=link.exam_region_id,
                    question_id=question.id,
                    answer_text=item.answer_text,
                    max_score=float(item.max_score),
                    rubric_text=item.rubric_text,
                    scoring_points=item.scoring_points,
                    status=StandardAnswerStatus.DRAFT,
                    question_text=question.question_text,
                    question_type=question.question_type,
                    source_provider=source_provider,
                    source_model=source_model,
                    generation_confidence=(
                        float(item.confidence) if item.confidence is not None else None
                    ),
                    validation_report={"human_confirmed": True},
                )
                session.add(answer)
                session.flush()
            next_number = (
                session.exec(
                    select(func.max(StandardAnswerRevision.revision_number)).where(
                        StandardAnswerRevision.standard_answer_id == answer.id
                    )
                ).one()
                or 0
            ) + 1
            revision = StandardAnswerRevision(
                standard_answer_id=answer.id,
                question_id=question.id,
                revision_number=next_number,
                question_key=question.question_key,
                question_text=question.question_text,
                question_type=question.question_type,
                answer_text=item.answer_text.strip(),
                max_score=item.max_score,
                rubric_text=item.rubric_text.strip() if item.rubric_text else None,
                scoring_points=item.scoring_points,
                source_provider=source_provider,
                source_model=source_model,
                generation_confidence=item.confidence,
                content_hash=_revision_hash(question=question, item=item),
                status=StandardAnswerRevisionStatus.DRAFT,
                created_by_id=current_user.id,
                preparation_item_id=item.id,
            )
            session.add(revision)
            session.flush()
            item.status = AnswerPreparationItemStatus.CONFIRMED
            item.revision_id = revision.id
            item.updated_at = now
            session.add(item)
        run.confirmed_at = now
        session.add(run)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="创建答案修订时发生版本冲突"
        ) from exc
    session.refresh(run)
    return _answer_run_public(session, run)


@router.get(
    "/{exam_id}/standard-answers/revisions",
    response_model=StandardAnswerRevisionsPublic,
)
def list_standard_answer_revisions(
    session: SessionDep, current_user: CurrentUser, exam_id: uuid.UUID
) -> StandardAnswerRevisionsPublic:
    _owned_exam(session, current_user, exam_id)
    revisions = list(
        session.exec(
            select(StandardAnswerRevision)
            .join(
                StandardAnswer,
                StandardAnswerRevision.standard_answer_id == StandardAnswer.id,
            )
            .where(StandardAnswer.exam_id == exam_id)
            .order_by(
                StandardAnswerRevision.question_key,
                col(StandardAnswerRevision.revision_number).desc(),
            )
        ).all()
    )
    revisions.sort(
        key=lambda item: (_natural_key(item.question_key), -item.revision_number)
    )
    return StandardAnswerRevisionsPublic(
        data=[StandardAnswerRevisionPublic.model_validate(item) for item in revisions],
        count=len(revisions),
    )


@router.post(
    "/{exam_id}/standard-answers/publish",
    response_model=StandardAnswerRevisionsPublic,
)
def publish_standard_answer_revisions(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    publish_in: StandardAnswerPublishRequest,
) -> StandardAnswerRevisionsPublic:
    _owned_exam(session, current_user, exam_id, require_write=True)
    statement = (
        select(StandardAnswerRevision, StandardAnswer)
        .join(
            StandardAnswer,
            StandardAnswerRevision.standard_answer_id == StandardAnswer.id,
        )
        .where(StandardAnswer.exam_id == exam_id)
    )
    if publish_in.revision_ids:
        statement = statement.where(
            col(StandardAnswerRevision.id).in_(publish_in.revision_ids)
        )
    else:
        statement = statement.where(
            StandardAnswerRevision.status == StandardAnswerRevisionStatus.DRAFT
        )
    rows = list(session.exec(statement).all())
    if publish_in.revision_ids and len(rows) != len(set(publish_in.revision_ids)):
        raise HTTPException(status_code=422, detail="部分答案修订不存在")
    if not rows:
        raise HTTPException(status_code=409, detail="没有可发布的答案修订")

    latest_by_question: dict[
        uuid.UUID, tuple[StandardAnswerRevision, StandardAnswer]
    ] = {}
    for revision, answer in rows:
        current = latest_by_question.get(revision.question_id)
        if not current or revision.revision_number > current[0].revision_number:
            latest_by_question[revision.question_id] = (revision, answer)
    confirmed_question_ids = set(
        session.exec(
            select(ExamQuestion.id).where(
                ExamQuestion.exam_id == exam_id,
                ExamQuestion.status == ExamQuestionStatus.CONFIRMED,
            )
        ).all()
    )
    already_published_ids = set(
        session.exec(
            select(StandardAnswer.question_id).where(
                StandardAnswer.exam_id == exam_id,
                StandardAnswer.current_revision_id.is_not(None),
                StandardAnswer.question_id.is_not(None),
            )
        ).all()
    )
    uncovered = confirmed_question_ids - set(latest_by_question) - already_published_ids
    if uncovered:
        raise HTTPException(status_code=409, detail="仍有已确认题目没有可发布答案")

    now = get_datetime_utc()
    published: list[StandardAnswerRevision] = []
    for revision, answer in latest_by_question.values():
        if revision.status != StandardAnswerRevisionStatus.PUBLISHED:
            revision.status = StandardAnswerRevisionStatus.PUBLISHED
            revision.published_by_id = current_user.id
            revision.published_at = now
            session.add(revision)
        # 无论 revision 此前是否已发布，都把标准答案同步到本次选定的版本——
        # 否则重复发布（或指定旧版本重发）不会修正 current_revision_id。
        answer.current_revision_id = revision.id
        answer.answer_text = revision.answer_text
        answer.max_score = float(revision.max_score)
        answer.rubric_text = revision.rubric_text
        answer.scoring_points = revision.scoring_points
        answer.status = StandardAnswerStatus.READY
        answer.version = revision.revision_number
        answer.source_provider = revision.source_provider
        answer.source_model = revision.source_model
        answer.generation_confidence = (
            float(revision.generation_confidence)
            if revision.generation_confidence is not None
            else None
        )
        answer.answer_hash = revision.content_hash
        answer.question_text = revision.question_text
        answer.question_type = revision.question_type
        answer.rubric_config = {
            "schema_version": "confirmed-answer-revision-v1",
            "scoring_points": revision.scoring_points,
        }
        answer.validation_report = {
            "valid": True,
            "human_confirmed": True,
            "published": True,
        }
        answer.published_at = now
        answer.published_by_id = current_user.id
        answer.updated_at = now
        session.add(answer)
        published.append(revision)
    session.commit()
    for revision in published:
        session.refresh(revision)
    return StandardAnswerRevisionsPublic(
        data=[StandardAnswerRevisionPublic.model_validate(item) for item in published],
        count=len(published),
    )
