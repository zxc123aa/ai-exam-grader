"""错题复习调度与知识点掌握度。

纯统计，不调模型。错题躺着不产生价值，被复习才有；这里负责「今天该复习什么」
和「哪个知识点最需要补」。

调度用简化 SM-2：只问「还会不会」，不让学生打字重做。重做形态成本高、完成率低，
等有真实使用数据再考虑。
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, col, func, or_, select

from app.models import (
    LearnerMastery,
    Student,
    WrongQuestionEntry,
    WrongQuestionEntryStatus,
    WrongQuestionReview,
    WrongQuestionReviewResult,
    WrongQuestionSource,
    get_datetime_utc,
)

# 间隔序列：答对往后走一档，easy 跳一档，hard 原地，again 回到第一档
INTERVAL_DAYS: tuple[int, ...] = (1, 3, 7, 15, 30)


def owner_key(student: Student, user_id: uuid.UUID | None) -> str:
    """掌握度的归属键。登录账号比学校侧档案稳定（升班会换档案）。"""
    if user_id is not None:
        return f"user:{user_id}"
    return f"student:{student.id}"


def entry_scope(student: Student, user_id: uuid.UUID) -> list:
    return [
        or_(
            WrongQuestionEntry.student_id == student.id,
            WrongQuestionEntry.student_user_id == user_id,
        ),
        WrongQuestionEntry.status == WrongQuestionEntryStatus.ACTIVE,
    ]


def next_interval_days(current_index: int, result: WrongQuestionReviewResult) -> int:
    """返回下一次间隔天数。`current_index` 是当前所处的档位（从 0 开始）。"""
    if result == WrongQuestionReviewResult.AGAIN:
        return INTERVAL_DAYS[0]
    if result == WrongQuestionReviewResult.HARD:
        return INTERVAL_DAYS[min(current_index, len(INTERVAL_DAYS) - 1)]
    step = 2 if result == WrongQuestionReviewResult.EASY else 1
    return INTERVAL_DAYS[min(current_index + step, len(INTERVAL_DAYS) - 1)]


def _interval_index(interval_days: int) -> int:
    for index, days in enumerate(INTERVAL_DAYS):
        if days >= interval_days:
            return index
    return len(INTERVAL_DAYS) - 1


def record_review(
    session: Session,
    *,
    entry: WrongQuestionEntry,
    source: WrongQuestionSource,
    student: Student,
    user_id: uuid.UUID,
    result: WrongQuestionReviewResult,
) -> WrongQuestionReview:
    """记录一次复习，推进调度并更新掌握度。每个条目只保留最新一条调度。"""
    now = get_datetime_utc()
    review = session.exec(
        select(WrongQuestionReview).where(WrongQuestionReview.entry_id == entry.id)
    ).first()
    current_index = _interval_index(review.interval_days) if review else -1
    interval = next_interval_days(current_index, result)
    next_due = now + timedelta(days=interval)
    if review is None:
        review = WrongQuestionReview(
            entry_id=entry.id,
            owner_user_id=user_id,
            reviewed_at=now,
            result=result,
            review_count=1,
            interval_days=interval,
            next_due_at=next_due,
            updated_at=now,
        )
    else:
        review.owner_user_id = user_id
        review.reviewed_at = now
        review.result = result
        review.review_count += 1
        review.interval_days = interval
        review.next_due_at = next_due
        review.updated_at = now
    session.add(review)

    key = owner_key(student, user_id)
    for name in source.knowledge_point_names or []:
        mastery = _get_or_create_mastery(
            session, key=key, subject=source.subject or "", name=name
        )
        mastery.last_reviewed_at = now
        mastery.updated_at = now
        session.add(mastery)
    session.commit()
    session.refresh(review)
    return review


def _get_or_create_mastery(
    session: Session, *, key: str, subject: str, name: str
) -> LearnerMastery:
    mastery = session.exec(
        select(LearnerMastery).where(
            LearnerMastery.owner_key == key,
            LearnerMastery.subject == subject,
            LearnerMastery.knowledge_point_name == name,
        )
    ).first()
    if mastery is None:
        mastery = LearnerMastery(
            owner_key=key, subject=subject, knowledge_point_name=name
        )
        session.add(mastery)
        session.flush()
    return mastery


def rebuild_mastery(
    session: Session, *, student: Student, user_id: uuid.UUID
) -> list[LearnerMastery]:
    """按当前错题本重算掌握度。

    掌握度是派生数据：满分题也建了条目，所以 attempts 是「做过几道」，
    wrong_count 是「错过几道」，分母不依赖已经可能被删掉的考试记录。
    """
    key = owner_key(student, user_id)
    rows = session.exec(
        select(WrongQuestionEntry, WrongQuestionSource)
        .select_from(WrongQuestionEntry)
        .join(
            WrongQuestionSource,
            WrongQuestionEntry.source_id == WrongQuestionSource.id,  # type: ignore[arg-type]
        )
        .where(*entry_scope(student, user_id))
    ).all()
    counters: dict[tuple[str, str], dict] = {}
    for entry, source in rows:
        for name in source.knowledge_point_names or []:
            bucket = counters.setdefault(
                (source.subject or "", name),
                {"attempts": 0, "wrong": 0, "last_wrong_at": None},
            )
            bucket["attempts"] += 1
            if entry.is_wrong:
                bucket["wrong"] += 1
                last = bucket["last_wrong_at"]
                if last is None or entry.released_at > last:
                    bucket["last_wrong_at"] = entry.released_at

    now = get_datetime_utc()
    result: list[LearnerMastery] = []
    for (subject, name), bucket in counters.items():
        mastery = _get_or_create_mastery(session, key=key, subject=subject, name=name)
        mastery.attempts = bucket["attempts"]
        mastery.wrong_count = bucket["wrong"]
        mastery.last_wrong_at = bucket["last_wrong_at"]
        mastery.updated_at = now
        session.add(mastery)
        result.append(mastery)
    # 知识点可能因为重新发布而消失，清掉不再有条目的记录
    stale = session.exec(
        select(LearnerMastery).where(LearnerMastery.owner_key == key)
    ).all()
    live = {(item.subject, item.knowledge_point_name) for item in result}
    for mastery in stale:
        if (mastery.subject, mastery.knowledge_point_name) not in live:
            session.delete(mastery)
    session.commit()
    result.sort(
        key=lambda item: (
            -(item.wrong_count / item.attempts if item.attempts else 0),
            -item.wrong_count,
            item.knowledge_point_name,
        )
    )
    return result


def due_entries(
    session: Session,
    *,
    student: Student,
    user_id: uuid.UUID,
    now: datetime | None = None,
    limit: int = 20,
) -> list[tuple[WrongQuestionEntry, WrongQuestionSource]]:
    """今天该复习的错题：没复习过的排最前，其余按到期时间。"""
    moment = now or datetime.now(UTC)
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
            *entry_scope(student, user_id),
            WrongQuestionEntry.is_wrong.is_(True),  # type: ignore[union-attr]
            or_(
                col(WrongQuestionReview.id).is_(None),
                WrongQuestionReview.next_due_at <= moment,
            ),
        )
        .order_by(
            col(WrongQuestionReview.next_due_at).asc().nulls_first(),
            col(WrongQuestionEntry.released_at).desc(),
        )
        .limit(min(max(1, limit), 100))
    ).all()
    return [(entry, source) for entry, source, _review in rows]


def due_count(
    session: Session,
    *,
    student: Student,
    user_id: uuid.UUID,
    now: datetime | None = None,
) -> int:
    moment = now or datetime.now(UTC)
    return session.exec(
        select(func.count())
        .select_from(WrongQuestionEntry)
        .outerjoin(
            WrongQuestionReview,
            WrongQuestionReview.entry_id == WrongQuestionEntry.id,  # type: ignore[arg-type]
        )
        .where(
            *entry_scope(student, user_id),
            WrongQuestionEntry.is_wrong.is_(True),  # type: ignore[union-attr]
            or_(
                col(WrongQuestionReview.id).is_(None),
                WrongQuestionReview.next_due_at <= moment,
            ),
        )
    ).one()


def cram_list(
    session: Session,
    *,
    student: Student,
    user_id: uuid.UUID,
    subject: str | None = None,
    limit: int = 30,
) -> list[tuple[WrongQuestionEntry, WrongQuestionSource, float]]:
    """考前突击清单。

    排序依据：所属知识点的错误率（错得多的先看）、是否长期没复习、以及卷面失分比例。
    不做花哨的权重调参，先给一个可解释的顺序。
    """
    mastery_rows = session.exec(
        select(LearnerMastery).where(
            LearnerMastery.owner_key == owner_key(student, user_id)
        )
    ).all()
    wrong_rate = {
        (item.subject, item.knowledge_point_name): (
            item.wrong_count / item.attempts if item.attempts else 0.0
        )
        for item in mastery_rows
    }
    reviewed_at = {
        (item.subject, item.knowledge_point_name): item.last_reviewed_at
        for item in mastery_rows
    }

    filters = list(entry_scope(student, user_id))
    filters.append(WrongQuestionEntry.is_wrong.is_(True))  # type: ignore[union-attr]
    if subject:
        filters.append(WrongQuestionSource.subject == subject)
    rows = session.exec(
        select(WrongQuestionEntry, WrongQuestionSource)
        .select_from(WrongQuestionEntry)
        .join(
            WrongQuestionSource,
            WrongQuestionEntry.source_id == WrongQuestionSource.id,  # type: ignore[arg-type]
        )
        .where(*filters)
    ).all()

    scored: list[tuple[WrongQuestionEntry, WrongQuestionSource, float]] = []
    for entry, source in rows:
        names = source.knowledge_point_names or []
        rates = [wrong_rate.get((source.subject or "", name), 0.0) for name in names]
        knowledge_score = max(rates) if rates else 0.0
        never_reviewed = all(
            reviewed_at.get((source.subject or "", name)) is None for name in names
        )
        loss_ratio = 0.0
        if entry.max_score:
            loss_ratio = max(
                0.0, 1 - (float(entry.score or 0) / float(entry.max_score))
            )
        score = knowledge_score * 2 + loss_ratio + (0.5 if never_reviewed else 0.0)
        scored.append((entry, source, round(score, 4)))
    scored.sort(key=lambda row: (-row[2], row[0].question_label))
    return scored[: min(max(1, limit), 100)]
