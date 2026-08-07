"""多租户数据隔离（阶段 2）：按 org 维度构造考试/班级的可见性与可写性判断。

可见性规则：
- 平台角色：不直接访问学校考试、班级、学生或答卷数据。
- 学校管理（school_owner / school_admin）：本校全部可见。
- 教师（teacher）：自己的考试；org.exam_sharing_enabled 时同校考试只读可见；
  共享批卷考试中被分配班级的老师对该考试可见，但 submission 级数据仅限负责班级。
- 班级：学校内共享，同校所有教师可见可用，跨校不可见。

写操作：仅限自己的考试；school_owner 可写本校任意考试；
平台角色不参与学校考试写操作。
被分配老师仅可写负责班级 submission 的批注。
"""

import uuid

from sqlalchemy import false, or_
from sqlmodel import Session, col, select

from app.api.deps import is_platform_user, is_school_manager
from app.models import (
    ClassGroup,
    Exam,
    GradingAssignment,
    Organization,
    Student,
    StudentSubmission,
    User,
    UserRole,
)


def get_user_org(session: Session, user: User) -> Organization | None:
    if user.org_id is None:
        return None
    return session.get(Organization, user.org_id)


def exam_sharing_enabled(session: Session, user: User) -> bool:
    org = get_user_org(session, user)
    return bool(org and org.exam_sharing_enabled)


def assigned_class_ids(
    session: Session, exam_id: uuid.UUID, user_id: uuid.UUID
) -> list[uuid.UUID]:
    """共享批卷中该老师被分配的班级 id 列表。"""
    return list(
        session.exec(
            select(GradingAssignment.class_id).where(
                GradingAssignment.exam_id == exam_id,
                GradingAssignment.user_id == user_id,
            )
        ).all()
    )


def _assigned_exam_clause(user: User):
    """考试级 where 条件：共享批卷开启且当前用户被分配的考试。"""
    assigned = select(GradingAssignment.exam_id).where(
        GradingAssignment.user_id == user.id
    )
    return col(Exam.shared_grading_enabled).is_(True) & col(Exam.id).in_(assigned)


def exams_visible_filter(session: Session, user: User):
    """考试列表查询的 where 条件（read_exams 等直接使用）。"""
    if is_platform_user(user):
        return false()
    if is_school_manager(user):
        # org_id 为 NULL 时 `== NULL` 恒不成立，自然看不到任何考试
        return Exam.org_id == user.org_id
    if exam_sharing_enabled(session, user):
        return or_(
            Exam.owner_id == user.id,
            Exam.org_id == user.org_id,
            _assigned_exam_clause(user),
        )
    return or_(Exam.owner_id == user.id, _assigned_exam_clause(user))


def can_see_exam(session: Session, user: User, exam: Exam) -> bool:
    if is_platform_user(user):
        return False
    if is_school_manager(user):
        return user.org_id is not None and exam.org_id == user.org_id
    if exam.owner_id == user.id:
        return True
    if exam.shared_grading_enabled and assigned_class_ids(session, exam.id, user.id):
        return True
    if user.org_id is not None and exam.org_id == user.org_id:
        return exam_sharing_enabled(session, user)
    return False


def can_write_exam(user: User, exam: Exam) -> bool:
    """写操作（更新/删除/上传/批改等）：自己的考试、school_owner 写本校、
    平台角色不参与学校考试写操作。"""
    if is_platform_user(user):
        return False
    if exam.owner_id == user.id:
        return True
    return (
        user.role == UserRole.SCHOOL_OWNER
        and user.org_id is not None
        and exam.org_id == user.org_id
    )


def classes_visible_filter(user: User):
    """班级列表查询的 where 条件。"""
    if is_platform_user(user):
        return false()
    return ClassGroup.org_id == user.org_id


def can_see_class(user: User, class_group: ClassGroup) -> bool:
    if is_platform_user(user):
        return False
    return user.org_id is not None and class_group.org_id == user.org_id


def resolve_target_org_id(
    session: Session, user: User, requested_org_id: uuid.UUID | None
) -> uuid.UUID | None:
    """创建考试/班级时确定归属学校。

    学校角色忽略请求里的 org_id，一律归入本人学校；平台角色不能创建
    学校考试或班级，始终返回 None。
    """
    del session, requested_org_id
    if is_platform_user(user):
        return None
    return user.org_id


# ---------------------------------------------------------------------------
# 共享批卷：被分配老师的 submission 级班级范围限制
# ---------------------------------------------------------------------------
def restricted_assigned_classes(
    session: Session, user: User, exam: Exam
) -> tuple[list[uuid.UUID], list[str]] | None:
    """返回 (class_ids, class_names) 当且仅当用户是该考试被分配的非管理老师
    （需要把 submission 级数据限制在负责班级内）；否则返回 None（不限制）。

    考试 owner / 学校管理不受限；考试未开启共享批卷或老师未被
    分配（此时若经 exam_sharing 可见，保持原有只读全量行为）也不受限。
    """
    if is_platform_user(user):
        return [], []
    if not exam.shared_grading_enabled:
        return None
    if is_school_manager(user):
        return None
    if exam.owner_id == user.id:
        return None
    class_ids = assigned_class_ids(session, exam.id, user.id)
    if not class_ids:
        return None
    names = list(
        session.exec(
            select(ClassGroup.name).where(col(ClassGroup.id).in_(class_ids))
        ).all()
    )
    return class_ids, names


def submission_class_filter(class_ids: list[uuid.UUID], class_names: list[str]):
    """被分配老师的 submission 级 where 条件：
    submission.class_name 命中负责班级名，或经 Student.class_id 命中负责班级。"""
    student_ids = select(Student.id).where(col(Student.class_id).in_(class_ids))
    return or_(
        col(StudentSubmission.class_name).in_(class_names),
        col(StudentSubmission.student_id).in_(student_ids),
    )


def submission_in_assigned_classes(
    session: Session,
    submission: StudentSubmission,
    class_ids: list[uuid.UUID],
    class_names: list[str],
) -> bool:
    """单条 submission 是否属于负责班级（与 submission_class_filter 同语义）。"""
    if submission.class_name and submission.class_name in class_names:
        return True
    if submission.student_id:
        student = session.get(Student, submission.student_id)
        return bool(student and student.class_id in class_ids)
    return False


def exam_classes_with_submissions(session: Session, exam: Exam) -> list[ClassGroup]:
    """本考试中「有答卷」的班级：submission.class_name 与本校 ClassGroup.name 匹配。"""
    names = list(
        session.exec(
            select(StudentSubmission.class_name)
            .where(
                StudentSubmission.exam_id == exam.id,
                col(StudentSubmission.class_name).is_not(None),
            )
            .distinct()
        ).all()
    )
    if not names:
        return []
    return list(
        session.exec(
            select(ClassGroup).where(
                ClassGroup.org_id == exam.org_id,
                col(ClassGroup.name).in_(names),
            )
        ).all()
    )
