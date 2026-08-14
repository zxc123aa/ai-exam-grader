"""成绩发布后把学生的逐题结果快照进错题本。

为什么是快照而不是视图（D-027）：删除考试会级联清空题目、批注和成绩发布记录，
裁切图还依赖处理任务的 JSON 或按题区实时重裁。做成视图的话，老师删一场考试、
学校欠费冻结或学生升班，学生的「终身」错题本就静默失效了。

因此这里把题干、标准答案、评分点、学生作答、未命中评分点和裁切图各留一份，
对来源只保留弱引用。
"""

import logging
import uuid
from io import BytesIO

from PIL import Image
from sqlmodel import Session, col, select

from app.models import (
    Exam,
    ExamQuestion,
    ExamQuestionRegion,
    ExamRegion,
    GradingItem,
    LearnerProfile,
    ScoreRelease,
    ScoreReleaseItem,
    ScoreReleaseStatus,
    StandardAnswer,
    StandardAnswerRevision,
    StoredFile,
    Student,
    StudentSubmission,
    SubmissionAnnotation,
    WrongQuestionEntry,
    WrongQuestionEntryStatus,
    WrongQuestionSource,
)
from app.services.knowledge_points import question_knowledge_names
from app.services.object_storage import put_storage_bytes
from app.services.submission_crops import (
    crop_region_from_image,
    render_stored_file_page_image,
    resolve_exam_region_paper_page,
)

logger = logging.getLogger(__name__)

IMAGE_MAX_WIDTH = 1600
IMAGE_QUALITY = 82


def build_entry_image_key(*, entry_id: uuid.UUID) -> str:
    """错题图放学习者命名空间，与考试和答卷的生命周期无关。"""
    return f"wrongbook/entries/{entry_id}.webp"


def extract_missed_points(annotation: SubmissionAnnotation) -> list[dict]:
    """从判分证据里取未命中的评分点。

    `grading_evidence` 是混合数组：既有 `{"stage": ...}` 的流水线记录，也有判分模型
    按评分点返回的 `{"point","matched","points","reason"}`。只保留后者中未命中的项。

    不要用 `grading_reasons`：那里装的是复核门禁信号（low_confidence、unreadable
    等），描述系统对自己识别质量的判断，不是学生的失分原因，也不该给学生看。
    """
    missed: list[dict] = []
    for item in annotation.grading_evidence or []:
        if not isinstance(item, dict) or "stage" in item:
            continue
        if "point" not in item and "matched" not in item:
            continue
        if item.get("matched") is True:
            continue
        entry = {
            "point": str(item.get("point") or "").strip(),
            "reason": str(item.get("reason") or "").strip(),
        }
        if item.get("points") is not None:
            try:
                entry["points"] = float(item["points"])
            except (TypeError, ValueError):
                pass
        if entry["point"] or entry["reason"]:
            missed.append(entry)
    return missed


def _resolve_question(
    session: Session, *, exam_id: uuid.UUID, annotation: SubmissionAnnotation
) -> tuple[ExamQuestion | None, ExamRegion | None]:
    region = (
        session.get(ExamRegion, annotation.exam_region_id)
        if annotation.exam_region_id
        else None
    )
    question: ExamQuestion | None = None
    if region is not None:
        link = session.exec(
            select(ExamQuestionRegion).where(
                ExamQuestionRegion.exam_region_id == region.id
            )
        ).first()
        if link:
            question = session.get(ExamQuestion, link.question_id)
    if question is None:
        question = session.exec(
            select(ExamQuestion).where(
                ExamQuestion.exam_id == exam_id,
                ExamQuestion.label == annotation.label,
            )
        ).first()
    return question, region


def _resolve_answer(
    session: Session,
    *,
    annotation: SubmissionAnnotation,
    question: ExamQuestion | None,
) -> tuple[str | None, list[dict]]:
    """取该题当时使用的标准答案与评分点。

    优先用批改项锁定的 revision，保证学生看到的是判分时那一版，而不是之后被改过的。
    """
    item = session.exec(
        select(GradingItem)
        .where(GradingItem.annotation_id == annotation.id)
        .order_by(col(GradingItem.completed_at).desc())
    ).first()
    if item and item.answer_revision_id:
        revision = session.get(StandardAnswerRevision, item.answer_revision_id)
        if revision:
            return revision.answer_text, list(revision.scoring_points or [])
    if annotation.exam_region_id:
        answer = session.exec(
            select(StandardAnswer).where(
                StandardAnswer.exam_region_id == annotation.exam_region_id
            )
        ).first()
        if answer:
            return answer.answer_text, list(answer.scoring_points or [])
    if question is not None:
        answer = session.exec(
            select(StandardAnswer).where(StandardAnswer.question_id == question.id)
        ).first()
        if answer:
            return answer.answer_text, list(answer.scoring_points or [])
    return None, []


class PageImageCache:
    """一次快照内按 (答卷文件, 页码) 缓存已渲染的页面图。

    `render_pdf_page_png` 全程持有进程级 `PDFIUM_LOCK`，所有 PDF 渲染都是串行的。
    一个班 40 人、每人 15 道错题如果逐题重渲，就是 600 次串行整页渲染；按页缓存后
    只需「答卷数 × 页数」次。
    """

    def __init__(self) -> None:
        self._images: dict[tuple[uuid.UUID, int], Image.Image] = {}
        self.render_count = 0

    def get(self, *, stored_file: StoredFile, page_number: int) -> Image.Image:
        key = (stored_file.id, page_number)
        image = self._images.get(key)
        if image is None:
            image = render_stored_file_page_image(
                stored_file=stored_file, page_number=page_number
            )
            self.render_count += 1
            self._images[key] = image
        return image

    def close(self) -> None:
        for image in self._images.values():
            image.close()
        self._images.clear()


def encode_entry_image(image: Image.Image) -> bytes:
    converted = image.convert("RGB")
    try:
        if converted.width > IMAGE_MAX_WIDTH:
            ratio = IMAGE_MAX_WIDTH / converted.width
            resized = converted.resize(
                (IMAGE_MAX_WIDTH, max(1, round(converted.height * ratio)))
            )
            if resized is not converted:
                converted.close()
            converted = resized
        buffer = BytesIO()
        converted.save(buffer, format="WEBP", quality=IMAGE_QUALITY, method=4)
        return buffer.getvalue()
    finally:
        converted.close()


def _copy_crop_image(
    session: Session,
    *,
    entry_id: uuid.UUID,
    submission: StudentSubmission,
    region: ExamRegion | None,
    pages: PageImageCache,
) -> str | None:
    """把题区裁切图复制成 WebP 存进学习者命名空间，失败返回 None。"""
    if region is None:
        return None
    stored_file = session.get(StoredFile, submission.stored_file_id)
    if stored_file is None:
        return None
    try:
        page_image = pages.get(
            stored_file=stored_file,
            page_number=resolve_exam_region_paper_page(session, region),
        )
        cropped = crop_region_from_image(image=page_image, region=region)
    except Exception:
        logger.warning(
            "wrongbook crop failed",
            extra={"entry_id": str(entry_id), "region_id": str(region.id)},
            exc_info=True,
        )
        return None
    try:
        payload = encode_entry_image(cropped)
    except Exception:
        logger.warning("wrongbook image encode failed", exc_info=True)
        return None
    finally:
        cropped.close()
    key = build_entry_image_key(entry_id=entry_id)
    put_storage_bytes(key, payload)
    return key


def snapshot_release(session: Session, release_id: uuid.UUID) -> int:
    """把一次成绩发布写进错题本，返回写入的条目数。

    幂等：同一个 release 重复投递不会产生重复条目。重新发布（新版本）会把该考试
    此前的条目置为 superseded，而不是原地改写。
    """
    release = session.get(ScoreRelease, release_id)
    if release is None or release.status != ScoreReleaseStatus.PUBLISHED:
        return 0
    exam = session.get(Exam, release.exam_id)
    if exam is None:
        return 0

    existing = session.exec(
        select(WrongQuestionEntry).where(WrongQuestionEntry.release_id == release.id)
    ).first()
    if existing:
        return 0

    items = list(
        session.exec(
            select(ScoreReleaseItem).where(ScoreReleaseItem.release_id == release.id)
        ).all()
    )
    if not items:
        return 0

    # 把该考试更早版本的条目标记为已被取代，学生端只读 active。
    superseded = session.exec(
        select(WrongQuestionEntry)
        .join(
            WrongQuestionSource,
            WrongQuestionEntry.source_id == WrongQuestionSource.id,  # type: ignore[arg-type]
        )
        .where(
            WrongQuestionSource.exam_id == exam.id,
            WrongQuestionEntry.release_id != release.id,
            WrongQuestionEntry.status == WrongQuestionEntryStatus.ACTIVE,
        )
    ).all()
    for entry in superseded:
        entry.status = WrongQuestionEntryStatus.SUPERSEDED
        session.add(entry)

    sources: dict[str, WrongQuestionSource] = {}
    created = 0
    pages = PageImageCache()
    current_submission_id: uuid.UUID | None = None
    # 按答卷分组处理：同一份答卷的同一页只渲染一次，换答卷时释放页面图，
    # 避免把整场考试所有页面都留在内存里。
    items.sort(key=lambda row: (str(row.submission_id), row.label))
    try:
        for item in items:
            if item.submission_id != current_submission_id:
                pages.close()
                current_submission_id = item.submission_id
            annotation = (
                session.get(SubmissionAnnotation, item.annotation_id)
                if item.annotation_id
                else None
            )
            submission = session.get(StudentSubmission, item.submission_id)
            if submission is None:
                continue
            question, region = (
                _resolve_question(session, exam_id=exam.id, annotation=annotation)
                if annotation
                else (None, None)
            )
            source = sources.get(item.label)
            if source is None:
                answer_text, scoring_points = (
                    _resolve_answer(session, annotation=annotation, question=question)
                    if annotation
                    else (None, [])
                )
                names = (
                    question_knowledge_names(session, [question.id]).get(
                        question.id, []
                    )
                    if question
                    else []
                )
                source = WrongQuestionSource(
                    exam_id=exam.id,
                    question_id=question.id if question else None,
                    release_id=release.id,
                    release_version=release.version,
                    exam_title=exam.title[:255],
                    subject=exam.subject,
                    grade_level=exam.grade_level,
                    exam_date=exam.exam_date,
                    question_label=item.label,
                    question_text=question.question_text if question else None,
                    question_type=question.question_type if question else None,
                    max_score=item.max_score,
                    standard_answer_text=answer_text,
                    scoring_points=scoring_points,
                    knowledge_point_names=names,
                    released_at=release.published_at,
                )
                session.add(source)
                session.flush()
                sources[item.label] = source

            student = (
                session.get(Student, submission.student_id)
                if submission.student_id
                else None
            )
            is_wrong = (
                item.score is not None
                and item.max_score is not None
                and float(item.score) < float(item.max_score)
            )
            # 学生已经有终身身份时直接挂上去；还没绑账号的等首次访问再认领（D-029）
            learner_id = None
            if student and student.user_id:
                learner_id = session.exec(
                    select(LearnerProfile.id).where(
                        LearnerProfile.user_id == student.user_id
                    )
                ).first()
            entry = WrongQuestionEntry(
                source_id=source.id,
                learner_id=learner_id,
                student_id=submission.student_id,
                student_user_id=student.user_id if student else None,
                student_name=submission.student_name
                or (student.name if student else None),
                class_name_at_time=submission.class_name,
                submission_id=submission.id,
                annotation_id=item.annotation_id,
                release_id=release.id,
                release_version=release.version,
                question_label=item.label,
                score=item.score,
                max_score=item.max_score,
                is_wrong=is_wrong,
                student_answer_text=(annotation.ocr_text if annotation else None),
                missed_points=_student_visible_missed_points(annotation, item),
                teacher_comment=item.comment,
                score_source=item.source,
                released_at=release.published_at,
            )
            session.add(entry)
            session.flush()
            if is_wrong:
                entry.image_storage_key = _copy_crop_image(
                    session,
                    entry_id=entry.id,
                    submission=submission,
                    region=region,
                    pages=pages,
                )
                session.add(entry)
            created += 1
    finally:
        pages.close()

    session.commit()
    logger.info(
        "wrongbook snapshot written",
        extra={
            "release_id": str(release.id),
            "entries": created,
            "page_renders": pages.render_count,
        },
    )
    return created


def _student_visible_missed_points(
    annotation: SubmissionAnnotation | None, item: ScoreReleaseItem
) -> list[dict]:
    """教师改分与模型判断冲突时，不展示模型的评分点清单。

    否则学生会同时看到教师给的分和模型「你这里没答到」的清单，两者互相矛盾。
    只在能证明冲突时隐藏：教师最终分与模型分不一致。教师认可模型分（两者相同）
    或从未有模型分时，评分点仍是唯一能解释「为什么扣分」的依据，照常展示。
    """
    if annotation is None:
        return []
    model_score = annotation.model_score
    if (
        item.source == "human"
        and model_score is not None
        and item.score is not None
        and float(item.score) != float(model_score)
    ):
        return []
    return extract_missed_points(annotation)
