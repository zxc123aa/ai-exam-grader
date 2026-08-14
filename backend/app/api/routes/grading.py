import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_teacher_user,
)
from app.core.config import settings
from app.models import (
    AnswerQuotaReservation,
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
    ScoreRelease,
    ScoreReleaseCreate,
    ScoreReleaseItem,
    ScoreReleasePublic,
    ScoreReleaseStatus,
    StandardAnswer,
    StandardAnswerRevision,
    StandardAnswerRevisionStatus,
    StudentSubmission,
    SubmissionAnnotation,
    get_datetime_utc,
)
from app.services import billing as billing_service
from app.services.grading_workflow import publish_standard_answers
from app.services.org_scope import (
    can_see_exam,
    can_write_exam,
    exam_classes_with_submissions,
    restricted_assigned_classes,
    submission_class_filter,
)
from app.services.system_config import get_grading_defaults
from app.worker import (
    process_grading_run,
    process_recognition_run,
    process_rubric_generation,
    process_wrongbook_snapshot,
    run_wrongbook_snapshot,
)

logger = logging.getLogger(__name__)

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
) -> Any:
    exam = owned_exam(session, current_user, run_in.exam_id, require_write=True)
    billing_service.require_model_entitlement(session, exam.org_id)
    submission = session.get(StudentSubmission, run_in.submission_id)
    if not submission or submission.exam_id != run_in.exam_id:
        raise HTTPException(status_code=404, detail="答卷不存在")
    defaults = get_grading_defaults(session, exam.org_id)
    run = GradingRun(
        exam_id=run_in.exam_id,
        created_by_id=current_user.id,
        provider=str(defaults["vision_provider"]),
        model=str(defaults["vision_model"]),
        fallback_models=[str(item) for item in defaults["vision_fallback_models"]],
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
    session.flush()
    expected_calls = session.exec(
        select(func.count())
        .select_from(ExamRegion)
        .where(ExamRegion.exam_id == exam.id)
    ).one()
    reservation = billing_service.reserve_task_or_raise(
        session,
        org_id=exam.org_id,
        task_type="answer_recognition",
        resource_id=str(run.id),
        idempotency_key=f"{exam.org_id}:answer_recognition:{run.id}:v1",
        expected_calls=max(1, expected_calls),
        grading_run_id=run.id,
    )
    if reservation:
        run.estimated_microcredits = reservation.estimated_microcredits
        run.reserved_microcredits = reservation.estimated_microcredits
        run.billing_status = "reserved"
        run.config_snapshot = {
            **run.config_snapshot,
            "billing_reservation_id": str(reservation.id),
        }
        session.add(run)
    session.commit()
    session.refresh(run)
    process_recognition_run.send(str(run.id))
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
                "unassignedCount": len(extraction.get("unassigned_evidence") or []),
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
            "estimated_credits": billing_service.microcredits_to_credits(
                run.estimated_microcredits
            ),
            "reserved_credits": billing_service.microcredits_to_credits(
                run.reserved_microcredits
            ),
            "settled_credits": billing_service.microcredits_to_credits(
                run.settled_microcredits
            ),
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
                StandardAnswerRevision.status == StandardAnswerRevisionStatus.PUBLISHED,
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
    defaults = get_grading_defaults(session, exam.org_id)
    # School users cannot override technical controls. Keeping these request
    # fields temporarily preserves old clients, but the platform policy is the
    # only source of truth so API callers cannot bypass the hidden UI.
    max_concurrency = int(defaults["max_concurrency"])
    max_parallel_submissions = min(8, max_concurrency)
    max_concurrency_per_submission = max(
        1, (max_concurrency + max_parallel_submissions - 1) // max_parallel_submissions
    )
    run = GradingRun(
        exam_id=run_in.exam_id,
        created_by_id=current_user.id,
        provider=defaults["grading_provider"],
        model=defaults["grading_model"],
        fallback_models=defaults["reasoning_fallback_models"],
        answer_version=max(locked_versions, default=1),
        config_snapshot={
            "submission_ids": [str(item) for item in run_in.submission_ids],
            "review_threshold": defaults["review_threshold"],
            "vision_provider": defaults["vision_provider"],
            "vision_model": defaults["vision_model"],
            "vision_fallback_models": defaults["vision_fallback_models"],
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
    session.flush()
    billing_service.require_model_entitlement(session, exam.org_id)
    expected_submissions = (
        len(run_in.submission_ids)
        or session.exec(
            select(func.count())
            .select_from(StudentSubmission)
            .where(StudentSubmission.exam_id == exam.id)
        ).one()
    )
    selected_submissions_query = select(StudentSubmission).where(
        StudentSubmission.exam_id == exam.id
    )
    if run_in.submission_ids:
        selected_submissions_query = selected_submissions_query.where(
            col(StudentSubmission.id).in_(run_in.submission_ids)
        )
    selected_submissions = list(session.exec(selected_submissions_query).all())
    answer_quota_reservation = billing_service.reserve_answer_quota(
        session,
        org_id=exam.org_id,
        exam_id=exam.id,
        grading_run_id=run.id,
        submissions=selected_submissions,
    )
    if settings.BILLING_ENFORCEMENT_ENABLED and answer_quota_reservation is None:
        raise HTTPException(
            status_code=402,
            detail="学校可用答卷额度不足，增购后可继续批改",
        )
    if answer_quota_reservation:
        run.config_snapshot = {
            **run.config_snapshot,
            "answer_quota_reservation_id": str(answer_quota_reservation.id),
            "answer_quota_reserved": answer_quota_reservation.reserved_answers,
        }
    estimate = billing_service.quote_microcredits(
        session,
        org_id=exam.org_id,
        workflow_purpose="grading_run",
        expected_calls=max(1, expected_submissions * len(questions) * 2),
    )
    run.estimated_microcredits = estimate
    try:
        reservation = billing_service.reserve_credits(
            session,
            org_id=exam.org_id,
            task_type="grading_run",
            resource_id=str(run.id),
            idempotency_key=f"{exam.org_id}:grading_run:{run.id}:v1",
            estimated_microcredits=estimate,
            grading_run_id=run.id,
        )
    except HTTPException:
        reservation = None
    if reservation:
        run.reserved_microcredits = reservation.estimated_microcredits
        run.billing_status = "reserved"
        run.config_snapshot = {
            **run.config_snapshot,
            "billing_reservation_id": str(reservation.id),
        }
    elif settings.TOKEN_BUDGET_ENFORCEMENT_ENABLED:
        run.status = GradingRunStatus.AWAITING_CREDITS
        run.billing_status = "awaiting_credits"
    else:
        run.billing_status = "shadow"
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
) -> Any:
    run = owned_run(session, current_user, run_id)
    if run.status == GradingRunStatus.AWAITING_CREDITS:
        exam = owned_exam(session, current_user, run.exam_id)
        try:
            reservation = billing_service.reserve_credits(
                session,
                org_id=exam.org_id,
                task_type="grading_run",
                resource_id=str(run.id),
                idempotency_key=f"{exam.org_id}:grading_run:{run.id}:v1",
                estimated_microcredits=run.estimated_microcredits,
                grading_run_id=run.id,
            )
        except HTTPException:
            reservation = None
        if not reservation:
            return run_public(session, run)
        run.status = GradingRunStatus.QUEUED
        run.billing_status = "reserved"
        run.reserved_microcredits = reservation.estimated_microcredits
        run.config_snapshot = {
            **run.config_snapshot,
            "billing_reservation_id": str(reservation.id),
        }
        session.add(run)
        session.commit()
    if run.status != GradingRunStatus.QUEUED:
        raise HTTPException(status_code=409, detail="该批次当前不能启动")
    process_grading_run.send(str(run.id))
    return run_public(session, run)


@router.post("/runs/{run_id}/retry", response_model=GradingRunPublic)
def retry_run(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    run_id: uuid.UUID,
) -> Any:
    run = owned_run(session, current_user, run_id)
    # Serialize retry requests for one run. This keeps quota reservations
    # idempotent when a user double-clicks or a client retries the HTTP call.
    run = session.exec(
        select(GradingRun).where(GradingRun.id == run.id).with_for_update()
    ).one()
    if run.status not in {
        GradingRunStatus.FAILED,
        GradingRunStatus.COMPLETED_WITH_ERRORS,
    }:
        raise HTTPException(status_code=409, detail="该批次当前无需重试")
    failed_items = list(
        session.exec(
            select(GradingItem).where(
                GradingItem.grading_run_id == run.id,
                GradingItem.status == GradingItemStatus.FAILED,
            )
        ).all()
    )
    exam = owned_exam(session, current_user, run.exam_id, require_write=True)
    failed_submission_ids = {item.submission_id for item in failed_items}
    submission_query = select(StudentSubmission).where(
        StudentSubmission.exam_id == exam.id
    )
    if failed_submission_ids:
        submission_query = submission_query.where(
            col(StudentSubmission.id).in_(failed_submission_ids)
        )
    else:
        configured_ids = [
            uuid.UUID(value)
            for value in (run.config_snapshot or {}).get("submission_ids", [])
        ]
        if configured_ids:
            submission_query = submission_query.where(
                col(StudentSubmission.id).in_(configured_ids)
            )
    retry_submissions = list(session.exec(submission_query).all())
    if not retry_submissions:
        raise HTTPException(status_code=409, detail="没有可重试的答卷")
    billing_service.require_model_entitlement(session, exam.org_id)
    retry_sequence = session.exec(
        select(func.count())
        .select_from(AnswerQuotaReservation)
        .where(AnswerQuotaReservation.grading_run_id == run.id)
    ).one()
    answer_reservation = billing_service.reserve_answer_quota(
        session,
        org_id=exam.org_id,
        exam_id=exam.id,
        grading_run_id=run.id,
        submissions=retry_submissions,
        idempotency_key=(
            f"{exam.org_id}:grading-run:{run.id}:answers:v{retry_sequence + 1}"
        ),
    )
    if settings.BILLING_ENFORCEMENT_ENABLED and answer_reservation is None:
        raise HTTPException(
            status_code=402, detail="学校可用答卷额度不足，增购后可重试"
        )
    snapshot = dict(run.config_snapshot or {})
    if answer_reservation:
        snapshot.update(
            answer_quota_reservation_id=str(answer_reservation.id),
            answer_quota_reserved=answer_reservation.reserved_answers,
        )
    # Token 成本是平台内部风控，不是客户计费单位。仅在显式开启内部
    # 预算保护时为重试创建新预留，不能复用已经结算的旧预留。
    if settings.TOKEN_BUDGET_ENFORCEMENT_ENABLED:
        estimate = billing_service.quote_microcredits(
            session,
            org_id=exam.org_id,
            workflow_purpose="grading_run",
            expected_calls=max(
                1, len(retry_submissions) * max(1, len(failed_items)) * 2
            ),
        )
        reservation = billing_service.reserve_credits(
            session,
            org_id=exam.org_id,
            task_type="grading_run_retry",
            resource_id=str(run.id),
            idempotency_key=(
                f"{exam.org_id}:grading-run:{run.id}:retry:v{retry_sequence + 1}"
            ),
            estimated_microcredits=estimate,
            grading_run_id=run.id,
        )
        if reservation is None:
            if answer_reservation:
                billing_service.release_answer_quota(session, answer_reservation.id)
            raise HTTPException(
                status_code=503, detail="平台模型服务暂时繁忙，请稍后重试"
            )
        snapshot["billing_reservation_id"] = str(reservation.id)
        run.estimated_microcredits = estimate
        run.reserved_microcredits = reservation.estimated_microcredits
        run.billing_status = "reserved"
    else:
        snapshot.pop("billing_reservation_id", None)
        run.billing_status = "shadow"
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
    run.config_snapshot = snapshot
    session.add(run)
    session.commit()
    process_grading_run.send(str(run.id))
    return run_public(session, run)


@router.post("/exams/{exam_id}/rubrics/generate", response_model=ProcessingTaskPublic)
def generate_rubrics(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
) -> Any:
    exam = owned_exam(session, current_user, exam_id, require_write=True)
    billing_service.require_model_entitlement(session, exam.org_id)
    task = ProcessingTask(
        task_type="professional_rubric_generation",
        created_by_id=current_user.id,
        input_ref={"exam_id": str(exam_id), "pipeline": "professional-rubric-v1"},
    )
    session.add(task)
    session.flush()
    answer_count = session.exec(
        select(func.count())
        .select_from(StandardAnswer)
        .where(StandardAnswer.exam_id == exam_id)
    ).one()
    reservation = billing_service.reserve_task_or_raise(
        session,
        org_id=exam.org_id,
        task_type="rubric_generation",
        resource_id=str(task.id),
        idempotency_key=f"{exam.org_id}:rubric_generation:{task.id}:v1",
        expected_calls=max(1, answer_count * 3),
    )
    if reservation:
        task.input_ref = {
            **(task.input_ref or {}),
            "billing_reservation_id": str(reservation.id),
        }
        session.add(task)
    session.commit()
    session.refresh(task)
    process_rubric_generation.send(str(task.id), str(exam_id))
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
        if annotation.score_source == "human":
            continue
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


def _enqueue_wrongbook_snapshot(release_id: uuid.UUID) -> None:
    """发布成绩后异步写错题本。

    快照是学生端的增强能力，任何失败都不能影响教师已经完成的成绩发布，
    因此这里吞掉异常，只记日志，由后续重新发布或补跑脚本兜底。
    """
    try:
        if settings.ENVIRONMENT == "local":
            run_wrongbook_snapshot(str(release_id))
            return
        try:
            process_wrongbook_snapshot.send(str(release_id))
        except Exception:
            run_wrongbook_snapshot(str(release_id))
    except Exception:
        logger.warning(
            "wrongbook snapshot failed",
            extra={"release_id": str(release_id)},
            exc_info=True,
        )


@router.post("/exams/{exam_id}/score-releases", response_model=ScoreReleasePublic)
def publish_exam_scores(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    release_in: ScoreReleaseCreate,
) -> Any:
    """Freeze the current reviewed score draft as the student-visible version."""
    exam = owned_exam(session, current_user, exam_id, require_write=True)
    # Serialize releases per exam, including the first release where no release row
    # exists yet. Locking only the previous release would allow two version-1 rows.
    session.exec(select(Exam).where(Exam.id == exam.id).with_for_update()).one()
    submissions = list(
        session.exec(
            select(StudentSubmission).where(StudentSubmission.exam_id == exam.id)
        ).all()
    )
    if not submissions:
        raise HTTPException(status_code=409, detail="考试尚无答卷，不能发布成绩")
    submission_ids = [item.id for item in submissions]
    annotations = list(
        session.exec(
            select(SubmissionAnnotation).where(
                col(SubmissionAnnotation.submission_id).in_(submission_ids)
            )
        ).all()
    )
    if not annotations:
        raise HTTPException(status_code=409, detail="考试尚未形成建议评分")

    latest: dict[tuple[uuid.UUID, str], SubmissionAnnotation] = {}
    for annotation in annotations:
        key = (annotation.submission_id, annotation.label)
        current = latest.get(key)
        if (
            current is None
            or (current.score_source != "human" and annotation.score_source == "human")
            or (
                current.score_source == annotation.score_source
                and (annotation.updated_at or annotation.created_at)
                > (current.updated_at or current.created_at)
            )
        ):
            latest[key] = annotation

    pending = [
        item
        for item in latest.values()
        if item.grading_status == "needs_review" and item.score_source != "human"
    ]
    if pending:
        raise HTTPException(
            status_code=409,
            detail=f"还有 {len(pending)} 道题待复核，处理完成后才能发布成绩",
        )

    confirmed_question_count = session.exec(
        select(func.count())
        .select_from(ExamQuestion)
        .where(
            ExamQuestion.exam_id == exam.id,
            ExamQuestion.status == ExamQuestionStatus.CONFIRMED,
        )
    ).one()
    minimum_items = max(1, confirmed_question_count)
    submission_groups: dict[str, list[StudentSubmission]] = {}
    for submission in submissions:
        if submission.student_id:
            group_key = f"student:{submission.student_id}"
        elif submission.student_name:
            group_key = (
                f"identity:{submission.class_name or ''}:{submission.student_name}"
            )
        else:
            group_key = f"submission:{submission.id}"
        submission_groups.setdefault(group_key, []).append(submission)
    incomplete_groups = []
    for group in submission_groups.values():
        group_ids = {submission.id for submission in group}
        scored = [
            item
            for (submission_id, _label), item in latest.items()
            if submission_id in group_ids and item.score is not None
        ]
        if len({item.label for item in scored}) < minimum_items:
            incomplete_groups.append(group)
    if incomplete_groups:
        raise HTTPException(
            status_code=409,
            detail=(
                f"还有 {len(incomplete_groups)} 份答卷未完成批改，"
                "全部形成成绩后才能发布"
            ),
        )

    previous = session.exec(
        select(ScoreRelease)
        .where(ScoreRelease.exam_id == exam.id)
        .order_by(col(ScoreRelease.version).desc())
        .with_for_update()
    ).first()
    if previous and previous.status == ScoreReleaseStatus.PUBLISHED:
        previous.status = ScoreReleaseStatus.SUPERSEDED
        session.add(previous)
    release = ScoreRelease(
        exam_id=exam.id,
        version=(previous.version + 1 if previous else 1),
        published_by_id=current_user.id,
        reason=release_in.reason,
    )
    session.add(release)
    session.flush()

    items = [
        ScoreReleaseItem(
            release_id=release.id,
            submission_id=annotation.submission_id,
            annotation_id=annotation.id,
            label=annotation.label,
            score=annotation.score,
            max_score=annotation.max_score,
            comment=annotation.comment,
            source="human" if annotation.score_source == "human" else "suggested",
        )
        for annotation in latest.values()
    ]
    session.add_all(items)
    session.commit()
    session.refresh(release)
    _enqueue_wrongbook_snapshot(release.id)
    return ScoreReleasePublic(**release.model_dump(), item_count=len(items))


@router.get(
    "/exams/{exam_id}/score-releases/current",
    response_model=ScoreReleasePublic | None,
)
def get_current_score_release(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
) -> Any:
    """Return the version currently visible to students, if one exists."""
    exam = owned_exam(session, current_user, exam_id)
    release = session.exec(
        select(ScoreRelease)
        .where(
            ScoreRelease.exam_id == exam.id,
            ScoreRelease.status == ScoreReleaseStatus.PUBLISHED,
        )
        .order_by(col(ScoreRelease.version).desc())
    ).first()
    if not release:
        return None
    item_count = session.exec(
        select(func.count())
        .select_from(ScoreReleaseItem)
        .where(ScoreReleaseItem.release_id == release.id)
    ).one()
    return ScoreReleasePublic(**release.model_dump(), item_count=item_count)
