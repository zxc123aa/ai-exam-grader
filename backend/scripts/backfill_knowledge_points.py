"""给存量已确认题目补知识点标注。

题目识别阶段历史上不写 knowledge_point，教师也很少手填，因此存量题库基本没有
知识点。错题本的归因聚合依赖它，这个脚本把历史题目补齐。

用法：
    python backend/scripts/backfill_knowledge_points.py --dry-run
    python backend/scripts/backfill_knowledge_points.py --exam-id <uuid>
    python backend/scripts/backfill_knowledge_points.py --limit 20

默认只处理「有已确认题目且至少一道题缺知识点」的考试，逐场提交，可随时中断续跑。
"""

import argparse
import logging
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, col, func, select  # noqa: E402

from app.core.db import engine  # noqa: E402
from app.models import Exam, ExamQuestion, ExamQuestionStatus  # noqa: E402
from app.services.knowledge_points import (  # noqa: E402
    resolve_taxonomy_subject,
    tag_exam_questions,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backfill-knowledge-points")


def candidate_exams(session: Session, exam_id: uuid.UUID | None) -> list[Exam]:
    statement = select(Exam)
    if exam_id:
        statement = statement.where(Exam.id == exam_id)
    exams = list(session.exec(statement.order_by(col(Exam.created_at))).all())
    selected: list[Exam] = []
    for exam in exams:
        if resolve_taxonomy_subject(exam.subject) is None:
            continue
        missing = session.exec(
            select(func.count())
            .select_from(ExamQuestion)
            .where(
                ExamQuestion.exam_id == exam.id,
                ExamQuestion.status == ExamQuestionStatus.CONFIRMED,
                col(ExamQuestion.knowledge_point).is_(None),
            )
        ).one()
        if missing:
            selected.append(exam)
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description="补齐存量题目的知识点标注")
    parser.add_argument("--exam-id", type=uuid.UUID, default=None)
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少场考试")
    parser.add_argument(
        "--dry-run", action="store_true", help="只列出待处理考试，不调用模型"
    )
    args = parser.parse_args()

    with Session(engine) as session:
        exams = candidate_exams(session, args.exam_id)
        if args.limit:
            exams = exams[: args.limit]
        if not exams:
            logger.info("没有需要补标的考试")
            return
        logger.info("待处理考试 %s 场", len(exams))
        for exam in exams:
            if args.dry_run:
                logger.info("  [dry-run] %s（%s）", exam.title, exam.subject)
                continue
            try:
                tagged = tag_exam_questions(session, exam=exam)
                logger.info("  %s：标注 %s 道题", exam.title, tagged)
            except Exception as exc:
                session.rollback()
                logger.warning("  %s：标注失败 %s", exam.title, exc)


if __name__ == "__main__":
    main()
