import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, func, select

from app.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_teacher_user,
)
from app.core.security import get_password_hash
from app.models import (
    ClassGroup,
    ClassGroupCreate,
    ClassGroupPublic,
    ClassGroupsPublic,
    ClassGroupUpdate,
    Message,
    Student,
    StudentBatchCreate,
    StudentBatchResult,
    StudentBatchRowResult,
    StudentBindAccount,
    StudentCreate,
    StudentPublic,
    StudentsPublic,
    StudentUpdate,
    User,
    UserRole,
)
from app.services.org_scope import (
    can_see_class,
    classes_visible_filter,
    resolve_target_org_id,
)

router = APIRouter(
    prefix="/classes",
    tags=["classes"],
    dependencies=[Depends(get_current_teacher_user)],
)


def get_class_for_user(
    *, session: Session, current_user: CurrentUser, class_id: uuid.UUID
) -> ClassGroup:
    """按 id 取班级。班级在学校内共享（同校教师都可读取/维护），
    跨校不可见：非本校班级一律 404。"""
    class_group = session.get(ClassGroup, class_id)
    if not class_group or not can_see_class(current_user, class_group):
        raise HTTPException(status_code=404, detail="Class not found")
    return class_group


def get_student_for_user(
    *, session: Session, current_user: CurrentUser, student_id: uuid.UUID
) -> Student:
    student = session.get(Student, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    get_class_for_user(
        session=session, current_user=current_user, class_id=student.class_id
    )
    return student


def build_class_group_public(
    *, class_group: ClassGroup, student_count: int
) -> ClassGroupPublic:
    return ClassGroupPublic(
        id=class_group.id,
        owner_id=class_group.owner_id,
        org_id=class_group.org_id,
        name=class_group.name,
        grade_level=class_group.grade_level,
        created_at=class_group.created_at,
        student_count=student_count,
    )


def count_students(session: Session, class_id: uuid.UUID) -> int:
    return session.exec(
        select(func.count()).select_from(Student).where(Student.class_id == class_id)
    ).one()


def build_student_public(*, session: Session, student: Student) -> StudentPublic:
    account_email = None
    if student.user_id:
        account_email = session.exec(
            select(User.email).where(User.id == student.user_id)
        ).first()
    return StudentPublic.model_validate(
        student, update={"account_email": account_email}
    )


def ensure_class_name_available(
    *,
    session: Session,
    org_id: uuid.UUID,
    name: str,
    exclude_id: uuid.UUID | None = None,
) -> None:
    # 班级名学校内唯一，避免同校建出同名班导致名单割裂；跨校允许同名
    statement = select(ClassGroup).where(
        ClassGroup.org_id == org_id, ClassGroup.name == name
    )
    if exclude_id is not None:
        statement = statement.where(ClassGroup.id != exclude_id)
    if session.exec(statement).first():
        raise HTTPException(status_code=409, detail="Class name already exists")


def ensure_student_name_available(
    *, session: Session, class_id: uuid.UUID, name: str, exclude_id: uuid.UUID | None = None
) -> None:
    statement = select(Student).where(
        Student.class_id == class_id, Student.name == name
    )
    if exclude_id is not None:
        statement = statement.where(Student.id != exclude_id)
    if session.exec(statement).first():
        raise HTTPException(
            status_code=409, detail="Student name already exists in this class"
        )


@router.get("/", response_model=ClassGroupsPublic)
def read_classes(session: SessionDep, current_user: CurrentUser) -> Any:
    count_sub = (
        select(Student.class_id, func.count().label("student_count"))
        .group_by(Student.class_id)
        .subquery()
    )
    statement = (
        select(ClassGroup, func.coalesce(count_sub.c.student_count, 0))
        .outerjoin(count_sub, ClassGroup.id == count_sub.c.class_id)
        .order_by(col(ClassGroup.created_at).desc())
    )
    # 班级学校内共享：同校教师可见本校全部班级，跨校不可见。
    rows = session.exec(statement.where(classes_visible_filter(current_user))).all()
    data = [
        build_class_group_public(class_group=class_group, student_count=student_count)
        for class_group, student_count in rows
    ]
    return ClassGroupsPublic(data=data, count=len(data))


@router.post("/", response_model=ClassGroupPublic)
def create_class(
    *, session: SessionDep, current_user: CurrentUser, class_in: ClassGroupCreate
) -> Any:
    name = class_in.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Class name must not be empty")
    # 班级一律归入当前学校。
    org_id = resolve_target_org_id(session, current_user, class_in.org_id)
    if org_id is None:
        raise HTTPException(status_code=400, detail="账号未归属学校，无法创建班级")
    ensure_class_name_available(session=session, org_id=org_id, name=name)
    class_group = ClassGroup(
        name=name,
        grade_level=class_in.grade_level,
        owner_id=current_user.id,
        org_id=org_id,
    )
    session.add(class_group)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Class name already exists")
    session.refresh(class_group)
    return build_class_group_public(class_group=class_group, student_count=0)


@router.patch("/{class_id}", response_model=ClassGroupPublic)
def update_class(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    class_id: uuid.UUID,
    class_in: ClassGroupUpdate,
) -> Any:
    class_group = get_class_for_user(
        session=session, current_user=current_user, class_id=class_id
    )
    update_data = class_in.model_dump(exclude_unset=True)
    if "name" in update_data and update_data["name"] is not None:
        new_name = update_data["name"].strip()
        if not new_name:
            raise HTTPException(status_code=422, detail="Class name must not be empty")
        ensure_class_name_available(
            session=session,
            org_id=class_group.org_id,
            name=new_name,
            exclude_id=class_group.id,
        )
        update_data["name"] = new_name
    class_group.sqlmodel_update(update_data)
    session.add(class_group)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Class name already exists")
    session.refresh(class_group)
    return build_class_group_public(
        class_group=class_group,
        student_count=count_students(session, class_group.id),
    )


@router.delete("/{class_id}", response_model=Message)
def delete_class(
    *, session: SessionDep, current_user: CurrentUser, class_id: uuid.UUID
) -> Any:
    class_group = get_class_for_user(
        session=session, current_user=current_user, class_id=class_id
    )
    if count_students(session, class_group.id):
        raise HTTPException(
            status_code=409, detail="Class has students; remove them first"
        )
    session.delete(class_group)
    session.commit()
    return Message(message="Class deleted successfully")


@router.get("/{class_id}/students", response_model=StudentsPublic)
def read_students(
    *, session: SessionDep, current_user: CurrentUser, class_id: uuid.UUID
) -> Any:
    get_class_for_user(session=session, current_user=current_user, class_id=class_id)
    statement = (
        select(Student)
        .where(Student.class_id == class_id)
        .order_by(col(Student.created_at).asc())
    )
    students = session.exec(statement).all()
    return StudentsPublic(
        data=[build_student_public(session=session, student=student) for student in students],
        count=len(students),
    )


@router.post("/{class_id}/students", response_model=StudentPublic)
def create_student(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    class_id: uuid.UUID,
    student_in: StudentCreate,
) -> Any:
    get_class_for_user(session=session, current_user=current_user, class_id=class_id)
    name = student_in.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Student name must not be empty")
    ensure_student_name_available(session=session, class_id=class_id, name=name)
    student = Student(
        class_id=class_id, name=name, student_no=student_in.student_no
    )
    session.add(student)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="Student name already exists in this class"
        )
    session.refresh(student)
    return build_student_public(session=session, student=student)


# 学生批量建账号的占位邮箱域名与统一初始密码
# TODO(v1 之后): 强制首次登录改密
STUDENT_ACCOUNT_DOMAIN = "school.local"
STUDENT_INITIAL_PASSWORD = "Dianfan@2026"
# 批量创建学生账号仅限学校管理角色。
ACCOUNT_CREATOR_ROLES = (
    UserRole.SCHOOL_OWNER,
    UserRole.SCHOOL_ADMIN,
)


@router.post("/{class_id}/students/batch", response_model=StudentBatchResult)
def create_students_batch(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    class_id: uuid.UUID,
    batch_in: StudentBatchCreate,
) -> Any:
    """花名册批量导入。dry_run=true 只校验不落库，逐行返回处理结果。"""
    class_group = get_class_for_user(
        session=session, current_user=current_user, class_id=class_id
    )
    if (
        batch_in.create_accounts
        and current_user.role not in ACCOUNT_CREATOR_ROLES
    ):
        raise HTTPException(
            status_code=403,
            detail="批量创建学生账号需要学校管理员权限",
        )
    existing_names = set(
        session.exec(select(Student.name).where(Student.class_id == class_id)).all()
    )
    seen_names: set[str] = set(existing_names)
    seen_emails: set[str] = set()
    row_results: list[StudentBatchRowResult] = []
    created = skipped = accounts_created = 0
    for row in batch_in.rows:
        name = row.name.strip()
        student_no = row.student_no.strip() if row.student_no else None
        if not name:
            row_results.append(
                StudentBatchRowResult(
                    name=row.name,
                    student_no=student_no,
                    action="error",
                    message="姓名不能为空",
                )
            )
            continue
        if name in seen_names:
            skipped += 1
            row_results.append(
                StudentBatchRowResult(
                    name=name,
                    student_no=student_no,
                    action="skip_exists",
                    message="该班级已存在同名学生",
                )
            )
            continue
        email: str | None = None
        if batch_in.create_accounts:
            if not student_no:
                row_results.append(
                    StudentBatchRowResult(
                        name=name,
                        student_no=None,
                        action="error",
                        message="创建账号必须填学号",
                    )
                )
                continue
            email = f"{student_no}@{STUDENT_ACCOUNT_DOMAIN}"
            if email in seen_emails or session.exec(
                select(User).where(User.email == email)
            ).first():
                row_results.append(
                    StudentBatchRowResult(
                        name=name,
                        student_no=student_no,
                        action="error",
                        message="该学号生成的登录邮箱已被占用",
                    )
                )
                continue
        seen_names.add(name)
        if email:
            seen_emails.add(email)
        created += 1
        row_results.append(
            StudentBatchRowResult(name=name, student_no=student_no, action="create")
        )
        if batch_in.dry_run:
            continue
        student = Student(class_id=class_id, name=name, student_no=student_no)
        session.add(student)
        if email:
            user = User(
                email=email,
                hashed_password=get_password_hash(STUDENT_INITIAL_PASSWORD),
                full_name=name,
                role=UserRole.STUDENT,
                org_id=class_group.org_id,
                is_active=True,
            )
            session.add(user)
            session.flush()
            student.user_id = user.id
            accounts_created += 1
    if not batch_in.dry_run:
        session.commit()
    errors = [r for r in row_results if r.action == "error"]
    return StudentBatchResult(
        created=created,
        skipped=skipped,
        accounts_created=accounts_created,
        rows=row_results,
        errors=errors,
    )


@router.patch("/students/{student_id}", response_model=StudentPublic)
def update_student(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    student_id: uuid.UUID,
    student_in: StudentUpdate,
) -> Any:
    student = get_student_for_user(
        session=session, current_user=current_user, student_id=student_id
    )
    update_data = student_in.model_dump(exclude_unset=True)
    if "name" in update_data and update_data["name"] is not None:
        new_name = update_data["name"].strip()
        if not new_name:
            raise HTTPException(
                status_code=422, detail="Student name must not be empty"
            )
        ensure_student_name_available(
            session=session,
            class_id=student.class_id,
            name=new_name,
            exclude_id=student.id,
        )
        update_data["name"] = new_name
    student.sqlmodel_update(update_data)
    session.add(student)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="Student name already exists in this class"
        )
    session.refresh(student)
    return build_student_public(session=session, student=student)


@router.delete("/students/{student_id}", response_model=Message)
def delete_student(
    *, session: SessionDep, current_user: CurrentUser, student_id: uuid.UUID
) -> Any:
    student = get_student_for_user(
        session=session, current_user=current_user, student_id=student_id
    )
    session.delete(student)
    session.commit()
    return Message(message="Student deleted successfully")


@router.post("/students/{student_id}/bind-account", response_model=StudentPublic)
def bind_student_account(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    student_id: uuid.UUID,
    bind_in: StudentBindAccount,
) -> Any:
    student = get_student_for_user(
        session=session, current_user=current_user, student_id=student_id
    )
    user = session.get(User, bind_in.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role != UserRole.STUDENT:
        raise HTTPException(
            status_code=400, detail="Only student accounts can be bound"
        )
    class_group = get_class_for_user(
        session=session, current_user=current_user, class_id=student.class_id
    )
    if user.org_id != class_group.org_id:
        raise HTTPException(status_code=404, detail="User not found")
    bound = session.exec(
        select(Student).where(
            Student.user_id == bind_in.user_id, Student.id != student.id
        )
    ).first()
    if bound:
        raise HTTPException(
            status_code=400, detail="This account is already bound to another student"
        )
    student.user_id = bind_in.user_id
    session.add(student)
    session.commit()
    session.refresh(student)
    return build_student_public(session=session, student=student)


@router.delete("/students/{student_id}/bind-account", response_model=StudentPublic)
def unbind_student_account(
    *, session: SessionDep, current_user: CurrentUser, student_id: uuid.UUID
) -> Any:
    student = get_student_for_user(
        session=session, current_user=current_user, student_id=student_id
    )
    student.user_id = None
    session.add(student)
    session.commit()
    session.refresh(student)
    return build_student_public(session=session, student=student)
