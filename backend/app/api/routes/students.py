import base64
import hashlib
import json
import uuid
from collections import Counter
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import case, func
from sqlmodel import Session, col, select

from app.api.deps import (
    CurrentUser,
    SessionDep,
    get_user_from_authorization_header,
    require_roles,
)
from app.core.config import settings
from app.models import (
    ClassGroup,
    Exam,
    ExamScoreSummaryPublic,
    ExamScoreSummaryRow,
    KnowledgeTrendPoint,
    KnowledgeTrendScorePoint,
    KnowledgeTrendSeries,
    KnowledgeTrendsPublic,
    LearnerEnrollmentPublic,
    LearnerProfile,
    LearnerProfilePublic,
    LearningAdviceFocusPoint,
    LearningAdvicePublic,
    PracticeAttemptStatus,
    PracticeSheet,
    PracticeSheetAttempt,
    PracticeSheetAttemptPublic,
    PracticeSheetCreate,
    PracticeSheetItemPublic,
    PracticeSheetListItem,
    PracticeSheetPublic,
    PracticeSheetsPublic,
    ScoreRelease,
    ScoreReleaseItem,
    ScoreReleaseStatus,
    SnapGradeItemPublic,
    SnapGradePublic,
    SnapSolvePublic,
    Student,
    StudentExamListItemPublic,
    StudentExamListPublic,
    StudentExamReportPublic,
    StudentExamReportQuestion,
    StudentSubmission,
    User,
    UserRole,
    WrongbookEntriesPublic,
    WrongbookEntryDetail,
    WrongbookEntryListItem,
    WrongbookEntryUpdate,
    WrongbookMasteryItem,
    WrongbookMasteryPublic,
    WrongbookReviewCreate,
    WrongbookReviewPublic,
    WrongQuestionEntry,
    WrongQuestionEntryStatus,
    WrongQuestionReview,
    WrongQuestionSource,
    get_datetime_utc,
)
from app.services import learner_identity, wrongbook_review
from app.services.file_storage import store_upload_file
from app.services.image_downscale import downscale_image_for_model
from app.services.object_storage import materialize_storage_key
from app.services.system_config import get_grading_defaults
from app.services.vision_grading import (
    VisionGradingError,
    call_json_model,
)

router = APIRouter(prefix="/students", tags=["students"])

# 学生专属端点：教师/管理员访问一律 403
CurrentStudentUser = Annotated[User, Depends(require_roles(UserRole.STUDENT))]


def _published_release(session: Session, exam_id: uuid.UUID) -> ScoreRelease | None:
    return session.exec(
        select(ScoreRelease)
        .where(
            ScoreRelease.exam_id == exam_id,
            ScoreRelease.status == ScoreReleaseStatus.PUBLISHED,
        )
        .order_by(col(ScoreRelease.version).desc())
    ).first()


def _release_class_position(
    session: Session,
    release: ScoreRelease,
    my_submission_ids: set[uuid.UUID],
) -> tuple[int | None, int, str | None]:
    """Calculate rank exclusively from the immutable published snapshot."""
    rows = list(
        session.exec(
            select(ScoreReleaseItem, StudentSubmission)
            .join(
                StudentSubmission,
                ScoreReleaseItem.submission_id == StudentSubmission.id,
            )
            .where(ScoreReleaseItem.release_id == release.id)
        ).all()
    )
    totals: dict[tuple[str, str], dict[str, Any]] = {}
    my_key: tuple[str, str] | None = None
    for item, submission in rows:
        key = (
            (submission.class_name or "").strip(),
            (submission.student_name or "").strip(),
        )
        entry = totals.setdefault(key, {"score": 0.0, "has_score": False})
        if item.score is not None:
            entry["score"] += item.score
            entry["has_score"] = True
        if submission.id in my_submission_ids:
            my_key = key
    if my_key is None:
        return None, 0, None
    classmates = [(key, value) for key, value in totals.items() if key[0] == my_key[0]]
    scored = sorted(
        (row for row in classmates if row[1]["has_score"]),
        key=lambda row: row[1]["score"],
        reverse=True,
    )
    rank = next(
        (index for index, (key, _value) in enumerate(scored, start=1) if key == my_key),
        None,
    )
    return rank, len(classmates), my_key[0] or None


def get_current_student_profile(
    *, session: Session, current_user: CurrentUser
) -> Student:
    """通过 Student.user_id 找到当前账号绑定的学生档案。"""
    student = session.exec(
        select(Student).where(Student.user_id == current_user.id)
    ).first()
    if not student:
        raise HTTPException(
            status_code=404,
            detail="账号未绑定学生档案，请联系老师绑定",
        )
    return student


def find_my_submissions(
    *, session: Session, student: Student, class_name: str | None
) -> list[StudentSubmission]:
    """我参加的答卷：优先按 student_id 匹配，再按「班级 + 姓名」兜底。"""
    submissions = list(
        session.exec(
            select(StudentSubmission).where(StudentSubmission.student_id == student.id)
        ).all()
    )
    matched_ids = {submission.id for submission in submissions}
    if class_name:
        class_group = session.get(ClassGroup, student.class_id)
        if not class_group:
            return submissions
        fallback = session.exec(
            select(StudentSubmission)
            .join(Exam, StudentSubmission.exam_id == Exam.id)
            .where(
                Exam.org_id == class_group.org_id,
                StudentSubmission.class_name == class_name,
                StudentSubmission.student_name == student.name,
            )
        ).all()
        for submission in fallback:
            if submission.id not in matched_ids:
                submissions.append(submission)
    return submissions


def _merge_rows_by_student(
    summary: ExamScoreSummaryPublic,
) -> dict[tuple[str, str], dict[str, Any]]:
    """把 summary 的逐答卷行按「班级 + 姓名」合并（与成绩分析口径一致）。"""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for row in summary.data:
        key = ((row.class_name or "").strip(), (row.student_name or "").strip())
        entry = merged.setdefault(
            key,
            {
                "class_name": row.class_name,
                "total_score": None,
                "total_max_score": None,
                "submission_ids": [],
            },
        )
        entry["submission_ids"].append(row.submission_id)
        if row.total_score is not None:
            entry["total_score"] = round(
                (entry["total_score"] or 0) + row.total_score, 2
            )
        if row.total_max_score is not None:
            entry["total_max_score"] = round(
                (entry["total_max_score"] or 0) + row.total_max_score, 2
            )
    return merged


def _compute_class_position(
    *,
    summary: ExamScoreSummaryPublic,
    my_rows: list[ExamScoreSummaryRow],
    my_submission_ids: set[uuid.UUID],
) -> tuple[int | None, int, str | None]:
    """在同班（class_name 相同）的合并行中按 total_score 降序算我的位次。

    返回 (class_rank, class_size, class_name)；我暂无成绩时 rank 为 None。
    """
    merged = _merge_rows_by_student(summary)
    my_entry = next(
        (
            entry
            for entry in merged.values()
            if any(
                submission_id in my_submission_ids
                for submission_id in entry["submission_ids"]
            )
        ),
        None,
    )
    if my_entry is None:
        # 兜底：summary 行里没有 submission_id 命中时按首行班级归位
        class_name = my_rows[0].class_name if my_rows else None
        return None, 0, class_name
    class_name = my_entry["class_name"]
    class_key = (class_name or "").strip()
    classmates = [entry for key, entry in merged.items() if key[0] == class_key]
    scored = sorted(
        (entry for entry in classmates if entry["total_score"] is not None),
        key=lambda entry: entry["total_score"],
        reverse=True,
    )
    class_rank = None
    for index, entry in enumerate(scored, start=1):
        if entry is my_entry:
            class_rank = index
            break
    return class_rank, len(classmates), class_name


def _get_my_exam_context(
    *, session: Session, current_user: CurrentUser
) -> tuple[Student, str | None, list[StudentSubmission]]:
    student = get_current_student_profile(session=session, current_user=current_user)
    class_group = session.get(ClassGroup, student.class_id)
    class_name = class_group.name if class_group else None
    submissions = find_my_submissions(
        session=session, student=student, class_name=class_name
    )
    return student, class_name, submissions


@router.get("/me/exams", response_model=StudentExamListPublic)
def read_my_exams(session: SessionDep, current_user: CurrentStudentUser) -> Any:
    _student, _class_name, submissions = _get_my_exam_context(
        session=session, current_user=current_user
    )
    my_submission_ids = {submission.id for submission in submissions}
    exam_ids = list(dict.fromkeys(submission.exam_id for submission in submissions))
    items: list[StudentExamListItemPublic] = []
    for exam_id in exam_ids:
        exam = session.get(Exam, exam_id)
        release = _published_release(session, exam_id)
        if not exam or not release:
            continue
        release_items = list(
            session.exec(
                select(ScoreReleaseItem).where(
                    ScoreReleaseItem.release_id == release.id,
                    col(ScoreReleaseItem.submission_id).in_(my_submission_ids),
                )
            ).all()
        )
        if not release_items:
            continue
        class_rank, class_size, class_name = _release_class_position(
            session, release, my_submission_ids
        )
        labels = {item.label for item in release_items}
        total_score = sum(
            item.score for item in release_items if item.score is not None
        )
        total_max_score = sum(
            item.max_score for item in release_items if item.max_score is not None
        )
        items.append(
            StudentExamListItemPublic(
                exam_id=exam.id,
                title=exam.title,
                subject=exam.subject,
                grade_level=exam.grade_level,
                exam_date=exam.exam_date,
                class_name=class_name,
                total_score=(
                    round(total_score, 2)
                    if any(item.score is not None for item in release_items)
                    else None
                ),
                total_max_score=(
                    round(total_max_score, 2)
                    if any(item.max_score is not None for item in release_items)
                    else None
                ),
                class_rank=class_rank,
                class_size=class_size,
                question_count=len(labels),
                pending_review_count=0,
            )
        )
    items.sort(
        key=lambda item: (item.exam_date is not None, item.exam_date),
        reverse=True,
    )
    return StudentExamListPublic(data=items, count=len(items))


def _my_entry_filter(learner: LearnerProfile) -> Any:
    """错题本归属只认终身身份（D-029）。

    条目在成绩发布时可能还没有 learner（学生尚未绑定账号），那些孤立条目由
    `resolve_learner` 在学生首次访问时认领，因此这里不需要再回落学校侧档案。
    """
    return WrongQuestionEntry.learner_id == learner.id


def get_current_learner(
    *, session: Session, current_user: User
) -> tuple[LearnerProfile, Student | None]:
    """学生端统一入口：终身身份 + 当前在校档案（可能没有）。

    与 `get_current_student_profile` 的区别：没绑学校档案也能拿到身份，因此毕业、
    转学或学校退订之后，学生仍然能访问自己的学习记录。
    """
    student = session.exec(
        select(Student).where(Student.user_id == current_user.id)
    ).first()
    learner = learner_identity.resolve_learner(
        session, user=current_user, student=student
    )
    return learner, student


def _my_entries_by_label(
    session: Session, *, release_id: uuid.UUID, submission_ids: set[uuid.UUID]
) -> dict[str, tuple[WrongQuestionEntry, WrongQuestionSource]]:
    if not submission_ids:
        return {}
    rows = session.exec(
        select(WrongQuestionEntry, WrongQuestionSource)
        .join(
            WrongQuestionSource,
            WrongQuestionEntry.source_id == WrongQuestionSource.id,  # type: ignore[arg-type]
        )
        .where(
            WrongQuestionEntry.release_id == release_id,
            col(WrongQuestionEntry.submission_id).in_(submission_ids),
            WrongQuestionEntry.status == WrongQuestionEntryStatus.ACTIVE,
        )
    ).all()
    return {entry.question_label: (entry, source) for entry, source in rows}


def _my_wrongbook_scope(learner: LearnerProfile) -> list[Any]:
    """我的、且当前有效的错题条目。所有错题本查询都从这里出发。"""
    return [
        _my_entry_filter(learner),
        WrongQuestionEntry.status == WrongQuestionEntryStatus.ACTIVE,
    ]


def _entry_source_join(statement: Any) -> Any:
    """条目 join 题面快照。显式指定左侧，否则只选 source 列时无法推断 FROM。"""
    return statement.select_from(WrongQuestionEntry).join(
        WrongQuestionSource,
        WrongQuestionEntry.source_id == WrongQuestionSource.id,  # type: ignore[arg-type]
    )


def _wrongbook_facets(
    session: Session, scope: list[Any]
) -> tuple[list[str], list[str]]:
    """筛选项只从我自己的条目里取，且不受当前筛选影响，避免按钮自己消失。"""
    subjects = [
        value
        for value in session.exec(
            _entry_source_join(select(WrongQuestionSource.subject).distinct()).where(
                *scope, col(WrongQuestionSource.subject).is_not(None)
            )
        ).all()
        if value
    ]
    knowledge_points = [
        value
        for value in session.exec(
            _entry_source_join(
                select(
                    func.jsonb_array_elements_text(
                        WrongQuestionSource.knowledge_point_names
                    ).label("name")
                ).distinct()
            ).where(*scope)
        ).all()
        if value
    ]
    return sorted(subjects), sorted(knowledge_points)


@router.get("/me/wrongbook/entries", response_model=WrongbookEntriesPublic)
def read_my_wrongbook(
    session: SessionDep,
    current_user: CurrentStudentUser,
    subject: str | None = None,
    knowledge_point: str | None = None,
    exam_id: uuid.UUID | None = None,
    wrong_only: bool = True,
    skip: int = 0,
    limit: int = 50,
) -> Any:
    """我的错题本。只读发布时写入的快照，与考试和答卷的存续无关。

    过滤、排序和分页都交给数据库：错题本按设计会累积多年，不能把全部条目取回内存。
    """
    learner, _student = get_current_learner(session=session, current_user=current_user)
    scope = _my_wrongbook_scope(learner)
    filters = list(scope)
    if wrong_only:
        filters.append(WrongQuestionEntry.is_wrong.is_(True))  # type: ignore[union-attr]
    if subject:
        filters.append(WrongQuestionSource.subject == subject)
    if exam_id:
        filters.append(WrongQuestionSource.exam_id == exam_id)
    if knowledge_point:
        # JSONB 包含查询，配 GIN 索引；不要把整列取回来在 Python 里判断
        filters.append(
            col(WrongQuestionSource.knowledge_point_names).contains([knowledge_point])
        )

    count = session.exec(_entry_source_join(select(func.count())).where(*filters)).one()
    rows = session.exec(
        _entry_source_join(
            select(WrongQuestionEntry, WrongQuestionSource, WrongQuestionReview)
        )
        .outerjoin(
            WrongQuestionReview,
            WrongQuestionReview.entry_id == WrongQuestionEntry.id,  # type: ignore[arg-type]
        )
        .where(*filters)
        .order_by(
            col(WrongQuestionEntry.released_at).desc(),
            col(WrongQuestionEntry.question_label).desc(),
            col(WrongQuestionEntry.id).desc(),
        )
        .offset(max(0, skip))
        .limit(min(max(1, limit), 200))
    ).all()
    subjects, knowledge_points = _wrongbook_facets(session, scope)
    return WrongbookEntriesPublic(
        data=[
            _entry_list_item(entry, source, review) for entry, source, review in rows
        ],
        count=count,
        subjects=subjects,
        knowledge_points=knowledge_points,
    )


def _entry_list_item(
    entry: WrongQuestionEntry,
    source: WrongQuestionSource,
    review: WrongQuestionReview | None = None,
) -> WrongbookEntryListItem:
    return WrongbookEntryListItem(
        entry_id=entry.id,
        exam_id=source.exam_id,
        exam_title=source.exam_title,
        subject=source.subject,
        exam_date=source.exam_date,
        question_label=entry.question_label,
        score=entry.score,
        max_score=entry.max_score,
        is_wrong=entry.is_wrong,
        knowledge_point_names=source.knowledge_point_names or [],
        error_reason=entry.error_reason,
        has_image=bool(entry.image_storage_key),
        released_at=entry.released_at,
        review_count=review.review_count if review else 0,
        next_due_at=review.next_due_at if review else None,
    )


@router.get("/me/profile", response_model=LearnerProfilePublic)
def read_my_learner_profile(
    session: SessionDep, current_user: CurrentStudentUser
) -> Any:
    """我的学习档案：终身身份 + 在校经历 + 错题累计。

    没绑学校档案也能访问：毕业、转学或学校退订之后，学生仍然拥有自己的学习记录。
    """
    learner, _student = get_current_learner(session=session, current_user=current_user)
    totals = session.exec(
        select(
            func.count(),
            func.coalesce(
                func.sum(
                    case((col(WrongQuestionEntry.is_wrong).is_(True), 1), else_=0)
                ),
                0,
            ),
        )
        .select_from(WrongQuestionEntry)
        .where(*_my_wrongbook_scope(learner))
    ).one()
    entry_count, wrong_count = int(totals[0]), int(totals[1])
    return LearnerProfilePublic(
        learner_id=learner.id,
        display_name=learner.display_name,
        grade_band=learner.grade_band,
        entry_count=entry_count,
        wrong_count=wrong_count,
        enrollments=[
            LearnerEnrollmentPublic(
                org_name=item.org_name_at_time,
                class_name=item.class_name_at_time,
                student_name=item.student_name_at_time,
                started_at=item.started_at,
                ended_at=item.ended_at,
            )
            for item in learner_identity.enrollments(session, learner)
        ],
    )


@router.get("/me/wrongbook/due", response_model=WrongbookEntriesPublic)
def read_my_due_reviews(
    session: SessionDep, current_user: CurrentStudentUser, limit: int = 20
) -> Any:
    """今天该复习的错题。没复习过的排最前，其余按到期时间。"""
    learner, _student = get_current_learner(session=session, current_user=current_user)
    rows = wrongbook_review.due_entries(session, learner=learner, limit=limit)
    total = wrongbook_review.due_count(session, learner=learner)
    return WrongbookEntriesPublic(
        data=[_entry_list_item(entry, source) for entry, source in rows],
        count=total,
    )


@router.get("/me/wrongbook/cram", response_model=WrongbookEntriesPublic)
def read_my_cram_list(
    session: SessionDep,
    current_user: CurrentStudentUser,
    subject: str | None = None,
    limit: int = 30,
) -> Any:
    """考前突击清单：按知识点错误率、是否长期未复习和卷面失分比例排序。"""
    learner, _student = get_current_learner(session=session, current_user=current_user)
    wrongbook_review.rebuild_mastery(session, learner=learner)
    rows = wrongbook_review.cram_list(
        session, learner=learner, subject=subject, limit=limit
    )
    return WrongbookEntriesPublic(
        data=[_entry_list_item(entry, source) for entry, source, _score in rows],
        count=len(rows),
    )


@router.get("/me/wrongbook/mastery", response_model=WrongbookMasteryPublic)
def read_my_mastery(session: SessionDep, current_user: CurrentStudentUser) -> Any:
    """按知识点的掌握度。派生数据，每次请求按当前错题本重算。"""
    learner, _student = get_current_learner(session=session, current_user=current_user)
    rows = wrongbook_review.rebuild_mastery(session, learner=learner)
    return WrongbookMasteryPublic(
        data=[
            WrongbookMasteryItem(
                subject=item.subject or None,
                knowledge_point_name=item.knowledge_point_name,
                attempts=item.attempts,
                wrong_count=item.wrong_count,
                wrong_rate=(
                    round(item.wrong_count / item.attempts * 100)
                    if item.attempts
                    else 0
                ),
                last_wrong_at=item.last_wrong_at,
                last_reviewed_at=item.last_reviewed_at,
            )
            for item in rows
        ],
        count=len(rows),
    )


@router.get("/me/knowledge-trends", response_model=KnowledgeTrendsPublic)
def read_my_knowledge_trends(
    session: SessionDep, current_user: CurrentStudentUser
) -> Any:
    """跨场次的长期趋势：每场发布的总分曲线 + 知识点错误率曲线。

    纯 SQL 聚合错题本快照（满分题也建行，分母自带），不调用模型。
    """
    learner, _student = get_current_learner(session=session, current_user=current_user)
    scope = _my_wrongbook_scope(learner)

    # 按发布场次聚合总分。release_id 会因考试删除变 NULL，NULL 场次的标题和
    # 日期仍在快照里，同一场的标题+日期一致，合并到一点不影响趋势展示。
    score_rows = session.exec(
        _entry_source_join(
            select(
                col(WrongQuestionSource.exam_title),
                col(WrongQuestionSource.exam_date),
                *[
                    func.max(col(WrongQuestionEntry.released_at)),
                    func.sum(WrongQuestionEntry.score),
                    func.sum(WrongQuestionEntry.max_score),
                ],
            )
        )
        .where(*scope)
        .group_by(
            WrongQuestionEntry.release_id,
            WrongQuestionSource.exam_title,
            WrongQuestionSource.exam_date,
        )
        .order_by(func.max(col(WrongQuestionEntry.released_at)))
    ).all()
    score_trend = [
        KnowledgeTrendScorePoint(
            exam_title=title,
            exam_date=exam_date,
            released_at=released_at,
            total_score=round(score, 2) if score is not None else None,
            total_max_score=round(max_score, 2) if max_score is not None else None,
        )
        for title, exam_date, released_at, score, max_score in score_rows
    ]

    # 按（知识点 × 发布场次）聚合错误率；JSONB 展开在数据库里做，配 GIN 索引
    kp_name = func.jsonb_array_elements_text(
        WrongQuestionSource.knowledge_point_names
    ).label("kp_name")
    kp_rows = session.exec(
        _entry_source_join(
            select(
                kp_name,
                col(WrongQuestionSource.subject),
                col(WrongQuestionSource.exam_title),
                col(WrongQuestionSource.exam_date),
                *[
                    func.max(col(WrongQuestionEntry.released_at)),
                    func.count(),
                    func.coalesce(
                        func.sum(
                            case(
                                (col(WrongQuestionEntry.is_wrong).is_(True), 1),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                ],
            )
        )
        .where(*scope)
        .group_by(
            kp_name,
            WrongQuestionSource.subject,
            WrongQuestionEntry.release_id,
            WrongQuestionSource.exam_title,
            WrongQuestionSource.exam_date,
        )
    ).all()
    series_map: dict[tuple[str | None, str], dict[str, Any]] = {}
    for name, subject, title, exam_date, released_at, attempts, wrong in kp_rows:
        series = series_map.setdefault(
            (subject, name),
            {
                "subject": subject,
                "knowledge_point": name,
                "total_wrong": 0,
                "points": [],
            },
        )
        series["total_wrong"] += int(wrong)
        series["points"].append(
            KnowledgeTrendPoint(
                exam_title=title,
                exam_date=exam_date,
                released_at=released_at,
                wrong_rate=round(int(wrong) / int(attempts) * 100) if attempts else 0,
                attempts=int(attempts),
                wrong=int(wrong),
            )
        )
    kp_trends = [
        KnowledgeTrendSeries(
            subject=series["subject"],
            knowledge_point=series["knowledge_point"],
            points=sorted(series["points"], key=lambda point: point.released_at),
        )
        for series in sorted(
            series_map.values(),
            key=lambda item: (-item["total_wrong"], item["knowledge_point"]),
        )
    ]
    return KnowledgeTrendsPublic(score_trend=score_trend, kp_trends=kp_trends)


@router.post(
    "/me/wrongbook/entries/{entry_id}/review", response_model=WrongbookReviewPublic
)
def review_my_wrongbook_entry(
    session: SessionDep,
    current_user: CurrentStudentUser,
    entry_id: uuid.UUID,
    review_in: WrongbookReviewCreate,
) -> Any:
    """提交一次复习结果，推进下次到期时间；可顺手标注错因。"""
    learner, _student = get_current_learner(session=session, current_user=current_user)
    entry, source = _owned_entry(session, learner=learner, entry_id=entry_id)
    if review_in.error_reason is not None:
        entry.error_reason = review_in.error_reason
        session.add(entry)
    review = wrongbook_review.record_review(
        session,
        entry=entry,
        source=source,
        learner=learner,
        user_id=current_user.id,
        result=review_in.result,
    )
    return WrongbookReviewPublic(
        entry_id=entry.id,
        result=review.result,
        review_count=review.review_count,
        interval_days=review.interval_days,
        next_due_at=review.next_due_at,
        due_count=wrongbook_review.due_count(session, learner=learner),
    )


def _owned_entry(
    session: Session, *, learner: LearnerProfile, entry_id: uuid.UUID
) -> tuple[WrongQuestionEntry, WrongQuestionSource]:
    row = session.exec(
        select(WrongQuestionEntry, WrongQuestionSource)
        .join(
            WrongQuestionSource,
            WrongQuestionEntry.source_id == WrongQuestionSource.id,  # type: ignore[arg-type]
        )
        .where(
            WrongQuestionEntry.id == entry_id,
            _my_entry_filter(learner),
        )
    ).first()
    if row is None:
        # 别人的错题与不存在的错题返回同一个结果，不泄露存在性
        raise HTTPException(status_code=404, detail="错题不存在")
    return row


def _entry_detail(
    entry: WrongQuestionEntry, source: WrongQuestionSource
) -> WrongbookEntryDetail:
    return WrongbookEntryDetail(
        entry_id=entry.id,
        exam_id=source.exam_id,
        exam_title=source.exam_title,
        subject=source.subject,
        grade_level=source.grade_level,
        exam_date=source.exam_date,
        class_name_at_time=entry.class_name_at_time,
        question_label=entry.question_label,
        question_text=source.question_text,
        question_type=source.question_type,
        score=entry.score,
        max_score=entry.max_score,
        is_wrong=entry.is_wrong,
        standard_answer_text=source.standard_answer_text,
        scoring_points=source.scoring_points or [],
        student_answer_text=entry.student_answer_text,
        missed_points=entry.missed_points or [],
        teacher_comment=entry.teacher_comment,
        knowledge_point_names=source.knowledge_point_names or [],
        error_reason=entry.error_reason,
        has_image=bool(entry.image_storage_key),
        released_at=entry.released_at,
    )


@router.get("/me/wrongbook/entries/{entry_id}", response_model=WrongbookEntryDetail)
def read_my_wrongbook_entry(
    session: SessionDep, current_user: CurrentStudentUser, entry_id: uuid.UUID
) -> Any:
    learner, _student = get_current_learner(session=session, current_user=current_user)
    entry, source = _owned_entry(session, learner=learner, entry_id=entry_id)
    return _entry_detail(entry, source)


@router.patch("/me/wrongbook/entries/{entry_id}", response_model=WrongbookEntryDetail)
def update_my_wrongbook_entry(
    session: SessionDep,
    current_user: CurrentStudentUser,
    entry_id: uuid.UUID,
    update_in: WrongbookEntryUpdate,
) -> Any:
    """单独修改错因标注（复习提交之外的入口）。传 null 清除已标注的错因。"""
    learner, _student = get_current_learner(session=session, current_user=current_user)
    entry, source = _owned_entry(session, learner=learner, entry_id=entry_id)
    entry.error_reason = update_in.error_reason
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return _entry_detail(entry, source)


def _learning_advice_stats(
    session: Session, learner: LearnerProfile, exam_id: uuid.UUID | None = None
) -> dict[str, Any] | None:
    """聚合错题本统计供学习建议模型参考；没有错题时返回 None。

    传 exam_id 时只统计该考试的错题，用于单场成绩报告页的学习建议。
    """
    rows = session.exec(
        select(WrongQuestionEntry, WrongQuestionSource, WrongQuestionReview)
        .select_from(WrongQuestionEntry)
        .join(
            WrongQuestionSource,
            WrongQuestionEntry.source_id == WrongQuestionSource.id,  # type: ignore[arg-type]
        )
        .outerjoin(
            WrongQuestionReview,
            WrongQuestionReview.entry_id == WrongQuestionEntry.id,  # type: ignore[arg-type]
        )
        .where(
            *_my_wrongbook_scope(learner),
            col(WrongQuestionEntry.is_wrong).is_(True),
            *([WrongQuestionSource.exam_id == exam_id] if exam_id is not None else []),
        )
    ).all()
    if not rows:
        return None

    mastery = {
        (item.subject, item.knowledge_point_name): item
        for item in wrongbook_review.rebuild_mastery(session, learner=learner)
    }
    points: dict[str, dict[str, Any]] = {}
    reasons: Counter[str] = Counter()
    exams: dict[str, dict[str, Any]] = {}
    for entry, source, review in rows:
        if entry.error_reason is not None:
            reasons[entry.error_reason.value] += 1
        for name in source.knowledge_point_names or []:
            point = points.setdefault(
                name,
                {
                    "knowledge_point": name,
                    "subject": source.subject,
                    "wrong_times": 0,
                    "last_wrong_at": None,
                    "review_count": 0,
                },
            )
            point["wrong_times"] += 1
            last = point["last_wrong_at"]
            if last is None or entry.released_at > last:
                point["last_wrong_at"] = entry.released_at
            if review:
                point["review_count"] += review.review_count
        exam_key = str(source.exam_id or source.release_id or source.exam_title)
        exam = exams.setdefault(
            exam_key,
            {
                "exam_title": source.exam_title,
                "exam_date": source.exam_date,
                "released_at": entry.released_at,
                "wrong_count": 0,
                "lost_points": 0.0,
            },
        )
        exam["wrong_count"] += 1
        if entry.released_at > exam["released_at"]:
            exam["released_at"] = entry.released_at
        if entry.max_score:
            exam["lost_points"] += max(
                0.0, float(entry.max_score) - float(entry.score or 0)
            )

    point_rows = sorted(
        points.values(),
        key=lambda item: (-item["wrong_times"], item["knowledge_point"]),
    )
    for point in point_rows:
        item = mastery.get((point["subject"] or "", point["knowledge_point"]))
        point["wrong_rate"] = (
            round(item.wrong_count / item.attempts * 100)
            if item and item.attempts
            else 0
        )
        if point["last_wrong_at"] is not None:
            point["last_wrong_at"] = point["last_wrong_at"].isoformat()
    recent_exams = sorted(
        exams.values(), key=lambda item: item["released_at"], reverse=True
    )[:3]
    for exam in recent_exams:
        exam["released_at"] = exam["released_at"].isoformat()
        exam["lost_points"] = round(exam["lost_points"], 2)
        # exam_date 是 date 对象，json.dumps 不可序列化，统一转 ISO 字符串
        if exam["exam_date"] is not None:
            exam["exam_date"] = exam["exam_date"].isoformat()
    return {
        "wrong_total": len(rows),
        "knowledge_points": point_rows,
        "error_reasons": dict(reasons),
        "recent_exams": recent_exams,
    }


def _parse_learning_advice(parsed: dict[str, Any]) -> dict[str, Any] | None:
    """校验模型返回的结构；字段缺失或类型不对都视为不可用。"""
    overall = str(parsed.get("overall") or "").strip()
    raw_points = parsed.get("focus_points")
    raw_plan = parsed.get("weekly_plan")
    if (
        not overall
        or not isinstance(raw_points, list)
        or not raw_points
        or not isinstance(raw_plan, list)
        or not raw_plan
    ):
        return None
    focus_points: list[dict[str, Any]] = []
    for item in raw_points:
        if not isinstance(item, dict):
            return None
        name = str(item.get("knowledge_point") or "").strip()
        advice = str(item.get("advice") or "").strip()
        raw_times = item.get("times")
        if raw_times is None:
            return None
        try:
            times = int(raw_times)
        except (TypeError, ValueError):
            return None
        if not name or not advice:
            return None
        focus_points.append({"knowledge_point": name, "times": times, "advice": advice})
    weekly_plan = [str(step).strip() for step in raw_plan if str(step).strip()]
    if not weekly_plan:
        return None
    return {
        "overall": overall,
        "focus_points": focus_points,
        "weekly_plan": weekly_plan[:5],
    }


@router.get("/me/learning-advice", response_model=LearningAdvicePublic)
def read_my_learning_advice(
    session: SessionDep,
    current_user: CurrentStudentUser,
    exam_id: uuid.UUID | None = None,
) -> Any:
    """基于错题本的针对性学习建议。

    传 exam_id 时只看该考试的错题（单场成绩报告页），否则看全部错题本。
    暂不缓存——每次请求都重新统计并调用模型生成；若成本或耗时成为问题，
    可后续按「统计摘要哈希」加缓存复用结果。
    """
    # 学习建议面向在校学生：未绑定学校档案的账号返回 404
    get_current_student_profile(session=session, current_user=current_user)
    learner, _student = get_current_learner(session=session, current_user=current_user)
    stats = _learning_advice_stats(session, learner, exam_id=exam_id)
    if stats is None:
        return LearningAdvicePublic(has_data=False)

    prompt = (
        "你是一位耐心的中学老师，正在根据学生的错题记录写学习建议。"
        "要求：说人话；具体到知识点和出错次数；禁止空话套话"
        "（不要写「努力学习」「继续加油」这类话）。"
        "只返回 JSON，不要 Markdown："
        '{"overall":"一段总述，点名最薄弱的知识点和它出错的次数",'
        '"focus_points":[{"knowledge_point":"知识点名","times":出错次数,'
        '"advice":"具体到题型或操作的建议，比如先背公式再做哪类题"}],'
        '"weekly_plan":["3-5条本周可执行的动作"]}。\n'
        f"错题统计：{json.dumps(stats, ensure_ascii=False)}"
    )
    defaults = get_grading_defaults(session)
    try:
        parsed, _used_model, _elapsed_ms = call_json_model(
            provider=defaults["grading_provider"],
            model=defaults["grading_model"],
            fallback_models=[],
            messages=[{"role": "user", "content": prompt}],
        )
    except VisionGradingError as exc:
        raise HTTPException(status_code=502, detail=f"学习建议生成失败：{exc}") from exc
    advice = _parse_learning_advice(parsed)
    if advice is None:
        raise HTTPException(status_code=502, detail="学习建议返回内容不完整，请重试")
    return LearningAdvicePublic(
        has_data=True,
        overall=advice["overall"],
        focus_points=[
            LearningAdviceFocusPoint(**item) for item in advice["focus_points"]
        ],
        weekly_plan=advice["weekly_plan"],
        generated_at=get_datetime_utc(),
    )


PRACTICE_SHEET_MAX_SEEDS = 5


def _practice_sheet_public(
    session: Session, sheet: PracticeSheet
) -> PracticeSheetPublic:
    attempts = session.exec(
        select(PracticeSheetAttempt)
        .where(PracticeSheetAttempt.sheet_id == sheet.id)
        .order_by(col(PracticeSheetAttempt.item_index))
    ).all()
    return PracticeSheetPublic(
        id=sheet.id,
        subject=sheet.subject,
        knowledge_point=sheet.knowledge_point,
        title=sheet.title,
        items=[PracticeSheetItemPublic(**item) for item in sheet.items],
        seed_count=sheet.seed_count,
        attempts=[
            PracticeSheetAttemptPublic(
                id=attempt.id,
                item_index=attempt.item_index,
                status=attempt.status,
                verdict=attempt.verdict,
                score=attempt.score,
                comment=attempt.comment,
                student_answer_text=attempt.student_answer_text,
                created_at=attempt.created_at,
            )
            for attempt in attempts
        ],
        created_at=sheet.created_at,
    )


@router.post("/me/practice-sheets", response_model=PracticeSheetPublic)
def create_my_practice_sheet(
    session: SessionDep,
    current_user: CurrentStudentUser,
    sheet_in: PracticeSheetCreate,
) -> Any:
    """以学生在该知识点上的错题为种子，出变式练习卷。

    错题题干+参考答案喂给模型，要求换情境/数值/问法重新命题，
    并给出参考答案和解析。生成即落库，刷新和打印都能找到同一份。
    """
    get_current_student_profile(session=session, current_user=current_user)
    learner, _student = get_current_learner(session=session, current_user=current_user)
    rows = session.exec(
        select(WrongQuestionEntry, WrongQuestionSource)
        .select_from(WrongQuestionEntry)
        .join(
            WrongQuestionSource,
            WrongQuestionEntry.source_id == WrongQuestionSource.id,  # type: ignore[arg-type]
        )
        .where(
            *_my_wrongbook_scope(learner),
            col(WrongQuestionEntry.is_wrong).is_(True),
        )
    ).all()
    seeds = [
        source
        for _entry, source in rows
        if sheet_in.knowledge_point in (source.knowledge_point_names or [])
    ]
    if not seeds:
        raise HTTPException(
            status_code=422,
            detail="这个知识点下还没有错题，先考一场再来出变式题",
        )
    seed_payload = [
        {
            "question": (source.question_text or "")[:600],
            "reference_answer": (source.standard_answer_text or "")[:400],
        }
        for source in seeds[:PRACTICE_SHEET_MAX_SEEDS]
    ]
    subject = seeds[0].subject or ""
    prompt = (
        f"你是一位中学{subject or '物理'}老师，正在围绕知识点「{sheet_in.knowledge_point}」"
        f"出 {sheet_in.count} 道变式练习题。下面是学生做错过的题目和参考答案。"
        "要求：考查同一个知识点，但换情境、换数值或换问法，不得照抄原题；"
        "难度与原题相当；每题给出参考答案和一两句解析。"
        "只返回 JSON，不要 Markdown："
        '{"questions":[{"question_text":"题目","answer":"参考答案","analysis":"解析"}]}。\n'
        f"学生错题：{json.dumps(seed_payload, ensure_ascii=False)}"
    )
    defaults = get_grading_defaults(session)
    try:
        parsed, used_model, _elapsed_ms = call_json_model(
            provider=defaults["grading_provider"],
            model=defaults["grading_model"],
            fallback_models=[],
            messages=[{"role": "user", "content": prompt}],
        )
    except VisionGradingError as exc:
        raise HTTPException(status_code=502, detail=f"变式题生成失败：{exc}") from exc
    items: list[dict] = []
    for raw in (parsed.get("questions") or [])[: sheet_in.count]:
        if not isinstance(raw, dict):
            continue
        question_text = str(raw.get("question_text") or "").strip()
        answer = str(raw.get("answer") or "").strip()
        if not question_text or not answer:
            continue
        items.append(
            {
                "question_text": question_text,
                "answer": answer,
                "analysis": str(raw.get("analysis") or "").strip(),
            }
        )
    if not items:
        raise HTTPException(status_code=502, detail="变式题返回内容不完整，请重试")
    sheet = PracticeSheet(
        learner_id=learner.id,
        student_user_id=current_user.id,
        subject=subject,
        knowledge_point=sheet_in.knowledge_point,
        title=f"{sheet_in.knowledge_point}变式练习",
        items=items,
        seed_count=len(seeds),
        model=used_model,
    )
    session.add(sheet)
    session.commit()
    session.refresh(sheet)
    return _practice_sheet_public(session, sheet)


@router.get("/me/practice-sheets", response_model=PracticeSheetsPublic)
def read_my_practice_sheets(
    session: SessionDep, current_user: CurrentStudentUser
) -> Any:
    learner, _student = get_current_learner(session=session, current_user=current_user)
    sheets = session.exec(
        select(PracticeSheet)
        .where(PracticeSheet.learner_id == learner.id)
        .order_by(col(PracticeSheet.created_at).desc())
    ).all()
    return PracticeSheetsPublic(
        data=[
            PracticeSheetListItem(
                id=sheet.id,
                subject=sheet.subject,
                knowledge_point=sheet.knowledge_point,
                title=sheet.title,
                item_count=len(sheet.items),
                created_at=sheet.created_at,
            )
            for sheet in sheets
        ],
        count=len(sheets),
    )


@router.get("/me/practice-sheets/{sheet_id}", response_model=PracticeSheetPublic)
def read_my_practice_sheet(
    session: SessionDep, current_user: CurrentStudentUser, sheet_id: uuid.UUID
) -> Any:
    learner, _student = get_current_learner(session=session, current_user=current_user)
    sheet = session.get(PracticeSheet, sheet_id)
    if sheet is None or sheet.learner_id != learner.id:
        raise HTTPException(status_code=404, detail="练习卷不存在")
    return _practice_sheet_public(session, sheet)


@router.post(
    "/me/practice-sheets/{sheet_id}/attempts",
    response_model=PracticeSheetAttemptPublic,
)
async def create_my_practice_attempt(
    session: SessionDep,
    current_user: CurrentStudentUser,
    sheet_id: uuid.UUID,
    item_index: Annotated[int, Form()],
    image: Annotated[UploadFile, File()],
) -> Any:
    """拍照提交变式练习某题的作答：立即返回 pending，后台判分。

    识别+判分要两次模型调用（1-2 分钟），同步等待在弱网络下长连接必断，
    前端拿不到结果。改为提交即返回，前端轮询 sheet 详情拿 verdict。
    判对推进该知识点在册错题的复习间隔，判错打回重练。每题只保留最新一次。
    """
    get_current_student_profile(session=session, current_user=current_user)
    learner, _student = get_current_learner(session=session, current_user=current_user)
    sheet = session.get(PracticeSheet, sheet_id)
    if sheet is None or sheet.learner_id != learner.id:
        raise HTTPException(status_code=404, detail="练习卷不存在")
    items = sheet.items or []
    if item_index < 0 or item_index >= len(items):
        raise HTTPException(status_code=422, detail="题号超出范围")
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=422, detail="请先选择作答照片")
    if len(image_bytes) > SNAP_MAX_IMAGE_BYTES:
        raise HTTPException(status_code=422, detail="图片超过 10MB，请压缩后再上传")

    await image.seek(0)
    stored = await store_upload_file(
        session=session, current_user=current_user, file=image
    )
    attempt = session.exec(
        select(PracticeSheetAttempt).where(
            PracticeSheetAttempt.sheet_id == sheet.id,
            PracticeSheetAttempt.item_index == item_index,
        )
    ).first()
    if attempt is None:
        attempt = PracticeSheetAttempt(sheet_id=sheet.id, learner_id=learner.id)
    attempt.item_index = item_index
    attempt.stored_file_id = stored.id
    attempt.status = PracticeAttemptStatus.PENDING
    attempt.verdict = None
    attempt.comment = ""
    attempt.student_answer_text = ""
    session.add(attempt)
    session.commit()
    session.refresh(attempt)

    if settings.ENVIRONMENT == "local":
        from app.services.practice_grading import run_practice_attempt

        run_practice_attempt(str(attempt.id))
        session.refresh(attempt)
    else:
        from app.worker import process_practice_attempt

        process_practice_attempt.send(str(attempt.id))

    return PracticeSheetAttemptPublic(
        id=attempt.id,
        item_index=attempt.item_index,
        status=attempt.status,
        verdict=attempt.verdict,
        score=attempt.score,
        comment=attempt.comment,
        student_answer_text=attempt.student_answer_text,
        created_at=attempt.created_at,
    )


SNAP_MAX_IMAGE_BYTES = 10 * 1024 * 1024


def _snap_extract_multi(
    image_bytes: bytes, defaults: dict[str, Any]
) -> list[tuple[str, str]]:
    """拍照批改的聚焦识别：读出照片里所有写了答案的题（最多 8 道）。

    批卷管线的整页结构化提取会逼模型把整页逐字转写，输出 token 是耗时大头
    （实测整页 80-130 秒）。这里只保留压缩题干（判分够用的关键条件）和学生
    作答，输出收敛了耗时就下来。
    """
    image = base64.b64encode(image_bytes).decode("ascii")
    prompt = (
        "这张照片里有学生作答的试卷内容。请找出所有写了答案的题（最多 8 道），"
        "每题给出：1) 题干——保留判分需要的条件、设问，选择题必须保留全部选项内容，"
        "150 字以内；2) 学生的手写作答原文。没写答案的题不要包含。"
        '只返回 JSON，不要 Markdown：{"items":[{"question_text":"题干（选择题含选项）","student_answer":"学生作答原文"}]}'
    )
    try:
        parsed, _used_model, _elapsed_ms = call_json_model(
            provider=defaults["vision_provider"],
            model=defaults["vision_model"],
            fallback_models=[],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image}"},
                        },
                    ],
                }
            ],
        )
    except VisionGradingError as exc:
        raise HTTPException(
            status_code=502, detail=f"题目识别失败，请重试：{exc}"
        ) from exc
    items: list[tuple[str, str]] = []
    for raw in (parsed.get("items") or [])[:8]:
        if not isinstance(raw, dict):
            continue
        question_text = str(raw.get("question_text") or "").strip()
        student_answer = str(raw.get("student_answer") or "").strip()
        if question_text:
            items.append((question_text, student_answer))
    return items


def _snap_transcribe(image_bytes: bytes, defaults: dict[str, Any]) -> str:
    """视觉模型读出照片中的题目文本。"""
    image = base64.b64encode(image_bytes).decode("ascii")
    prompt = (
        "请把照片里的题目完整读出来，包括题干、选项、公式和图中关键信息；"
        "公式尽量用纯文本表达，看不清的位置写「看不清」。"
        '只返回 JSON，不要 Markdown：{"question_text":"题目全文"}'
    )
    try:
        parsed, _used_model, _elapsed_ms = call_json_model(
            provider=defaults["vision_provider"],
            model=defaults["vision_model"],
            fallback_models=[],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image}"},
                        },
                    ],
                }
            ],
        )
    except VisionGradingError as exc:
        raise HTTPException(
            status_code=502, detail=f"题目识别失败，请重试：{exc}"
        ) from exc
    return str(parsed.get("question_text") or "").strip()


def _snap_standard_answer(
    question_text: str, defaults: dict[str, Any]
) -> tuple[str, str]:
    """解题模型独立解出标准答案，供答疑展示或批改对照。返回 (answer, explanation)。"""
    prompt = (
        "你是一位耐心的中学老师。请独立解答下面的题目，不要臆测题目之外的条件；"
        "题目信息不足时在 explanation 里说明缺少什么。"
        "只返回 JSON，不要 Markdown："
        '{"answer":"最终答案","explanation":"分步讲解，说人话，让学生看懂思路"}\n'
        f"题目：{question_text}"
    )
    try:
        parsed, _used_model, _elapsed_ms = call_json_model(
            provider=defaults["grading_provider"],
            model=defaults["grading_model"],
            fallback_models=[],
            messages=[{"role": "user", "content": prompt}],
        )
    except VisionGradingError as exc:
        raise HTTPException(
            status_code=502, detail=f"解答生成失败，请重试：{exc}"
        ) from exc
    answer = str(parsed.get("answer") or "").strip()
    explanation = str(parsed.get("explanation") or "").strip()
    if not answer or not explanation:
        raise HTTPException(status_code=502, detail="解答生成失败，请重试")
    return answer, explanation


def _snap_grade_call(
    *,
    question_text: str,
    student_answer: str,
    standard_answer: str,
    max_score: float,
    defaults: dict[str, Any],
) -> tuple[float, str]:
    """按评分细则风格判分，返回 (score, comment)。"""
    prompt = (
        "你是严谨的中文试卷阅卷教师。根据标准答案和满分给学生作答判分："
        "结果正确但过程有瑕疵酌情扣少量分；结果错误只看过程中有价值的步骤给步骤分；"
        "评语说人话，指出对在哪里、错在哪里、下次注意什么，不要空话。"
        "只返回 JSON，不要 Markdown："
        '{"score":0,"comment":"中文评语"}。score 必须在 0 到满分之间。\n'
        f"题目：{question_text}\n"
        f"学生作答：{student_answer}\n"
        f"标准答案：{standard_answer}\n"
        f"满分：{max_score}\n"
        "评分细则：按答案正确程度给分，关键步骤缺失要扣分"
    )
    try:
        parsed, _used_model, _elapsed_ms = call_json_model(
            provider=defaults["grading_provider"],
            model=defaults["grading_model"],
            fallback_models=[],
            messages=[{"role": "user", "content": prompt}],
        )
    except VisionGradingError as exc:
        raise HTTPException(status_code=502, detail=f"批改失败，请重试：{exc}") from exc
    try:
        score = float(parsed.get("score"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="批改失败，请重试") from exc
    score = min(max(score, 0.0), max_score)
    comment = str(parsed.get("comment") or "").strip()
    if not comment:
        raise HTTPException(status_code=502, detail="批改失败，请重试")
    return score, comment


def _snap_solve_and_grade_all(
    items: list[tuple[str, str]], max_score: float, defaults: dict[str, Any]
) -> list[dict]:
    """一次推理调用完成多题的独立解答+判分，返回每题 {score, comment}。

    每题两个推理调用（解题+判分）串行太慢，合并成一次：模型先在心里独立
    求解，再对照学生作答给分和评语。
    """
    payload = [
        {"question_text": question, "student_answer": answer}
        for question, answer in items
    ]
    prompt = (
        "你是严谨的中文阅卷教师。对下面每道题：先独立求出正确答案，再对照学生作答判分。"
        "结果正确但过程有瑕疵酌情扣少量分；结果错误只看有价值步骤给步骤分；"
        "评语说人话，指出对在哪里、错在哪里，不要空话。"
        "只返回 JSON，不要 Markdown："
        '{"items":[{"score":0,"comment":"中文评语"}]}，items 顺序与输入一致，'
        f"score 在 0 到 {max_score} 之间。\n"
        f"题目与学生作答：{json.dumps(payload, ensure_ascii=False)}"
    )
    try:
        parsed, _used_model, _elapsed_ms = call_json_model(
            provider=defaults["grading_provider"],
            model=defaults["grading_model"],
            fallback_models=[],
            messages=[{"role": "user", "content": prompt}],
        )
    except VisionGradingError as exc:
        raise HTTPException(status_code=502, detail=f"批改失败，请重试：{exc}") from exc
    results: list[dict] = []
    raw_items = parsed.get("items") or []
    for index, (question, answer) in enumerate(items):
        raw = raw_items[index] if index < len(raw_items) else None
        if not isinstance(raw, dict):
            raise HTTPException(status_code=502, detail="批改返回内容不完整，请重试")
        try:
            score = float(raw.get("score"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=502, detail="批改失败，请重试") from exc
        comment = str(raw.get("comment") or "").strip()
        if not comment:
            raise HTTPException(status_code=502, detail="批改失败，请重试")
        results.append(
            {
                "question_text": question,
                "student_answer": answer,
                "score": min(max(score, 0.0), max_score),
                "comment": comment,
            }
        )
    return results


@router.post("/me/snap", response_model=SnapSolvePublic | SnapGradePublic)
async def snap_question(
    session: SessionDep,
    current_user: CurrentUser,
    image: Annotated[UploadFile, File()],
    mode: Annotated[Literal["solve", "grade"], Form()] = "solve",
    max_score: Annotated[float, Form()] = 10.0,
) -> Any:
    """拍题答疑 / 拍照批改。一次性问答，不写入任何学习记录。

    所有登录角色可用（老师和管理员也要靠它试识别效果），学生之外的角色
    只是没有「我的学习记录」入口，问答本身不涉及学生数据。
    """
    del current_user  # 仅做登录校验（依赖注入），不使用其数据
    if max_score <= 0 or max_score > 100:
        raise HTTPException(status_code=422, detail="满分需在 0 到 100 之间")
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=422, detail="请先选择题目照片")
    if len(image_bytes) > SNAP_MAX_IMAGE_BYTES:
        raise HTTPException(status_code=422, detail="图片超过 10MB，请压缩后再上传")
    model_image_bytes = downscale_image_for_model(image_bytes)
    # 同一张照片同一模式的结果落盘缓存：调用要约 1 分钟，弱网络下客户端
    # 长连接可能中断，但服务端会继续算完；用户点「重试」时命中缓存秒回。
    cache_key = hashlib.sha256(
        model_image_bytes + f"|{mode}|{max_score}".encode()
    ).hexdigest()
    cache_dir = Path(settings.STORAGE_CACHE_DIR) / "snap"
    cache_path = cache_dir / f"{cache_key}.json"
    try:
        cached = json.loads(cache_path.read_bytes())
        if isinstance(cached, dict) and cached.get("mode") == mode:
            return cached
    except (OSError, ValueError):
        pass
    defaults = get_grading_defaults(session)
    if mode == "solve":
        question_text = _snap_transcribe(model_image_bytes, defaults)
        if not question_text:
            raise HTTPException(status_code=422, detail="没认出题目，请拍清楚一点再试")
        answer, explanation = _snap_standard_answer(question_text, defaults)
        result: dict[str, Any] = SnapSolvePublic(
            question_text=question_text,
            answer=answer,
            explanation=explanation,
        ).model_dump()
    else:
        extracted = _snap_extract_multi(model_image_bytes, defaults)
        if not extracted:
            raise HTTPException(status_code=422, detail="没认出题目，请拍清楚一点再试")
        if not any(answer for _question, answer in extracted):
            raise HTTPException(
                status_code=422, detail="没看到你的作答，请拍到写了答案的区域再试"
            )
        extracted = [(question, answer) for question, answer in extracted if answer]
        graded = _snap_solve_and_grade_all(extracted, max_score, defaults)
        first = graded[0]
        result = SnapGradePublic(
            question_text=first["question_text"],
            student_answer=first["student_answer"],
            score=first["score"],
            max_score=max_score,
            comment=first["comment"],
            items=[SnapGradeItemPublic(**item, max_score=max_score) for item in graded],
        ).model_dump()
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(json.dumps(result, ensure_ascii=False).encode())
    except OSError:
        pass
    return result


@router.get("/me/wrongbook/entries/{entry_id}/image")
def read_my_wrongbook_entry_image(
    session: SessionDep,
    entry_id: uuid.UUID,
    authorization: str | None = Header(default=None),
) -> FileResponse:
    """错题的答题裁切图。

    走 Authorization 头而不是依赖注入，`<img>` 取图时前端用 fetch 带上 token。
    图片存在学习者命名空间，因此这里只需校验条目归属，不涉及考试权限。
    """
    user = get_user_from_authorization_header(
        session=session, authorization=authorization
    )
    if user.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="仅学生可访问错题本")
    learner, _student = get_current_learner(session=session, current_user=user)
    entry, _source = _owned_entry(session, learner=learner, entry_id=entry_id)
    if not entry.image_storage_key:
        raise HTTPException(status_code=404, detail="该题没有留存答题图")
    try:
        path = materialize_storage_key(entry.image_storage_key)
    except Exception:
        raise HTTPException(status_code=404, detail="答题图暂不可用")
    if not path.exists():
        raise HTTPException(status_code=404, detail="答题图暂不可用")
    return FileResponse(path=path, media_type="image/webp", filename=path.name)


@router.get("/me/exams/{exam_id}/report", response_model=StudentExamReportPublic)
def read_my_exam_report(
    session: SessionDep, current_user: CurrentStudentUser, exam_id: uuid.UUID
) -> Any:
    student, _class_name, submissions = _get_my_exam_context(
        session=session, current_user=current_user
    )
    my_submission_ids = {submission.id for submission in submissions}
    # 数据隔离：未参加的考试一律 404，不区分「不存在」与「属于别人」
    exam = session.get(Exam, exam_id)
    if not exam or not any(submission.exam_id == exam_id for submission in submissions):
        raise HTTPException(status_code=404, detail="Exam not found")

    release = _published_release(session, exam_id)
    if not release:
        raise HTTPException(status_code=404, detail="成绩尚未发布")
    release_items = list(
        session.exec(
            select(ScoreReleaseItem).where(
                ScoreReleaseItem.release_id == release.id,
                col(ScoreReleaseItem.submission_id).in_(my_submission_ids),
            )
        ).all()
    )
    if not release_items:
        raise HTTPException(status_code=404, detail="成绩尚未发布")

    class_rank, class_size, class_name = _release_class_position(
        session, release, my_submission_ids
    )
    entries = _my_entries_by_label(
        session, release_id=release.id, submission_ids=my_submission_ids
    )
    questions = [
        StudentExamReportQuestion(
            label=item.label,
            score=item.score,
            max_score=item.max_score,
            score_source="final",
            comment=item.comment,
            suggested_comment=None,
            entry_id=entries[item.label][0].id if item.label in entries else None,
            knowledge_point_names=(
                entries[item.label][1].knowledge_point_names
                if item.label in entries
                else []
            ),
            has_image=(
                bool(entries[item.label][0].image_storage_key)
                if item.label in entries
                else False
            ),
        )
        for item in sorted(release_items, key=lambda value: value.label)
    ]
    total_score = sum(
        question.score for question in questions if question.score is not None
    )
    total_max_score = sum(
        question.max_score for question in questions if question.max_score is not None
    )
    return StudentExamReportPublic(
        exam_id=exam.id,
        title=exam.title,
        subject=exam.subject,
        grade_level=exam.grade_level,
        exam_date=exam.exam_date,
        class_name=class_name,
        student_name=student.name,
        total_score=(
            round(total_score, 2)
            if any(question.score is not None for question in questions)
            else None
        ),
        total_max_score=(
            round(total_max_score, 2)
            if any(question.max_score is not None for question in questions)
            else None
        ),
        class_rank=class_rank,
        class_size=class_size,
        questions=questions,
    )
