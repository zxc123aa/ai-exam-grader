import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.core.config import settings
from app.core.db import engine, init_db
from app.main import app
from app.models import (
    AnswerPreparationItem,
    AnswerPreparationRun,
    ClassGroup,
    Exam,
    ExamClassLink,
    ExamDocument,
    ExamQuestion,
    ExamQuestionRegion,
    ExamRegion,
    GradingAssignment,
    GradingAuditEvent,
    GradingItem,
    GradingRun,
    Organization,
    ProcessingTask,
    QuestionRecognitionItem,
    QuestionRecognitionRun,
    StandardAnswer,
    StandardAnswerRevision,
    StoredFile,
    Student,
    StudentSubmission,
    SubmissionAnnotation,
    SystemConfig,
    TeacherClassLink,
    User,
)
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session]:
    if "test" not in settings.POSTGRES_DB.casefold():
        raise RuntimeError(
            "Refusing to run destructive test cleanup against a non-test database. "
            "Set POSTGRES_DB to a dedicated database name containing 'test'."
        )
    with Session(engine) as session:
        init_db(session)
        # 默认学校在会话结束的清库中会被删除，每次会话开始时确保它存在
        # （与迁移 a7b8c9d0e1f2 插入的默认学校一致）
        default_org_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        if not session.get(Organization, default_org_id):
            session.add(
                Organization(id=default_org_id, name="默认学校", code="default")
            )
            session.commit()
        yield session
        for model in (
            SystemConfig,
            ProcessingTask,
            GradingAuditEvent,
            GradingItem,
            SubmissionAnnotation,
            GradingRun,
            StudentSubmission,
            GradingAssignment,
            TeacherClassLink,
            ExamClassLink,
            Student,
            ClassGroup,
            StandardAnswerRevision,
            AnswerPreparationItem,
            AnswerPreparationRun,
            StandardAnswer,
            QuestionRecognitionItem,
            QuestionRecognitionRun,
            ExamQuestionRegion,
            ExamQuestion,
            ExamRegion,
            ExamDocument,
            StoredFile,
            Exam,
            User,
            Organization,
        ):
            statement = delete(model)
            session.execute(statement)
        session.commit()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean_class_students_between_tests() -> Generator[None]:
    """班级名全校唯一后，测试间必须清掉班级/学生，否则同名冲突。

    只清班级关联与学生/班级表；StudentSubmission.student_id 由 FK
    ON DELETE SET NULL 自动置空，用户/考试等其余数据沿用会话级共享。
    """
    yield
    with Session(engine) as session:
        for model in (GradingAssignment, TeacherClassLink, ExamClassLink, Student, ClassGroup):
            session.execute(delete(model))
        session.commit()


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
