"""题目知识点标注。

刻意不改 Node 参考算法的 OCR prompt：D-012 让 Node 独占识别实现，D-021 要求任何
识别改动都要重新报文字准确率，把知识点塞进 OCR prompt 会拖累转写质量并触发一轮
重新评测。这里改为在题目确认后用纯文本推理打标，不需要图片，也能回填历史题库。

教师标注永远优先：只有教师没填知识点的题目才会送进模型。
"""

import json
import logging
import uuid
from decimal import Decimal

from sqlmodel import Session, col, select

from app.models import (
    Exam,
    ExamQuestion,
    ExamQuestionKnowledgeLink,
    ExamQuestionStatus,
    KnowledgePoint,
    QuestionKnowledgeSource,
)
from app.services.billing import ModelCallContext
from app.services.knowledge_point_taxonomy import TAXONOMY
from app.services.system_config import get_grading_defaults
from app.services.vision_grading import call_json_model_with_metadata

logger = logging.getLogger(__name__)

WORKFLOW_PURPOSE = "knowledge_point_tagging"
# 低于该置信度不写入，留给教师手动标注，避免用错误知识点污染错题本聚合。
MIN_CONFIDENCE = 0.6
MAX_QUESTIONS_PER_CALL = 40
QUESTION_TEXT_LIMIT = 600


def resolve_taxonomy_subject(subject: str | None) -> str | None:
    """把考试科目映射到知识点树的学科键。

    考试科目是自由文本（可能是「物理」「初中物理」「物理（上）」），因此按包含匹配。
    """
    if not subject:
        return None
    for key in TAXONOMY:
        if key in subject:
            return key
    return None


def load_points(session: Session, subject_key: str) -> list[KnowledgePoint]:
    return list(
        session.exec(
            select(KnowledgePoint)
            .where(KnowledgePoint.subject == subject_key)
            .order_by(col(KnowledgePoint.sort_order))
        ).all()
    )


def _leaf_points(points: list[KnowledgePoint]) -> list[KnowledgePoint]:
    parent_ids = {point.parent_id for point in points if point.parent_id}
    return [point for point in points if point.id not in parent_ids]


def match_point_by_text(
    points: list[KnowledgePoint], text: str | None
) -> KnowledgePoint | None:
    """把教师填写的自由文本知识点对到树节点，对不上返回 None。"""
    if not text:
        return None
    cleaned = text.strip()
    if not cleaned:
        return None
    for point in points:
        if point.name == cleaned:
            return point
    for point in points:
        if cleaned in point.aliases:
            return point
    for point in points:
        if point.name and (point.name in cleaned or cleaned in point.name):
            return point
    return None


def _link_question(
    session: Session,
    *,
    question: ExamQuestion,
    point: KnowledgePoint,
    source: QuestionKnowledgeSource,
    confidence: float | None,
) -> None:
    existing = session.exec(
        select(ExamQuestionKnowledgeLink).where(
            ExamQuestionKnowledgeLink.question_id == question.id,
            ExamQuestionKnowledgeLink.knowledge_point_id == point.id,
        )
    ).first()
    if existing:
        # 教师标注可以覆盖 AI 标注，反向不行。
        if (
            existing.source == QuestionKnowledgeSource.AI
            and source == QuestionKnowledgeSource.TEACHER
        ):
            existing.source = source
            existing.confidence = None
            session.add(existing)
        return
    session.add(
        ExamQuestionKnowledgeLink(
            question_id=question.id,
            knowledge_point_id=point.id,
            source=source,
            confidence=(
                Decimal(str(round(confidence, 4))) if confidence is not None else None
            ),
            is_primary=True,
        )
    )


def _build_prompt(
    points: list[KnowledgePoint], questions: list[ExamQuestion], subject_key: str
) -> str:
    catalog = "\n".join(
        f"- {point.code} {point.name}"
        + (f"（含：{'、'.join(point.aliases)}）" if point.aliases else "")
        for point in points
    )
    payload = [
        {
            "questionKey": question.question_key,
            "label": question.label,
            "text": question.question_text[:QUESTION_TEXT_LIMIT],
        }
        for question in questions
    ]
    return (
        f"你是{subject_key}教师，负责把考题归入知识点。\n"
        f"可选知识点（只能使用下列编码）：\n{catalog}\n\n"
        f"待归类题目：\n{json.dumps(payload, ensure_ascii=False)}\n\n"
        '只返回 JSON：{"results":[{"questionKey":"原样返回","code":"知识点编码",'
        '"confidence":0到1}]}。'
        "无法判断的题目不要出现在 results 中，不要臆造不存在的编码。"
    )


def tag_exam_questions(
    session: Session,
    *,
    exam: Exam,
    reservation_id: uuid.UUID | None = None,
) -> int:
    """给考试内缺知识点的已确认题目打标，返回成功标注的题目数。

    调用方不应因为标注失败而中断主流程：知识点是增强信息，不是批改前置条件。
    """
    subject_key = resolve_taxonomy_subject(exam.subject)
    if not subject_key:
        logger.info(
            "skip knowledge point tagging, unsupported subject",
            extra={"exam_id": str(exam.id), "subject": exam.subject},
        )
        return 0
    points = load_points(session, subject_key)
    if not points:
        return 0
    leaves = _leaf_points(points)
    if not leaves:
        return 0

    questions = list(
        session.exec(
            select(ExamQuestion).where(
                ExamQuestion.exam_id == exam.id,
                ExamQuestion.status == ExamQuestionStatus.CONFIRMED,
            )
        ).all()
    )
    if not questions:
        return 0

    tagged = 0
    pending: list[ExamQuestion] = []
    for question in questions:
        teacher_point = match_point_by_text(points, question.knowledge_point)
        if teacher_point is not None:
            _link_question(
                session,
                question=question,
                point=teacher_point,
                source=QuestionKnowledgeSource.TEACHER,
                confidence=None,
            )
            tagged += 1
            continue
        if question.knowledge_point and question.knowledge_point.strip():
            # 教师填了但对不上词表：保留自由文本，不用 AI 覆盖教师判断。
            continue
        pending.append(question)

    if not pending:
        session.commit()
        return tagged

    defaults = get_grading_defaults(session, exam.org_id)
    by_code = {point.code: point for point in leaves}
    for start in range(0, len(pending), MAX_QUESTIONS_PER_CALL):
        batch = pending[start : start + MAX_QUESTIONS_PER_CALL]
        prompt = _build_prompt(leaves, batch, subject_key)
        context = ModelCallContext(
            org_id=exam.org_id,
            exam_id=exam.id,
            reservation_id=reservation_id,
            workflow_purpose=WORKFLOW_PURPOSE,
            resource_id=str(exam.id),
            billing_key=f"{exam.org_id}:{WORKFLOW_PURPOSE}:{exam.id}:{start}:v1",
        )
        parsed, _model, _elapsed, _meta = call_json_model_with_metadata(
            provider=str(defaults["grading_provider"]),
            model=str(defaults["grading_model"]),
            fallback_models=list(defaults.get("fallback_models") or []),
            messages=[{"role": "user", "content": prompt}],
            billing_context=context,
            workflow_purpose=WORKFLOW_PURPOSE,
        )
        by_key = {question.question_key: question for question in batch}
        for row in parsed.get("results") or []:
            if not isinstance(row, dict):
                continue
            question = by_key.get(str(row.get("questionKey") or ""))
            point = by_code.get(str(row.get("code") or ""))
            if question is None or point is None:
                continue
            try:
                confidence = float(row.get("confidence"))
            except (TypeError, ValueError):
                continue
            if confidence < MIN_CONFIDENCE:
                continue
            _link_question(
                session,
                question=question,
                point=point,
                source=QuestionKnowledgeSource.AI,
                confidence=confidence,
            )
            # 回写自由文本列，保持题库筛选、组卷复制和教师报告映射继续可用。
            question.knowledge_point = point.name
            session.add(question)
            tagged += 1
    session.commit()
    return tagged


def question_knowledge_names(
    session: Session, question_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    """题目 -> 知识点名称列表，供错题本快照与学生端展示。"""
    if not question_ids:
        return {}
    rows = session.exec(
        select(ExamQuestionKnowledgeLink, KnowledgePoint)
        .join(
            KnowledgePoint,
            ExamQuestionKnowledgeLink.knowledge_point_id == KnowledgePoint.id,  # type: ignore[arg-type]
        )
        .where(col(ExamQuestionKnowledgeLink.question_id).in_(question_ids))
    ).all()
    names: dict[uuid.UUID, list[str]] = {}
    for link, point in rows:
        bucket = names.setdefault(link.question_id, [])
        if point.name not in bucket:
            bucket.append(point.name)
    return names
