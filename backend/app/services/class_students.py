"""班级 / 学生归位服务（整改计划阶段 2）。

答卷导入时匹配或自动创建 ClassGroup / Student，供上传答卷等入口复用。
班级在学校内共享：同校任何账号导入的答卷都归位到本校同名班级，
跨校互不影响。

匹配优先级：学号（student_no，全校唯一）> (班级名, 姓名) 精确匹配 >
自动创建。学号命中时以花名册为准——姓名错别字会被学号纠正。
"""

import uuid

from sqlmodel import Session, select

from app.models import ClassGroup, Student


def resolve_student_for_submission(
    *,
    session: Session,
    owner_id: uuid.UUID,
    org_id: uuid.UUID,
    class_name: str | None,
    student_name: str | None,
    student_identifier: str | None = None,
) -> Student | None:
    """按学号/(org_id, class_name, student_name) 匹配或创建班级/学生。

    学号（student_identifier ↔ Student.student_no）全校优先：命中即归位，
    姓名错别字由调用方按返回的 student.name 校正。学号多义（不同班同号）
    时用 class_name 收窄，仍多义则落回姓名路径。
    class_name 和 student_name 都为空时返回 None（不建班、不归位）。
    调用方负责把返回的 student.id 写入答卷并统一 commit。
    """
    class_name = (class_name or "").strip()
    student_name = (student_name or "").strip()
    student_identifier = (student_identifier or "").strip()

    if student_identifier:
        by_no = (
            select(Student)
            .join(ClassGroup, Student.class_id == ClassGroup.id)  # type: ignore[arg-type]
            .where(
                ClassGroup.org_id == org_id,
                Student.student_no == student_identifier,
            )
        )
        if class_name:
            hit = session.exec(by_no.where(ClassGroup.name == class_name)).first()
            if hit is not None:
                return hit
        matches = list(session.exec(by_no).all())
        if len(matches) == 1:
            return matches[0]
        # 学号不存在或多义：继续走姓名路径

    if not class_name or not student_name:
        return None
    class_group = session.exec(
        select(ClassGroup).where(
            ClassGroup.org_id == org_id,
            ClassGroup.name == class_name,
        )
    ).first()
    if class_group is None:
        class_group = ClassGroup(owner_id=owner_id, org_id=org_id, name=class_name)
        session.add(class_group)
        session.flush()
    student = session.exec(
        select(Student).where(
            Student.class_id == class_group.id,
            Student.name == student_name,
        )
    ).first()
    if student is None:
        student = Student(class_id=class_group.id, name=student_name)
        session.add(student)
        session.flush()
    return student
