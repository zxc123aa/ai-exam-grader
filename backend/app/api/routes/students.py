import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlmodel import Session, col, select

from app.api.deps import (
    CurrentUser,
    SessionDep,
    get_user_from_authorization_header,
    require_roles,
)
from app.models import (
    ClassGroup,
    Exam,
    ExamScoreSummaryPublic,
    ExamScoreSummaryRow,
    ScoreRelease,
    ScoreReleaseItem,
    ScoreReleaseStatus,
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
    WrongQuestionEntry,
    WrongQuestionEntryStatus,
    WrongQuestionSource,
)
from app.services.object_storage import materialize_storage_key

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


def _my_entry_filter(student: Student, user_id: uuid.UUID) -> Any:
    """错题本归属：学校侧档案或登录账号任一命中即属于我。

    学校侧 `Student` 会因升班或删除而失效（`ON DELETE SET NULL`），登录账号是当前
    唯一稳定的锚点；终身身份见 AEG-068。
    """
    return or_(
        WrongQuestionEntry.student_id == student.id,
        WrongQuestionEntry.student_user_id == user_id,
    )


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
    """我的错题本。只读发布时写入的快照，与考试和答卷的存续无关。"""
    student = get_current_student_profile(session=session, current_user=current_user)
    base = (
        select(WrongQuestionEntry, WrongQuestionSource)
        .join(
            WrongQuestionSource,
            WrongQuestionEntry.source_id == WrongQuestionSource.id,  # type: ignore[arg-type]
        )
        .where(
            _my_entry_filter(student, current_user.id),
            WrongQuestionEntry.status == WrongQuestionEntryStatus.ACTIVE,
        )
    )
    rows = list(session.exec(base).all())
    # 筛选项从我自己的条目里取，学生看不到与自己无关的学科和知识点。
    subjects = sorted(
        {source.subject for _entry, source in rows if source.subject}, reverse=False
    )
    knowledge_points = sorted(
        {
            name
            for _entry, source in rows
            for name in source.knowledge_point_names or []
            if name
        }
    )
    selected = [
        (entry, source)
        for entry, source in rows
        if (not wrong_only or entry.is_wrong)
        and (not subject or source.subject == subject)
        and (not exam_id or source.exam_id == exam_id)
        and (
            not knowledge_point
            or knowledge_point in (source.knowledge_point_names or [])
        )
    ]
    selected.sort(
        key=lambda row: (row[0].released_at, row[0].question_label), reverse=True
    )
    page = selected[skip : skip + limit] if limit > 0 else selected
    return WrongbookEntriesPublic(
        data=[
            WrongbookEntryListItem(
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
                has_image=bool(entry.image_storage_key),
                released_at=entry.released_at,
            )
            for entry, source in page
        ],
        count=len(selected),
        subjects=subjects,
        knowledge_points=knowledge_points,
    )


def _owned_entry(
    session: Session, *, current_user: User, entry_id: uuid.UUID
) -> tuple[WrongQuestionEntry, WrongQuestionSource]:
    student = get_current_student_profile(session=session, current_user=current_user)
    row = session.exec(
        select(WrongQuestionEntry, WrongQuestionSource)
        .join(
            WrongQuestionSource,
            WrongQuestionEntry.source_id == WrongQuestionSource.id,  # type: ignore[arg-type]
        )
        .where(
            WrongQuestionEntry.id == entry_id,
            _my_entry_filter(student, current_user.id),
        )
    ).first()
    if row is None:
        # 别人的错题与不存在的错题返回同一个结果，不泄露存在性
        raise HTTPException(status_code=404, detail="错题不存在")
    return row


@router.get("/me/wrongbook/entries/{entry_id}", response_model=WrongbookEntryDetail)
def read_my_wrongbook_entry(
    session: SessionDep, current_user: CurrentStudentUser, entry_id: uuid.UUID
) -> Any:
    entry, source = _owned_entry(session, current_user=current_user, entry_id=entry_id)
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
        has_image=bool(entry.image_storage_key),
        released_at=entry.released_at,
    )


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
    entry, _source = _owned_entry(session, current_user=user, entry_id=entry_id)
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
