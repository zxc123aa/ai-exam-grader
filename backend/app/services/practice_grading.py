"""变式练习作答判分：读照片 → 判分 → 联动错题复习调度。

从 students.py 的同步端点抽出来，供 worker 异步执行。提交时照片已落库
（stored_file_id），这里按 attempt id 取回，不依赖请求上下文。
"""

import base64
import logging
import uuid

from sqlmodel import Session, col, select

from app.core.db import engine
from app.models import (
    PracticeAttemptStatus,
    PracticeSheet,
    PracticeSheetAttempt,
    PracticeVerdict,
    StoredFile,
    WrongQuestionEntry,
    WrongQuestionReviewResult,
    WrongQuestionSource,
)
from app.services import wrongbook_review
from app.services.file_storage import get_stored_file_path
from app.services.system_config import get_grading_defaults
from app.services.vision_grading import VisionGradingError, call_json_model

logger = logging.getLogger(__name__)

_ATTEMPT_REVIEW_RESULT = {
    PracticeVerdict.CORRECT: WrongQuestionReviewResult.GOOD,
    PracticeVerdict.PARTIAL: WrongQuestionReviewResult.HARD,
    PracticeVerdict.WRONG: WrongQuestionReviewResult.AGAIN,
}


def _transcribe_answer(image_bytes: bytes, defaults: dict) -> str:
    """视觉模型读出照片里学生的手写作答。"""
    image = base64.b64encode(image_bytes).decode("ascii")
    prompt = (
        "请读出这张照片里学生的手写作答内容，包括算式、选项、数值、单位和符号；"
        "看不清的位置写「看不清」，不要脑补。"
        '只返回 JSON，不要 Markdown：{"answer_text":"作答内容"}'
    )
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
    return str(parsed.get("answer_text") or "").strip()


def _grade_answer(
    *, question_text: str, student_answer: str, reference: str, defaults: dict
) -> tuple[float, str]:
    """对照变式题参考答案判分，返回 (0-1 得分, 评语)。"""
    prompt = (
        "你是严谨的中文阅卷教师。根据参考答案给学生的作答判分："
        "结果正确给满分；结果正确但过程有小瑕疵酌情扣少量；结果错误只看有价值步骤给步骤分。"
        "评语说人话，指出对在哪里、错在哪里，不要空话。"
        '只返回 JSON，不要 Markdown：{"score":0到1,"comment":"中文评语"}。\n'
        f"题目：{question_text}\n"
        f"学生作答：{student_answer}\n"
        f"参考答案：{reference}"
    )
    parsed, _used_model, _elapsed_ms = call_json_model(
        provider=defaults["grading_provider"],
        model=defaults["grading_model"],
        fallback_models=[],
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        score = float(parsed.get("score"))
    except (TypeError, ValueError) as exc:
        raise VisionGradingError("模型未返回有效分数") from exc
    comment = str(parsed.get("comment") or "").strip()
    if not comment:
        raise VisionGradingError("模型未返回评语")
    return min(max(score, 0.0), 1.0), comment


def grade_practice_attempt(session: Session, attempt_id: uuid.UUID) -> None:
    """执行一次练习判分。任何异常都落 failed 状态，不让任务静默消失。"""
    attempt = session.get(PracticeSheetAttempt, attempt_id)
    if attempt is None or attempt.status != PracticeAttemptStatus.PENDING:
        return
    try:
        sheet = session.get(PracticeSheet, attempt.sheet_id)
        stored = (
            session.get(StoredFile, attempt.stored_file_id)
            if attempt.stored_file_id
            else None
        )
        if sheet is None or stored is None:
            raise VisionGradingError("练习卷或作答照片不存在")
        items = sheet.items or []
        if attempt.item_index >= len(items):
            raise VisionGradingError("题号超出范围")
        item = items[attempt.item_index]

        defaults = get_grading_defaults(session)
        image_bytes = get_stored_file_path(stored).read_bytes()
        student_answer = _transcribe_answer(image_bytes, defaults)
        if not student_answer:
            raise VisionGradingError("没认出作答内容，请拍清楚一点再试")
        reference = str(item.get("answer") or "")
        analysis = str(item.get("analysis") or "")
        if analysis:
            reference = f"{reference}\n解析：{analysis}"
        score, comment = _grade_answer(
            question_text=str(item.get("question_text") or ""),
            student_answer=student_answer,
            reference=reference,
            defaults=defaults,
        )
        verdict = (
            PracticeVerdict.CORRECT
            if score >= 0.99
            else PracticeVerdict.WRONG
            if score <= 0
            else PracticeVerdict.PARTIAL
        )
        attempt.verdict = verdict
        attempt.score = score
        attempt.comment = comment
        attempt.student_answer_text = student_answer
        attempt.status = PracticeAttemptStatus.GRADED
        session.add(attempt)
        session.commit()

        # 联动复习调度：这个知识点的在册错题按 verdict 推进/打回
        from app.models import LearnerProfile

        learner = session.get(LearnerProfile, attempt.learner_id)
        if learner is None:
            return
        review_result = _ATTEMPT_REVIEW_RESULT[verdict]
        seed_rows = session.exec(
            select(WrongQuestionEntry, WrongQuestionSource)
            .select_from(WrongQuestionEntry)
            .join(
                WrongQuestionSource,
                WrongQuestionEntry.source_id == WrongQuestionSource.id,  # type: ignore[arg-type]
            )
            .where(
                col(WrongQuestionEntry.learner_id) == learner.id,
                col(WrongQuestionEntry.is_wrong).is_(True),
            )
        ).all()
        for entry, source in seed_rows:
            if sheet.knowledge_point not in (source.knowledge_point_names or []):
                continue
            wrongbook_review.record_review(
                session,
                entry=entry,
                source=source,
                learner=learner,
                user_id=learner.user_id or attempt.learner_id,
                result=review_result,
            )
    except Exception as exc:
        logger.warning(
            "practice attempt grading failed",
            extra={"attempt_id": str(attempt_id)},
            exc_info=True,
        )
        attempt.status = PracticeAttemptStatus.FAILED
        attempt.comment = f"判分失败：{exc}"[:500]
        session.add(attempt)
        session.commit()


def run_practice_attempt(attempt_id: str) -> None:
    with Session(engine) as session:
        grade_practice_attempt(session, uuid.UUID(attempt_id))
