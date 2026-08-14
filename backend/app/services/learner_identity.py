"""终身学习者身份的解析与历史认领（D-029）。

学生身份锚定在学生自己的账号上，学校侧的 `Student` 只是「在校经历」。因此：

- 首次访问时自动生成 `LearnerProfile`，不需要额外的注册动作。
- 每次访问都把当前学校档案登记成一条在校经历（升班、转学各一条），并快照学校名与
  班级名——学校或班级被删后，学生仍要看懂「这题是哪一年在哪个班考的」。
- 认领此前挂在其学校档案上的孤立错题：成绩发布时学生可能还没绑账号，条目当时只
  记了 `student_id`。
"""

import uuid

from sqlmodel import Session, col, or_, select

from app.models import (
    ClassGroup,
    LearnerEnrollment,
    LearnerProfile,
    Organization,
    Student,
    User,
    WrongQuestionEntry,
    WrongQuestionReview,
    get_datetime_utc,
)


def get_or_create_learner(
    session: Session, *, user: User, student: Student | None
) -> LearnerProfile:
    learner = session.exec(
        select(LearnerProfile).where(LearnerProfile.user_id == user.id)
    ).first()
    now = get_datetime_utc()
    if learner is None:
        learner = LearnerProfile(
            user_id=user.id,
            display_name=(student.name if student else None) or user.full_name,
            created_at=now,
            updated_at=now,
        )
        session.add(learner)
        session.flush()
    elif student and not learner.display_name:
        learner.display_name = student.name
        learner.updated_at = now
        session.add(learner)
    return learner


def record_enrollment(
    session: Session, *, learner: LearnerProfile, student: Student
) -> LearnerEnrollment:
    """登记一条在校经历。同一个学校档案只记一次，姓名与班级名保持最新快照。"""
    enrollment = session.exec(
        select(LearnerEnrollment).where(
            LearnerEnrollment.learner_id == learner.id,
            LearnerEnrollment.student_id == student.id,
        )
    ).first()
    class_group = session.get(ClassGroup, student.class_id)
    organization = (
        session.get(Organization, class_group.org_id) if class_group else None
    )
    if enrollment is None:
        enrollment = LearnerEnrollment(
            learner_id=learner.id,
            org_id=class_group.org_id if class_group else None,
            student_id=student.id,
            org_name_at_time=organization.name if organization else None,
            class_name_at_time=class_group.name if class_group else None,
            student_name_at_time=student.name,
        )
    else:
        enrollment.org_name_at_time = (
            organization.name if organization else enrollment.org_name_at_time
        )
        enrollment.class_name_at_time = (
            class_group.name if class_group else enrollment.class_name_at_time
        )
        enrollment.student_name_at_time = student.name
    session.add(enrollment)
    return enrollment


def adopt_orphan_entries(
    session: Session, *, learner: LearnerProfile, user_id: uuid.UUID
) -> int:
    """把还没挂到终身身份上的历史条目认领过来，返回认领数量。

    命中条件是「条目的学校档案属于我的某段在校经历」或「条目记的登录账号就是我」。
    成绩发布时学生可能还没绑账号，这一步让后绑定的学生也能拿回历史。
    """
    student_ids = [
        value
        for value in session.exec(
            select(LearnerEnrollment.student_id).where(
                LearnerEnrollment.learner_id == learner.id,
                col(LearnerEnrollment.student_id).is_not(None),
            )
        ).all()
        if value
    ]
    conditions = [WrongQuestionEntry.student_user_id == user_id]
    if student_ids:
        conditions.append(col(WrongQuestionEntry.student_id).in_(student_ids))
    orphans = session.exec(
        select(WrongQuestionEntry).where(
            col(WrongQuestionEntry.learner_id).is_(None), or_(*conditions)
        )
    ).all()
    for entry in orphans:
        entry.learner_id = learner.id
        session.add(entry)
    reviews = session.exec(
        select(WrongQuestionReview).where(
            col(WrongQuestionReview.learner_id).is_(None),
            WrongQuestionReview.owner_user_id == user_id,
        )
    ).all()
    for review in reviews:
        review.learner_id = learner.id
        session.add(review)
    return len(orphans)


def resolve_learner(
    session: Session, *, user: User, student: Student | None
) -> LearnerProfile:
    """学生端入口统一走这里：拿到终身身份，并顺带登记经历、认领历史。"""
    learner = get_or_create_learner(session, user=user, student=student)
    if student is not None:
        record_enrollment(session, learner=learner, student=student)
    adopt_orphan_entries(session, learner=learner, user_id=user.id)
    session.commit()
    session.refresh(learner)
    return learner


def enrollments(session: Session, learner: LearnerProfile) -> list[LearnerEnrollment]:
    return list(
        session.exec(
            select(LearnerEnrollment)
            .where(LearnerEnrollment.learner_id == learner.id)
            .order_by(col(LearnerEnrollment.started_at).asc())
        ).all()
    )
