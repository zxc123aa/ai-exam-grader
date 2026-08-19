"""答卷-学生归位匹配：学号优先 + 姓名兜底 + 自动创建。"""

from sqlmodel import Session

from app.models import ClassGroup, Organization, Student, User, UserRole
from app.services.class_students import resolve_student_for_submission
from tests.utils.utils import random_email, random_lower_string


def _school(db: Session, label: str) -> tuple[Organization, User]:
    org = Organization(name=f"匹配学校-{label}", code=f"match-{random_lower_string()}")
    db.add(org)
    db.flush()
    owner = User(
        email=random_email(),
        hashed_password="x",
        full_name=f"校长{label}",
        role=UserRole.SCHOOL_OWNER,
        org_id=org.id,
    )
    db.add(owner)
    db.commit()
    db.refresh(org)
    db.refresh(owner)
    return org, owner


def _roster_student(
    db: Session, org, owner, class_name: str, name: str, student_no: str | None
) -> Student:
    class_group = ClassGroup(name=class_name, org_id=org.id, owner_id=owner.id)
    db.add(class_group)
    db.flush()
    student = Student(class_id=class_group.id, name=name, student_no=student_no)
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def test_student_no_matches_even_with_typo_name(db: Session) -> None:
    """学号命中即归位，姓名错别字不影响（调用方按 student.name 校正）。"""
    org, owner = _school(db, "学号优先")
    roster = _roster_student(db, org, owner, "001班", "张杉", "2026001")

    student = resolve_student_for_submission(
        session=db,
        owner_id=owner.id,
        org_id=org.id,
        class_name="001班",
        student_name="张彬",  # 错别字
        student_identifier="2026001",
    )
    assert student is not None
    assert student.id == roster.id
    assert student.name == "张杉"


def test_student_no_narrows_by_class_when_duplicated(db: Session) -> None:
    """不同班同号：给了班级名就按班级收窄。"""
    org, owner = _school(db, "同号")
    roster_a = _roster_student(db, org, owner, "001班", "王一", "100")
    _roster_student(db, org, owner, "002班", "王二", "100")

    student = resolve_student_for_submission(
        session=db,
        owner_id=owner.id,
        org_id=org.id,
        class_name="001班",
        student_name="王一",
        student_identifier="100",
    )
    assert student is not None
    assert student.id == roster_a.id


def test_unknown_student_no_falls_back_to_name(db: Session) -> None:
    """学号不存在时走 (班级, 姓名) 路径。"""
    org, owner = _school(db, "兜底")
    roster = _roster_student(db, org, owner, "001班", "李雷", "2026002")

    student = resolve_student_for_submission(
        session=db,
        owner_id=owner.id,
        org_id=org.id,
        class_name="001班",
        student_name="李雷",
        student_identifier="9999999",
    )
    assert student is not None
    assert student.id == roster.id


def test_no_match_still_auto_creates(db: Session) -> None:
    """无学号无花名册：保持自动创建（向后兼容）。"""
    org, owner = _school(db, "自动创建")

    student = resolve_student_for_submission(
        session=db,
        owner_id=owner.id,
        org_id=org.id,
        class_name="003班",
        student_name="韩梅梅",
        student_identifier=None,
    )
    assert student is not None
    assert student.name == "韩梅梅"
    assert student.id is not None


def test_ambiguous_student_no_without_class_falls_back_to_name(db: Session) -> None:
    """学号多义且没给班级：落回 (班级, 姓名) 路径，不乱归。"""
    org, owner = _school(db, "多义")
    _roster_student(db, org, owner, "001班", "王一", "100")
    roster_b = _roster_student(db, org, owner, "002班", "王二", "100")

    student = resolve_student_for_submission(
        session=db,
        owner_id=owner.id,
        org_id=org.id,
        class_name="002班",
        student_name="王二",
        student_identifier="100",
    )
    assert student is not None
    assert student.id == roster_b.id
