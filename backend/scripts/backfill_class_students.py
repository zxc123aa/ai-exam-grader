"""一次性数据回填脚本（整改计划阶段 2）。

按答卷的 (exam.owner_id, class_name) 建 ClassGroup（空 class_name 跳过），
按 (class, student_name) 建 Student，并回填 studentsubmission.student_id。

用法：
    cd backend && python scripts/backfill_class_students.py
"""

from sqlmodel import Session, select

from app.core.db import engine
from app.models import ClassGroup, Exam, Student, StudentSubmission


def main() -> None:
    with Session(engine) as session:
        rows = session.exec(
            select(StudentSubmission, Exam).join(
                Exam, StudentSubmission.exam_id == Exam.id
            )
        ).all()
        classes: dict[tuple, ClassGroup] = {}
        students: dict[tuple, Student] = {}
        created_classes = created_students = linked = skipped = 0
        for submission, exam in rows:
            class_name = (submission.class_name or "").strip()
            student_name = (submission.student_name or "").strip()
            if not class_name or not student_name:
                skipped += 1
                continue
            class_key = (exam.owner_id, class_name)
            class_group = classes.get(class_key)
            if class_group is None:
                class_group = session.exec(
                    select(ClassGroup).where(
                        ClassGroup.owner_id == exam.owner_id,
                        ClassGroup.name == class_name,
                    )
                ).first()
                if class_group is None:
                    class_group = ClassGroup(owner_id=exam.owner_id, name=class_name)
                    session.add(class_group)
                    session.flush()
                    created_classes += 1
                classes[class_key] = class_group
            student_key = (class_group.id, student_name)
            student = students.get(student_key)
            if student is None:
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
                    created_students += 1
                students[student_key] = student
            if submission.student_id != student.id:
                submission.student_id = student.id
                session.add(submission)
                linked += 1
        session.commit()
        print(
            f"新建班级 {created_classes} 个，新建学生 {created_students} 名，"
            f"回填答卷 {linked} 份，跳过（无班级/姓名）{skipped} 份。"
        )


if __name__ == "__main__":
    main()
