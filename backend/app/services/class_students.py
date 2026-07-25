"""班级 / 学生归位服务（整改计划阶段 2）。

答卷导入时按 (org_id, class_name, student_name) 匹配或自动创建
ClassGroup / Student，供上传答卷等入口复用。班级在学校内共享：
同校任何账号导入的答卷都归位到本校同名班级，跨校互不影响。
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
) -> Student | None:
    """按 (org_id, class_name, student_name) 匹配或创建班级/学生。

    班级学校内共享：任何账号导入的答卷都归位到本校同名班级，
    不存在时以 owner_id（导入者）创建。class_name 或 student_name
    为空时返回 None（不建班、不归位）。
    调用方负责把返回的 student.id 写入答卷并统一 commit。
    """
    class_name = (class_name or "").strip()
    student_name = (student_name or "").strip()
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
