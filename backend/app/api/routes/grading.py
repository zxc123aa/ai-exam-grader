import uuid
from math import ceil
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_teacher_user,
)
from app.models import (
    Exam,
    ExamQuestion,
    ExamQuestionStatus,
    ExamRegion,
    GradingAssignment,
    GradingAuditEvent,
    GradingAuditEventPublic,
    GradingItem,
    GradingItemStatus,
    GradingReviewItem,
    GradingRun,
    GradingRunCreate,
    GradingRunPublic,
    GradingRunsPublic,
    GradingRunStatus,
    ProcessingTask,
    ProcessingTaskPublic,
    RecognitionItemPublic,
    RecognitionItemUpdate,
    RecognitionRunCreate,
    StandardAnswer,
    StandardAnswerRevision,
    StandardAnswerRevisionStatus,
    StudentSubmission,
    SubmissionAnnotation,
    get_datetime_utc,
)
from app.services.grading_workflow import execute_grading_run, publish_standard_answers
from app.services.org_scope import (
    can_see_exam,
    can_write_exam,
    exam_classes_with_submissions,
    restricted_assigned_classes,
    submission_class_filter,
)
from app.services.recognition_workflow import execute_recognition_run
from app.services.rubric_workflow import execute_rubric_generation
from app.services.system_config import get_grading_defaults

router = APIRouter(
    prefix="/grading",
    tags=["grading"],
    dependencies=[Depends(get_current_teacher_user)],
)


def owned_exam(
    session: SessionDep,
    user: CurrentUser,
    exam_id: uuid.UUID,
    *,
    require_write: bool = False,
) -> Exam:
    exam = session.get(Exam, exam_id)
    if not exam or not can_see_exam(session, user, exam):
        raise HTTPException(status_code=404, detail="考试不存在")
    if require_write and not can_write_exam(user, exam):
        raise HTTPException(status_code=403, detail="无权修改该考试")
    return exam


def owned_run(session: SessionDep, user: CurrentUser, run_id: uuid.UUID) -> GradingRun:
    run = session.get(GradingRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="批改批次不存在")
    owned_exam(session, user, run.exam_id)
    return run


def recognition_item_public(item: GradingItem, region: Any) -> RecognitionItemPublic:
    extraction = item.extraction_result or {}
    return RecognitionItemPublic(
        item_id=item.id,
        submission_id=item.submission_id,
        exam_region_id=item.exam_region_id,
        label=region.label,
        status=item.status,
        question_text=extraction.get("question_text"),
        student_answer=extraction.get("student_answer"),
        final_answer=extraction.get("final_answer"),
        confidence=extraction.get("confidence"),
        notes=extraction.get("notes", []),
        printed_question_marks=extraction.get("printed_question_marks", []),
        answer_entries=extraction.get("answer_entries", []),
        unassigned_evidence=extraction.get("unassigned_evidence", []),
        grading_answer=extraction.get("grading_answer"),
        grading_eligible=bool(extraction.get("grading_eligible", False)),
        answer_verification=extraction.get("answer_verification", {}),
        error_message=item.error_message,
    )


@router.post("/recognition/runs", response_model=GradingRunPublic)
def create_recognition_run(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    run_in: RecognitionRunCreate,
    background_tasks: BackgroundTasks,
) -> Any:
    owned_exam(session, current_user, run_in.exam_id, require_write=True)
    submission = session.get(StudentSubmission, run_in.submission_id)
    if not submission or submission.exam_id != run_in.exam_id:
        raise HTTPException(status_code=404, detail="答卷不存在")
    run = GradingRun(
        exam_id=run_in.exam_id,
        created_by_id=current_user.id,
        provider=run_in.provider,
        model=run_in.model,
        fallback_models=[],
        config_snapshot={
            "pipeline": "recognition_preview",
            "submission_id": str(run_in.submission_id),
            "max_concurrency": run_in.max_concurrency,
            "verification_mode": run_in.verification_mode,
            # A recognition preview is the source run itself.  The optional
            # `recognition_run_id` belongs to GradingRunCreate (the later
            # scoring run), not RecognitionRunCreate.  Referencing it here
            # made every preview creation fail with AttributeError / HTTP 500.
            "recognition_run_id": None,
            "recognition_confirmed": False,
        },
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    background_tasks.add_task(execute_recognition_run, str(run.id))
    return run_public(session, run)


@router.get(
    "/recognition/runs/{run_id}/items", response_model=list[RecognitionItemPublic]
)
def read_recognition_items(
    session: SessionDep, current_user: CurrentUser, run_id: uuid.UUID
) -> Any:
    run = owned_run(session, current_user, run_id)
    rows = session.exec(
        select(GradingItem, ExamRegion)
        .join(ExamRegion, GradingItem.exam_region_id == ExamRegion.id)
        .where(GradingItem.grading_run_id == run.id)
        .order_by(ExamRegion.page_number, ExamRegion.y)
    ).all()
    return [recognition_item_public(item, region) for item, region in rows]


@router.patch("/recognition/items/{item_id}", response_model=RecognitionItemPublic)
def update_recognition_item(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    item_id: uuid.UUID,
    item_in: RecognitionItemUpdate,
) -> Any:
    item = session.get(GradingItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="识别题块不存在")
    run = owned_run(session, current_user, item.grading_run_id)
    if run.config_snapshot.get("recognition_confirmed"):
        raise HTTPException(status_code=409, detail="识别结果已确认，不能直接修改")
    region = session.get(ExamRegion, item.exam_region_id)
    extraction = dict(item.extraction_result or {})
    changes = item_in.model_dump(exclude_unset=True)
    approve_for_grading = changes.pop("approve_for_grading", None)
    approval_source = changes.pop("approval_source", None)
    previous_answer = str(extraction.get("student_answer") or "")
    extraction.update(changes)
    if "student_answer" in changes:
        revised_answer = str(changes.get("student_answer") or "").strip()
        extraction["student_answer"] = revised_answer
        extraction["final_answer"] = revised_answer
        extraction["grading_answer"] = revised_answer
        extraction["grading_eligible"] = False
        extraction["answer_entries"] = []
        extraction["answer_structure"] = {
            "version": "teacher_draft_v1",
            "slotCount": 0,
            "assignedCount": 0,
            "missingCount": 0,
            "unassignedCount": len(extraction.get("unassigned_evidence") or []),
            "gradingEligible": False,
            "verificationStatus": "teacher_draft",
            "coordinatePrecision": "teacher_confirmed_text",
        }
    if approve_for_grading is not None:
        revised_answer = str(extraction.get("student_answer") or "").strip()
        if approve_for_grading and not revised_answer:
            raise HTTPException(status_code=422, detail="批准判分前必须填写学生答案")
        extraction["grading_eligible"] = bool(approve_for_grading)
        if approve_for_grading:
            approved_at = get_datetime_utc().isoformat()
            source = approval_source or "teacher_edit"
            extraction["grading_answer"] = revised_answer
            extraction["final_answer"] = revised_answer
            extraction["answer_entries"] = [
                {
                    "slotId": "teacher_confirmed_full_answer",
                    "subquestion": None,
                    "slotIndex": 1,
                    "text": revised_answer,
                    "status": "assigned",
                    "confidence": 1,
                    "evidenceBounds": [],
                    "coordinatePrecision": "teacher_confirmed_text",
                    "expectedKind": "teacher_override",
                }
            ]
            extraction["answer_structure"] = {
                "version": "teacher_confirmed_v1",
                "slotCount": 1,
                "assignedCount": 1,
                "missingCount": 0,
                "unassignedCount": len(
                    extraction.get("unassigned_evidence") or []
                ),
                "gradingEligible": True,
                "verificationStatus": "teacher_confirmed",
                "coordinatePrecision": "teacher_confirmed_text",
            }
            extraction["answer_verification"] = {
                **dict(extraction.get("answer_verification") or {}),
                "status": "teacher_confirmed",
                "approvedBy": str(current_user.id),
                "approvedAt": approved_at,
                "approvalSource": source,
                "previousStudentAnswer": previous_answer,
            }
            edits = list((run.config_snapshot or {}).get("recognition_edits", []))
            edits.append(
                {
                    "item_id": str(item.id),
                    "label": region.label if region else None,
                    "approved_by": str(current_user.id),
                    "approved_at": approved_at,
                    "approval_source": source,
                    "previous_student_answer": previous_answer,
                    "student_answer": revised_answer,
                }
            )
            run.config_snapshot = {
                **(run.config_snapshot or {}),
                "recognition_edits": edits[-200:],
            }
            session.add(run)
    item.extraction_result = extraction
    item.status = GradingItemStatus.COMPLETED
    session.add(item)
    session.commit()
    session.refresh(item)
    return recognition_item_public(item, region)


@router.post("/recognition/runs/{run_id}/confirm", response_model=GradingRunPublic)
def confirm_recognition(
    *, session: SessionDep, current_user: CurrentUser, run_id: uuid.UUID
) -> Any:
    run = owned_run(session, current_user, run_id)
    items = list(
        session.exec(
            select(GradingItem).where(GradingItem.grading_run_id == run.id)
        ).all()
    )
    if (
        run.status
        not in {GradingRunStatus.COMPLETED, GradingRunStatus.COMPLETED_WITH_ERRORS}
        or not items
        or any(item.status != GradingItemStatus.COMPLETED for item in items)
    ):
        raise HTTPException(
            status_code=409, detail="所有题块识别完成且无失败后才能确认"
        )
    blocked_items = [
        item
        for item in items
        if not bool((item.extraction_result or {}).get("grading_eligible", False))
    ]
    if blocked_items:
        raise HTTPException(
            status_code=409,
            detail=(
                f"还有 {len(blocked_items)} 道题的识别证据未批准，"
                "请逐题选择首轮、扩边候选或手工修改后再确认"
            ),
        )
    run.config_snapshot = {**run.config_snapshot, "recognition_confirmed": True}
    session.add(run)
    session.commit()
    return run_public(session, run)


def run_public(session: SessionDep, run: GradingRun) -> GradingRunPublic:
    annotation_ids = select(GradingAuditEvent.annotation_id).where(
        GradingAuditEvent.grading_run_id == run.id
    )
    average = session.exec(
        select(func.avg(SubmissionAnnotation.model_confidence)).where(
            SubmissionAnnotation.id.in_(annotation_ids),
            SubmissionAnnotation.model_confidence.is_not(None),
        )
    ).one()
    return GradingRunPublic.model_validate(
        run,
        update={
            "average_confidence": float(average) if average is not None else None,
            "timing": (run.config_snapshot or {}).get("timing", {}),
        },
    )


@router.post("/runs", response_model=GradingRunPublic)
def create_run(
    *, session: SessionDep, current_user: CurrentUser, run_in: GradingRunCreate
) -> Any:
    exam = owned_exam(session, current_user, run_in.exam_id, require_write=True)
    # 共享批卷守卫：所有有答卷的班级必须已分配老师，否则不能发起批改
    if exam.shared_grading_enabled:
        assigned_ids = set(
            session.exec(
                select(GradingAssignment.class_id).where(
                    GradingAssignment.exam_id == exam.id
                )
            ).all()
        )
        missing_names = [
            class_group.name
            for class_group in exam_classes_with_submissions(session, exam)
            if class_group.id not in assigned_ids
        ]
        if missing_names:
            raise HTTPException(
                status_code=400,
                detail=(
                    "共享批卷尚有班级未分配老师，无法发起批改："
                    f"{', '.join(missing_names)}"
                ),
            )
    if run_in.recognition_run_id:
        recognition = owned_run(session, current_user, run_in.recognition_run_id)
        if recognition.config_snapshot.get(
            "pipeline"
        ) != "recognition_preview" or not recognition.config_snapshot.get(
            "recognition_confirmed"
        ):
            raise HTTPException(
                status_code=409, detail="请先完成并确认 Gemini 识别结果"
            )
        if str(run_in.exam_id) != str(recognition.exam_id):
            raise HTTPException(status_code=422, detail="识别批次与考试不匹配")
    questions = list(
        session.exec(
            select(ExamQuestion).where(
                ExamQuestion.exam_id == run_in.exam_id,
                ExamQuestion.status == ExamQuestionStatus.CONFIRMED,
            )
        ).all()
    )
    answer_rows = list(
        session.exec(
            select(StandardAnswer, StandardAnswerRevision)
            .join(
                StandardAnswerRevision,
                StandardAnswer.current_revision_id == StandardAnswerRevision.id,
            )
            .where(
                StandardAnswer.exam_id == run_in.exam_id,
                StandardAnswer.question_id.is_not(None),
                StandardAnswerRevision.status
                == StandardAnswerRevisionStatus.PUBLISHED,
            )
        ).all()
    )
    locked_revisions = {
        str(answer.question_id): str(revision.id)
        for answer, revision in answer_rows
        if answer.question_id
    }
    missing = [
        question.question_key
        for question in questions
        if str(question.id) not in locked_revisions
    ]
    if not questions or missing:
        detail = (
            f"以下题目没有已发布标准答案：{', '.join(missing[:10])}"
            if missing
            else "请先确认题目并发布标准答案"
        )
        raise HTTPException(status_code=409, detail=detail)
    locked_versions = [revision.revision_number for _, revision in answer_rows]
    # 请求未显式给的字段回落系统设置（DB 覆盖 + env 兜底）
    defaults = get_grading_defaults(session)
    if (
        run_in.max_parallel_submissions is not None
        or run_in.max_concurrency_per_submission is not None
    ):
        max_parallel_submissions = run_in.max_parallel_submissions or 8
        max_concurrency_per_submission = (
            run_in.max_concurrency_per_submission or 4
        )
        max_concurrency = min(
            32, max_parallel_submissions * max_concurrency_per_submission
        )
    else:
        # 旧客户端只传 max_concurrency：保持原总并发，并推导出兼容的两级限制。
        max_concurrency = (
            run_in.max_concurrency
            if run_in.max_concurrency is not None
            else int(defaults["max_concurrency"])
        )
        max_parallel_submissions = min(8, max_concurrency)
        max_concurrency_per_submission = max(
            1, ceil(max_concurrency / max_parallel_submissions)
        )
    run = GradingRun(
        exam_id=run_in.exam_id,
        created_by_id=current_user.id,
        provider=run_in.provider or defaults["grading_provider"],
        model=run_in.model or defaults["grading_model"],
        fallback_models=run_in.fallback_models or defaults["fallback_models"],
        answer_version=max(locked_versions, default=1),
        config_snapshot={
            "submission_ids": [str(item) for item in run_in.submission_ids],
            "review_threshold": run_in.review_threshold
            if run_in.review_threshold is not None
            else defaults["review_threshold"],
            "vision_provider": run_in.vision_provider
            or defaults["vision_provider"],
            "vision_model": run_in.vision_model or defaults["vision_model"],
            "max_concurrency": max_concurrency,
            "max_parallel_submissions": max_parallel_submissions,
            "max_concurrency_per_submission": max_concurrency_per_submission,
            "recognition_run_id": str(run_in.recognition_run_id)
            if run_in.recognition_run_id
            else None,
            "answer_revision_ids": locked_revisions,
        },
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run_public(session, run)


@router.get("/runs", response_model=GradingRunsPublic)
def list_runs(
    session: SessionDep, current_user: CurrentUser, exam_id: uuid.UUID
) -> Any:
    owned_exam(session, current_user, exam_id)
    statement = (
        select(GradingRun)
        .where(GradingRun.exam_id == exam_id)
        .order_by(col(GradingRun.created_at).desc())
    )
    rows = list(session.exec(statement).all())
    return GradingRunsPublic(
        data=[run_public(session, item) for item in rows], count=len(rows)
    )


@router.get("/runs/{run_id}", response_model=GradingRunPublic)
def get_run(session: SessionDep, current_user: CurrentUser, run_id: uuid.UUID) -> Any:
    return run_public(session, owned_run(session, current_user, run_id))


@router.post("/runs/{run_id}/start", response_model=GradingRunPublic)
def start_run(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    run_id: uuid.UUID,
    background_tasks: BackgroundTasks,
) -> Any:
    run = owned_run(session, current_user, run_id)
    if run.status not in {"queued", "failed", "completed_with_errors"}:
        raise HTTPException(status_code=409, detail="该批次当前不能启动")
    background_tasks.add_task(execute_grading_run, str(run.id))
    return run_public(session, run)


@router.post("/runs/{run_id}/retry", response_model=GradingRunPublic)
def retry_run(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    run_id: uuid.UUID,
    background_tasks: BackgroundTasks,
) -> Any:
    run = owned_run(session, current_user, run_id)
    failed_items = session.exec(
        select(GradingItem).where(
            GradingItem.grading_run_id == run.id,
            GradingItem.status == GradingItemStatus.FAILED,
        )
    ).all()
    for item in failed_items:
        item.status, item.attempts, item.error_message = (
            GradingItemStatus.QUEUED,
            0,
            None,
        )
        session.add(item)
    run.status, run.error_message, run.completed_at = (
        GradingRunStatus.QUEUED,
        None,
        None,
    )
    session.add(run)
    session.commit()
    background_tasks.add_task(execute_grading_run, str(run.id))
    return run_public(session, run)


@router.post("/exams/{exam_id}/rubrics/generate", response_model=ProcessingTaskPublic)
def generate_rubrics(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    background_tasks: BackgroundTasks,
) -> Any:
    owned_exam(session, current_user, exam_id, require_write=True)
    task = ProcessingTask(
        task_type="professional_rubric_generation",
        created_by_id=current_user.id,
        input_ref={"exam_id": str(exam_id), "pipeline": "professional-rubric-v1"},
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    background_tasks.add_task(execute_rubric_generation, str(task.id), str(exam_id))
    return task


@router.post("/runs/{run_id}/publish-answers", response_model=GradingRunPublic)
def publish_answers(
    *, session: SessionDep, current_user: CurrentUser, run_id: uuid.UUID
) -> Any:
    run = owned_run(session, current_user, run_id)
    publish_standard_answers(session, run)
    session.refresh(run)
    return run_public(session, run)


@router.get("/runs/{run_id}/review-queue", response_model=list[GradingReviewItem])
def review_queue(
    session: SessionDep, current_user: CurrentUser, run_id: uuid.UUID
) -> Any:
    run = owned_run(session, current_user, run_id)
    audit_annotation_ids = select(GradingAuditEvent.annotation_id).where(
        GradingAuditEvent.grading_run_id == run.id
    )
    statement = (
        select(SubmissionAnnotation, StudentSubmission)
        .join(
            StudentSubmission,
            SubmissionAnnotation.submission_id == StudentSubmission.id,
        )
        .where(SubmissionAnnotation.id.in_(audit_annotation_ids))
    )
    # 共享批卷：被分配的非管理老师只看到负责班级的复核项
    exam = session.get(Exam, run.exam_id)
    if exam is not None:
        restricted = restricted_assigned_classes(session, current_user, exam)
        if restricted is not None:
            statement = statement.where(submission_class_filter(*restricted))
    rows = session.exec(statement).all()
    result = []
    threshold = float(run.config_snapshot.get("review_threshold", 0.8))
    for annotation, submission in rows:
        reasons = {item.get("type") for item in annotation.grading_reasons}
        mirror = "mirror" in (submission.registration_notes or "").lower()
        if (
            annotation.model_confidence is not None
            and annotation.model_confidence >= threshold
            and not reasons
            and not mirror
        ):
            continue
        risk = (
            "镜像/配准异常"
            if mirror
            else ("模型失败" if "model_failure" in reasons else "低置信度")
        )
        result.append(
            GradingReviewItem(
                submission_id=submission.id,
                student_name=submission.student_name,
                student_identifier=submission.student_identifier,
                annotation_id=annotation.id,
                label=annotation.label,
                score=annotation.score,
                max_score=annotation.max_score,
                confidence=annotation.model_confidence,
                risk=risk,
                priority=100 if mirror or "model_failure" in reasons else 50,
            )
        )
    return sorted(result, key=lambda item: (-item.priority, item.confidence or 0))


@router.get("/runs/{run_id}/audit", response_model=list[GradingAuditEventPublic])
def audit_log(session: SessionDep, current_user: CurrentUser, run_id: uuid.UUID) -> Any:
    run = owned_run(session, current_user, run_id)
    return list(
        session.exec(
            select(GradingAuditEvent)
            .where(GradingAuditEvent.grading_run_id == run.id)
            .order_by(GradingAuditEvent.created_at)
        ).all()
    )
