import base64
import json
import logging
import statistics
import time
import uuid
from pathlib import Path
from typing import Any, Literal

import cv2
import numpy as np
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, Response
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, func, select

from app.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_teacher_user,
    get_user_from_authorization_header,
    is_platform_user,
)
from app.core.config import settings
from app.models import (
    AnnotationGradingStatus,
    AnswerPreparationRun,
    ClassGroup,
    Exam,
    ExamAnalysisReportPublic,
    ExamClassLink,
    ExamComposeRequest,
    ExamCreate,
    ExamDocument,
    ExamDocumentOrderUpdate,
    ExamDocumentPreprocessedUploadRequest,
    ExamDocumentPublic,
    ExamDocumentQuadPreprocessRequest,
    ExamDocumentRecognitionRequest,
    ExamDocumentsPublic,
    ExamDocumentType,
    ExamPublic,
    ExamQuestion,
    ExamQuestionRegion,
    ExamQuestionStatus,
    ExamRegion,
    ExamRegionCandidate,
    ExamRegionCandidatesPublic,
    ExamRegionCreate,
    ExamRegionPublic,
    ExamRegionsPublic,
    ExamRegionType,
    ExamRegionUpdate,
    ExamScoreSummaryPublic,
    ExamScoreSummaryQuestion,
    ExamScoreSummaryRow,
    ExamsPublic,
    ExamUpdate,
    ExamWorkflowStepPublic,
    ExamWorkflowSummaryPublic,
    GradingAssigneePublic,
    GradingAssignment,
    GradingAssignmentClassPublic,
    GradingAssignmentItemPublic,
    GradingAssignmentsPublic,
    GradingAssignmentsUpdate,
    GradingRun,
    GradingRunStatus,
    Message,
    ProcessingTask,
    ProcessingTaskPublic,
    ProcessingTaskStatus,
    QuestionBankEntryPublic,
    QuestionBankPublic,
    QuestionRecognitionRun,
    ScoreRelease,
    ScoreReleaseStatus,
    StandardAnswer,
    StandardAnswerCreate,
    StandardAnswerPublic,
    StandardAnswerRevision,
    StandardAnswerRevisionStatus,
    StandardAnswersPublic,
    StandardAnswerStatus,
    StandardAnswerUpdate,
    StoredFile,
    StoredFilePublic,
    StudentSubmission,
    StudentSubmissionPublic,
    StudentSubmissionRegistrationUpdate,
    StudentSubmissionsPublic,
    StudentSubmissionStatus,
    SubmissionAnnotation,
    SubmissionAnnotationCreate,
    SubmissionAnnotationPublic,
    SubmissionAnnotationsPublic,
    SubmissionAnnotationStatus,
    SubmissionAnnotationUpdate,
    SubmissionRegistrationStatus,
    TeacherClassLink,
    User,
    UserRole,
    get_datetime_utc,
)
from app.services.class_students import resolve_student_for_submission
from app.services.exam_photo_preprocessing import (
    PhotoPreprocessingError,
    preprocess_exam_photo_with_page_quads,
)
from app.services.file_storage import (
    MAX_UPLOAD_BYTES,
    MAX_ZIP_UPLOAD_BYTES,
    SCAN_PHOTO_CONTENT_TYPES,
    assert_allowed_signature,
    cleanup_stored_file_path,
    get_stored_file_path,
    is_zip_upload,
    read_upload_file_bytes,
    store_generated_file,
    store_upload_file,
    validate_scan_photo_upload_file,
)
from app.services.object_storage import materialize_storage_key
from app.services.org_scope import (
    assigned_class_ids,
    can_see_exam,
    can_write_exam,
    exam_classes_with_submissions,
    exams_visible_filter,
    resolve_target_org_id,
    restricted_assigned_classes,
    submission_class_filter,
    submission_in_assigned_classes,
)
from app.services.pdf_rendering import (
    InvalidPdfError,
    get_pdf_page_count,
    image_bytes_to_pdf,
    merge_pdf_bytes,
    render_pdf_page_jpeg,
    render_pdf_page_png,
)
from app.services.question_segmentation import (
    ENGINE_NAME as QUESTION_SEGMENTATION_ENGINE,
)
from app.services.question_segmentation import (
    GEMINI_LAYOUT_ENGINE_NAME,
    OCR_ANCHOR_ENGINE_NAME,
    QuestionSegmentationEngine,
    decode_image,
    find_question_region_candidates,
)
from app.services.reference_algorithm import (
    layout_stored_file,
    process_stored_file,
    process_stored_file_page_context,
    process_stored_files,
)
from app.services.scan_preprocessing import preprocess_scan_photo_bytes
from app.services.submission_crops import (
    SubmissionCropError,
    crop_region_png,
    resolve_exam_region_paper_page,
)
from app.services.system_config import get_grading_defaults
from app.services.vision_grading import VisionGradingError, call_json_model
from app.services.zip_submissions import build_pdf_bytes_from_zip
from app.worker import (
    process_exam_document_preprocessing,
    process_submission_processing_task,
    run_submission_processing_task,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/exams",
    tags=["exams"],
    dependencies=[Depends(get_current_teacher_user)],
)


def get_exam_for_user(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    require_write: bool = False,
) -> Exam:
    """按可见性取考试：不可见一律 404（不区分「不存在」与「跨校/他人考试」）。

    require_write=True 时再叠加写权限校验（自己的考试 / school_owner 写本校 /
    平台超管），可见但无权写时 403。
    """
    exam = session.get(Exam, exam_id)
    if not exam or not can_see_exam(session, current_user, exam):
        raise HTTPException(status_code=404, detail="Exam not found")
    if require_write and not can_write_exam(current_user, exam):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return exam


def build_exam_public(
    *, session: Session, exam: Exam, is_assigned: bool = False
) -> ExamPublic:
    """ExamPublic 组装：附加 ExamClassLink 读出的 class_ids / class_names。"""
    public = ExamPublic.model_validate(exam)
    public.is_assigned = is_assigned
    rows = session.exec(
        select(ExamClassLink, ClassGroup)
        .join(ClassGroup, ExamClassLink.class_id == ClassGroup.id)
        .where(
            ExamClassLink.exam_id == exam.id,
            ClassGroup.org_id == exam.org_id,
        )
        .order_by(col(ClassGroup.name).asc())
    ).all()
    public.class_ids = [link.class_id for link, _class_group in rows]
    public.class_names = [class_group.name for _link, class_group in rows]
    return public


@router.get("/{exam_id}/workflow-summary", response_model=ExamWorkflowSummaryPublic)
def read_exam_workflow_summary(
    session: SessionDep, current_user: CurrentUser, exam_id: uuid.UUID
) -> ExamWorkflowSummaryPublic:
    """Return one teacher-facing next action without exposing model internals."""
    exam = get_exam_for_user(
        session=session, current_user=current_user, exam_id=exam_id
    )
    paper_count = session.exec(
        select(func.count())
        .select_from(ExamDocument)
        .where(
            ExamDocument.exam_id == exam.id,
            ExamDocument.document_type == ExamDocumentType.BLANK_EXAM,
        )
    ).one()
    region_count = session.exec(
        select(func.count())
        .select_from(ExamRegion)
        .where(ExamRegion.exam_id == exam.id)
    ).one()
    confirmed_question_count = session.exec(
        select(func.count())
        .select_from(ExamQuestion)
        .where(
            ExamQuestion.exam_id == exam.id,
            ExamQuestion.status == ExamQuestionStatus.CONFIRMED,
        )
    ).one()
    ready_answer_count = session.exec(
        select(func.count())
        .select_from(StandardAnswer)
        .where(
            StandardAnswer.exam_id == exam.id,
            StandardAnswer.status == StandardAnswerStatus.READY,
        )
    ).one()
    submission_count = session.exec(
        select(func.count())
        .select_from(StudentSubmission)
        .where(StudentSubmission.exam_id == exam.id)
    ).one()
    latest_run = session.exec(
        select(GradingRun)
        .where(GradingRun.exam_id == exam.id)
        .order_by(col(GradingRun.created_at).desc())
    ).first()
    review_count = session.exec(
        select(func.count())
        .select_from(SubmissionAnnotation)
        .join(StudentSubmission)
        .where(
            StudentSubmission.exam_id == exam.id,
            SubmissionAnnotation.status == SubmissionAnnotationStatus.NEEDS_REVIEW,
        )
    ).one()
    published = session.exec(
        select(ScoreRelease.id).where(
            ScoreRelease.exam_id == exam.id,
            ScoreRelease.status == ScoreReleaseStatus.PUBLISHED,
        )
    ).first()

    run_finished = bool(
        latest_run
        and latest_run.status
        in {GradingRunStatus.COMPLETED, GradingRunStatus.COMPLETED_WITH_ERRORS}
    )
    run_active = bool(
        latest_run
        and latest_run.status in {GradingRunStatus.QUEUED, GradingRunStatus.RUNNING}
    )
    conditions = [
        (
            paper_count == 0,
            "import_paper",
            "导入模板卷",
            "",
            "先上传模板卷，系统会自动准备后续步骤。",
        ),
        (
            region_count == 0,
            "mark_questions",
            "确认题目区域",
            "marking",
            "确认每道题在卷面上的位置。",
        ),
        (
            confirmed_question_count == 0,
            "confirm_questions",
            "确认题目内容",
            "questions",
            "检查题目内容，确认后再准备参考答案。",
        ),
        (
            ready_answer_count < confirmed_question_count,
            "prepare_answers",
            "确认参考答案",
            "answers",
            "检查参考答案和评分点，确认无误后开始批改。",
        ),
        (
            submission_count == 0,
            "import_submissions",
            "导入学生答卷",
            "grading",
            "导入学生答卷后即可开始批改。",
        ),
        (
            run_active,
            "wait_grading",
            "查看批改进度",
            "grading",
            "批改正在后台进行，你可以离开页面，异常结果会集中提醒。",
        ),
        (
            not run_finished,
            "start_grading",
            "开始批改",
            "grading",
            "准备工作已完成，可以开始本次批改。",
        ),
        (
            review_count > 0,
            "review_exceptions",
            f"复核 {review_count} 处异常",
            "workbench",
            "正常结果已经处理，只需集中检查这些异常。",
        ),
        (
            not published,
            "publish_scores",
            "发布成绩",
            "scores",
            "复核完成后发布成绩，学生才能查看。",
        ),
    ]
    next_action, next_label, route, message = (
        "view_results",
        "查看成绩",
        "scores",
        "本次考试已完成，可以查看成绩和学情分析。",
    )
    for matched, code, label, candidate_route, candidate_message in conditions:
        if matched:
            next_action, next_label, route, message = (
                code,
                label,
                candidate_route,
                candidate_message,
            )
            break
    completed = {
        "import": paper_count > 0,
        "marking": region_count > 0,
        "questions": confirmed_question_count > 0,
        "answers": confirmed_question_count > 0
        and ready_answer_count >= confirmed_question_count,
        "grading": run_finished,
        "scores": published is not None,
    }
    active_code = {
        "import_paper": "import",
        "mark_questions": "marking",
        "confirm_questions": "questions",
        "prepare_answers": "answers",
        "import_submissions": "grading",
        "wait_grading": "grading",
        "start_grading": "grading",
        "review_exceptions": "grading",
        "publish_scores": "scores",
        "view_results": "scores",
    }[next_action]
    labels = {
        "import": "导入模板卷",
        "marking": "确认题目区域",
        "questions": "确认题目内容",
        "answers": "确认参考答案",
        "grading": "批改与复核",
        "scores": "发布成绩",
    }
    counts = {
        "import": paper_count,
        "marking": region_count,
        "questions": confirmed_question_count,
        "answers": ready_answer_count,
        "grading": review_count,
        "scores": 1 if published else 0,
    }
    return ExamWorkflowSummaryPublic(
        exam_id=exam.id,
        next_action=next_action,
        next_label=next_label,
        next_path=f"/exams/{exam.id}/{route}".rstrip("/"),
        message=message,
        steps=[
            ExamWorkflowStepPublic(
                code=code,
                label=label,
                status="completed"
                if completed[code]
                else "active"
                if code == active_code
                else "pending",
                count=counts[code],
            )
            for code, label in labels.items()
        ],
    )


def replace_exam_class_links(
    *,
    session: Session,
    exam: Exam,
    class_ids: list[uuid.UUID],
) -> None:
    """整体重建考试的班级关联；班级不存在或不在考试所属学校时 400。"""
    unique_ids = list(dict.fromkeys(class_ids))
    class_groups = (
        list(
            session.exec(
                select(ClassGroup).where(
                    col(ClassGroup.id).in_(unique_ids),
                    ClassGroup.org_id == exam.org_id,
                )
            ).all()
        )
        if unique_ids
        else []
    )
    if len(class_groups) != len(unique_ids):
        raise HTTPException(
            status_code=400,
            detail="Invalid class_ids: 班级不存在或不属于本学校",
        )
    for link in session.exec(
        select(ExamClassLink).where(ExamClassLink.exam_id == exam.id)
    ).all():
        session.delete(link)
    for class_id in unique_ids:
        session.add(ExamClassLink(exam_id=exam.id, class_id=class_id))


def get_stored_file_page_count(stored_file: StoredFile) -> int:
    page_count = 1
    path = get_stored_file_path(stored_file)
    if stored_file.content_type == "application/pdf" and path.exists():
        try:
            page_count = get_pdf_page_count(path)
        except InvalidPdfError:
            page_count = 1
    return page_count


def validate_uploaded_pdf(stored_file: StoredFile) -> None:
    if stored_file.content_type != "application/pdf":
        return
    try:
        get_pdf_page_count(get_stored_file_path(stored_file))
    except InvalidPdfError:
        cleanup_stored_file_path(get_stored_file_path(stored_file))
        raise HTTPException(
            status_code=415,
            detail="Uploaded PDF could not be opened",
        )


def build_exam_document_public(
    *, exam_document: ExamDocument, stored_file: StoredFile
) -> ExamDocumentPublic:
    return ExamDocumentPublic(
        id=exam_document.id,
        exam_id=exam_document.exam_id,
        stored_file_id=exam_document.stored_file_id,
        document_type=exam_document.document_type,
        sort_order=exam_document.sort_order,
        created_at=exam_document.created_at,
        stored_file=StoredFilePublic.model_validate(stored_file),
        page_count=get_stored_file_page_count(stored_file),
        original_stored_file_id=exam_document.original_stored_file_id,
        preprocessing_status=exam_document.preprocessing_status,
        preprocessing_quality=exam_document.preprocessing_quality,
        preprocessing_metadata=exam_document.preprocessing_metadata,
    )


def get_next_exam_document_sort_order(
    *, session: SessionDep, exam_id: uuid.UUID, document_type: ExamDocumentType
) -> int:
    current_max = session.exec(
        select(func.max(ExamDocument.sort_order)).where(
            ExamDocument.exam_id == exam_id,
            ExamDocument.document_type == document_type,
        )
    ).one()
    return int(current_max or 0) + 1


def delete_exam_source_derived_data(*, session: SessionDep, exam_id: uuid.UUID) -> None:
    """Remove data that becomes stale when the imported paper source is replaced."""
    for model in (
        GradingRun,
        AnswerPreparationRun,
        QuestionRecognitionRun,
        StandardAnswer,
        ExamQuestion,
        ExamRegion,
    ):
        rows = session.exec(select(model).where(model.exam_id == exam_id)).all()
        for row in rows:
            session.delete(row)


def refine_stacked_question_regions(raw_regions: list[dict]) -> list[dict]:
    """Normalize Gemini question boxes for a single-column exam page.

    Gemini sometimes returns the correct vertical split but a later question's
    left edge starts at the first text line instead of the printed question
    number. On exam pages, vertically stacked question blocks should usually
    share the same text column. This keeps side-by-side regions unchanged.
    """
    regions = [dict(region) for region in raw_regions if isinstance(region, dict)]
    if len(regions) < 2:
        return regions

    parsed: list[tuple[dict, float, float, float, float]] = []
    for region in regions:
        try:
            xmin = max(0.0, min(1000.0, float(region.get("xmin", 0))))
            ymin = max(0.0, min(1000.0, float(region.get("ymin", 0))))
            xmax = max(xmin + 1.0, min(1000.0, float(region.get("xmax", 1000))))
            ymax = max(ymin + 1.0, min(1000.0, float(region.get("ymax", 1000))))
        except (TypeError, ValueError):
            continue
        parsed.append((region, xmin, ymin, xmax, ymax))
    if len(parsed) < 2:
        return regions

    side_by_side_pairs = 0
    comparable_pairs = 0
    for index, (_left_region, left_xmin, left_ymin, left_xmax, left_ymax) in enumerate(
        parsed
    ):
        for _right_region, right_xmin, right_ymin, right_xmax, right_ymax in parsed[
            index + 1 :
        ]:
            vertical_overlap = min(left_ymax, right_ymax) - max(left_ymin, right_ymin)
            min_height = max(1.0, min(left_ymax - left_ymin, right_ymax - right_ymin))
            if vertical_overlap / min_height > 0.35:
                comparable_pairs += 1
                horizontal_gap = max(left_xmin, right_xmin) - min(left_xmax, right_xmax)
                if horizontal_gap > 20:
                    side_by_side_pairs += 1
    if comparable_pairs and side_by_side_pairs / comparable_pairs > 0.4:
        return regions

    column_left = min(item[1] for item in parsed)
    column_right = max(item[3] for item in parsed)
    for region, xmin, _ymin, xmax, _ymax in parsed:
        if xmin - column_left > 45:
            region["xmin"] = column_left
            region["refinement"] = {
                **(
                    region.get("refinement")
                    if isinstance(region.get("refinement"), dict)
                    else {}
                ),
                "applied": True,
                "method": "stacked-column-left-align",
            }
        if column_right - xmax > 60:
            region["xmax"] = column_right
            region["refinement"] = {
                **(
                    region.get("refinement")
                    if isinstance(region.get("refinement"), dict)
                    else {}
                ),
                "applied": True,
                "method": "stacked-column-right-align",
            }
    return regions


def build_student_submission_public(
    *, submission: StudentSubmission, stored_file: StoredFile
) -> StudentSubmissionPublic:
    return StudentSubmissionPublic(
        id=submission.id,
        exam_id=submission.exam_id,
        stored_file_id=submission.stored_file_id,
        student_name=submission.student_name,
        student_identifier=submission.student_identifier,
        class_name=submission.class_name,
        student_id=submission.student_id,
        status=submission.status,
        registration_status=submission.registration_status,
        registration_quality=submission.registration_quality,
        registration_notes=submission.registration_notes,
        registration_homography=submission.registration_homography,
        registered_at=submission.registered_at,
        created_at=submission.created_at,
        updated_at=submission.updated_at,
        stored_file=StoredFilePublic.model_validate(stored_file),
        page_count=get_stored_file_page_count(stored_file),
        original_stored_file_id=submission.original_stored_file_id,
    )


def score_quality_warnings(
    quality_warnings: Any,
) -> tuple[list[dict[str, Any]], float]:
    """把质量告警序列化，并按告警种类折算成 0-1 的扫描质量分。

    客户端前处理上传与服务端管线共用这一套口径。分开各算一套的话，同一张卷子
    在两条路径下会给出不可比的百分比，老师只会以为扫描质量变了。
    """
    warnings = [
        {
            "code": warning.code,
            "severity": warning.severity,
            "message": warning.message,
        }
        for warning in quality_warnings
    ]
    # Do not make the score depend on page count by deducting the same risk
    # once per page. Score distinct failure modes by their actual severity.
    penalty_by_code = {
        "low_sharpness": 0.25,
        "page_aspect_outlier": 0.15,
        "vision_page_polygon_failed": 0.15,
        "vision_page_polygon_rejected": 0.10,
        "low_gutter_confidence": 0.10,
        "split_half_page_fallback": 0.08,
        "doc_unwarping_quality_rejected": 0.06,
        "doc_unwarping_unavailable": 0.06,
        "content_near_top_edge": 0.03,
        "content_near_bottom_edge": 0.03,
        "content_near_left_edge": 0.03,
        "content_near_right_edge": 0.03,
    }
    unique_warning_codes = {
        item["code"] for item in warnings if item["severity"] == "warning"
    }
    warning_penalty = sum(
        penalty_by_code.get(code, 0.05) for code in unique_warning_codes
    )
    warning_penalty += 0.01 * len(
        {item["code"] for item in warnings if item["severity"] == "info"}
    )
    return warnings, round(max(0.0, min(1.0, 1.0 - warning_penalty)), 4)


def build_preprocessing_metadata(preprocessed: Any) -> tuple[dict, float, str]:
    warnings, quality = score_quality_warnings(preprocessed.quality_warnings)
    status = (
        "ready"
        if preprocessed.quality_status == "pass" and quality >= 0.85
        else "review"
    )
    metadata = {
        "source": "mobile_document_preprocessing_v2",
        "scan_engine": settings.SCAN_ENGINE,
        "quality": {
            "status": preprocessed.quality_status,
            "score": quality,
            "warnings": warnings,
        },
        "detected_quad": preprocessed.detected_quad,
        "spread_size": list(preprocessed.spread_size),
        "split": {
            "strategy": preprocessed.split.strategy,
            "gutter_ratio": preprocessed.split.gutter_ratio,
            "gutter_confidence": preprocessed.split.gutter_confidence,
            "overlap_pixels": preprocessed.split.overlap_pixels,
        },
        "pages": [
            {
                "name": page.name,
                "x_start": page.x_start,
                "x_end": page.x_end,
                "width": int(page.image.shape[1]),
                "height": int(page.image.shape[0]),
                "source_quad": page.source_quad,
                "homography": page.homography,
                "quality": page.quality,
            }
            for page in preprocessed.pages
        ],
        "debug": preprocessed.debug,
    }
    return metadata, quality, status


def encode_preview_jpeg(image: np.ndarray, *, max_side: int = 1800) -> bytes:
    height, width = image.shape[:2]
    scale = min(max_side / max(height, width), 1.0)
    preview = image
    if scale < 1.0:
        preview = cv2.resize(
            image,
            (max(1, int(width * scale)), max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    ok, buffer = cv2.imencode(".jpg", preview, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    if not ok:
        raise PhotoPreprocessingError("Could not encode preprocessing preview")
    return buffer.tobytes()


def build_preprocessing_detected_overlay(
    *, source_contents: bytes, preprocessed: Any
) -> bytes:
    image_buffer = np.frombuffer(source_contents, dtype=np.uint8)
    image = cv2.imdecode(image_buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise PhotoPreprocessingError("Could not decode source image for overlay")

    overlay = image.copy()
    colors = [(0, 180, 255), (0, 255, 0), (255, 160, 0), (255, 0, 255)]
    for index, page in enumerate(preprocessed.pages, start=1):
        source_quad = getattr(page, "source_quad", None)
        if not source_quad:
            continue
        try:
            points = np.asarray(source_quad, dtype=np.float32)
        except (TypeError, ValueError):
            continue
        if points.shape != (4, 2) or not np.isfinite(points).all():
            continue
        color = colors[(index - 1) % len(colors)]
        int_points = points.astype("int32").reshape((-1, 1, 2))
        cv2.polylines(overlay, [int_points], isClosed=True, color=color, thickness=6)
        cv2.putText(
            overlay,
            f"page {index}",
            tuple(int_points[0, 0]),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            color,
            3,
            cv2.LINE_AA,
        )
    return encode_preview_jpeg(overlay)


def store_preprocessing_preview_files(
    *,
    session: SessionDep,
    owner_id: uuid.UUID,
    source_name: str,
    source_contents: bytes,
    preprocessed: Any,
) -> dict[str, Any]:
    preview_files: dict[str, Any] = {}
    try:
        overlay_bytes = build_preprocessing_detected_overlay(
            source_contents=source_contents,
            preprocessed=preprocessed,
        )
        overlay_file = store_generated_file(
            session=session,
            owner_id=owner_id,
            original_filename=f"{source_name}-detected-overlay.jpg",
            content_type="image/jpeg",
            contents=overlay_bytes,
            commit=False,
        )
        preview_files["detected_overlay"] = {
            "stored_file_id": str(overlay_file.id),
            "filename": overlay_file.original_filename,
            "content_type": overlay_file.content_type,
        }
    except (PhotoPreprocessingError, OSError, cv2.error):
        pass

    try:
        spread_bytes = encode_preview_jpeg(preprocessed.enhanced_spread)
        spread_file = store_generated_file(
            session=session,
            owner_id=owner_id,
            original_filename=f"{source_name}-corrected-spread.jpg",
            content_type="image/jpeg",
            contents=spread_bytes,
            commit=False,
        )
        preview_files["corrected_spread"] = {
            "stored_file_id": str(spread_file.id),
            "filename": spread_file.original_filename,
            "content_type": spread_file.content_type,
        }
    except (PhotoPreprocessingError, OSError, cv2.error):
        pass
    return preview_files


def preprocess_uploaded_image_file(
    *,
    session: SessionDep,
    owner_id: uuid.UUID,
    stored_file: StoredFile,
    preprocess_mode: Literal["auto", "force", "none"],
) -> tuple[StoredFile, dict | None, float | None, str, uuid.UUID | None]:
    if (
        preprocess_mode == "none"
        or stored_file.content_type not in SCAN_PHOTO_CONTENT_TYPES
    ):
        return stored_file, None, None, "not_required", None
    try:
        source_contents = get_stored_file_path(stored_file).read_bytes()
        preprocessed = preprocess_scan_photo_bytes(
            source_contents,
            filename=stored_file.original_filename,
            content_type=stored_file.content_type or "image/jpeg",
        )
        source_name = Path(stored_file.original_filename).stem
        processed_file = store_generated_file(
            session=session,
            owner_id=owner_id,
            original_filename=f"{source_name}-scanned.pdf",
            content_type="application/pdf",
            contents=preprocessed.pdf_bytes,
            commit=False,
        )
        metadata, quality, status_value = build_preprocessing_metadata(preprocessed)
        metadata["preview_files"] = store_preprocessing_preview_files(
            session=session,
            owner_id=owner_id,
            source_name=source_name,
            source_contents=source_contents,
            preprocessed=preprocessed,
        )
        return processed_file, metadata, quality, status_value, stored_file.id
    except (PhotoPreprocessingError, OSError) as exc:
        if preprocess_mode == "force":
            raise HTTPException(
                status_code=422,
                detail=f"Could not preprocess exam photo: {exc}",
            ) from exc
        return (
            stored_file,
            {
                "source": "mobile_document_preprocessing_v2",
                "scan_engine": settings.SCAN_ENGINE,
                "quality": {
                    "status": "review",
                    "score": 0.0,
                    "warnings": [
                        {
                            "code": "preprocessing_failed",
                            "severity": "warning",
                            "message": str(exc),
                        }
                    ],
                },
            },
            0.0,
            "review",
            None,
        )


def should_queue_image_preprocessing(
    *, stored_file: StoredFile, preprocess_mode: Literal["auto", "force", "none"]
) -> bool:
    return (
        preprocess_mode != "none"
        and stored_file.content_type in SCAN_PHOTO_CONTENT_TYPES
    )


def mark_preprocessing_enqueue_failed(
    *, session: SessionDep, documents: list[ExamDocument], exc: Exception
) -> None:
    message = str(exc).strip() or exc.__class__.__name__
    for document in documents:
        document.preprocessing_status = "failed"
        document.preprocessing_quality = 0.0
        document.preprocessing_metadata = {
            "source": "async_scan_preprocessing_v1",
            "scan_engine": settings.SCAN_ENGINE,
            "error": {
                "code": "enqueue_failed",
                "message": message[:500],
            },
        }
        session.add(document)
    session.commit()


def get_exam_document_for_user(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    document_id: uuid.UUID,
    require_write: bool = False,
) -> tuple[ExamDocument, StoredFile]:
    get_exam_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        require_write=require_write,
    )
    statement = (
        select(ExamDocument, StoredFile)
        .join(StoredFile, ExamDocument.stored_file_id == StoredFile.id)
        .where(ExamDocument.id == document_id, ExamDocument.exam_id == exam_id)
    )
    row = session.exec(statement).first()
    if not row:
        raise HTTPException(status_code=404, detail="Exam file not found")
    return row


def auto_rectify_exam_document_record(
    *,
    session: SessionDep,
    exam_document: ExamDocument,
    stored_file: StoredFile,
) -> tuple[StoredFile, ExamDocument]:
    source_file = get_exam_document_source_image(
        session=session,
        exam_document=exam_document,
        stored_file=stored_file,
    )
    source_path = get_stored_file_path(source_file)
    source_contents = source_path.read_bytes()
    preprocessed = preprocess_scan_photo_bytes(
        source_contents,
        filename=source_file.original_filename,
        content_type=source_file.content_type or "image/jpeg",
    )
    metadata, quality, status_value = build_preprocessing_metadata(preprocessed)
    metadata = {
        **metadata,
        "source": "auto_scan_engine_rectifier_v1",
        "scan_engine": settings.SCAN_ENGINE,
    }
    source_name = Path(source_file.original_filename).stem
    processed_file = store_generated_file(
        session=session,
        owner_id=source_file.uploaded_by_id,
        original_filename=f"{source_name}-auto-scanned.pdf",
        content_type="application/pdf",
        contents=preprocessed.pdf_bytes,
        commit=False,
    )
    metadata["preview_files"] = store_preprocessing_preview_files(
        session=session,
        owner_id=source_file.uploaded_by_id,
        source_name=source_name,
        source_contents=source_contents,
        preprocessed=preprocessed,
    )
    exam_document.stored_file_id = processed_file.id
    exam_document.original_stored_file_id = source_file.id
    exam_document.preprocessing_status = status_value
    exam_document.preprocessing_quality = quality
    exam_document.preprocessing_metadata = metadata
    session.add(exam_document)
    return processed_file, exam_document


def get_exam_document_source_image(
    *, session: SessionDep, exam_document: ExamDocument, stored_file: StoredFile
) -> StoredFile:
    source_file = stored_file
    if exam_document.original_stored_file_id:
        original = session.get(StoredFile, exam_document.original_stored_file_id)
        if original:
            source_file = original
    if source_file.content_type not in SCAN_PHOTO_CONTENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail="Manual document corner preprocessing requires the original JPG or PNG image",
        )
    return source_file


def normalized_quads_to_pixels(
    request: ExamDocumentQuadPreprocessRequest, *, image_width: int, image_height: int
) -> list[np.ndarray]:
    quads: list[np.ndarray] = []
    for page in request.pages:
        points = np.array(
            [[point.x * image_width, point.y * image_height] for point in page.points],
            dtype="float32",
        )
        if points.shape != (4, 2) or not np.isfinite(points).all():
            raise HTTPException(status_code=422, detail="Invalid page quad points")
        quads.append(points)
    return quads


def get_student_submission_for_user(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    submission_id: uuid.UUID,
    require_write: bool = False,
    skip_assigned_restriction: bool = False,
) -> tuple[StudentSubmission, StoredFile]:
    exam = get_exam_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        require_write=require_write,
    )
    statement = (
        select(StudentSubmission, StoredFile)
        .join(StoredFile, StudentSubmission.stored_file_id == StoredFile.id)
        .where(
            StudentSubmission.id == submission_id,
            StudentSubmission.exam_id == exam_id,
        )
    )
    row = session.exec(statement).first()
    if not row:
        raise HTTPException(status_code=404, detail="Student submission not found")
    # 共享批卷：被分配的非管理老师只能看到负责班级的答卷
    if not skip_assigned_restriction:
        restricted = restricted_assigned_classes(session, current_user, exam)
        if restricted is not None:
            class_ids, class_names = restricted
            if not submission_in_assigned_classes(
                session, row[0], class_ids, class_names
            ):
                raise HTTPException(
                    status_code=404, detail="Student submission not found"
                )
    return row


def assert_can_write_submission_annotations(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam: Exam,
    submission: StudentSubmission,
) -> None:
    """批注写权限：考试可写者（owner/校方管理/平台超管）放行；
    共享批卷中被分配的老师只能改负责班级的答卷，跨班 403。"""
    if can_write_exam(current_user, exam):
        return
    restricted = restricted_assigned_classes(session, current_user, exam)
    if restricted is not None:
        class_ids, class_names = restricted
        if submission_in_assigned_classes(session, submission, class_ids, class_names):
            return
    raise HTTPException(status_code=403, detail="无权批改非负责班级的答卷")


def get_exam_region_for_user(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    region_id: uuid.UUID,
    require_write: bool = False,
) -> ExamRegion:
    get_exam_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        require_write=require_write,
    )
    region = session.get(ExamRegion, region_id)
    if not region or region.exam_id != exam_id:
        raise HTTPException(status_code=404, detail="Exam region not found")
    return region


def get_standard_answer_for_user(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    answer_id: uuid.UUID,
    require_write: bool = False,
) -> StandardAnswer:
    get_exam_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        require_write=require_write,
    )
    answer = session.get(StandardAnswer, answer_id)
    if not answer or answer.exam_id != exam_id:
        raise HTTPException(status_code=404, detail="Standard answer not found")
    return answer


def get_question_region_for_standard_answer(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    region_id: uuid.UUID,
    require_write: bool = False,
) -> ExamRegion:
    region = get_exam_region_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        region_id=region_id,
        require_write=require_write,
    )
    if region.region_type != ExamRegionType.QUESTION:
        raise HTTPException(
            status_code=422,
            detail="Standard answers can only be attached to question regions",
        )
    return region


def get_submission_annotation_for_user(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    submission_id: uuid.UUID,
    annotation_id: uuid.UUID,
    require_write: bool = False,
) -> SubmissionAnnotation:
    get_student_submission_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        submission_id=submission_id,
        require_write=require_write,
    )
    annotation = session.get(SubmissionAnnotation, annotation_id)
    if not annotation or annotation.submission_id != submission_id:
        raise HTTPException(status_code=404, detail="Submission annotation not found")
    return annotation


def get_submission_annotation_for_write(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    submission_id: uuid.UUID,
    annotation_id: uuid.UUID,
) -> SubmissionAnnotation:
    """批注写端点取数：考试可见后按「可写考试 或 被分配老师负责班级」校验，
    被分配老师跨班写 403。"""
    exam = get_exam_for_user(
        session=session, current_user=current_user, exam_id=exam_id
    )
    submission, _stored_file = get_student_submission_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        submission_id=submission_id,
        skip_assigned_restriction=True,
    )
    assert_can_write_submission_annotations(
        session=session,
        current_user=current_user,
        exam=exam,
        submission=submission,
    )
    annotation = session.get(SubmissionAnnotation, annotation_id)
    if not annotation or annotation.submission_id != submission_id:
        raise HTTPException(status_code=404, detail="Submission annotation not found")
    return annotation


def _cached_pdf_page_preview(
    stored_file: StoredFile, path: Path, page_number: int
) -> bytes:
    """PDF 页面预览落盘缓存：按文件 id+页码存 JPEG，命中即读，避免每次重渲染。

    StoredFile 内容上传后不可变，缓存不需要失效逻辑。
    """
    cache_dir = Path(settings.STORAGE_CACHE_DIR) / "page-previews"
    cache_path = cache_dir / f"{stored_file.id}-p{page_number}.jpg"
    try:
        return cache_path.read_bytes()
    except OSError:
        pass
    contents = render_pdf_page_jpeg(path, page_number)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(contents)
    except OSError:
        # 缓存写不进去不影响出图
        pass
    return contents


def _warm_pdf_page_preview_cache(stored_file: StoredFile) -> None:
    """上传完成后预生成页面预览缓存，老师首次打开框选/批卷页不用等渲染。

    预热失败只影响首次加载速度，绝不能让上传本身失败。
    """
    if stored_file.content_type != "application/pdf":
        return
    path = get_stored_file_path(stored_file)
    try:
        page_count = get_pdf_page_count(path)
    except InvalidPdfError:
        return
    for page_number in range(1, page_count + 1):
        try:
            _cached_pdf_page_preview(stored_file, path, page_number)
        except (InvalidPdfError, IndexError):
            break


def build_page_image_response(*, stored_file: StoredFile, page_number: int) -> Response:
    path = get_stored_file_path(stored_file)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Stored file not found")
    if page_number < 1:
        raise HTTPException(status_code=422, detail="Page number must be at least 1")

    if stored_file.content_type == "application/pdf":
        try:
            contents = _cached_pdf_page_preview(stored_file, path, page_number)
        except InvalidPdfError:
            raise HTTPException(
                status_code=415, detail="Stored PDF could not be opened"
            )
        except IndexError:
            raise HTTPException(status_code=404, detail="PDF page not found")
        return Response(
            content=contents,
            media_type="image/jpeg",
            # 预览按文件 id+页码缓存落盘，内容不可变，长缓存安全
            headers={"Cache-Control": "private, max-age=31536000, immutable"},
        )

    if page_number != 1:
        raise HTTPException(status_code=404, detail="Image file has only one page")
    return FileResponse(
        path=path,
        media_type=stored_file.content_type or "application/octet-stream",
        filename=stored_file.original_filename,
    )


def read_stored_file_page_image_bytes(
    *, stored_file: StoredFile, page_number: int
) -> bytes:
    path = get_stored_file_path(stored_file)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Stored file not found")
    if page_number < 1:
        raise HTTPException(status_code=422, detail="Page number must be at least 1")
    if stored_file.content_type == "application/pdf":
        try:
            return render_pdf_page_png(path, page_number)
        except InvalidPdfError:
            raise HTTPException(
                status_code=415, detail="Stored PDF could not be opened"
            )
        except IndexError:
            raise HTTPException(status_code=404, detail="PDF page not found")
    if page_number != 1:
        raise HTTPException(status_code=404, detail="Image file has only one page")
    return path.read_bytes()


def crop_region_from_stored_file(
    *,
    stored_file: StoredFile,
    region: ExamRegion,
    page_number: int | None = None,
) -> bytes:
    try:
        return crop_region_png(
            stored_file=stored_file, region=region, page_number=page_number
        )
    except SubmissionCropError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/", response_model=ExamsPublic)
def read_exams(
    session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 100
) -> Any:
    visible = exams_visible_filter(session, current_user)
    count_statement = select(func.count()).select_from(Exam).where(visible)
    statement = (
        select(Exam)
        .where(visible)
        .order_by(col(Exam.created_at).desc())
        .offset(skip)
        .limit(limit)
    )

    count = session.exec(count_statement).one()
    exams = session.exec(statement).all()
    # 当前用户被分配的共享批卷考试（列表一次查询，避免逐考试回表）
    assigned_exam_ids = set(
        session.exec(
            select(GradingAssignment.exam_id).where(
                GradingAssignment.user_id == current_user.id
            )
        ).all()
    )
    return ExamsPublic(
        data=[
            build_exam_public(
                session=session,
                exam=exam,
                is_assigned=(
                    exam.shared_grading_enabled and exam.id in assigned_exam_ids
                ),
            )
            for exam in exams
        ],
        count=count,
    )


@router.post("/", response_model=ExamPublic)
def create_exam(
    *, session: SessionDep, current_user: CurrentUser, exam_in: ExamCreate
) -> Any:
    # 学校角色的考试归入本人学校；平台角色必须显式指定 org_id
    org_id = resolve_target_org_id(session, current_user, exam_in.org_id)
    if org_id is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "平台账号创建考试必须指定 org_id"
                if is_platform_user(current_user)
                else "账号未归属学校，无法创建考试"
            ),
        )
    exam = Exam.model_validate(
        exam_in.model_dump(exclude={"class_ids", "org_id"}),
        update={"owner_id": current_user.id, "org_id": org_id},
    )
    session.add(exam)
    session.flush()
    if exam_in.class_ids is not None:
        replace_exam_class_links(
            session=session,
            exam=exam,
            class_ids=exam_in.class_ids,
        )
    session.commit()
    session.refresh(exam)
    return build_exam_public(session=session, exam=exam)


# 注意：/question-bank 与 /compose 必须注册在 /{exam_id} 之前，
# 否则 "question-bank" 会被当作 exam_id 解析。
@router.get("/question-bank", response_model=QuestionBankPublic)
def read_question_bank(
    session: SessionDep,
    current_user: CurrentUser,
    knowledge_point: str | None = None,
    question_type: str | None = None,
    difficulty: int | None = None,
) -> Any:
    statement = (
        select(ExamQuestion, Exam)
        .join(Exam, ExamQuestion.exam_id == Exam.id)
        .where(ExamQuestion.status == ExamQuestionStatus.CONFIRMED)
    )
    # 题库按学校共享：本校已确认题目全员可见，跨校不可见
    if not is_platform_user(current_user):
        statement = statement.where(Exam.org_id == current_user.org_id)
    if knowledge_point:
        statement = statement.where(ExamQuestion.knowledge_point == knowledge_point)
    if question_type:
        statement = statement.where(ExamQuestion.question_type == question_type)
    if difficulty is not None:
        statement = statement.where(ExamQuestion.difficulty == difficulty)
    rows = list(session.exec(statement).all())

    published_scores: dict[uuid.UUID, float] = {}
    question_ids = [question.id for question, _exam in rows]
    if question_ids:
        answers = session.exec(
            select(StandardAnswer).where(
                col(StandardAnswer.question_id).in_(question_ids),
                StandardAnswer.current_revision_id.is_not(None),
            )
        ).all()
        published_scores = {answer.question_id: answer.max_score for answer in answers}

    entries = [
        QuestionBankEntryPublic(
            question_id=question.id,
            exam_id=exam.id,
            exam_title=exam.title,
            question_key=question.question_key,
            label=question.label,
            question_text=question.question_text[:200],
            question_type=question.question_type,
            knowledge_point=question.knowledge_point,
            difficulty=question.difficulty,
            max_score=published_scores.get(question.id),
        )
        for question, exam in rows
    ]
    entries.sort(key=lambda entry: (entry.exam_title, entry.question_key))
    return QuestionBankPublic(data=entries, count=len(entries))


@router.post("/compose", response_model=ExamPublic)
def compose_exam(
    *, session: SessionDep, current_user: CurrentUser, compose_in: ExamComposeRequest
) -> Any:
    question_ids = list(dict.fromkeys(compose_in.question_ids))
    questions = list(
        session.exec(
            select(ExamQuestion).where(
                col(ExamQuestion.id).in_(question_ids),
                ExamQuestion.status == ExamQuestionStatus.CONFIRMED,
            )
        ).all()
    )
    if len(questions) != len(question_ids):
        raise HTTPException(status_code=422, detail="部分题目不存在或尚未确认")
    questions_by_id = {question.id: question for question in questions}
    source_exam_ids = {question.exam_id for question in questions}
    source_exams = {
        exam.id: exam
        for exam in session.exec(
            select(Exam).where(col(Exam.id).in_(source_exam_ids))
        ).all()
    }
    if not is_platform_user(current_user):
        if current_user.org_id is None:
            raise HTTPException(status_code=400, detail="账号未归属学校，无法组卷")
        for source_exam in source_exams.values():
            if source_exam.org_id != current_user.org_id:
                raise HTTPException(status_code=403, detail="无权访问题目来源考试")
        org_id = current_user.org_id
    else:
        # 平台账号组卷：来源考试必须属于同一所学校，新卷挂到该校
        source_org_ids = {source_exam.org_id for source_exam in source_exams.values()}
        if len(source_org_ids) != 1:
            raise HTTPException(
                status_code=400, detail="题目来源考试必须属于同一所学校"
            )
        org_id = source_org_ids.pop()

    exam = Exam.model_validate(
        ExamCreate(title=compose_in.title),
        update={"owner_id": current_user.id, "org_id": org_id},
    )
    session.add(exam)
    session.flush()

    now = get_datetime_utc()
    for index, question_id in enumerate(question_ids, start=1):
        source = questions_by_id[question_id]
        question = ExamQuestion(
            exam_id=exam.id,
            question_key=str(index),
            label=source.label,
            question_text=source.question_text,
            question_type=source.question_type,
            knowledge_point=source.knowledge_point,
            difficulty=source.difficulty,
            status=ExamQuestionStatus.CONFIRMED,
            confirmed_by_id=current_user.id,
            confirmed_at=now,
            updated_at=now,
        )
        session.add(question)
        session.flush()

        source_answer = session.exec(
            select(StandardAnswer).where(
                StandardAnswer.question_id == source.id,
                StandardAnswer.current_revision_id.is_not(None),
            )
        ).first()
        if not source_answer or not source_answer.current_revision_id:
            continue
        source_revision = session.get(
            StandardAnswerRevision, source_answer.current_revision_id
        )
        if not source_revision:
            continue
        # 数字卷没有扫描区域，region 关联留空。
        answer = StandardAnswer(
            exam_id=exam.id,
            exam_region_id=None,
            question_id=question.id,
            answer_text=source_revision.answer_text,
            max_score=float(source_revision.max_score),
            rubric_text=source_revision.rubric_text,
            scoring_points=source_revision.scoring_points,
            status=StandardAnswerStatus.READY,
            version=1,
            source_provider=source_revision.source_provider,
            source_model=source_revision.source_model,
            generation_confidence=(
                float(source_revision.generation_confidence)
                if source_revision.generation_confidence is not None
                else None
            ),
            answer_hash=source_revision.content_hash,
            question_text=source_revision.question_text,
            question_type=source_revision.question_type,
            rubric_config={
                "schema_version": "confirmed-answer-revision-v1",
                "scoring_points": source_revision.scoring_points,
            },
            validation_report={
                "valid": True,
                "human_confirmed": True,
                "published": True,
            },
            published_at=now,
            published_by_id=current_user.id,
            updated_at=now,
        )
        session.add(answer)
        session.flush()
        revision = StandardAnswerRevision(
            standard_answer_id=answer.id,
            question_id=question.id,
            revision_number=1,
            question_key=question.question_key,
            question_text=source_revision.question_text,
            question_type=source_revision.question_type,
            answer_text=source_revision.answer_text,
            max_score=source_revision.max_score,
            rubric_text=source_revision.rubric_text,
            scoring_points=source_revision.scoring_points,
            source_provider=source_revision.source_provider,
            source_model=source_revision.source_model,
            generation_confidence=source_revision.generation_confidence,
            content_hash=source_revision.content_hash,
            status=StandardAnswerRevisionStatus.PUBLISHED,
            created_by_id=current_user.id,
            published_by_id=current_user.id,
            published_at=now,
        )
        session.add(revision)
        session.flush()
        answer.current_revision_id = revision.id
        session.add(answer)
    session.commit()
    session.refresh(exam)
    return exam


@router.get("/{exam_id}", response_model=ExamPublic)
def read_exam(
    session: SessionDep, current_user: CurrentUser, exam_id: uuid.UUID
) -> Any:
    exam = get_exam_for_user(
        session=session, current_user=current_user, exam_id=exam_id
    )
    is_assigned = exam.shared_grading_enabled and bool(
        assigned_class_ids(session, exam.id, current_user.id)
    )
    return build_exam_public(session=session, exam=exam, is_assigned=is_assigned)


def _build_grading_assignments_public(
    *, session: SessionDep, exam: Exam, include_candidates: bool = False
) -> GradingAssignmentsPublic:
    rows = session.exec(
        select(GradingAssignment, ClassGroup, User)
        .join(ClassGroup, GradingAssignment.class_id == ClassGroup.id)
        .join(User, GradingAssignment.user_id == User.id)
        .where(GradingAssignment.exam_id == exam.id)
        .order_by(col(ClassGroup.name).asc())
    ).all()
    assignments = [
        GradingAssignmentItemPublic(
            class_id=class_group.id,
            class_name=class_group.name,
            user_id=user.id,
            user_name=user.full_name or user.email,
        )
        for _assignment, class_group, user in rows
    ]
    assigned_class_id_set = {assignment.class_id for assignment in assignments}
    unassigned = [
        GradingAssignmentClassPublic(
            class_id=class_group.id, class_name=class_group.name
        )
        for class_group in exam_classes_with_submissions(session, exam)
        if class_group.id not in assigned_class_id_set
    ]
    candidates: list[GradingAssigneePublic] = []
    if include_candidates:
        users = session.exec(
            select(User)
            .where(
                User.org_id == exam.org_id,
                User.is_active.is_(True),
                col(User.role).in_(
                    [
                        UserRole.TEACHER,
                        UserRole.SCHOOL_ADMIN,
                        UserRole.SCHOOL_OWNER,
                    ]
                ),
            )
            .order_by(col(User.full_name).asc(), col(User.email).asc())
        ).all()
        user_ids = [user.id for user in users]
        links = (
            session.exec(
                select(TeacherClassLink).where(
                    col(TeacherClassLink.user_id).in_(user_ids)
                )
            ).all()
            if user_ids
            else []
        )
        class_ids_by_user: dict[uuid.UUID, list[uuid.UUID]] = {}
        for link in links:
            class_ids_by_user.setdefault(link.user_id, []).append(link.class_id)
        candidates = [
            GradingAssigneePublic(
                user_id=user.id,
                user_name=user.full_name or user.email,
                class_ids=class_ids_by_user.get(user.id, []),
            )
            for user in users
        ]
    return GradingAssignmentsPublic(
        enabled=exam.shared_grading_enabled,
        assignments=assignments,
        unassigned=unassigned,
        candidates=candidates,
    )


@router.get("/{exam_id}/grading-assignments", response_model=GradingAssignmentsPublic)
def read_grading_assignments(
    session: SessionDep, current_user: CurrentUser, exam_id: uuid.UUID
) -> Any:
    """共享批卷分配（只读）：本校非学生角色均可读；跨校 404。"""
    exam = session.get(Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    if not is_platform_user(current_user) and (
        current_user.org_id is None or current_user.org_id != exam.org_id
    ):
        raise HTTPException(status_code=404, detail="Exam not found")
    return _build_grading_assignments_public(
        session=session,
        exam=exam,
        include_candidates=can_write_exam(current_user, exam),
    )


@router.put("/{exam_id}/grading-assignments", response_model=GradingAssignmentsPublic)
def update_grading_assignments(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    assignments_in: GradingAssignmentsUpdate,
) -> Any:
    """整体覆盖共享批卷分配：exam owner / school_owner / school_admin 可写。

    校验：班级属于本考试学校；被分配用户是本校非 student 角色。
    """
    exam = session.get(Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    if not is_platform_user(current_user) and (
        current_user.org_id is None or current_user.org_id != exam.org_id
    ):
        raise HTTPException(status_code=404, detail="Exam not found")
    if not can_write_exam(current_user, exam):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    # 同班重复出现时以最后一条为准
    entries: dict[uuid.UUID, uuid.UUID] = {}
    for entry in assignments_in.assignments:
        entries[entry.class_id] = entry.user_id
    class_ids = list(entries)
    class_groups = (
        list(
            session.exec(
                select(ClassGroup).where(
                    col(ClassGroup.id).in_(class_ids),
                    ClassGroup.org_id == exam.org_id,
                )
            ).all()
        )
        if class_ids
        else []
    )
    if len(class_groups) != len(class_ids):
        raise HTTPException(
            status_code=400,
            detail="Invalid class_ids: 班级不存在或不属于本学校",
        )
    user_ids = list(dict.fromkeys(entries.values()))
    assignees = (
        list(session.exec(select(User).where(col(User.id).in_(user_ids))).all())
        if user_ids
        else []
    )
    for assignee in assignees:
        if (
            assignee.org_id != exam.org_id
            or assignee.role == UserRole.STUDENT
            or is_platform_user(assignee)
        ):
            raise HTTPException(
                status_code=400,
                detail="Invalid user_id: 被分配老师必须是本校非学生角色",
            )
    if len(assignees) != len(user_ids):
        raise HTTPException(status_code=400, detail="Invalid user_id: 用户不存在")
    for assignment in session.exec(
        select(GradingAssignment).where(GradingAssignment.exam_id == exam.id)
    ).all():
        session.delete(assignment)
    session.flush()
    for class_id, user_id in entries.items():
        session.add(
            GradingAssignment(exam_id=exam.id, class_id=class_id, user_id=user_id)
        )
    exam.shared_grading_enabled = assignments_in.enabled
    session.add(exam)
    session.commit()
    session.refresh(exam)
    return _build_grading_assignments_public(
        session=session, exam=exam, include_candidates=True
    )


@router.post("/{exam_id}/files", response_model=ExamDocumentPublic)
async def upload_exam_file(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    file: UploadFile,
    document_type: ExamDocumentType = Form(default=ExamDocumentType.BLANK_EXAM),
    preprocess: Literal["auto", "force", "none"] = Form(default="auto"),
) -> Any:
    exam = get_exam_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        require_write=True,
    )
    stored_file = await store_upload_file(
        session=session,
        current_user=current_user,
        file=file,
        owner_id=exam.owner_id,
        commit=False,
        validate_exam_file=True,
    )
    try:
        validate_uploaded_pdf(stored_file)
    except HTTPException:
        session.rollback()
        raise
    queue_preprocessing = should_queue_image_preprocessing(
        stored_file=stored_file, preprocess_mode=preprocess
    )
    active_file = stored_file
    try:
        preprocessing_status = "queued" if queue_preprocessing else "not_required"
        preprocessing_metadata = (
            {
                "source": "async_scan_preprocessing_v1",
                "scan_engine": settings.SCAN_ENGINE,
            }
            if queue_preprocessing
            else None
        )
        exam_document = ExamDocument(
            exam_id=exam.id,
            stored_file_id=active_file.id,
            original_stored_file_id=(stored_file.id if queue_preprocessing else None),
            document_type=document_type,
            sort_order=get_next_exam_document_sort_order(
                session=session,
                exam_id=exam.id,
                document_type=document_type,
            ),
            preprocessing_status=preprocessing_status,
            preprocessing_quality=None,
            preprocessing_metadata=preprocessing_metadata,
        )
        session.add(exam_document)
        session.commit()
    except Exception:
        session.rollback()
        cleanup_stored_file_path(get_stored_file_path(stored_file))
        if active_file.id != stored_file.id:
            cleanup_stored_file_path(get_stored_file_path(active_file))
        raise
    session.refresh(exam_document)
    session.refresh(active_file)
    if queue_preprocessing:
        try:
            process_exam_document_preprocessing.send(str(exam_document.id))
        except Exception as exc:
            mark_preprocessing_enqueue_failed(
                session=session, documents=[exam_document], exc=exc
            )
            session.refresh(exam_document)
    else:
        try:
            _warm_pdf_page_preview_cache(active_file)
        except Exception:
            logger.warning(
                "page preview warm-up failed",
                extra={"stored_file_id": str(active_file.id)},
                exc_info=True,
            )
    return build_exam_document_public(
        exam_document=exam_document, stored_file=active_file
    )


@router.post("/{exam_id}/files/batch", response_model=ExamDocumentsPublic)
async def upload_exam_files(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    files: list[UploadFile],
    document_type: ExamDocumentType = Form(default=ExamDocumentType.BLANK_EXAM),
    preprocess: Literal["auto", "force", "none"] = Form(default="auto"),
) -> ExamDocumentsPublic:
    exam = get_exam_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        require_write=True,
    )
    if not files:
        raise HTTPException(status_code=422, detail="At least one file is required")
    if len(files) > 50:
        raise HTTPException(status_code=422, detail="At most 50 files can be uploaded")

    stored_files: list[StoredFile] = []
    active_files: list[StoredFile] = []
    documents: list[ExamDocument] = []
    queued_documents: list[ExamDocument] = []
    next_sort_order = get_next_exam_document_sort_order(
        session=session,
        exam_id=exam.id,
        document_type=document_type,
    )
    try:
        for offset, file in enumerate(files):
            stored_file = await store_upload_file(
                session=session,
                current_user=current_user,
                file=file,
                owner_id=exam.owner_id,
                commit=False,
                validate_exam_file=True,
            )
            stored_files.append(stored_file)
            validate_uploaded_pdf(stored_file)
            queue_preprocessing = should_queue_image_preprocessing(
                stored_file=stored_file, preprocess_mode=preprocess
            )
            active_file = stored_file
            preprocessing_status = "queued" if queue_preprocessing else "not_required"
            preprocessing_metadata = (
                {
                    "source": "async_scan_preprocessing_v1",
                    "scan_engine": settings.SCAN_ENGINE,
                }
                if queue_preprocessing
                else None
            )
            active_files.append(active_file)
            document = ExamDocument(
                exam_id=exam.id,
                stored_file_id=active_file.id,
                original_stored_file_id=(
                    stored_file.id if queue_preprocessing else None
                ),
                document_type=document_type,
                sort_order=next_sort_order + offset,
                preprocessing_status=preprocessing_status,
                preprocessing_quality=None,
                preprocessing_metadata=preprocessing_metadata,
            )
            session.add(document)
            documents.append(document)
            if queue_preprocessing:
                queued_documents.append(document)
        session.commit()
    except Exception:
        session.rollback()
        for stored_file in stored_files:
            cleanup_stored_file_path(get_stored_file_path(stored_file))
        for active_file in active_files:
            if all(active_file.id != stored_file.id for stored_file in stored_files):
                cleanup_stored_file_path(get_stored_file_path(active_file))
        raise

    enqueue_failed: list[ExamDocument] = []
    for document in queued_documents:
        try:
            process_exam_document_preprocessing.send(str(document.id))
        except Exception:
            enqueue_failed.append(document)
    if enqueue_failed:
        mark_preprocessing_enqueue_failed(
            session=session,
            documents=enqueue_failed,
            exc=RuntimeError("Background preprocessing queue is unavailable"),
        )

    public_documents = []
    for document, active_file in zip(documents, active_files, strict=True):
        session.refresh(document)
        session.refresh(active_file)
        public_documents.append(
            build_exam_document_public(
                exam_document=document,
                stored_file=active_file,
            )
        )
    return ExamDocumentsPublic(data=public_documents, count=len(public_documents))


@router.patch("/{exam_id}/files/order", response_model=ExamDocumentsPublic)
def reorder_exam_files(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    order_in: ExamDocumentOrderUpdate,
) -> ExamDocumentsPublic:
    get_exam_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        require_write=True,
    )
    if len(order_in.document_ids) != len(set(order_in.document_ids)):
        raise HTTPException(
            status_code=422, detail="Document order contains duplicates"
        )

    documents = list(
        session.exec(
            select(ExamDocument).where(
                ExamDocument.exam_id == exam_id,
                col(ExamDocument.id).in_(order_in.document_ids),
            )
        ).all()
    )
    if len(documents) != len(order_in.document_ids):
        raise HTTPException(
            status_code=422,
            detail="Some exam documents do not belong to this exam",
        )
    document_type = documents[0].document_type
    if any(document.document_type != document_type for document in documents):
        raise HTTPException(
            status_code=422,
            detail="Only documents of the same type can be reordered together",
        )
    all_type_ids = set(
        session.exec(
            select(ExamDocument.id).where(
                ExamDocument.exam_id == exam_id,
                ExamDocument.document_type == document_type,
            )
        ).all()
    )
    if set(order_in.document_ids) != all_type_ids:
        raise HTTPException(
            status_code=422,
            detail="The complete document order is required",
        )

    by_id = {document.id: document for document in documents}
    for sort_order, document_id in enumerate(order_in.document_ids, start=1):
        document = by_id[document_id]
        document.sort_order = sort_order
        session.add(document)
    session.commit()

    rows = session.exec(
        select(ExamDocument, StoredFile)
        .join(StoredFile, ExamDocument.stored_file_id == StoredFile.id)
        .where(
            ExamDocument.exam_id == exam_id,
            ExamDocument.document_type == document_type,
        )
        .order_by(col(ExamDocument.sort_order).asc())
    ).all()
    public_documents = [
        build_exam_document_public(
            exam_document=document,
            stored_file=stored_file,
        )
        for document, stored_file in rows
    ]
    return ExamDocumentsPublic(data=public_documents, count=len(public_documents))


@router.get("/{exam_id}/files", response_model=ExamDocumentsPublic)
def read_exam_files(
    session: SessionDep, current_user: CurrentUser, exam_id: uuid.UUID
) -> Any:
    get_exam_for_user(session=session, current_user=current_user, exam_id=exam_id)

    count_statement = (
        select(func.count())
        .select_from(ExamDocument)
        .where(ExamDocument.exam_id == exam_id)
    )
    statement = (
        select(ExamDocument, StoredFile)
        .join(StoredFile, ExamDocument.stored_file_id == StoredFile.id)
        .where(ExamDocument.exam_id == exam_id)
        .order_by(
            col(ExamDocument.document_type).asc(),
            col(ExamDocument.sort_order).asc(),
            col(ExamDocument.created_at).asc(),
        )
    )

    count = session.exec(count_statement).one()
    rows = session.exec(statement).all()
    documents = [
        build_exam_document_public(exam_document=exam_document, stored_file=stored_file)
        for exam_document, stored_file in rows
    ]
    return ExamDocumentsPublic(data=documents, count=count)


@router.delete("/{exam_id}/files", response_model=ExamDocumentsPublic)
def clear_exam_paper_files(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
) -> ExamDocumentsPublic:
    exam = get_exam_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        require_write=True,
    )
    delete_exam_source_derived_data(session=session, exam_id=exam.id)
    documents = session.exec(
        select(ExamDocument).where(
            ExamDocument.exam_id == exam.id,
            ExamDocument.document_type == ExamDocumentType.BLANK_EXAM,
        )
    ).all()
    for document in documents:
        session.delete(document)
    session.commit()

    rows = session.exec(
        select(ExamDocument, StoredFile)
        .join(StoredFile, ExamDocument.stored_file_id == StoredFile.id)
        .where(ExamDocument.exam_id == exam.id)
        .order_by(
            col(ExamDocument.document_type).asc(),
            col(ExamDocument.sort_order).asc(),
            col(ExamDocument.created_at).asc(),
        )
    ).all()
    public_documents = [
        build_exam_document_public(
            exam_document=exam_document,
            stored_file=stored_file,
        )
        for exam_document, stored_file in rows
    ]
    return ExamDocumentsPublic(data=public_documents, count=len(public_documents))


@router.delete("/{exam_id}/files/{document_id}", response_model=ExamDocumentsPublic)
def delete_exam_file(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    document_id: uuid.UUID,
) -> ExamDocumentsPublic:
    exam = get_exam_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        require_write=True,
    )
    document = session.get(ExamDocument, document_id)
    if not document or document.exam_id != exam.id:
        raise HTTPException(status_code=404, detail="Exam file not found")

    document_type = document.document_type
    regions = session.exec(
        select(ExamRegion).where(ExamRegion.exam_document_id == document.id)
    ).all()
    for region in regions:
        session.delete(region)
    session.delete(document)
    session.commit()

    remaining_documents = session.exec(
        select(ExamDocument)
        .where(
            ExamDocument.exam_id == exam.id,
            ExamDocument.document_type == document_type,
        )
        .order_by(
            col(ExamDocument.sort_order).asc(), col(ExamDocument.created_at).asc()
        )
    ).all()
    for index, item in enumerate(remaining_documents, start=1):
        item.sort_order = index
        session.add(item)
    session.commit()

    rows = session.exec(
        select(ExamDocument, StoredFile)
        .join(StoredFile, ExamDocument.stored_file_id == StoredFile.id)
        .where(ExamDocument.exam_id == exam.id)
        .order_by(
            col(ExamDocument.document_type).asc(),
            col(ExamDocument.sort_order).asc(),
            col(ExamDocument.created_at).asc(),
        )
    ).all()
    public_documents = [
        build_exam_document_public(
            exam_document=exam_document,
            stored_file=stored_file,
        )
        for exam_document, stored_file in rows
    ]
    return ExamDocumentsPublic(data=public_documents, count=len(public_documents))


@router.post("/{exam_id}/files/reference-recognition")
def recognize_exam_files_with_reference_algorithm(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    recognition_in: ExamDocumentRecognitionRequest,
) -> dict:
    exam = get_exam_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        require_write=True,
    )
    if len(recognition_in.document_ids) != len(set(recognition_in.document_ids)):
        raise HTTPException(status_code=422, detail="Document list contains duplicates")
    rows = session.exec(
        select(ExamDocument, StoredFile)
        .join(StoredFile, ExamDocument.stored_file_id == StoredFile.id)
        .where(
            ExamDocument.exam_id == exam_id,
            col(ExamDocument.id).in_(recognition_in.document_ids),
        )
    ).all()
    by_id = {document.id: (document, stored_file) for document, stored_file in rows}
    documents = [
        by_id[document_id]
        for document_id in recognition_in.document_ids
        if document_id in by_id
    ]
    if len(documents) != len(recognition_in.document_ids):
        raise HTTPException(
            status_code=422,
            detail="Some exam documents do not belong to this exam",
        )
    try:
        defaults = get_grading_defaults(session, exam.org_id)
        return process_stored_files(
            documents=documents,
            verification_mode=recognition_in.verification_mode,
            provider=str(defaults["region_provider"]),
            model=str(defaults["region_model"]),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"参考算法识别失败：{exc}",
        ) from exc


@router.get("/{exam_id}/files/{document_id}/content")
def read_exam_file_content(
    session: SessionDep,
    exam_id: uuid.UUID,
    document_id: uuid.UUID,
    authorization: str | None = Header(default=None),
) -> FileResponse:
    user = get_user_from_authorization_header(
        session=session, authorization=authorization
    )
    exam_document, stored_file = get_exam_document_for_user(
        session=session,
        current_user=user,
        exam_id=exam_id,
        document_id=document_id,
    )
    path = get_stored_file_path(stored_file)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Stored file not found")

    return FileResponse(
        path=path,
        media_type=stored_file.content_type or "application/octet-stream",
        filename=stored_file.original_filename,
    )


@router.get("/{exam_id}/files/{document_id}/source-image")
def read_exam_file_source_image(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    document_id: uuid.UUID,
) -> FileResponse:
    exam_document, stored_file = get_exam_document_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        document_id=document_id,
    )
    source_file = get_exam_document_source_image(
        session=session,
        exam_document=exam_document,
        stored_file=stored_file,
    )
    path = get_stored_file_path(source_file)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Original image not found")
    return FileResponse(
        path=path,
        media_type=source_file.content_type or "application/octet-stream",
        filename=source_file.original_filename,
    )


@router.get("/{exam_id}/files/{document_id}/pages/{page_number}/image")
def read_exam_file_page_image(
    session: SessionDep,
    exam_id: uuid.UUID,
    document_id: uuid.UUID,
    page_number: int,
    authorization: str | None = Header(default=None),
) -> Response:
    user = get_user_from_authorization_header(
        session=session, authorization=authorization
    )
    exam_document, stored_file = get_exam_document_for_user(
        session=session,
        current_user=user,
        exam_id=exam_id,
        document_id=document_id,
    )
    return build_page_image_response(stored_file=stored_file, page_number=page_number)


@router.get("/{exam_id}/files/{document_id}/preprocessing-preview/{kind}")
def read_exam_file_preprocessing_preview(
    session: SessionDep,
    exam_id: uuid.UUID,
    document_id: uuid.UUID,
    kind: Literal["detected_overlay", "corrected_spread"],
    authorization: str | None = Header(default=None),
) -> FileResponse:
    user = get_user_from_authorization_header(
        session=session, authorization=authorization
    )
    exam_document, _stored_file = get_exam_document_for_user(
        session=session,
        current_user=user,
        exam_id=exam_id,
        document_id=document_id,
    )
    metadata = (
        exam_document.preprocessing_metadata
        if isinstance(exam_document.preprocessing_metadata, dict)
        else {}
    )
    preview_files = metadata.get("preview_files")
    if not isinstance(preview_files, dict):
        raise HTTPException(status_code=404, detail="Preprocessing preview not found")
    preview = preview_files.get(kind)
    if not isinstance(preview, dict):
        raise HTTPException(status_code=404, detail="Preprocessing preview not found")
    stored_file_id = preview.get("stored_file_id")
    if not stored_file_id:
        raise HTTPException(status_code=404, detail="Preprocessing preview not found")
    try:
        preview_file_id = uuid.UUID(str(stored_file_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Preprocessing preview not found")
    preview_file = session.get(StoredFile, preview_file_id)
    if not preview_file:
        raise HTTPException(status_code=404, detail="Preprocessing preview not found")
    path = get_stored_file_path(preview_file)
    if not path.exists():
        raise HTTPException(
            status_code=404, detail="Preprocessing preview file missing"
        )
    return FileResponse(
        path=path,
        media_type=preview_file.content_type or "image/jpeg",
        filename=preview_file.original_filename,
    )


@router.post(
    "/{exam_id}/files/{document_id}/preview-with-quads",
)
def preview_exam_file_with_quads(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    document_id: uuid.UUID,
    preprocess_in: ExamDocumentQuadPreprocessRequest,
) -> dict[str, Any]:
    exam_document, stored_file = get_exam_document_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        document_id=document_id,
    )
    source_file = get_exam_document_source_image(
        session=session,
        exam_document=exam_document,
        stored_file=stored_file,
    )
    source_path = get_stored_file_path(source_file)
    contents = source_path.read_bytes()
    image_buffer = np.frombuffer(contents, dtype=np.uint8)
    image = cv2.imdecode(image_buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=422, detail="Could not decode original image")
    height, width = image.shape[:2]
    page_quads = normalized_quads_to_pixels(
        preprocess_in,
        image_width=width,
        image_height=height,
    )
    try:
        preprocessed = preprocess_exam_photo_with_page_quads(
            contents,
            page_quads,
            detector=preprocess_in.detector,
            margin_mode=preprocess_in.margin_mode,
        )
    except PhotoPreprocessingError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Could not preview exam file with manual corners: {exc}",
        ) from exc

    metadata, quality, status_value = build_preprocessing_metadata(preprocessed)
    previews: list[dict[str, Any]] = []
    for index, page in enumerate(preprocessed.pages, start=1):
        ok, buffer = cv2.imencode(
            ".jpg", page.image, [int(cv2.IMWRITE_JPEG_QUALITY), 88]
        )
        if not ok:
            raise HTTPException(status_code=500, detail="Could not encode preview page")
        previews.append(
            {
                "pageNumber": index,
                "name": page.name,
                "width": int(page.image.shape[1]),
                "height": int(page.image.shape[0]),
                "imageUrl": "data:image/jpeg;base64,"
                + base64.b64encode(buffer).decode("ascii"),
                "orientation": page.quality.get("orientation"),
            }
        )

    return {
        "quality": quality,
        "status": status_value,
        "pageCount": len(previews),
        "pages": previews,
        "metadata": metadata,
    }


@router.post(
    "/{exam_id}/files/{document_id}/preprocess-with-quads",
    response_model=ExamDocumentPublic,
)
def preprocess_exam_file_with_quads(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    document_id: uuid.UUID,
    preprocess_in: ExamDocumentQuadPreprocessRequest,
) -> ExamDocumentPublic:
    exam_document, stored_file = get_exam_document_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        document_id=document_id,
        require_write=True,
    )
    source_file = get_exam_document_source_image(
        session=session,
        exam_document=exam_document,
        stored_file=stored_file,
    )
    source_path = get_stored_file_path(source_file)
    contents = source_path.read_bytes()
    image_buffer = np.frombuffer(contents, dtype=np.uint8)
    image = cv2.imdecode(image_buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=422, detail="Could not decode original image")
    height, width = image.shape[:2]
    page_quads = normalized_quads_to_pixels(
        preprocess_in,
        image_width=width,
        image_height=height,
    )
    try:
        preprocessed = preprocess_exam_photo_with_page_quads(
            contents,
            page_quads,
            detector=preprocess_in.detector,
            margin_mode=preprocess_in.margin_mode,
        )
        metadata, quality, status_value = build_preprocessing_metadata(preprocessed)
        metadata = {
            **metadata,
            "source": "manual_quad_document_preprocessing_v1",
            "manual_quad_request": {
                "detector": preprocess_in.detector,
                "margin_mode": preprocess_in.margin_mode,
                "pages": [
                    {
                        "label": page.label,
                        "points": [
                            {"x": point.x, "y": point.y} for point in page.points
                        ],
                    }
                    for page in preprocess_in.pages
                ],
            },
        }
        source_name = Path(source_file.original_filename).stem
        processed_file = store_generated_file(
            session=session,
            owner_id=source_file.uploaded_by_id,
            original_filename=f"{source_name}-manual-scanned.pdf",
            content_type="application/pdf",
            contents=preprocessed.pdf_bytes,
            commit=False,
        )
        metadata["preview_files"] = store_preprocessing_preview_files(
            session=session,
            owner_id=source_file.uploaded_by_id,
            source_name=source_name,
            source_contents=contents,
            preprocessed=preprocessed,
        )
        exam_document.stored_file_id = processed_file.id
        exam_document.original_stored_file_id = source_file.id
        exam_document.preprocessing_status = status_value
        exam_document.preprocessing_quality = quality
        exam_document.preprocessing_metadata = metadata
        session.add(exam_document)
        session.commit()
    except PhotoPreprocessingError as exc:
        session.rollback()
        raise HTTPException(
            status_code=422,
            detail=f"Could not preprocess exam file with manual corners: {exc}",
        ) from exc
    session.refresh(exam_document)
    session.refresh(processed_file)
    return build_exam_document_public(
        exam_document=exam_document,
        stored_file=processed_file,
    )


@router.post(
    "/{exam_id}/files/{document_id}/upload-preprocessed",
    response_model=ExamDocumentPublic,
)
def upload_client_preprocessed_pages(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    document_id: uuid.UUID,
    upload_in: ExamDocumentPreprocessedUploadRequest,
) -> ExamDocumentPublic:
    """Accept client-preprocessed pages (warped, enhanced, deskewed locally).

    The server only applies orientation normalization (Gemini) and PDF packaging.
    This offloads the heaviest CPU work (perspective warp, CLAHE, Hough deskew)
    to the browser while keeping API-key-protected Gemini calls server-side.
    """
    from app.services.exam_photo_preprocessing import (
        PreprocessedPage,
        SplitMetadata,
        build_page_quality_warnings,
        build_quality_warnings,
        encode_pdf,
        fine_deskew_page,
        normalize_reading_orientation,
        quality_status_from_warnings,
    )

    exam_document, stored_file = get_exam_document_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        document_id=document_id,
        require_write=True,
    )
    source_file = get_exam_document_source_image(
        session=session,
        exam_document=exam_document,
        stored_file=stored_file,
    )

    pages: list[PreprocessedPage] = []
    current_x = 0
    orientation_attempts: list[dict[str, Any]] = []
    processed_file = None

    try:
        for page_data in upload_in.pages:
            # Decode base64 JPEG
            try:
                raw = base64.b64decode(page_data.image_base64, validate=True)
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid base64 for page '{page_data.name}': {exc}",
                ) from exc

            image_buffer = np.frombuffer(raw, dtype=np.uint8)
            image = cv2.imdecode(image_buffer, cv2.IMREAD_COLOR)
            if image is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"Could not decode JPEG for page '{page_data.name}'",
                )

            # Lightweight deskew pass to correct any browser/WASM precision drift.
            deskewed, deskew_meta = fine_deskew_page(image)
            # Orientation normalization (Gemini) — the only server-side ML step
            # in the client-preprocessed path.
            oriented, orientation_meta = normalize_reading_orientation(deskewed)
            orientation_attempts.append(
                {"name": page_data.name, **orientation_meta, "deskew": deskew_meta}
            )

            width = oriented.shape[1]
            height = oriented.shape[0]
            pages.append(
                PreprocessedPage(
                    name=page_data.name,
                    image=oriented,
                    x_start=current_x,
                    x_end=current_x + width,
                    source_quad=(
                        page_data.source_quad
                        if page_data.source_quad
                        else [[0, 0], [width, 0], [width, height], [0, height]]
                    ),
                    quality={
                        "client_preprocessed": True,
                        "detector": upload_in.detector,
                        "orientation": orientation_meta,
                        "deskew": deskew_meta,
                    },
                )
            )
            current_x += width

        # Package as PDF
        pdf_bytes = encode_pdf(pages)

        # 质量判定与服务端管线共用 build_quality_warnings + 同一张扣分表。
        # 各算一套的话，同一张卷子在两条路径下会给出不可比的百分比，
        # 老师只会以为扫描质量变了。
        # low_sharpness 判的是原始照片，所以这里把原图读出来解一次码：
        # 相比两次 Gemini 转正（约 10 秒）这点开销可忽略，换来的是
        # 「照片模糊」「顶部内容靠近裁切边缘」这类该复核的提示不会丢。
        original_image = cv2.imdecode(
            np.frombuffer(
                get_stored_file_path(source_file).read_bytes(), dtype=np.uint8
            ),
            cv2.IMREAD_COLOR,
        )
        split_metadata = SplitMetadata(
            strategy="client_provided",
            gutter_ratio=0.5 if len(pages) > 1 else None,
            gutter_confidence=1.0,
            overlap_pixels=0,
        )
        quality_warnings = (
            build_page_quality_warnings(pages)
            if original_image is None
            else build_quality_warnings(
                original=original_image,
                pages=pages,
                split=split_metadata,
                partial_landscape=False,
            )
        )
        warnings_json, quality_score = score_quality_warnings(quality_warnings)
        quality_status = quality_status_from_warnings(quality_warnings)
        # preprocessing_status 是给界面看的（前端只认 ready/review/failed），
        # metadata.quality.status 是内部口径（pass/review）。早期版本把 "pass"
        # 直接写进 preprocessing_status，界面上就会出现生硬的「pass」徽章。
        status_value = (
            "ready" if quality_status == "pass" and quality_score >= 0.85 else "review"
        )
        metadata: dict[str, Any] = {
            "source": "client_preprocessed_upload_v1",
            "detector": upload_in.detector,
            "margin_mode": upload_in.margin_mode,
            "page_count": len(pages),
            "spread_size": [
                current_x,
                max((p.image.shape[0] for p in pages), default=0),
            ],
            "split": {
                "strategy": split_metadata.strategy,
                "gutter_ratio": split_metadata.gutter_ratio,
                "gutter_confidence": split_metadata.gutter_confidence,
                "overlap_pixels": split_metadata.overlap_pixels,
            },
            "quality": {
                "status": quality_status,
                "score": quality_score,
                "warnings": warnings_json,
            },
            "orientation_attempts": orientation_attempts,
            "timings": {},
            "debug": {
                "engine": "client_opencvjs_upload_v1",
                "page_detector": upload_in.detector,
            },
        }

        source_name = Path(source_file.original_filename).stem
        processed_file = store_generated_file(
            session=session,
            owner_id=source_file.uploaded_by_id,
            original_filename=f"{source_name}-client-scanned.pdf",
            content_type="application/pdf",
            contents=pdf_bytes,
            commit=False,
        )

        exam_document.stored_file_id = processed_file.id
        exam_document.original_stored_file_id = source_file.id
        exam_document.preprocessing_status = status_value
        exam_document.preprocessing_quality = quality_score
        exam_document.preprocessing_metadata = metadata
        session.add(exam_document)
        session.commit()
        session.refresh(exam_document)
        session.refresh(processed_file)

        try:
            _warm_pdf_page_preview_cache(processed_file)
        except Exception:
            logger.warning(
                "page preview warm-up failed",
                extra={"stored_file_id": str(processed_file.id)},
                exc_info=True,
            )

        return build_exam_document_public(
            exam_document=exam_document,
            stored_file=processed_file,
        )
    except HTTPException:
        raise
    except Exception as exc:
        session.rollback()
        if processed_file is not None:
            try:
                cleanup_stored_file_path(get_stored_file_path(processed_file))
            except Exception:
                pass
        raise HTTPException(
            status_code=422,
            detail=f"Failed to process client-preprocessed upload: {exc}",
        ) from exc


@router.post(
    "/{exam_id}/files/{document_id}/auto-rectify",
    response_model=ExamDocumentPublic,
)
def auto_rectify_exam_file(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    document_id: uuid.UUID,
) -> ExamDocumentPublic:
    exam_document, stored_file = get_exam_document_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        document_id=document_id,
        require_write=True,
    )
    try:
        processed_file, exam_document = auto_rectify_exam_document_record(
            session=session,
            exam_document=exam_document,
            stored_file=stored_file,
        )
        session.commit()
    except (PhotoPreprocessingError, OSError) as exc:
        session.rollback()
        raise HTTPException(
            status_code=422,
            detail=f"Could not auto-rectify exam file: {exc}",
        ) from exc

    session.refresh(exam_document)
    session.refresh(processed_file)
    return build_exam_document_public(
        exam_document=exam_document,
        stored_file=processed_file,
    )


@router.post(
    "/{exam_id}/files/auto-rectify",
    response_model=ExamDocumentsPublic,
)
def auto_rectify_exam_files(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
) -> ExamDocumentsPublic:
    get_exam_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        require_write=True,
    )
    rows = session.exec(
        select(ExamDocument, StoredFile)
        .join(StoredFile, ExamDocument.stored_file_id == StoredFile.id)
        .where(
            ExamDocument.exam_id == exam_id,
            ExamDocument.document_type == ExamDocumentType.BLANK_EXAM,
        )
        .order_by(
            col(ExamDocument.sort_order).asc(),
            col(ExamDocument.created_at).asc(),
        )
    ).all()
    if not rows:
        raise HTTPException(status_code=422, detail="No exam files to auto-rectify")

    processed_by_document_id: dict[uuid.UUID, StoredFile] = {}
    try:
        for exam_document, stored_file in rows:
            processed_file, updated_document = auto_rectify_exam_document_record(
                session=session,
                exam_document=exam_document,
                stored_file=stored_file,
            )
            processed_by_document_id[updated_document.id] = processed_file
        session.commit()
    except (PhotoPreprocessingError, OSError) as exc:
        session.rollback()
        raise HTTPException(
            status_code=422,
            detail=f"Could not auto-rectify all exam files: {exc}",
        ) from exc

    public_documents = []
    for exam_document, _old_stored_file in rows:
        session.refresh(exam_document)
        stored_file = processed_by_document_id.get(exam_document.id)
        if stored_file is None:
            stored_file = session.get(StoredFile, exam_document.stored_file_id)
        if stored_file is None:
            raise HTTPException(status_code=500, detail="Auto-rectified file missing")
        session.refresh(stored_file)
        public_documents.append(
            build_exam_document_public(
                exam_document=exam_document,
                stored_file=stored_file,
            )
        )
    return ExamDocumentsPublic(data=public_documents, count=len(public_documents))


@router.get(
    "/{exam_id}/files/{document_id}/region-candidates",
    response_model=ExamRegionCandidatesPublic,
)
def read_exam_region_candidates(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    document_id: uuid.UUID,
    page_number: int = 1,
    engine: QuestionSegmentationEngine = QUESTION_SEGMENTATION_ENGINE,
) -> ExamRegionCandidatesPublic:
    started_perf = time.perf_counter()
    if engine not in {
        QUESTION_SEGMENTATION_ENGINE,
        OCR_ANCHOR_ENGINE_NAME,
        GEMINI_LAYOUT_ENGINE_NAME,
    }:
        raise HTTPException(
            status_code=422, detail=f"Unsupported segmentation engine: {engine}"
        )
    exam_document, stored_file = get_exam_document_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        document_id=document_id,
    )
    page_bytes = read_stored_file_page_image_bytes(
        stored_file=stored_file,
        page_number=page_number,
    )
    try:
        image = decode_image(page_bytes)
    except ValueError:
        raise HTTPException(status_code=422, detail="Could not decode page image")
    orientation_ms = 0
    layout_ms = 0
    refinement_ms = 0
    rotation = 0
    upright_image = None
    provider = None
    provider_label = None
    requested_provider = None
    provider_failover_count = 0
    if engine == GEMINI_LAYOUT_ENGINE_NAME:
        try:
            exam = session.get(Exam, exam_id)
            layout_defaults = get_grading_defaults(
                session, exam.org_id if exam else None
            )
            layout_payload = layout_stored_file(
                stored_file=stored_file,
                page_numbers=[page_number],
                assume_upright=bool(exam_document.preprocessing_status == "completed"),
                provider=str(layout_defaults["region_provider"]),
                model=str(layout_defaults["region_model"]),
            )
            layouts = [
                item
                for item in layout_payload.get("layouts", [])
                if isinstance(item, dict)
            ]
            layout = next(
                (
                    item
                    for item in layouts
                    if str(item.get("pageId") or "") == f"page-{page_number}"
                ),
                layouts[page_number - 1] if 0 <= page_number - 1 < len(layouts) else {},
            )
            raw_regions = refine_stacked_question_regions(layout.get("regions", []))
            used_model = "reference-node"
            layout_ms = int(
                layout.get("regionModelElapsedMs", layout.get("regionElapsedMs", 0))
            )
            refinement_ms = int(layout.get("refinementElapsedMs", 0))
            orientation_ms = int(layout.get("orientationElapsedMs", 0))
            rotation = int(layout.get("rotation", 0) or 0)
            upright_image = layout.get("uprightImage")
            provider = str(layout.get("provider") or "") or None
            provider_label = str(layout.get("providerLabel") or "") or None
            requested_provider = str(layout.get("requestedProvider") or "") or None
            provider_failover_count = int(layout.get("providerFailoverCount", 0) or 0)
            candidates = []
            for index, region in enumerate(raw_regions, start=1):
                try:
                    ymin = max(0.0, min(1000.0, float(region.get("ymin", 0))))
                    xmin = max(0.0, min(1000.0, float(region.get("xmin", 0))))
                    ymax = max(ymin + 1.0, min(1000.0, float(region.get("ymax", 1000))))
                    xmax = max(xmin + 1.0, min(1000.0, float(region.get("xmax", 1000))))
                except (TypeError, ValueError):
                    continue
                question_number = str(region.get("questionNumber") or "").strip()
                label = str(region.get("label") or question_number or f"第{index}题")
                refinement = region.get("refinement")
                if not isinstance(refinement, dict):
                    refinement = {}
                try:
                    confidence = max(
                        0.0,
                        min(
                            1.0,
                            float(
                                refinement.get(
                                    "confidence",
                                    region.get("confidence", 0.75),
                                )
                            ),
                        ),
                    )
                except (TypeError, ValueError):
                    confidence = 0.75
                reasons = ["reference-analyzeLayout", "question-number-bounds"]
                if refinement.get("applied"):
                    reasons.append("horizontal-projection-snap")
                candidates.append(
                    ExamRegionCandidate(
                        label=label,
                        region_type=ExamRegionType.QUESTION,
                        page_number=page_number,
                        x=round(xmin / 1000, 4),
                        y=round(ymin / 1000, 4),
                        width=round((xmax - xmin) / 1000, 4),
                        height=round((ymax - ymin) / 1000, 4),
                        confidence=confidence,
                        source=f"gemini_layout:{used_model}",
                        reasons=reasons,
                    )
                )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Gemini 版面分析失败，两个提供者均不可用；"
                    "已保留上一次候选区域，请稍后重试。"
                ),
            ) from exc
    else:
        candidates = find_question_region_candidates(
            image, page_number=page_number, engine=engine
        )
    return ExamRegionCandidatesPublic(
        data=candidates,
        count=len(candidates),
        page_number=page_number,
        engine=engine,
        elapsed_ms=round((time.perf_counter() - started_perf) * 1000),
        orientation_ms=orientation_ms,
        layout_ms=layout_ms,
        refinement_ms=refinement_ms,
        rotation=rotation,
        upright_image=upright_image,
        provider=provider,
        provider_label=provider_label,
        requested_provider=requested_provider,
        provider_failover_count=provider_failover_count,
    )


@router.post("/{exam_id}/files/{document_id}/reference-recognition")
def recognize_exam_document_with_reference_algorithm(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    document_id: uuid.UUID,
) -> dict:
    _document, stored_file = get_exam_document_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        document_id=document_id,
        require_write=True,
    )
    try:
        exam = session.get(Exam, exam_id)
        defaults = get_grading_defaults(session, exam.org_id if exam else None)
        return process_stored_file(
            stored_file=stored_file,
            provider=str(defaults["region_provider"]),
            model=str(defaults["region_model"]),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"参考算法识别失败：{exc}",
        ) from exc


@router.post("/{exam_id}/files/{document_id}/pages/{page_number}/reference-recognition")
def recognize_exam_document_page_with_reference_algorithm(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    document_id: uuid.UUID,
    page_number: int,
) -> dict:
    document, stored_file = get_exam_document_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        document_id=document_id,
        require_write=True,
    )
    # 结果按 文件+页 落盘缓存：识别要约 1 分钟，弱网络下客户端长连接可能
    # 中断，重试时命中缓存秒回，不会白等第二轮模型调用。文件内容不可变。
    cache_dir = Path(settings.STORAGE_CACHE_DIR) / "reference-recognition"
    cache_path = cache_dir / f"{stored_file.id}-p{page_number}.json"
    try:
        cached = json.loads(cache_path.read_bytes())
        if isinstance(cached, dict) and cached.get("results") is not None:
            return cached
    except (OSError, ValueError):
        pass
    documents = session.exec(
        select(ExamDocument, StoredFile)
        .join(StoredFile, ExamDocument.stored_file_id == StoredFile.id)
        .where(
            ExamDocument.exam_id == exam_id,
            ExamDocument.document_type == document.document_type,
        )
        .order_by(
            col(ExamDocument.sort_order).asc(),
            col(ExamDocument.created_at).asc(),
        )
    ).all()
    try:
        exam = session.get(Exam, exam_id)
        defaults = get_grading_defaults(session, exam.org_id if exam else None)
        result = process_stored_file_page_context(
            documents=list(documents),
            target_document_id=document.id,
            target_page_number=page_number,
            context_radius=1,
            provider=str(defaults["region_provider"]),
            model=str(defaults["region_model"]),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"参考算法当前页识别失败：{exc}",
        ) from exc
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(json.dumps(result, ensure_ascii=False).encode())
    except OSError:
        pass
    return result


@router.post("/{exam_id}/submissions", response_model=StudentSubmissionPublic)
async def upload_student_submission(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    file: UploadFile,
    original_file: UploadFile | None = File(default=None),
    student_name: str | None = Form(default=None),
    student_identifier: str | None = Form(default=None),
    class_name: str | None = Form(default=None),
    preprocess: Literal["auto", "force", "none"] = Form(default="auto"),
    client_quality: float | None = Form(default=None, ge=0.0, le=1.0),
) -> Any:
    exam = get_exam_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        require_write=True,
    )
    # 客户端本地预处理路径：原始照片随首屏一并上传留存，
    # client_quality 为浏览器内文档检测的置信度。
    client_original_file: StoredFile | None = None
    if original_file is not None:
        validate_scan_photo_upload_file(original_file)
        original_contents = await read_upload_file_bytes(file=original_file)
        assert_allowed_signature(
            contents_start=original_contents[:16],
            allowed_content_types=SCAN_PHOTO_CONTENT_TYPES,
            content_type=original_file.content_type,
        )
        client_original_file = store_generated_file(
            session=session,
            owner_id=exam.owner_id,
            original_filename=original_file.filename or "original-photo.jpg",
            content_type=original_file.content_type or "image/jpeg",
            contents=original_contents,
            commit=False,
        )
    zip_upload = is_zip_upload(filename=file.filename, content_type=file.content_type)
    stored_file = await store_upload_file(
        session=session,
        current_user=current_user,
        file=file,
        owner_id=exam.owner_id,
        commit=False,
        validate_exam_file=True,
        max_bytes=MAX_ZIP_UPLOAD_BYTES if zip_upload else MAX_UPLOAD_BYTES,
        too_large_status=(
            status.HTTP_422_UNPROCESSABLE_ENTITY
            if zip_upload
            else status.HTTP_413_CONTENT_TOO_LARGE
        ),
    )
    try:
        validate_uploaded_pdf(stored_file)
    except HTTPException:
        session.rollback()
        raise
    active_file = stored_file
    zip_note: str | None = None
    try:
        if zip_upload:
            # zip 答卷包：解包照片 → 逐张预处理 → 合并多页 PDF；
            # 原始 zip 作为 original 留存，答卷文件用生成的 PDF。
            zip_contents = get_stored_file_path(stored_file).read_bytes()
            merged_pdf, image_count, preprocessed_count = build_pdf_bytes_from_zip(
                zip_contents, preprocess_mode=preprocess
            )
            source_name = Path(stored_file.original_filename).stem
            active_file = store_generated_file(
                session=session,
                owner_id=exam.owner_id,
                original_filename=f"{source_name}-scanned.pdf",
                content_type="application/pdf",
                contents=merged_pdf,
                commit=False,
            )
            preprocessing_metadata = None
            preprocessing_quality = None
            preprocessing_status = "not_required"
            original_file_id = stored_file.id
            zip_note = (
                f"ZIP 解包：{image_count} 张照片合并为一份答卷，"
                f"{preprocessed_count} 张已自动校正"
            )
        else:
            (
                active_file,
                preprocessing_metadata,
                preprocessing_quality,
                preprocessing_status,
                original_file_id,
            ) = preprocess_uploaded_image_file(
                session=session,
                owner_id=exam.owner_id,
                stored_file=stored_file,
                preprocess_mode=preprocess,
            )
        if client_original_file is not None:
            # 客户端本地预处理：显式上传的原始照片优先作为原图留存
            original_file_id = client_original_file.id
        submission = StudentSubmission(
            exam_id=exam.id,
            stored_file_id=active_file.id,
            original_stored_file_id=original_file_id,
            student_name=student_name,
            student_identifier=student_identifier,
            class_name=class_name,
            status=StudentSubmissionStatus.REGISTRATION_PENDING,
            registration_status=SubmissionRegistrationStatus.PENDING,
            registration_quality=(
                client_quality if client_quality is not None else preprocessing_quality
            ),
            registration_notes=(
                f"客户端本地预处理；检测置信度 {round(client_quality * 100)}%"
                if client_quality is not None
                else (
                    zip_note
                    if zip_note is not None
                    else (
                        f"scan_preprocessing={preprocessing_status}"
                        if preprocessing_metadata is not None
                        else None
                    )
                )
            ),
            registration_homography=preprocessing_metadata,
        )
        student = resolve_student_for_submission(
            session=session,
            owner_id=exam.owner_id,
            org_id=exam.org_id,
            class_name=class_name,
            student_name=student_name,
        )
        if student is not None:
            submission.student_id = student.id
        session.add(submission)
        session.commit()
    except Exception:
        session.rollback()
        cleanup_stored_file_path(get_stored_file_path(stored_file))
        if active_file.id != stored_file.id:
            cleanup_stored_file_path(get_stored_file_path(active_file))
        if client_original_file is not None:
            cleanup_stored_file_path(get_stored_file_path(client_original_file))
        raise
    session.refresh(submission)
    session.refresh(active_file)
    return build_student_submission_public(
        submission=submission, stored_file=active_file
    )


@router.get("/{exam_id}/submissions", response_model=StudentSubmissionsPublic)
def read_student_submissions(
    session: SessionDep, current_user: CurrentUser, exam_id: uuid.UUID
) -> Any:
    exam = get_exam_for_user(
        session=session, current_user=current_user, exam_id=exam_id
    )
    count_statement = (
        select(func.count())
        .select_from(StudentSubmission)
        .where(StudentSubmission.exam_id == exam_id)
    )
    statement = (
        select(StudentSubmission, StoredFile)
        .join(StoredFile, StudentSubmission.stored_file_id == StoredFile.id)
        .where(StudentSubmission.exam_id == exam_id)
        .order_by(col(StudentSubmission.created_at).desc())
    )
    # 共享批卷：被分配的非管理老师只看到负责班级的答卷
    restricted = restricted_assigned_classes(session, current_user, exam)
    if restricted is not None:
        class_filter = submission_class_filter(*restricted)
        count_statement = count_statement.where(class_filter)
        statement = statement.where(class_filter)
    count = session.exec(count_statement).one()
    rows = session.exec(statement).all()
    submissions = [
        build_student_submission_public(submission=submission, stored_file=stored_file)
        for submission, stored_file in rows
    ]
    return StudentSubmissionsPublic(data=submissions, count=count)


@router.get("/{exam_id}/scores/summary", response_model=ExamScoreSummaryPublic)
def read_exam_scores_summary(
    session: SessionDep, current_user: CurrentUser, exam_id: uuid.UUID
) -> Any:
    exam = get_exam_for_user(
        session=session, current_user=current_user, exam_id=exam_id
    )
    restricted = restricted_assigned_classes(session, current_user, exam)
    return _build_exam_scores_summary(
        session=session, exam_id=exam_id, restricted=restricted
    )


def _build_exam_scores_summary(
    *,
    session: Session,
    exam_id: uuid.UUID,
    restricted: tuple[list[uuid.UUID], list[str]] | None = None,
) -> ExamScoreSummaryPublic:
    submissions_statement = (
        select(StudentSubmission)
        .where(StudentSubmission.exam_id == exam_id)
        .order_by(
            col(StudentSubmission.class_name).asc(),
            col(StudentSubmission.student_name).asc(),
            col(StudentSubmission.created_at).asc(),
        )
    )
    if restricted is not None:
        submissions_statement = submissions_statement.where(
            submission_class_filter(*restricted)
        )
    submissions = list(session.exec(submissions_statement).all())
    annotations = (
        list(
            session.exec(
                select(SubmissionAnnotation).where(
                    col(SubmissionAnnotation.submission_id).in_(
                        [submission.id for submission in submissions]
                    )
                )
            ).all()
        )
        if submissions
        else []
    )
    annotations_by_submission: dict[uuid.UUID, list[SubmissionAnnotation]] = {}
    for annotation in annotations:
        annotations_by_submission.setdefault(annotation.submission_id, []).append(
            annotation
        )
    stored_files_by_id: dict[uuid.UUID, StoredFile] = (
        {
            stored_file.id: stored_file
            for stored_file in session.exec(
                select(StoredFile).where(
                    col(StoredFile.id).in_(
                        [submission.stored_file_id for submission in submissions]
                    )
                )
            ).all()
        }
        if submissions
        else {}
    )
    rows: list[ExamScoreSummaryRow] = []
    for submission in submissions:
        submission_annotations = annotations_by_submission.get(submission.id, [])
        # 同一题号（label）可能有多次评分：优先取教师复核后的最终分
        # （score_source == "human"），否则取最新的 AI 建议分。
        by_label: dict[str, list[SubmissionAnnotation]] = {}
        for annotation in submission_annotations:
            by_label.setdefault(annotation.label, []).append(annotation)
        questions: list[ExamScoreSummaryQuestion] = []
        for label, group in by_label.items():
            chosen = next(
                (
                    annotation
                    for annotation in group
                    if annotation.score_source == "human"
                ),
                max(
                    group,
                    key=lambda annotation: (
                        annotation.created_at is not None,
                        annotation.created_at,
                    ),
                ),
            )
            questions.append(
                ExamScoreSummaryQuestion(
                    label=label,
                    score=chosen.score,
                    max_score=chosen.max_score,
                    score_source=(
                        "final" if chosen.score_source == "human" else "ai_suggested"
                    ),
                    annotation_id=chosen.id,
                )
            )
        questions.sort(key=lambda question: question.label)
        pending_review_count = sum(
            1
            for annotation in submission_annotations
            if annotation.grading_status == AnnotationGradingStatus.NEEDS_REVIEW
            and annotation.score_source != "human"
        )
        if questions:
            scores = [question.score for question in questions]
            max_scores = [question.max_score for question in questions]
            total_score = (
                round(sum(score for score in scores if score is not None), 2)
                if any(score is not None for score in scores)
                else None
            )
            total_max_score = (
                round(sum(score for score in max_scores if score is not None), 2)
                if any(score is not None for score in max_scores)
                else None
            )
        else:
            total_score = None
            total_max_score = None
        rows.append(
            ExamScoreSummaryRow(
                submission_id=submission.id,
                student_name=submission.student_name,
                student_identifier=submission.student_identifier,
                class_name=submission.class_name,
                total_score=total_score,
                total_max_score=total_max_score,
                questions=questions,
                status=submission.status,
                registration_status=submission.registration_status,
                registration_quality=submission.registration_quality,
                registration_notes=submission.registration_notes,
                page_count=(
                    get_stored_file_page_count(
                        stored_files_by_id[submission.stored_file_id]
                    )
                    if submission.stored_file_id in stored_files_by_id
                    else None
                ),
                pending_review_count=pending_review_count,
            )
        )
    return ExamScoreSummaryPublic(data=rows, count=len(rows))


def _compute_exam_analysis_stats(summary: ExamScoreSummaryPublic) -> dict | None:
    """汇总成绩统计数据：按「班级 + 学生姓名」合并多条 submission（与前端
    成绩矩阵口径一致），计算整体指标和各题得分率。没有任何成绩时返回 None。"""
    students: dict[str, dict] = {}
    for row in summary.data:
        class_name = (row.class_name or "").strip() or "未分班"
        student_name = (row.student_name or "").strip() or "未识别"
        key = f"{class_name}{student_name}"
        student = students.setdefault(
            key, {"total_score": None, "total_max_score": None, "questions": {}}
        )
        if row.total_score is not None:
            student["total_score"] = (student["total_score"] or 0) + row.total_score
        if row.total_max_score is not None:
            student["total_max_score"] = (
                student["total_max_score"] or 0
            ) + row.total_max_score
        for question in row.questions:
            existing = student["questions"].get(question.label)
            if existing is None or (
                existing.get("score_source") != "final"
                and question.score_source == "final"
            ):
                student["questions"][question.label] = {
                    "score": question.score,
                    "max_score": question.max_score,
                    "score_source": question.score_source,
                }
    scored = [s for s in students.values() if s["total_score"] is not None]
    if not scored:
        return None
    totals = [float(s["total_score"]) for s in scored]
    full_marks = [float(s["total_max_score"]) for s in scored if s["total_max_score"]]
    full_mark = max(full_marks) if full_marks else None
    sorted_totals = sorted(totals)
    quartile = max(1, len(sorted_totals) // 4)
    question_stats: dict[str, dict] = {}
    for student in scored:
        for label, question in student["questions"].items():
            if question["score"] is None or not question["max_score"]:
                continue
            entry = question_stats.setdefault(label, {"score": 0.0, "max": 0.0})
            entry["score"] += float(question["score"])
            entry["max"] += float(question["max_score"])
    question_rates = [
        {"label": label, "rate": round(entry["score"] / entry["max"] * 100, 1)}
        for label, entry in question_stats.items()
        if entry["max"] > 0
    ]
    question_rates.sort(key=lambda item: item["rate"])
    return {
        "student_count": len(scored),
        "average": round(sum(totals) / len(totals), 1),
        "full_mark": full_mark,
        "max": max(totals),
        "min": min(totals),
        "pass_rate": (
            round(
                sum(1 for t in totals if full_mark and t >= full_mark * 0.6)
                / len(totals)
                * 100,
                1,
            )
            if full_mark
            else None
        ),
        "excellent_rate": (
            round(
                sum(1 for t in totals if full_mark and t >= full_mark * 0.85)
                / len(totals)
                * 100,
                1,
            )
            if full_mark
            else None
        ),
        "stddev": round(statistics.pstdev(totals), 2) if len(totals) > 1 else 0.0,
        "top_quartile_avg": round(sum(sorted_totals[-quartile:]) / quartile, 1),
        "bottom_quartile_avg": round(sum(sorted_totals[:quartile]) / quartile, 1),
        "weakest_questions": question_rates[:3],
    }


@router.post("/{exam_id}/analysis-report", response_model=ExamAnalysisReportPublic)
def create_exam_analysis_report(
    session: SessionDep, current_user: CurrentUser, exam_id: uuid.UUID
) -> Any:
    """基于最新批阅成绩调用 LLM 生成四段式班级学情报告。

    暂不做持久化缓存——每次调用都重新统计并生成；后续如报告生成耗时或
    成本成为问题，可增加缓存表（按 exam_id + 成绩摘要哈希）复用结果。
    """
    exam = get_exam_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        require_write=True,
    )
    summary = _build_exam_scores_summary(session=session, exam_id=exam_id)
    stats = _compute_exam_analysis_stats(summary)
    if stats is None:
        raise HTTPException(
            status_code=400,
            detail="该考试还没有批改成绩，无法生成学情报告",
        )
    prompt = (
        "你是一位经验丰富的中文教研员。根据以下班级考试统计数据，撰写学情分析报告。"
        "只返回 JSON，不要 Markdown："
        '{"overall":"整体表现（2-3句，结合平均分/及格率/优秀率）",'
        '"weak":"薄弱点（结合得分率最低的题目，2-3句）",'
        '"polar":"两极分化提示（结合标准差与前25%/后25%均分差距，1-2句）",'
        '"advice":"教学建议（2-3条可执行建议，连贯成段）"}。\n'
        f"考试：{exam.title}\n"
        f"统计数据：{json.dumps(stats, ensure_ascii=False)}"
    )
    defaults = get_grading_defaults(session, exam.org_id)
    try:
        parsed, _used_model, _elapsed_ms = call_json_model(
            provider=defaults["grading_provider"],
            model=defaults["grading_model"],
            fallback_models=[],
            messages=[{"role": "user", "content": prompt}],
        )
    except VisionGradingError as exc:
        raise HTTPException(
            status_code=502, detail=f"AI 学情报告生成失败：{exc}"
        ) from exc
    report = {
        key: str(parsed.get(key) or "").strip()
        for key in ("overall", "weak", "polar", "advice")
    }
    if not all(report.values()):
        raise HTTPException(status_code=502, detail="AI 学情报告返回内容不完整，请重试")
    return ExamAnalysisReportPublic(**report, generated_at=get_datetime_utc())


@router.post(
    "/{exam_id}/submissions/preprocess-photo",
    response_model=StudentSubmissionPublic,
)
async def preprocess_student_submission_photo(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    file: UploadFile,
    student_name: str | None = Form(default=None),
    student_identifier: str | None = Form(default=None),
    class_name: str | None = Form(default=None),
) -> Any:
    exam = get_exam_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        require_write=True,
    )
    if is_zip_upload(filename=file.filename, content_type=file.content_type):
        # zip 答卷包：解包后逐张走照片预处理，合并为一份多页 PDF 答卷
        contents = await read_upload_file_bytes(
            file=file,
            max_bytes=MAX_ZIP_UPLOAD_BYTES,
            too_large_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
        if not contents[:4].startswith(b"PK"):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Uploaded file content does not match its declared type",
            )
        merged_pdf, image_count, preprocessed_count = build_pdf_bytes_from_zip(
            contents, preprocess_mode="auto"
        )
        source_name = Path(file.filename or "scan-photos").stem
        original_file = store_generated_file(
            session=session,
            owner_id=exam.owner_id,
            original_filename=file.filename or "scan-photos.zip",
            content_type=file.content_type or "application/zip",
            contents=contents,
            commit=False,
        )
        stored_file = store_generated_file(
            session=session,
            owner_id=exam.owner_id,
            original_filename=f"{source_name}-preprocessed.pdf",
            content_type="application/pdf",
            contents=merged_pdf,
            commit=False,
        )
        try:
            submission = StudentSubmission(
                exam_id=exam.id,
                stored_file_id=stored_file.id,
                original_stored_file_id=original_file.id,
                student_name=student_name,
                student_identifier=student_identifier,
                class_name=class_name,
                status=StudentSubmissionStatus.REGISTRATION_PENDING,
                registration_status=SubmissionRegistrationStatus.PENDING,
                registration_notes=(
                    f"ZIP 解包：{image_count} 张照片已预处理并合并为一份答卷，"
                    f"{preprocessed_count} 张已自动校正"
                ),
            )
            student = resolve_student_for_submission(
                session=session,
                owner_id=exam.owner_id,
                org_id=exam.org_id,
                class_name=class_name,
                student_name=student_name,
            )
            if student is not None:
                submission.student_id = student.id
            session.add(submission)
            session.commit()
        except Exception:
            session.rollback()
            cleanup_stored_file_path(get_stored_file_path(stored_file))
            cleanup_stored_file_path(get_stored_file_path(original_file))
            raise
        session.refresh(submission)
        session.refresh(stored_file)
        return build_student_submission_public(
            submission=submission, stored_file=stored_file
        )
    validate_scan_photo_upload_file(file)
    contents = await read_upload_file_bytes(file=file)
    assert_allowed_signature(
        contents_start=contents[:16],
        allowed_content_types=SCAN_PHOTO_CONTENT_TYPES,
        content_type=file.content_type,
    )
    try:
        preprocessed = preprocess_scan_photo_bytes(
            contents,
            filename=file.filename or "scan-photo.jpg",
            content_type=file.content_type or "image/jpeg",
        )
    except PhotoPreprocessingError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Could not preprocess exam photo: {exc}",
        )

    source_name = Path(file.filename or "scan-photo").stem
    pdf_filename = f"{source_name}-preprocessed.pdf"
    original_file = store_generated_file(
        session=session,
        owner_id=exam.owner_id,
        original_filename=file.filename or "scan-photo.jpg",
        content_type=file.content_type or "image/jpeg",
        contents=contents,
        commit=False,
    )
    stored_file = store_generated_file(
        session=session,
        owner_id=exam.owner_id,
        original_filename=pdf_filename,
        content_type="application/pdf",
        contents=preprocessed.pdf_bytes,
        commit=False,
    )
    preprocessing_metadata, preprocessing_quality, preprocessing_status = (
        build_preprocessing_metadata(preprocessed)
    )
    try:
        submission = StudentSubmission(
            exam_id=exam.id,
            stored_file_id=stored_file.id,
            original_stored_file_id=original_file.id,
            student_name=student_name,
            student_identifier=student_identifier,
            class_name=class_name,
            status=StudentSubmissionStatus.REGISTRATION_PENDING,
            registration_status=SubmissionRegistrationStatus.PENDING,
            registration_quality=preprocessing_quality,
            registration_notes=(
                "手机照片已预处理；"
                f"分割为 {len(preprocessed.pages)} 页，"
                f"原图 {preprocessed.spread_size[0]}x{preprocessed.spread_size[1]}，"
                f"扫描质量：{preprocessed.quality_status}，"
                f"状态：{preprocessing_status}"
            ),
            registration_homography=preprocessing_metadata,
        )
        student = resolve_student_for_submission(
            session=session,
            owner_id=exam.owner_id,
            org_id=exam.org_id,
            class_name=class_name,
            student_name=student_name,
        )
        if student is not None:
            submission.student_id = student.id
        session.add(submission)
        session.commit()
    except Exception:
        session.rollback()
        cleanup_stored_file_path(get_stored_file_path(stored_file))
        cleanup_stored_file_path(get_stored_file_path(original_file))
        raise
    session.refresh(submission)
    session.refresh(stored_file)
    return build_student_submission_public(
        submission=submission, stored_file=stored_file
    )


def stored_file_to_pdf_bytes(stored_file: StoredFile) -> bytes:
    path = get_stored_file_path(stored_file)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Stored file not found")
    if stored_file.content_type == "application/pdf":
        return path.read_bytes()
    try:
        return image_bytes_to_pdf(path.read_bytes())
    except InvalidPdfError:
        raise HTTPException(
            status_code=415, detail="Stored image could not be converted to PDF"
        )


def build_appended_pages_pdf_bytes(
    *, stored_file: StoredFile, preprocess_mode: Literal["auto", "force", "none"]
) -> bytes:
    """Convert an uploaded file into PDF pages ready to append.

    Photos go through the same rectification/split flow as the
    preprocess-photo endpoint; PDFs are appended as-is; ZIP 包按解包照片
    逐张处理后合并追加。
    """
    if is_zip_upload(
        filename=stored_file.original_filename,
        content_type=stored_file.content_type,
    ):
        zip_contents = get_stored_file_path(stored_file).read_bytes()
        merged_pdf, _image_count, _preprocessed_count = build_pdf_bytes_from_zip(
            zip_contents, preprocess_mode=preprocess_mode
        )
        return merged_pdf
    contents = stored_file_to_pdf_bytes(stored_file)
    if stored_file.content_type == "application/pdf" or preprocess_mode == "none":
        return contents
    source_path = get_stored_file_path(stored_file)
    raw_contents = source_path.read_bytes()
    try:
        preprocessed = preprocess_scan_photo_bytes(
            raw_contents,
            filename=stored_file.original_filename,
            content_type=stored_file.content_type or "image/jpeg",
        )
        return preprocessed.pdf_bytes
    except (PhotoPreprocessingError, OSError) as exc:
        if preprocess_mode == "force":
            raise HTTPException(
                status_code=422,
                detail=f"Could not preprocess exam photo: {exc}",
            ) from exc
        return contents


@router.post(
    "/{exam_id}/submissions/{submission_id}/pages",
    response_model=StudentSubmissionPublic,
)
async def append_student_submission_pages(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    submission_id: uuid.UUID,
    file: UploadFile,
    preprocess: Literal["auto", "force", "none"] = Form(default="auto"),
) -> Any:
    exam = get_exam_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        require_write=True,
    )
    submission, stored_file = get_student_submission_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        submission_id=submission_id,
        require_write=True,
    )
    if submission.registration_status == SubmissionRegistrationStatus.MANUAL_CONFIRMED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Registration is already confirmed; appending pages would invalidate it",
        )
    annotation_count = session.exec(
        select(func.count())
        .select_from(SubmissionAnnotation)
        .where(SubmissionAnnotation.submission_id == submission.id)
    ).one()
    if annotation_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Submission already has grading data; appending pages would invalidate it",
        )
    zip_upload = is_zip_upload(filename=file.filename, content_type=file.content_type)
    uploaded_file = await store_upload_file(
        session=session,
        current_user=current_user,
        file=file,
        owner_id=exam.owner_id,
        commit=False,
        validate_exam_file=True,
        max_bytes=MAX_ZIP_UPLOAD_BYTES if zip_upload else MAX_UPLOAD_BYTES,
        too_large_status=(
            status.HTTP_422_UNPROCESSABLE_ENTITY
            if zip_upload
            else status.HTTP_413_CONTENT_TOO_LARGE
        ),
    )
    try:
        validate_uploaded_pdf(uploaded_file)
    except HTTPException:
        session.rollback()
        raise
    merged_file: StoredFile | None = None
    try:
        appended_pdf = build_appended_pages_pdf_bytes(
            stored_file=uploaded_file, preprocess_mode=preprocess
        )
        merged_pdf = merge_pdf_bytes(
            stored_file_to_pdf_bytes(stored_file),
            appended_pdf,
        )
        source_name = Path(stored_file.original_filename).stem
        merged_file = store_generated_file(
            session=session,
            owner_id=exam.owner_id,
            original_filename=f"{source_name}-appended.pdf",
            content_type="application/pdf",
            contents=merged_pdf,
            commit=False,
        )
        submission.stored_file_id = merged_file.id
        submission.updated_at = get_datetime_utc()
        session.add(submission)
        session.flush()
        # Only delete the previous stored file after the submission no longer
        # references it (FK studentsubmission.stored_file_id has CASCADE).
        session.delete(stored_file)
        session.delete(uploaded_file)
        session.commit()
    except Exception:
        session.rollback()
        cleanup_stored_file_path(get_stored_file_path(uploaded_file))
        if merged_file is not None:
            cleanup_stored_file_path(get_stored_file_path(merged_file))
        raise
    cleanup_stored_file_path(get_stored_file_path(stored_file))
    cleanup_stored_file_path(get_stored_file_path(uploaded_file))
    session.refresh(submission)
    session.refresh(merged_file)
    return build_student_submission_public(
        submission=submission, stored_file=merged_file
    )


@router.get(
    "/{exam_id}/submissions/{submission_id}",
    response_model=StudentSubmissionPublic,
)
def read_student_submission(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    submission_id: uuid.UUID,
) -> Any:
    submission, stored_file = get_student_submission_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        submission_id=submission_id,
    )
    return build_student_submission_public(
        submission=submission, stored_file=stored_file
    )


@router.patch(
    "/{exam_id}/submissions/{submission_id}/registration",
    response_model=StudentSubmissionPublic,
)
def update_student_submission_registration(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    submission_id: uuid.UUID,
    registration_in: StudentSubmissionRegistrationUpdate,
) -> Any:
    submission, stored_file = get_student_submission_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        submission_id=submission_id,
        require_write=True,
    )
    updated_at = get_datetime_utc()
    submission.registration_status = registration_in.registration_status
    submission.registration_quality = registration_in.registration_quality
    submission.registration_notes = registration_in.registration_notes
    submission.registration_homography = registration_in.registration_homography
    submission.registered_at = updated_at
    submission.updated_at = updated_at
    if registration_in.registration_status == SubmissionRegistrationStatus.FAILED:
        submission.status = StudentSubmissionStatus.REGISTRATION_FAILED
    elif (
        registration_in.registration_status
        == SubmissionRegistrationStatus.MANUAL_CONFIRMED
    ):
        submission.status = StudentSubmissionStatus.READY_FOR_REVIEW
    else:
        submission.status = StudentSubmissionStatus.REGISTRATION_PENDING
        submission.registered_at = None
    session.add(submission)
    session.commit()
    session.refresh(submission)
    return build_student_submission_public(
        submission=submission, stored_file=stored_file
    )


@router.post(
    "/{exam_id}/submissions/{submission_id}/processing-tasks",
    response_model=ProcessingTaskPublic,
)
def create_student_submission_processing_task(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    submission_id: uuid.UUID,
) -> Any:
    get_student_submission_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        submission_id=submission_id,
        require_write=True,
    )
    task = ProcessingTask(
        task_type="student_submission_processing",
        status=ProcessingTaskStatus.QUEUED,
        progress=0,
        created_by_id=current_user.id,
        input_ref={
            "exam_id": str(exam_id),
            "submission_id": str(submission_id),
            "pipeline": "submission_processing_v1",
        },
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    if settings.ENVIRONMENT == "local":
        run_submission_processing_task(str(task.id))
        session.refresh(task)
        return task
    try:
        process_submission_processing_task.send(str(task.id))
    except Exception:
        run_submission_processing_task(str(task.id))
        session.refresh(task)
    return task


@router.get("/{exam_id}/submissions/{submission_id}/pages/{page_number}/image")
def read_student_submission_page_image(
    session: SessionDep,
    exam_id: uuid.UUID,
    submission_id: uuid.UUID,
    page_number: int,
    authorization: str | None = Header(default=None),
) -> Response:
    user = get_user_from_authorization_header(
        session=session, authorization=authorization
    )
    _submission, stored_file = get_student_submission_for_user(
        session=session,
        current_user=user,
        exam_id=exam_id,
        submission_id=submission_id,
    )
    return build_page_image_response(stored_file=stored_file, page_number=page_number)


@router.get(
    "/{exam_id}/submissions/{submission_id}/regions",
    response_model=ExamRegionsPublic,
)
def read_student_submission_template_regions(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    submission_id: uuid.UUID,
    page_number: int | None = None,
) -> Any:
    get_student_submission_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        submission_id=submission_id,
    )
    if page_number is not None and page_number < 1:
        raise HTTPException(status_code=422, detail="Page number must be at least 1")
    statement = (
        select(ExamRegion)
        .where(ExamRegion.exam_id == exam_id)
        .order_by(col(ExamRegion.created_at).asc())
    )
    regions = session.exec(statement).all()
    # 题目关联（question_key/label/role），供前端把跨页续题并入正题展示。
    link_statement = (
        select(ExamQuestionRegion, ExamQuestion)
        .join(ExamQuestion, ExamQuestionRegion.question_id == ExamQuestion.id)
        .where(ExamQuestion.exam_id == exam_id)
    )
    links_by_region: dict[uuid.UUID, tuple[ExamQuestionRegion, ExamQuestion]] = {
        link.exam_region_id: (link, question)
        for link, question in session.exec(link_statement).all()
    }
    # Regions store document-local page numbers; submissions are single
    # multi-page files, so expose (and filter by) global paper pages.
    public_regions = []
    for region in regions:
        public = ExamRegionPublic.model_validate(region)
        public.page_number = resolve_exam_region_paper_page(session, region)
        if page_number is not None and public.page_number != page_number:
            continue
        link_entry = links_by_region.get(region.id)
        if link_entry is not None:
            link, question = link_entry
            public.question_key = question.question_key
            public.question_label = question.label
            public.region_role = link.role.value
        public_regions.append(public)
    return ExamRegionsPublic(
        data=public_regions,
        count=len(public_regions),
    )


@router.get("/{exam_id}/submissions/{submission_id}/regions/{region_id}/crop")
def read_student_submission_region_crop(
    session: SessionDep,
    exam_id: uuid.UUID,
    submission_id: uuid.UUID,
    region_id: uuid.UUID,
    authorization: str | None = Header(default=None),
) -> Response:
    user = get_user_from_authorization_header(
        session=session, authorization=authorization
    )
    _submission, stored_file = get_student_submission_for_user(
        session=session,
        current_user=user,
        exam_id=exam_id,
        submission_id=submission_id,
    )
    region = get_exam_region_for_user(
        session=session,
        current_user=user,
        exam_id=exam_id,
        region_id=region_id,
    )
    return Response(
        content=crop_region_from_stored_file(
            stored_file=stored_file,
            region=region,
            page_number=resolve_exam_region_paper_page(session, region),
        ),
        media_type="image/png",
    )


@router.get("/{exam_id}/submissions/{submission_id}/annotations/{annotation_id}/crop")
def read_submission_annotation_crop(
    session: SessionDep,
    exam_id: uuid.UUID,
    submission_id: uuid.UUID,
    annotation_id: uuid.UUID,
    authorization: str | None = Header(default=None),
) -> FileResponse:
    user = get_user_from_authorization_header(
        session=session, authorization=authorization
    )
    annotation = get_submission_annotation_for_user(
        session=session,
        current_user=user,
        exam_id=exam_id,
        submission_id=submission_id,
        annotation_id=annotation_id,
    )
    if not annotation.exam_region_id:
        raise HTTPException(status_code=404, detail="Annotation crop not found")

    tasks = session.exec(
        select(ProcessingTask)
        .where(ProcessingTask.task_type == "student_submission_processing")
        .order_by(col(ProcessingTask.created_at).desc())
    ).all()
    matching_crop = None
    for task in tasks:
        input_ref = task.input_ref or {}
        output_ref = task.output_ref or {}
        if str(input_ref.get("exam_id")) == str(exam_id) and str(
            input_ref.get("submission_id")
        ) == str(submission_id):
            for crop in output_ref.get("region_crops", []):
                if str(crop.get("region_id")) == str(annotation.exam_region_id):
                    matching_crop = crop
                    break
        if matching_crop:
            break

    storage_key = matching_crop.get("storage_key") if matching_crop else None
    if storage_key:
        try:
            path = materialize_storage_key(str(storage_key))
        except Exception:
            path = None
        if path is not None and path.exists():
            return FileResponse(path=path, media_type="image/png", filename=path.name)

    # 回退：批量批改生成的批注没有持久化裁切图，按模板区域实时裁切。
    _submission, stored_file = get_student_submission_for_user(
        session=session,
        current_user=user,
        exam_id=exam_id,
        submission_id=submission_id,
    )
    region = session.get(ExamRegion, annotation.exam_region_id)
    if region is None or region.exam_id != exam_id:
        raise HTTPException(status_code=404, detail="Annotation crop not found")
    return Response(
        content=crop_region_from_stored_file(
            stored_file=stored_file,
            region=region,
            page_number=resolve_exam_region_paper_page(session, region),
        ),
        media_type="image/png",
    )


@router.get(
    "/{exam_id}/submissions/{submission_id}/annotations",
    response_model=SubmissionAnnotationsPublic,
)
def read_submission_annotations(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    submission_id: uuid.UUID,
) -> Any:
    get_student_submission_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        submission_id=submission_id,
    )
    statement = (
        select(SubmissionAnnotation)
        .where(SubmissionAnnotation.submission_id == submission_id)
        .order_by(col(SubmissionAnnotation.created_at).asc())
    )
    annotations = session.exec(statement).all()
    return SubmissionAnnotationsPublic(
        data=[
            SubmissionAnnotationPublic.model_validate(annotation)
            for annotation in annotations
        ],
        count=len(annotations),
    )


@router.post(
    "/{exam_id}/submissions/{submission_id}/annotations",
    response_model=SubmissionAnnotationPublic,
)
def create_submission_annotation(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    submission_id: uuid.UUID,
    annotation_in: SubmissionAnnotationCreate,
) -> Any:
    exam = get_exam_for_user(
        session=session, current_user=current_user, exam_id=exam_id
    )
    submission, _stored_file = get_student_submission_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        submission_id=submission_id,
        skip_assigned_restriction=True,
    )
    assert_can_write_submission_annotations(
        session=session,
        current_user=current_user,
        exam=exam,
        submission=submission,
    )
    if annotation_in.exam_region_id:
        get_exam_region_for_user(
            session=session,
            current_user=current_user,
            exam_id=exam_id,
            region_id=annotation_in.exam_region_id,
        )
    annotation = SubmissionAnnotation.model_validate(
        annotation_in, update={"submission_id": submission_id}
    )
    session.add(annotation)
    session.commit()
    session.refresh(annotation)
    return annotation


@router.patch(
    "/{exam_id}/submissions/{submission_id}/annotations/{annotation_id}",
    response_model=SubmissionAnnotationPublic,
)
def update_submission_annotation(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    submission_id: uuid.UUID,
    annotation_id: uuid.UUID,
    annotation_in: SubmissionAnnotationUpdate,
) -> Any:
    annotation = get_submission_annotation_for_write(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        submission_id=submission_id,
        annotation_id=annotation_id,
    )
    update_data = annotation_in.model_dump(exclude_unset=True)
    audit_reason = update_data.pop("audit_reason", None)
    old_score = annotation.score
    old_comment = annotation.comment
    next_x = update_data.get("x", annotation.x)
    next_y = update_data.get("y", annotation.y)
    next_width = update_data.get("width", annotation.width)
    next_height = update_data.get("height", annotation.height)
    if next_x + next_width > 1 or next_y + next_height > 1:
        raise HTTPException(
            status_code=422,
            detail="Annotation bounds must stay within normalized page coordinates",
        )
    annotation.sqlmodel_update(update_data)
    if "score" in update_data or "comment" in update_data:
        from app.models import GradingAuditEvent

        annotation.score_source = "human"
        annotation.grading_status = AnnotationGradingStatus.SUCCEEDED
        annotation.status = SubmissionAnnotationStatus.ACCEPTED
        session.add(
            GradingAuditEvent(
                submission_id=submission_id,
                annotation_id=annotation.id,
                operator_id=current_user.id,
                source="human",
                old_score=old_score,
                new_score=annotation.score,
                old_comment=old_comment,
                new_comment=annotation.comment,
                reason=audit_reason or "人工复核修改",
            )
        )
    annotation.updated_at = get_datetime_utc()
    session.add(annotation)
    session.commit()
    session.refresh(annotation)
    return annotation


@router.delete("/{exam_id}/submissions/{submission_id}/annotations/{annotation_id}")
def delete_submission_annotation(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    submission_id: uuid.UUID,
    annotation_id: uuid.UUID,
) -> Message:
    annotation = get_submission_annotation_for_write(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        submission_id=submission_id,
        annotation_id=annotation_id,
    )
    session.delete(annotation)
    session.commit()
    return Message(message="Submission annotation deleted successfully")


@router.get("/{exam_id}/answers", response_model=StandardAnswersPublic)
def read_standard_answers(
    session: SessionDep, current_user: CurrentUser, exam_id: uuid.UUID
) -> Any:
    get_exam_for_user(session=session, current_user=current_user, exam_id=exam_id)
    statement = (
        select(StandardAnswer)
        .where(StandardAnswer.exam_id == exam_id)
        .order_by(col(StandardAnswer.created_at).asc())
    )
    answers = session.exec(statement).all()
    return StandardAnswersPublic(
        data=[StandardAnswerPublic.model_validate(answer) for answer in answers],
        count=len(answers),
    )


@router.post("/{exam_id}/answers", response_model=StandardAnswerPublic)
def create_standard_answer(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    answer_in: StandardAnswerCreate,
) -> Any:
    get_exam_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        require_write=True,
    )
    region = get_question_region_for_standard_answer(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        region_id=answer_in.exam_region_id,
    )
    existing = session.exec(
        select(StandardAnswer).where(StandardAnswer.exam_region_id == region.id)
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Standard answer already exists for this question region",
        )
    answer = StandardAnswer.model_validate(
        answer_in,
        update={
            "exam_id": exam_id,
            "exam_region_id": region.id,
        },
    )
    session.add(answer)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Standard answer already exists for this question region",
        )
    session.refresh(answer)
    return answer


@router.get("/{exam_id}/answers/{answer_id}", response_model=StandardAnswerPublic)
def read_standard_answer(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    answer_id: uuid.UUID,
) -> Any:
    return get_standard_answer_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        answer_id=answer_id,
    )


@router.patch("/{exam_id}/answers/{answer_id}", response_model=StandardAnswerPublic)
def update_standard_answer(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    answer_id: uuid.UUID,
    answer_in: StandardAnswerUpdate,
) -> Any:
    answer = get_standard_answer_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        answer_id=answer_id,
        require_write=True,
    )
    if answer.current_revision_id is not None:
        raise HTTPException(
            status_code=409,
            detail="Published answers are immutable; create and publish a new revision",
        )
    answer.sqlmodel_update(answer_in.model_dump(exclude_unset=True))
    answer.updated_at = get_datetime_utc()
    session.add(answer)
    affected_annotations = (
        session.exec(
            select(SubmissionAnnotation).where(
                SubmissionAnnotation.exam_region_id == answer.exam_region_id
            )
        ).all()
        if answer.exam_region_id is not None
        else []
    )
    for annotation in affected_annotations:
        if annotation.grading_status in {
            AnnotationGradingStatus.SUCCEEDED,
            AnnotationGradingStatus.NEEDS_REVIEW,
        }:
            annotation.grading_status = AnnotationGradingStatus.STALE
            annotation.updated_at = get_datetime_utc()
            session.add(annotation)
    session.commit()
    session.refresh(answer)
    return answer


@router.delete("/{exam_id}/answers/{answer_id}")
def delete_standard_answer(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    answer_id: uuid.UUID,
) -> Message:
    answer = get_standard_answer_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        answer_id=answer_id,
        require_write=True,
    )
    if answer.current_revision_id is not None:
        raise HTTPException(
            status_code=409,
            detail="Published answers are immutable and cannot be deleted",
        )
    session.delete(answer)
    session.commit()
    return Message(message="Standard answer deleted successfully")


@router.get("/{exam_id}/regions", response_model=ExamRegionsPublic)
def read_exam_regions(
    session: SessionDep, current_user: CurrentUser, exam_id: uuid.UUID
) -> Any:
    get_exam_for_user(session=session, current_user=current_user, exam_id=exam_id)
    statement = (
        select(ExamRegion)
        .where(ExamRegion.exam_id == exam_id)
        .order_by(col(ExamRegion.created_at).asc())
    )
    regions = session.exec(statement).all()
    return ExamRegionsPublic(
        data=[ExamRegionPublic.model_validate(region) for region in regions],
        count=len(regions),
    )


@router.post("/{exam_id}/regions", response_model=ExamRegionPublic)
def create_exam_region(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    region_in: ExamRegionCreate,
) -> Any:
    exam = get_exam_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        require_write=True,
    )
    if region_in.exam_document_id:
        document = session.get(ExamDocument, region_in.exam_document_id)
        if not document or document.exam_id != exam_id:
            raise HTTPException(
                status_code=422, detail="Exam document does not belong to this exam"
            )
    region = ExamRegion.model_validate(region_in, update={"exam_id": exam.id})
    session.add(region)
    session.commit()
    session.refresh(region)
    return region


@router.patch("/{exam_id}/regions/{region_id}", response_model=ExamRegionPublic)
def update_exam_region(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    region_id: uuid.UUID,
    region_in: ExamRegionUpdate,
) -> Any:
    region = get_exam_region_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        region_id=region_id,
        require_write=True,
    )
    update_data = region_in.model_dump(exclude_unset=True)
    document_id = update_data.get("exam_document_id")
    if document_id:
        document = session.get(ExamDocument, document_id)
        if not document or document.exam_id != exam_id:
            raise HTTPException(
                status_code=422, detail="Exam document does not belong to this exam"
            )
    next_x = update_data.get("x", region.x)
    next_y = update_data.get("y", region.y)
    next_width = update_data.get("width", region.width)
    next_height = update_data.get("height", region.height)
    if next_x + next_width > 1 or next_y + next_height > 1:
        raise HTTPException(
            status_code=422,
            detail="Region bounds must stay within normalized page coordinates",
        )
    region.sqlmodel_update(update_data)
    region.updated_at = get_datetime_utc()
    session.add(region)
    session.commit()
    session.refresh(region)
    return region


@router.delete("/{exam_id}/regions/{region_id}")
def delete_exam_region(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    region_id: uuid.UUID,
) -> Message:
    region = get_exam_region_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        region_id=region_id,
        require_write=True,
    )
    session.delete(region)
    session.commit()
    return Message(message="Exam region deleted successfully")


@router.patch("/{exam_id}", response_model=ExamPublic)
def update_exam(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    exam_in: ExamUpdate,
) -> Any:
    exam = get_exam_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        require_write=True,
    )
    update_data = exam_in.model_dump(exclude_unset=True, exclude={"class_ids"})
    exam.sqlmodel_update(update_data)
    session.add(exam)
    if exam_in.class_ids is not None:
        replace_exam_class_links(
            session=session,
            exam=exam,
            class_ids=exam_in.class_ids,
        )
    session.commit()
    session.refresh(exam)
    return build_exam_public(session=session, exam=exam)


@router.delete("/{exam_id}")
def delete_exam(
    session: SessionDep, current_user: CurrentUser, exam_id: uuid.UUID
) -> Message:
    exam = get_exam_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        require_write=True,
    )
    session.delete(exam)
    session.commit()
    return Message(message="Exam deleted successfully")
