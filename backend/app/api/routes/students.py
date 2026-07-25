import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, col, select

from app.api.deps import CurrentUser, SessionDep, require_roles
from app.api.routes.exams import _build_exam_scores_summary
from app.models import (
    ClassGroup,
    Exam,
    ExamScoreSummaryPublic,
    ExamScoreSummaryRow,
    Student,
    StudentExamListItemPublic,
    StudentExamListPublic,
    StudentExamReportPublic,
    StudentExamReportQuestion,
    StudentSubmission,
    SubmissionAnnotation,
    User,
    UserRole,
)

router = APIRouter(prefix="/students", tags=["students"])

# 学生专属端点：教师/管理员访问一律 403
CurrentStudentUser = Annotated[User, Depends(require_roles(UserRole.STUDENT))]


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
            select(StudentSubmission).where(
                StudentSubmission.student_id == student.id
            )
        ).all()
    )
    matched_ids = {submission.id for submission in submissions}
    if class_name:
        fallback = session.exec(
            select(StudentSubmission).where(
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
    classmates = [
        entry
        for key, entry in merged.items()
        if key[0] == class_key
    ]
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
def read_my_exams(
    session: SessionDep, current_user: CurrentStudentUser
) -> Any:
    _student, _class_name, submissions = _get_my_exam_context(
        session=session, current_user=current_user
    )
    my_submission_ids = {submission.id for submission in submissions}
    exam_ids = list(dict.fromkeys(submission.exam_id for submission in submissions))
    items: list[StudentExamListItemPublic] = []
    for exam_id in exam_ids:
        exam = session.get(Exam, exam_id)
        if not exam:
            continue
        summary = _build_exam_scores_summary(session=session, exam_id=exam_id)
        my_rows = [
            row for row in summary.data if row.submission_id in my_submission_ids
        ]
        if not my_rows:
            continue
        class_rank, class_size, class_name = _compute_class_position(
            summary=summary,
            my_rows=my_rows,
            my_submission_ids=my_submission_ids,
        )
        labels = {
            question.label for row in my_rows for question in row.questions
        }
        total_score = sum(
            row.total_score for row in my_rows if row.total_score is not None
        )
        total_max_score = sum(
            row.total_max_score
            for row in my_rows
            if row.total_max_score is not None
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
                    if any(row.total_score is not None for row in my_rows)
                    else None
                ),
                total_max_score=(
                    round(total_max_score, 2)
                    if any(row.total_max_score is not None for row in my_rows)
                    else None
                ),
                class_rank=class_rank,
                class_size=class_size,
                question_count=len(labels),
                pending_review_count=sum(
                    row.pending_review_count for row in my_rows
                ),
            )
        )
    items.sort(
        key=lambda item: (item.exam_date is not None, item.exam_date),
        reverse=True,
    )
    return StudentExamListPublic(data=items, count=len(items))


@router.get(
    "/me/exams/{exam_id}/report", response_model=StudentExamReportPublic
)
def read_my_exam_report(
    session: SessionDep, current_user: CurrentStudentUser, exam_id: uuid.UUID
) -> Any:
    student, _class_name, submissions = _get_my_exam_context(
        session=session, current_user=current_user
    )
    my_submission_ids = {submission.id for submission in submissions}
    # 数据隔离：未参加的考试一律 404，不区分「不存在」与「属于别人」
    exam = session.get(Exam, exam_id)
    if not exam or not any(
        submission.exam_id == exam_id for submission in submissions
    ):
        raise HTTPException(status_code=404, detail="Exam not found")

    summary = _build_exam_scores_summary(session=session, exam_id=exam_id)
    my_rows = [
        row for row in summary.data if row.submission_id in my_submission_ids
    ]
    if not my_rows:
        raise HTTPException(status_code=404, detail="Exam not found")
    class_rank, class_size, class_name = _compute_class_position(
        summary=summary,
        my_rows=my_rows,
        my_submission_ids=my_submission_ids,
    )

    # 逐题合并：同一 label 优先教师复核后的最终分（final）
    by_label: dict[str, Any] = {}
    for row in my_rows:
        for question in row.questions:
            existing = by_label.get(question.label)
            if existing is None or (
                existing.score_source != "final"
                and question.score_source == "final"
            ):
                by_label[question.label] = question
    annotation_ids = [
        question.annotation_id
        for question in by_label.values()
        if question.annotation_id
    ]
    annotations_by_id = (
        {
            annotation.id: annotation
            for annotation in session.exec(
                select(SubmissionAnnotation).where(
                    col(SubmissionAnnotation.id).in_(annotation_ids)
                )
            ).all()
        }
        if annotation_ids
        else {}
    )
    questions = [
        StudentExamReportQuestion(
            label=question.label,
            score=question.score,
            max_score=question.max_score,
            score_source=question.score_source,
            comment=(
                annotation.comment
                if (annotation := annotations_by_id.get(question.annotation_id))
                else None
            ),
            suggested_comment=(
                annotation.suggested_comment
                if (annotation := annotations_by_id.get(question.annotation_id))
                else None
            ),
        )
        for _label, question in sorted(by_label.items())
    ]
    total_score = sum(
        question.score for question in questions if question.score is not None
    )
    total_max_score = sum(
        question.max_score
        for question in questions
        if question.max_score is not None
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
