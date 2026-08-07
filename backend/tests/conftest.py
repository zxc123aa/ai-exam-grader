import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app import crud
from app.core.config import settings
from app.core.db import engine, init_db
from app.main import app
from app.models import (
    AddonSku,
    AnswerPreparationItem,
    AnswerPreparationRun,
    AnswerQuotaAllocation,
    AnswerQuotaGrant,
    AnswerQuotaReservation,
    BillableAnswerSheet,
    BillingRateVersion,
    ClassGroup,
    CommerceOrder,
    CreditGrant,
    CreditLedgerEntry,
    CreditReservation,
    CreditReservationAllocation,
    Exam,
    ExamClassLink,
    ExamDocument,
    ExamQuestion,
    ExamQuestionRegion,
    ExamRegion,
    FunctionModelAssignment,
    GradingAssignment,
    GradingAuditEvent,
    GradingItem,
    GradingRun,
    InvoiceApplication,
    ModelRoutePolicy,
    ModelRouteTarget,
    ModelRouteVersion,
    ModelRouteVersionTarget,
    ModelUsageEvent,
    OfferingRateVersion,
    OrderItem,
    Organization,
    OrganizationJobLease,
    OrganizationModelSelection,
    OrganizationSubscription,
    OrganizationUsagePolicy,
    OutboxEvent,
    PaymentAttempt,
    PaymentWebhookEvent,
    PendingOrganizationSignup,
    PlanVersion,
    PlatformModelOffering,
    ProcessingTask,
    ProviderAuditLog,
    ProviderChannel,
    ProviderCredential,
    ProviderHealthState,
    ProviderInternalRateVersion,
    ProviderModelMapping,
    ProviderReconciliationBatch,
    ProviderReconciliationItem,
    QuestionRecognitionItem,
    QuestionRecognitionRun,
    RefundRequest,
    ScoreRelease,
    ScoreReleaseItem,
    StandardAnswer,
    StandardAnswerRevision,
    StandardModel,
    StoredFile,
    Student,
    StudentSubmission,
    SubmissionAnnotation,
    SystemConfig,
    TeacherClassLink,
    User,
    UserCreate,
    UserRole,
)
from tests.utils.user import (
    authentication_token_from_email,
    user_authentication_headers,
)
from tests.utils.utils import (
    get_superuser_token_headers,
    random_email,
    random_lower_string,
)


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
            PendingOrganizationSignup,
            OutboxEvent,
            RefundRequest,
            InvoiceApplication,
            PaymentWebhookEvent,
            PaymentAttempt,
            OrderItem,
            ProviderReconciliationItem,
            ProviderReconciliationBatch,
            ModelUsageEvent,
            BillableAnswerSheet,
            AnswerQuotaAllocation,
            AnswerQuotaReservation,
            AnswerQuotaGrant,
            CommerceOrder,
            AddonSku,
            PlanVersion,
            OrganizationModelSelection,
            OrganizationJobLease,
            OrganizationUsagePolicy,
            OfferingRateVersion,
            PlatformModelOffering,
            FunctionModelAssignment,
            ModelRouteVersionTarget,
            ModelRouteVersion,
            ModelRouteTarget,
            ProviderHealthState,
            ProviderInternalRateVersion,
            ProviderAuditLog,
            ProviderCredential,
            ProviderModelMapping,
            StandardModel,
            ModelRoutePolicy,
            ProviderChannel,
            CreditLedgerEntry,
            CreditReservationAllocation,
            CreditReservation,
            CreditGrant,
            OrganizationSubscription,
            BillingRateVersion,
            SystemConfig,
            ProcessingTask,
            ScoreReleaseItem,
            ScoreRelease,
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
        for model in (
            GradingAssignment,
            TeacherClassLink,
            ExamClassLink,
            Student,
            ClassGroup,
        ):
            session.execute(delete(model))
        session.commit()


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def school_owner_user(db: Session) -> tuple[User, str]:
    """学校业务测试使用买方总管理员，平台超管不参与校内业务。"""
    password = random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(),
            password=password,
            role=UserRole.SCHOOL_OWNER,
            org_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        ),
    )
    return user, password


@pytest.fixture(scope="module")
def school_owner_token_headers(
    client: TestClient, school_owner_user: tuple[User, str]
) -> dict[str, str]:
    user, password = school_owner_user
    return user_authentication_headers(
        client=client, email=user.email, password=password
    )


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
