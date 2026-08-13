import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, or_
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
    WrongbookMasteryItem,
    WrongbookMasteryPublic,
    WrongbookReviewCreate,
    WrongbookReviewPublic,
    WrongQuestionEntry,
    WrongQuestionEntryStatus,
    WrongQuestionReview,
    WrongQuestionSource,
)
from app.services import wrongbook_review
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


def _my_wrongbook_scope(student: Student, user_id: uuid.UUID) -> list[Any]:
    """我的、且当前有效的错题条目。所有错题本查询都从这里出发。"""
    return [
        _my_entry_filter(student, user_id),
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
    student = get_current_student_profile(session=session, current_user=current_user)
    scope = _my_wrongbook_scope(student, current_user.id)
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
                review_count=review.review_count if review else 0,
                next_due_at=review.next_due_at if review else None,
            )
            for entry, source, review in rows
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
        has_image=bool(entry.image_storage_key),
        released_at=entry.released_at,
        review_count=review.review_count if review else 0,
        next_due_at=review.next_due_at if review else None,
    )


@router.get("/me/wrongbook/due", response_model=WrongbookEntriesPublic)
def read_my_due_reviews(
    session: SessionDep, current_user: CurrentStudentUser, limit: int = 20
) -> Any:
    """今天该复习的错题。没复习过的排最前，其余按到期时间。"""
    student = get_current_student_profile(session=session, current_user=current_user)
    rows = wrongbook_review.due_entries(
        session, student=student, user_id=current_user.id, limit=limit
    )
    total = wrongbook_review.due_count(
        session, student=student, user_id=current_user.id
    )
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
    student = get_current_student_profile(session=session, current_user=current_user)
    wrongbook_review.rebuild_mastery(session, student=student, user_id=current_user.id)
    rows = wrongbook_review.cram_list(
        session,
        student=student,
        user_id=current_user.id,
        subject=subject,
        limit=limit,
    )
    return WrongbookEntriesPublic(
        data=[_entry_list_item(entry, source) for entry, source, _score in rows],
        count=len(rows),
    )


@router.get("/me/wrongbook/mastery", response_model=WrongbookMasteryPublic)
def read_my_mastery(session: SessionDep, current_user: CurrentStudentUser) -> Any:
    """按知识点的掌握度。派生数据，每次请求按当前错题本重算。"""
    student = get_current_student_profile(session=session, current_user=current_user)
    rows = wrongbook_review.rebuild_mastery(
        session, student=student, user_id=current_user.id
    )
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


@router.post(
    "/me/wrongbook/entries/{entry_id}/review", response_model=WrongbookReviewPublic
)
def review_my_wrongbook_entry(
    session: SessionDep,
    current_user: CurrentStudentUser,
    entry_id: uuid.UUID,
    review_in: WrongbookReviewCreate,
) -> Any:
    """提交一次复习结果，推进下次到期时间。"""
    entry, source = _owned_entry(session, current_user=current_user, entry_id=entry_id)
    student = get_current_student_profile(session=session, current_user=current_user)
    review = wrongbook_review.record_review(
        session,
        entry=entry,
        source=source,
        student=student,
        user_id=current_user.id,
        result=review_in.result,
    )
    return WrongbookReviewPublic(
        entry_id=entry.id,
        result=review.result,
        review_count=review.review_count,
        interval_days=review.interval_days,
        next_due_at=review.next_due_at,
        due_count=wrongbook_review.due_count(
            session, student=student, user_id=current_user.id
        ),
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
