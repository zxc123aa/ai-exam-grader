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
    Exam,
    ExamDocument,
    ExamQuestion,
    ExamQuestionRegion,
    ExamRegion,
    GradingAuditEvent,
    GradingItem,
    GradingRun,
    ProcessingTask,
    QuestionRecognitionItem,
    QuestionRecognitionRun,
    StandardAnswer,
    StandardAnswerRevision,
    StoredFile,
    StudentSubmission,
    SubmissionAnnotation,
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
        yield session
        for model in (
            ProcessingTask,
            GradingAuditEvent,
            GradingItem,
            SubmissionAnnotation,
            GradingRun,
            StudentSubmission,
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
        ):
            statement = delete(model)
            session.execute(statement)
        session.commit()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
