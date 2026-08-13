import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Optional

from pydantic import EmailStr, model_validator
from sqlalchemy import BigInteger, Column, DateTime, Numeric, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


class UserRole(StrEnum):
    # 平台侧角色（org_id 为 NULL）
    PLATFORM_SUPERUSER = "platform_superuser"
    PLATFORM_ADMIN = "platform_admin"
    PLATFORM_SUPPORT = "platform_support"
    # 学校侧角色（org_id 指向 Organization）
    SCHOOL_OWNER = "school_owner"
    SCHOOL_ADMIN = "school_admin"
    TEACHER = "teacher"
    STUDENT = "student"


class OrganizationServiceState(StrEnum):
    """学校服务状态；状态本身决定账号和业务入口是否可用。"""

    ACTIVE = "active"
    READ_ONLY = "read_only"
    FROZEN = "frozen"
    DELETING = "deleting"


class OrganizationType(StrEnum):
    SCHOOL = "school"
    TRAINING = "training"
    OTHER = "other"


# 组织（学校）。平台角色用户不属于任何组织。
class OrganizationBase(SQLModel):
    name: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=50)
    organization_type: OrganizationType = Field(
        default=OrganizationType.SCHOOL,
        sa_column=Column(
            SAEnum(
                OrganizationType,
                name="organizationtype",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    status: OrganizationServiceState = Field(
        default=OrganizationServiceState.ACTIVE,
        sa_column=Column(
            SAEnum(
                OrganizationServiceState,
                name="organizationservicestate",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    # 教师间考试互见开关
    exam_sharing_enabled: bool = False
    contact_name: str | None = Field(default=None, max_length=100)


class Organization(OrganizationBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    code: str = Field(min_length=1, max_length=50, unique=True, index=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    users: list["User"] = Relationship(back_populates="organization")


class OrganizationCreate(OrganizationBase):
    pass


class OrganizationUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = Field(default=None, min_length=1, max_length=50)
    status: OrganizationServiceState | None = None
    exam_sharing_enabled: bool | None = None
    contact_name: str | None = Field(default=None, max_length=100)
    organization_type: OrganizationType | None = None


class PendingOrganizationSignup(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    organization_type: OrganizationType = Field(
        sa_column=Column(
            SAEnum(
                OrganizationType,
                name="organizationtype",
                values_callable=lambda enum: [item.value for item in enum],
                create_type=False,
            ),
            nullable=False,
        )
    )
    organization_name: str = Field(min_length=1, max_length=200)
    contact_name: str = Field(min_length=1, max_length=100)
    email: str = Field(unique=True, index=True, max_length=255)
    hashed_password: str
    token_hash: str = Field(unique=True, index=True, max_length=64)
    expires_at: datetime = Field(sa_type=DateTime(timezone=True))  # type: ignore
    last_sent_at: datetime = Field(sa_type=DateTime(timezone=True))  # type: ignore
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore


class OrganizationPublic(OrganizationBase):
    id: uuid.UUID
    created_at: datetime | None = None


class OrganizationsPublic(SQLModel):
    data: list[OrganizationPublic]
    count: int


# 平台管理端点 schema（/platform/orgs）
class PlatformOrgOwnerCreate(SQLModel):
    """新建学校时附带的首个 school_owner 账号。"""

    email: EmailStr = Field(max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class PlatformOrgCreate(SQLModel):
    name: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=50)
    contact_name: str | None = Field(default=None, max_length=100)
    owner: PlatformOrgOwnerCreate | None = None


class PlatformOrgUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = Field(default=None, min_length=1, max_length=50)
    status: OrganizationServiceState | None = None
    contact_name: str | None = Field(default=None, max_length=100)


class PlatformOrgListItem(SQLModel):
    id: uuid.UUID
    name: str
    code: str
    status: OrganizationServiceState
    exam_count: int = 0
    student_count: int = 0
    teacher_count: int = 0
    class_count: int = 0
    account_count: int = 0
    unbound_student_count: int = 0
    contact_name: str | None = None
    owner_name: str | None = None
    owner_email: str | None = None
    created_at: datetime | None = None


class PlatformOrgsPublic(SQLModel):
    data: list[PlatformOrgListItem]
    count: int


class PlatformOrgUserItem(SQLModel):
    id: uuid.UUID
    email: str  # 见 UserBase.email：学生占位邮箱 @school.local 过不了 EmailStr
    full_name: str | None = None
    role: UserRole
    is_active: bool


class PlatformOrgDetail(SQLModel):
    id: uuid.UUID
    name: str
    code: str
    status: OrganizationServiceState
    exam_sharing_enabled: bool
    contact_name: str | None = None
    created_at: datetime | None = None
    exam_count: int = 0
    student_count: int = 0
    teacher_count: int = 0
    class_count: int = 0
    account_count: int = 0
    unbound_student_count: int = 0
    users: list[PlatformOrgUserItem] = Field(default_factory=list)


class PlatformDirectoryItem(SQLModel):
    """平台人员目录中的一条账号或学生名册记录。"""

    record_type: str
    record_id: uuid.UUID
    user_id: uuid.UUID | None = None
    student_id: uuid.UUID | None = None
    name: str
    role: UserRole
    email: str | None = None
    person_no: str | None = None
    org_id: uuid.UUID
    org_name: str
    class_id: uuid.UUID | None = None
    class_name: str | None = None
    class_names: list[str] = Field(default_factory=list)
    link_status: str
    is_active: bool | None = None
    created_at: datetime | None = None


class PlatformDirectoryPublic(SQLModel):
    data: list[PlatformDirectoryItem]
    count: int


# 学校设置端点 schema（/org/settings）
class OrgSettingsPublic(SQLModel):
    name: str
    code: str
    organization_type: OrganizationType
    exam_sharing_enabled: bool
    contact_name: str | None = None


class OrgSettingsUpdate(SQLModel):
    contact_name: str | None = Field(default=None, max_length=100)
    exam_sharing_enabled: bool | None = None


class OrgOnboardingPublic(SQLModel):
    class_count: int
    teacher_count: int
    student_count: int
    teacher_exam_count: int


# Shared properties
class UserBase(SQLModel):
    # 注意：学生占位账号使用 {学号}@school.local，.local 是保留域，通不过 EmailStr，
    # 因此基类用 plain str；创建/更新入口（UserCreate/UserUpdate 等）仍用 EmailStr 校验
    email: str = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)
    role: UserRole = UserRole.TEACHER
    # 教职工工号（学校侧账号用，可选）
    employee_no: str | None = Field(default=None, max_length=50)


# Properties to receive via API on creation
class UserCreate(UserBase):
    # 覆盖基类：手工创建账号仍要求合法邮箱格式
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    # 平台角色为 None；学校角色指向所属组织
    org_id: uuid.UUID | None = None


class OrganizationSignupCreate(SQLModel):
    organization_type: OrganizationType
    organization_name: str = Field(min_length=1, max_length=200)
    contact_name: str = Field(min_length=1, max_length=100)
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    turnstile_token: str = Field(min_length=1, max_length=2048)


class OrganizationSignupResend(SQLModel):
    email: EmailStr = Field(max_length=255)
    turnstile_token: str = Field(min_length=1, max_length=2048)


class OrganizationSignupVerify(SQLModel):
    token: str = Field(min_length=32, max_length=256)


class OrganizationSignupRequested(SQLModel):
    message: str
    expires_in_seconds: int


class SignupOrganizationPublic(SQLModel):
    id: uuid.UUID
    code: str
    name: str
    organization_type: OrganizationType


class OrganizationSignupCompleted(SQLModel):
    access_token: str
    token_type: str = "bearer"
    organization: SignupOrganizationPublic
    trial_ends_at: datetime
    answer_quota: int


# Properties to receive via API on update, all are optional
class UserUpdate(SQLModel):
    email: EmailStr | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    is_superuser: bool | None = None
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: UserRole | None = None
    org_id: uuid.UUID | None = None
    employee_no: str | None = Field(default=None, max_length=50)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    role: UserRole = Field(
        default=UserRole.TEACHER,
        sa_column=Column(
            SAEnum(
                UserRole,
                name="userrole",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    # 平台角色为 NULL；学校角色指向所属组织
    org_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="organization.id",
        nullable=True,
        ondelete="SET NULL",
        index=True,
    )
    organization: Organization | None = Relationship(back_populates="users")
    # 任教档案：任教学科标签（字符串数组），班级关联在 TeacherClassLink
    subjects: list[str] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    exams: list["Exam"] = Relationship(back_populates="owner")
    class_groups: list["ClassGroup"] = Relationship(back_populates="owner")
    files: list["StoredFile"] = Relationship(back_populates="uploaded_by")
    processing_tasks: list["ProcessingTask"] = Relationship(back_populates="created_by")


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None
    org_id: uuid.UUID | None = None
    # 非表字段：由端点根据 org_id 填充
    org_name: str | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# Shared properties
class ExamStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class ProcessingTaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ExamDocumentType(StrEnum):
    BLANK_EXAM = "blank_exam"
    ANSWER_KEY = "answer_key"


class ExamRegionType(StrEnum):
    QUESTION = "question"
    ANSWER_AREA = "answer_area"
    HEADER = "header"
    OTHER = "other"


class StudentSubmissionStatus(StrEnum):
    UPLOADED = "uploaded"
    REGISTRATION_PENDING = "registration_pending"
    REGISTRATION_FAILED = "registration_failed"
    READY_FOR_REVIEW = "ready_for_review"


class SubmissionRegistrationStatus(StrEnum):
    PENDING = "pending"
    MANUAL_CONFIRMED = "manual_confirmed"
    AUTO_CONFIRMED = "auto_confirmed"
    FAILED = "failed"


class SubmissionAnnotationStatus(StrEnum):
    NEEDS_REVIEW = "needs_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class AnnotationGradingStatus(StrEnum):
    NOT_STARTED = "not_started"
    SUCCEEDED = "succeeded"
    SKIPPED_MISSING_ANSWER = "skipped_missing_answer"
    NEEDS_REVIEW = "needs_review"
    STALE = "stale"


class StandardAnswerStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"


class GradingRunStatus(StrEnum):
    AWAITING_CREDITS = "awaiting_credits"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


class ScoreReleaseStatus(StrEnum):
    PUBLISHED = "published"
    SUPERSEDED = "superseded"


class GradingItemStatus(StrEnum):
    QUEUED = "queued"
    EXTRACTING = "extracting"
    GRADING = "grading"
    COMPLETED = "completed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class QuestionType(StrEnum):
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    FILL_BLANK = "fill_blank"
    CALCULATION = "calculation"
    PROOF = "proof"
    SHORT_ANSWER = "short_answer"
    ESSAY = "essay"


class ExamQuestionStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"


class QuestionRegionRole(StrEnum):
    PRIMARY = "primary"
    CONTINUATION = "continuation"
    FIGURE = "figure"


class WorkflowRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


class SubscriptionStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    EXPIRED = "expired"
    SUSPENDED = "suspended"


class CreditGrantSource(StrEnum):
    SUBSCRIPTION = "subscription"
    TOP_UP = "top_up"
    ADJUSTMENT = "adjustment"


class CommerceOrderStatus(StrEnum):
    PENDING_PAYMENT = "pending_payment"
    PAID = "paid"
    FULFILLED = "fulfilled"
    CLOSED = "closed"
    REFUNDING = "refunding"
    REFUNDED = "refunded"


class PaymentMethod(StrEnum):
    WECHAT_NATIVE = "wechat_native"
    BANK_TRANSFER = "bank_transfer"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CLOSED = "closed"
    REFUNDED = "refunded"


class InvoiceStatus(StrEnum):
    SUBMITTED = "submitted"
    APPROVED = "approved"
    ISSUED = "issued"
    REJECTED = "rejected"


class RefundStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"


class CreditReservationStatus(StrEnum):
    ACTIVE = "active"
    SETTLED = "settled"
    RELEASED = "released"


class ModelUsageStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    MISSING_USAGE = "missing_usage"


class ProviderChannelKind(StrEnum):
    OFFICIAL_API = "official_api"
    AUTHORIZED_RELAY = "authorized_relay"
    NEW_API = "new_api"
    SUB2API = "sub2api"
    CLI_PROXY_API = "cli_proxy_api"
    CUSTOM = "custom"


class ProviderChannelStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DRAINING = "draining"
    DISABLED = "disabled"


class ProviderProtocol(StrEnum):
    OPENAI_CHAT = "openai_chat"
    OPENAI_RESPONSES = "openai_responses"


class ProviderHealthStatus(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OPEN = "open"
    DISABLED = "disabled"


class ModelRouteVersionStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class OrganizationRiskState(StrEnum):
    NORMAL = "normal"
    THROTTLED = "throttled"
    BLOCKED = "blocked"
    FROZEN = "frozen"


class UsageReconciliationStatus(StrEnum):
    PENDING = "pending"
    MATCHED = "matched"
    MISMATCH = "mismatch"
    MISSING_UPSTREAM = "missing_upstream"
    MISSING_LOCAL = "missing_local"


class SchoolModelScope(StrEnum):
    VISION = "vision"
    REFERENCE_ANSWER = "reference_answer"
    GRADING = "grading"


class QuestionRecognitionItemStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    EXCLUDED = "excluded"


class AnswerPreparationSource(StrEnum):
    MODEL = "model"
    DOCUMENT = "document"


class AnswerPreparationItemStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    MATCHED = "matched"
    CONFLICT = "conflict"
    UNMATCHED = "unmatched"
    FAILED = "failed"
    CONFIRMED = "confirmed"


class StandardAnswerRevisionStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


class ExamBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    subject: str | None = Field(default=None, max_length=100)
    grade_level: str | None = Field(default=None, max_length=100)
    exam_date: date | None = None
    description: str | None = Field(default=None, max_length=500)
    status: ExamStatus = ExamStatus.DRAFT
    # 大考共享批卷：开启后按班级分配老师，未分完不能发起批改
    shared_grading_enabled: bool = False


class ExamCreate(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    subject: str | None = Field(default=None, max_length=100)
    grade_level: str | None = Field(default=None, max_length=100)
    exam_date: date | None = None
    description: str | None = Field(default=None, max_length=500)
    # 仅 schema 字段：创建时同步重建 ExamClassLink，不写入 exam 表
    class_ids: list[uuid.UUID] | None = None
    # 仅 schema 字段：平台角色创建考试时必须显式指定归属学校；
    # 学校角色忽略该字段，考试一律归入本人所在学校
    org_id: uuid.UUID | None = None


class ExamUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    subject: str | None = Field(default=None, max_length=100)
    grade_level: str | None = Field(default=None, max_length=100)
    exam_date: date | None = None
    description: str | None = Field(default=None, max_length=500)
    status: ExamStatus | None = None
    # 仅 schema 字段：非 None 时整体重建 ExamClassLink
    class_ids: list[uuid.UUID] | None = None


class Exam(ExamBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    status: ExamStatus = Field(
        default=ExamStatus.DRAFT,
        sa_column=Column(
            SAEnum(
                ExamStatus,
                name="examstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="RESTRICT"
    )
    # 考试归属的学校（多租户隔离维度），回填默认学校后 NOT NULL
    org_id: uuid.UUID = Field(foreign_key="organization.id", nullable=False, index=True)
    owner: User | None = Relationship(back_populates="exams")
    documents: list["ExamDocument"] = Relationship(
        back_populates="exam", cascade_delete=True
    )
    regions: list["ExamRegion"] = Relationship(
        back_populates="exam", cascade_delete=True
    )
    standard_answers: list["StandardAnswer"] = Relationship(
        back_populates="exam", cascade_delete=True
    )
    submissions: list["StudentSubmission"] = Relationship(
        back_populates="exam", cascade_delete=True
    )
    # 必须由 ORM 先删成绩发布快照：`ScoreReleaseItem.submission_id` 是 RESTRICT，
    # 否则删考试时会先删答卷而被数据库拒绝，接口直接 500。
    score_releases: list["ScoreRelease"] = Relationship(
        back_populates="exam", cascade_delete=True
    )


class ExamPublic(ExamBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    org_id: uuid.UUID
    created_at: datetime | None = None
    # 由端点从 ExamClassLink 组装填充（非表字段）
    class_ids: list[uuid.UUID] = Field(default_factory=list)
    class_names: list[str] = Field(default_factory=list)
    # 非表字段：当前用户是否是本考试的被分配批卷老师
    is_assigned: bool = False


class ExamsPublic(SQLModel):
    data: list[ExamPublic]
    count: int


class StoredFileBase(SQLModel):
    original_filename: str = Field(min_length=1, max_length=255)
    content_type: str | None = Field(default=None, max_length=255)
    storage_key: str = Field(min_length=1, max_length=500, unique=True)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64, index=True)


class StoredFile(StoredFileBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    uploaded_by_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="RESTRICT"
    )
    uploaded_by: User | None = Relationship(back_populates="files")
    exam_documents: list["ExamDocument"] = Relationship(
        back_populates="stored_file",
        cascade_delete=True,
        sa_relationship_kwargs={"foreign_keys": "ExamDocument.stored_file_id"},
    )
    student_submissions: list["StudentSubmission"] = Relationship(
        back_populates="stored_file",
        cascade_delete=True,
        sa_relationship_kwargs={"foreign_keys": "StudentSubmission.stored_file_id"},
    )


class StoredFilePublic(StoredFileBase):
    id: uuid.UUID
    uploaded_by_id: uuid.UUID
    created_at: datetime | None = None


class ExamDocumentBase(SQLModel):
    document_type: ExamDocumentType = ExamDocumentType.BLANK_EXAM
    sort_order: int = Field(default=1, ge=1)


class ExamDocument(ExamDocumentBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    document_type: ExamDocumentType = Field(
        default=ExamDocumentType.BLANK_EXAM,
        sa_column=Column(
            SAEnum(
                ExamDocumentType,
                name="examdocumenttype",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    exam_id: uuid.UUID = Field(
        foreign_key="exam.id", nullable=False, ondelete="CASCADE"
    )
    stored_file_id: uuid.UUID = Field(
        foreign_key="storedfile.id", nullable=False, ondelete="CASCADE"
    )
    original_stored_file_id: uuid.UUID | None = Field(
        default=None, foreign_key="storedfile.id", nullable=True, ondelete="SET NULL"
    )
    preprocessing_status: str = Field(default="not_required", max_length=50)
    preprocessing_quality: float | None = Field(default=None, ge=0, le=1)
    preprocessing_metadata: dict | None = Field(default=None, sa_column=Column(JSONB))
    exam: Exam | None = Relationship(back_populates="documents")
    stored_file: StoredFile | None = Relationship(
        back_populates="exam_documents",
        sa_relationship_kwargs={"foreign_keys": "ExamDocument.stored_file_id"},
    )


class ExamDocumentPublic(ExamDocumentBase):
    id: uuid.UUID
    exam_id: uuid.UUID
    stored_file_id: uuid.UUID
    stored_file: StoredFilePublic
    page_count: int = 1
    original_stored_file_id: uuid.UUID | None = None
    preprocessing_status: str = "not_required"
    preprocessing_quality: float | None = None
    preprocessing_metadata: dict | None = None
    created_at: datetime | None = None


class ExamDocumentsPublic(SQLModel):
    data: list[ExamDocumentPublic]
    count: int


class ExamDocumentOrderUpdate(SQLModel):
    document_ids: list[uuid.UUID] = Field(min_length=1)


class ExamDocumentRecognitionRequest(SQLModel):
    document_ids: list[uuid.UUID] = Field(min_length=1)
    verification_mode: Literal["fast", "selective", "evidence"] = "fast"


class DocumentQuadPoint(SQLModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class DocumentPageQuad(SQLModel):
    label: str | None = Field(default=None, max_length=50)
    points: list[DocumentQuadPoint] = Field(min_length=4, max_length=4)


class ExamDocumentQuadPreprocessRequest(SQLModel):
    pages: list[DocumentPageQuad] = Field(min_length=1, max_length=2)
    detector: str = Field(default="manual_corner_editor", max_length=100)
    margin_mode: str = Field(default="conservative", regex="^(conservative|minimal)$")


class ExamRegionBase(SQLModel):
    label: str = Field(min_length=1, max_length=100)
    region_type: ExamRegionType = ExamRegionType.QUESTION
    page_number: int = Field(default=1, ge=1)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def validate_bounds(self) -> "ExamRegionBase":
        if self.x + self.width > 1:
            raise ValueError("Region x + width must be less than or equal to 1")
        if self.y + self.height > 1:
            raise ValueError("Region y + height must be less than or equal to 1")
        return self


class ExamRegionCreate(ExamRegionBase):
    exam_document_id: uuid.UUID | None = None


class ExamRegionUpdate(SQLModel):
    label: str | None = Field(default=None, min_length=1, max_length=100)
    region_type: ExamRegionType | None = None
    page_number: int | None = Field(default=None, ge=1)
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    width: float | None = Field(default=None, gt=0, le=1)
    height: float | None = Field(default=None, gt=0, le=1)
    exam_document_id: uuid.UUID | None = None


class ExamRegion(ExamRegionBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    region_type: ExamRegionType = Field(
        default=ExamRegionType.QUESTION,
        sa_column=Column(
            SAEnum(
                ExamRegionType,
                name="examregiontype",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    exam_id: uuid.UUID = Field(
        foreign_key="exam.id", nullable=False, ondelete="CASCADE"
    )
    exam_document_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="examdocument.id",
        nullable=True,
        ondelete="CASCADE",
        index=True,
    )
    exam: Exam | None = Relationship(back_populates="regions")
    standard_answer: Optional["StandardAnswer"] = Relationship(
        back_populates="exam_region", cascade_delete=True
    )


class ExamRegionPublic(ExamRegionBase):
    id: uuid.UUID
    exam_id: uuid.UUID
    exam_document_id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # 关联题目信息（无关联时为 None）；续页区域 role 为 "continuation"。
    question_key: str | None = None
    question_label: str | None = None
    region_role: str | None = None


class ExamRegionsPublic(SQLModel):
    data: list[ExamRegionPublic]
    count: int


class ExamRegionCandidate(SQLModel):
    label: str
    region_type: ExamRegionType = ExamRegionType.QUESTION
    page_number: int = Field(default=1, ge=1)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)
    confidence: float = Field(ge=0, le=1)
    source: str
    reasons: list[str] = Field(default_factory=list)


class ExamRegionCandidatesPublic(SQLModel):
    data: list[ExamRegionCandidate]
    count: int
    page_number: int
    engine: str
    elapsed_ms: int = 0
    orientation_ms: int = 0
    layout_ms: int = 0
    refinement_ms: int = 0
    rotation: int = 0
    upright_image: str | None = None
    provider: str | None = None
    provider_label: str | None = None
    requested_provider: str | None = None
    provider_failover_count: int = 0


class ExamQuestion(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("exam_id", "question_key", name="uq_examquestion_exam_key"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    exam_id: uuid.UUID = Field(
        foreign_key="exam.id", nullable=False, ondelete="CASCADE", index=True
    )
    question_key: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=255)
    question_text: str = Field(min_length=1, max_length=20000)
    question_type: str | None = Field(default=None, max_length=50)
    knowledge_point: str | None = Field(default=None, max_length=100)
    difficulty: int | None = Field(default=None, ge=1, le=5)
    recognition_confidence: Decimal | None = Field(
        default=None,
        sa_column=Column(Numeric(5, 4), nullable=True),
    )
    status: ExamQuestionStatus = Field(
        default=ExamQuestionStatus.DRAFT,
        sa_column=Column(
            SAEnum(
                ExamQuestionStatus,
                name="examquestionstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    confirmed_by_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", nullable=True, ondelete="SET NULL"
    )
    confirmed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class ExamQuestionRegion(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "question_id", "exam_region_id", name="uq_examquestionregion_pair"
        ),
        UniqueConstraint("exam_region_id", name="uq_examquestionregion_region"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    question_id: uuid.UUID = Field(
        foreign_key="examquestion.id", nullable=False, ondelete="CASCADE", index=True
    )
    exam_region_id: uuid.UUID = Field(
        foreign_key="examregion.id", nullable=False, ondelete="CASCADE", index=True
    )
    sequence: int = Field(default=1, ge=1)
    role: QuestionRegionRole = Field(
        default=QuestionRegionRole.PRIMARY,
        sa_column=Column(
            SAEnum(
                QuestionRegionRole,
                name="questionregionrole",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class KnowledgePointSource(StrEnum):
    CURRICULUM = "curriculum"
    CUSTOM = "custom"


class QuestionKnowledgeSource(StrEnum):
    AI = "ai"
    TEACHER = "teacher"


class KnowledgePoint(SQLModel, table=True):
    """学科知识点树。平台级受控词表，不按学校隔离。

    `ExamQuestion.knowledge_point` 自由文本列保留不动：题库筛选、组卷复制和
    教师报告的题号映射都依赖它，这里只增加规范化引用。
    """

    __table_args__ = (
        UniqueConstraint("subject", "code", name="uq_knowledgepoint_subject_code"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    subject: str = Field(min_length=1, max_length=50, index=True)
    grade_band: str = Field(default="junior", max_length=50)
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    parent_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="knowledgepoint.id",
        nullable=True,
        ondelete="SET NULL",
    )
    aliases: list[str] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    source: KnowledgePointSource = Field(
        default=KnowledgePointSource.CURRICULUM,
        sa_column=Column(
            SAEnum(
                KnowledgePointSource,
                name="knowledgepointsource",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    sort_order: int = Field(default=0)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class ExamQuestionKnowledgeLink(SQLModel, table=True):
    """题目与知识点的规范化关联。教师标注优先于 AI 标注。"""

    __table_args__ = (
        UniqueConstraint(
            "question_id",
            "knowledge_point_id",
            name="uq_examquestionknowledgelink_pair",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    question_id: uuid.UUID = Field(
        foreign_key="examquestion.id", nullable=False, ondelete="CASCADE", index=True
    )
    knowledge_point_id: uuid.UUID = Field(
        foreign_key="knowledgepoint.id", nullable=False, ondelete="CASCADE", index=True
    )
    confidence: Decimal | None = Field(
        default=None,
        sa_column=Column(Numeric(5, 4), nullable=True),
    )
    source: QuestionKnowledgeSource = Field(
        default=QuestionKnowledgeSource.AI,
        sa_column=Column(
            SAEnum(
                QuestionKnowledgeSource,
                name="questionknowledgesource",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    is_primary: bool = Field(default=False)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class QuestionRecognitionRun(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    exam_id: uuid.UUID = Field(
        foreign_key="exam.id", nullable=False, ondelete="CASCADE", index=True
    )
    created_by_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="RESTRICT"
    )
    provider: str = Field(default="fluxnode_gemini", max_length=100)
    model: str = Field(default="gemini-3.5-flash", max_length=200)
    engine: str = Field(default="reference-node", max_length=100)
    status: WorkflowRunStatus = Field(
        default=WorkflowRunStatus.QUEUED,
        sa_column=Column(
            SAEnum(
                WorkflowRunStatus,
                name="workflowrunstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    document_ids: list[str] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    timing: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    raw_output: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    error_message: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    started_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    completed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    confirmed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore


class QuestionRecognitionItem(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "run_id", "source_item_key", name="uq_questionrecognitionitem_run_source"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(
        foreign_key="questionrecognitionrun.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    source_item_key: str = Field(max_length=255)
    question_key: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=255)
    question_text: str = Field(default="", max_length=20000)
    student_answer_text: str | None = Field(default=None, max_length=12000)
    question_type: str | None = Field(default=None, max_length=50)
    knowledge_point: str | None = Field(default=None, max_length=100)
    difficulty: int | None = Field(default=None, ge=1, le=5)
    confidence: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(5, 4), nullable=True)
    )
    notes: str | None = Field(default=None, max_length=4000)
    region_ids: list[str] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    region_snapshots: list[dict] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    raw_result: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    status: QuestionRecognitionItemStatus = Field(
        default=QuestionRecognitionItemStatus.DRAFT,
        sa_column=Column(
            SAEnum(
                QuestionRecognitionItemStatus,
                name="questionrecognitionitemstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    confirmed_question_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="examquestion.id",
        nullable=True,
        ondelete="SET NULL",
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class ExamQuestionPublic(SQLModel):
    id: uuid.UUID
    exam_id: uuid.UUID
    question_key: str
    label: str
    question_text: str
    question_type: str | None = None
    knowledge_point: str | None = None
    difficulty: int | None = None
    recognition_confidence: float | None = None
    status: ExamQuestionStatus
    region_ids: list[uuid.UUID] = Field(default_factory=list)
    confirmed_by_id: uuid.UUID | None = None
    confirmed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ExamQuestionsPublic(SQLModel):
    data: list[ExamQuestionPublic]
    count: int


class QuestionBankEntryPublic(SQLModel):
    question_id: uuid.UUID
    exam_id: uuid.UUID
    exam_title: str
    question_key: str
    label: str
    question_text: str
    question_type: str | None = None
    knowledge_point: str | None = None
    difficulty: int | None = None
    max_score: float | None = None


class QuestionBankPublic(SQLModel):
    data: list[QuestionBankEntryPublic]
    count: int


class ExamComposeRequest(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    question_ids: list[uuid.UUID] = Field(min_length=1)


class QuestionRecognitionRunCreate(SQLModel):
    document_ids: list[uuid.UUID] = Field(min_length=1)


class MarkingRecognitionImport(SQLModel):
    document_ids: list[uuid.UUID] = Field(min_length=1)
    covered_page_ids: list[str] = Field(min_length=1)
    results: list[dict] = Field(min_length=1)
    blocks: list[dict] = Field(min_length=1)
    layouts: list[dict] = Field(default_factory=list)
    timing: dict = Field(default_factory=dict)


class QuestionRecognitionRunPublic(SQLModel):
    id: uuid.UUID
    exam_id: uuid.UUID
    created_by_id: uuid.UUID
    provider: str
    model: str
    engine: str
    status: WorkflowRunStatus
    document_ids: list[str]
    timing: dict
    error_message: str | None = None
    item_count: int = 0
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    confirmed_at: datetime | None = None


class QuestionRecognitionRunsPublic(SQLModel):
    data: list[QuestionRecognitionRunPublic]
    count: int


class QuestionRecognitionItemPublic(SQLModel):
    id: uuid.UUID
    run_id: uuid.UUID
    source_item_key: str
    question_key: str
    label: str
    question_text: str
    student_answer_text: str | None = None
    question_type: str | None = None
    knowledge_point: str | None = None
    difficulty: int | None = None
    confidence: float | None = None
    notes: str | None = None
    region_ids: list[str]
    region_snapshots: list[dict]
    status: QuestionRecognitionItemStatus
    confirmed_question_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class QuestionRecognitionItemUpdate(SQLModel):
    question_key: str | None = Field(default=None, min_length=1, max_length=100)
    label: str | None = Field(default=None, min_length=1, max_length=255)
    question_text: str | None = Field(default=None, max_length=20000)
    student_answer_text: str | None = Field(default=None, max_length=12000)
    question_type: str | None = Field(default=None, max_length=50)
    knowledge_point: str | None = Field(default=None, max_length=100)
    difficulty: int | None = Field(default=None, ge=1, le=5)
    confidence: float | None = Field(default=None, ge=0, le=1)
    notes: str | None = Field(default=None, max_length=4000)
    region_ids: list[uuid.UUID] | None = None
    status: QuestionRecognitionItemStatus | None = None


class StandardAnswerBase(SQLModel):
    answer_text: str = Field(min_length=1, max_length=12000)
    max_score: float = Field(gt=0)
    rubric_text: str | None = Field(default=None, max_length=8000)
    scoring_points: list[dict] = Field(default_factory=list)
    status: StandardAnswerStatus = StandardAnswerStatus.DRAFT

    @model_validator(mode="after")
    def validate_scoring_points(self) -> "StandardAnswerBase":
        for index, point in enumerate(self.scoring_points, start=1):
            if not isinstance(point, dict):
                raise ValueError(f"Scoring point {index} must be an object")
            missing = {"id", "description", "points", "required"} - set(point)
            if missing:
                raise ValueError(
                    f"Scoring point {index} missing fields: {', '.join(sorted(missing))}"
                )
            if not str(point["id"]).strip():
                raise ValueError(f"Scoring point {index} id is required")
            if not str(point["description"]).strip():
                raise ValueError(f"Scoring point {index} description is required")
            try:
                points = float(point["points"])
            except (TypeError, ValueError):
                raise ValueError(f"Scoring point {index} points must be numeric")
            if points < 0:
                raise ValueError(f"Scoring point {index} points must be non-negative")
            if not isinstance(point["required"], bool):
                raise ValueError(f"Scoring point {index} required must be boolean")
        return self


class StandardAnswerCreate(StandardAnswerBase):
    exam_region_id: uuid.UUID


class StandardAnswerUpdate(SQLModel):
    answer_text: str | None = Field(default=None, min_length=1, max_length=12000)
    max_score: float | None = Field(default=None, gt=0)
    rubric_text: str | None = Field(default=None, max_length=8000)
    scoring_points: list[dict] | None = None
    status: StandardAnswerStatus | None = None

    @model_validator(mode="after")
    def validate_scoring_points(self) -> "StandardAnswerUpdate":
        if self.scoring_points is None:
            return self
        StandardAnswerBase(
            answer_text="placeholder",
            max_score=1,
            scoring_points=self.scoring_points,
        )
        return self


class StandardAnswer(StandardAnswerBase, table=True):
    __table_args__ = (
        UniqueConstraint("exam_region_id", name="uq_standardanswer_exam_region_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    scoring_points: list[dict] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    status: StandardAnswerStatus = Field(
        default=StandardAnswerStatus.DRAFT,
        sa_column=Column(
            SAEnum(
                StandardAnswerStatus,
                name="standardanswerstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    version: int = Field(default=1, ge=1)
    source_provider: str | None = Field(default=None, max_length=100)
    source_model: str | None = Field(default=None, max_length=200)
    generation_confidence: float | None = Field(default=None, ge=0, le=1)
    answer_hash: str | None = Field(default=None, max_length=64)
    published_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    published_by_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", nullable=True, ondelete="SET NULL"
    )
    question_text: str | None = Field(default=None, max_length=12000)
    question_type: str | None = Field(default=None, max_length=50)
    rubric_config: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    validation_report: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    exam_id: uuid.UUID = Field(
        foreign_key="exam.id", nullable=False, ondelete="CASCADE"
    )
    # 数字卷（重新组卷）没有扫描区域，允许为空。
    exam_region_id: uuid.UUID | None = Field(
        default=None, foreign_key="examregion.id", nullable=True, ondelete="CASCADE"
    )
    question_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="examquestion.id",
        nullable=True,
        ondelete="CASCADE",
        index=True,
    )
    current_revision_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="standardanswerrevision.id",
        nullable=True,
        ondelete="SET NULL",
    )
    exam: Exam | None = Relationship(back_populates="standard_answers")
    exam_region: ExamRegion | None = Relationship(back_populates="standard_answer")


class StandardAnswerPublic(StandardAnswerBase):
    id: uuid.UUID
    exam_id: uuid.UUID
    exam_region_id: uuid.UUID | None = None
    question_id: uuid.UUID | None = None
    current_revision_id: uuid.UUID | None = None
    version: int = 1
    source_provider: str | None = None
    source_model: str | None = None
    generation_confidence: float | None = None
    answer_hash: str | None = None
    published_at: datetime | None = None
    published_by_id: uuid.UUID | None = None
    question_text: str | None = None
    question_type: str | None = None
    rubric_config: dict = Field(default_factory=dict)
    validation_report: dict = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class StandardAnswersPublic(SQLModel):
    data: list[StandardAnswerPublic]
    count: int


class AnswerPreparationRun(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    exam_id: uuid.UUID = Field(
        foreign_key="exam.id", nullable=False, ondelete="CASCADE", index=True
    )
    created_by_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    source_type: AnswerPreparationSource = Field(
        sa_column=Column(
            SAEnum(
                AnswerPreparationSource,
                name="answerpreparationsource",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        )
    )
    provider: str = Field(default="pomoai", max_length=100)
    model: str = Field(default="gpt-5.6-sol", max_length=200)
    document_ids: list[str] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    status: WorkflowRunStatus = Field(
        default=WorkflowRunStatus.QUEUED,
        sa_column=Column(
            SAEnum(
                WorkflowRunStatus,
                name="workflowrunstatus",
                values_callable=lambda enum: [item.value for item in enum],
                create_type=False,
            ),
            nullable=False,
        ),
    )
    timing: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    raw_output: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    error_message: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    started_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    completed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    confirmed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore


class AnswerPreparationItem(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "run_id", "source_item_key", name="uq_answerpreparationitem_run_source"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(
        foreign_key="answerpreparationrun.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    question_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="examquestion.id",
        nullable=True,
        ondelete="SET NULL",
        index=True,
    )
    source_item_key: str = Field(max_length=255)
    source_question_key: str | None = Field(default=None, max_length=100)
    answer_text: str = Field(default="", max_length=20000)
    max_score: Decimal = Field(
        default=Decimal("1.00"),
        sa_column=Column(Numeric(8, 2), nullable=False),
    )
    rubric_text: str | None = Field(default=None, max_length=12000)
    scoring_points: list[dict] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    confidence: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(5, 4), nullable=True)
    )
    match_reason: str | None = Field(default=None, max_length=2000)
    raw_result: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    status: AnswerPreparationItemStatus = Field(
        default=AnswerPreparationItemStatus.QUEUED,
        sa_column=Column(
            SAEnum(
                AnswerPreparationItemStatus,
                name="answerpreparationitemstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    revision_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="standardanswerrevision.id",
        nullable=True,
        ondelete="SET NULL",
    )
    error_message: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class StandardAnswerRevision(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "standard_answer_id",
            "revision_number",
            name="uq_standardanswerrevision_answer_number",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    standard_answer_id: uuid.UUID = Field(
        foreign_key="standardanswer.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    question_id: uuid.UUID = Field(
        foreign_key="examquestion.id", nullable=False, ondelete="CASCADE", index=True
    )
    revision_number: int = Field(ge=1)
    question_key: str = Field(min_length=1, max_length=100)
    question_text: str = Field(min_length=1, max_length=20000)
    question_type: str | None = Field(default=None, max_length=50)
    answer_text: str = Field(min_length=1, max_length=20000)
    max_score: Decimal = Field(sa_column=Column(Numeric(8, 2), nullable=False))
    rubric_text: str | None = Field(default=None, max_length=12000)
    scoring_points: list[dict] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    source_provider: str | None = Field(default=None, max_length=100)
    source_model: str | None = Field(default=None, max_length=200)
    generation_confidence: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(5, 4), nullable=True)
    )
    content_hash: str = Field(min_length=64, max_length=64)
    status: StandardAnswerRevisionStatus = Field(
        default=StandardAnswerRevisionStatus.DRAFT,
        sa_column=Column(
            SAEnum(
                StandardAnswerRevisionStatus,
                name="standardanswerrevisionstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    created_by_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    published_by_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", nullable=True, ondelete="SET NULL"
    )
    preparation_item_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="answerpreparationitem.id",
        nullable=True,
        ondelete="SET NULL",
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    published_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore


class AnswerPreparationRunCreate(SQLModel):
    source_type: AnswerPreparationSource
    document_ids: list[uuid.UUID] = Field(default_factory=list)


class AnswerPreparationRunPublic(SQLModel):
    id: uuid.UUID
    exam_id: uuid.UUID
    created_by_id: uuid.UUID
    source_type: AnswerPreparationSource
    provider: str
    model: str
    document_ids: list[str]
    status: WorkflowRunStatus
    timing: dict
    error_message: str | None = None
    item_count: int = 0
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    confirmed_at: datetime | None = None


class AnswerPreparationRunsPublic(SQLModel):
    data: list[AnswerPreparationRunPublic]
    count: int


class AnswerPreparationItemPublic(SQLModel):
    id: uuid.UUID
    run_id: uuid.UUID
    question_id: uuid.UUID | None = None
    source_item_key: str
    source_question_key: str | None = None
    answer_text: str
    max_score: float
    rubric_text: str | None = None
    scoring_points: list[dict]
    confidence: float | None = None
    match_reason: str | None = None
    status: AnswerPreparationItemStatus
    revision_id: uuid.UUID | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class AnswerPreparationItemUpdate(SQLModel):
    question_id: uuid.UUID | None = None
    answer_text: str | None = Field(default=None, min_length=1, max_length=20000)
    max_score: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    rubric_text: str | None = Field(default=None, max_length=12000)
    scoring_points: list[dict] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    match_reason: str | None = Field(default=None, max_length=2000)
    status: AnswerPreparationItemStatus | None = None


class StandardAnswerRevisionPublic(SQLModel):
    id: uuid.UUID
    standard_answer_id: uuid.UUID
    question_id: uuid.UUID
    revision_number: int
    question_key: str
    question_text: str
    question_type: str | None = None
    answer_text: str
    max_score: float
    rubric_text: str | None = None
    scoring_points: list[dict]
    source_provider: str | None = None
    source_model: str | None = None
    generation_confidence: float | None = None
    content_hash: str
    status: StandardAnswerRevisionStatus
    created_by_id: uuid.UUID
    published_by_id: uuid.UUID | None = None
    preparation_item_id: uuid.UUID | None = None
    created_at: datetime
    published_at: datetime | None = None


class StandardAnswerRevisionsPublic(SQLModel):
    data: list[StandardAnswerRevisionPublic]
    count: int


class StandardAnswerPublishRequest(SQLModel):
    revision_ids: list[uuid.UUID] = Field(default_factory=list)


class StudentSubmissionBase(SQLModel):
    student_name: str | None = Field(default=None, max_length=255)
    student_identifier: str | None = Field(default=None, max_length=100)
    class_name: str | None = Field(default=None, max_length=100)
    status: StudentSubmissionStatus = StudentSubmissionStatus.REGISTRATION_PENDING
    registration_status: SubmissionRegistrationStatus = (
        SubmissionRegistrationStatus.PENDING
    )
    registration_quality: float | None = Field(default=None, ge=0, le=1)
    registration_notes: str | None = Field(default=None, max_length=1000)


class StudentSubmissionCreate(SQLModel):
    student_name: str | None = Field(default=None, max_length=255)
    student_identifier: str | None = Field(default=None, max_length=100)
    class_name: str | None = Field(default=None, max_length=100)


class StudentSubmissionRegistrationUpdate(SQLModel):
    registration_status: SubmissionRegistrationStatus
    registration_quality: float | None = Field(default=None, ge=0, le=1)
    registration_notes: str | None = Field(default=None, max_length=1000)
    registration_homography: dict | None = None


class StudentSubmission(StudentSubmissionBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    status: StudentSubmissionStatus = Field(
        default=StudentSubmissionStatus.REGISTRATION_PENDING,
        sa_column=Column(
            SAEnum(
                StudentSubmissionStatus,
                name="studentsubmissionstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    registration_status: SubmissionRegistrationStatus = Field(
        default=SubmissionRegistrationStatus.PENDING,
        sa_column=Column(
            SAEnum(
                SubmissionRegistrationStatus,
                name="submissionregistrationstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    registration_homography: dict | None = Field(default=None, sa_column=Column(JSONB))
    registered_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )  # type: ignore
    exam_id: uuid.UUID = Field(
        foreign_key="exam.id", nullable=False, ondelete="CASCADE"
    )
    stored_file_id: uuid.UUID = Field(
        foreign_key="storedfile.id", nullable=False, ondelete="CASCADE"
    )
    original_stored_file_id: uuid.UUID | None = Field(
        default=None, foreign_key="storedfile.id", nullable=True, ondelete="SET NULL"
    )
    student_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="student.id",
        nullable=True,
        ondelete="SET NULL",
        index=True,
    )
    student: Optional["Student"] = Relationship()
    exam: Exam | None = Relationship(back_populates="submissions")
    stored_file: StoredFile | None = Relationship(
        back_populates="student_submissions",
        sa_relationship_kwargs={"foreign_keys": "StudentSubmission.stored_file_id"},
    )
    annotations: list["SubmissionAnnotation"] = Relationship(
        back_populates="submission", cascade_delete=True
    )


class StudentSubmissionPublic(StudentSubmissionBase):
    id: uuid.UUID
    exam_id: uuid.UUID
    stored_file_id: uuid.UUID
    stored_file: StoredFilePublic
    page_count: int = 1
    original_stored_file_id: uuid.UUID | None = None
    student_id: uuid.UUID | None = None
    registration_homography: dict | None = None
    registered_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class StudentSubmissionsPublic(SQLModel):
    data: list[StudentSubmissionPublic]
    count: int


class ExamScoreSummaryQuestion(SQLModel):
    label: str
    score: float | None = None
    max_score: float | None = None
    # "final" = 教师复核后的最终分（score_source == "human"），
    # "ai_suggested" = AI 建议分（尚无教师确认）。
    score_source: str | None = None
    annotation_id: uuid.UUID | None = None


class ExamScoreSummaryRow(SQLModel):
    submission_id: uuid.UUID
    student_name: str | None = None
    student_identifier: str | None = None
    class_name: str | None = None
    total_score: float | None = None
    total_max_score: float | None = None
    questions: list[ExamScoreSummaryQuestion] = Field(default_factory=list)
    status: StudentSubmissionStatus = StudentSubmissionStatus.REGISTRATION_PENDING
    registration_status: SubmissionRegistrationStatus = (
        SubmissionRegistrationStatus.PENDING
    )
    registration_quality: float | None = None
    registration_notes: str | None = None
    page_count: int | None = None
    pending_review_count: int = 0


class ExamScoreSummaryPublic(SQLModel):
    data: list[ExamScoreSummaryRow]
    count: int


class ExamAnalysisReportPublic(SQLModel):
    overall: str
    weak: str
    polar: str
    advice: str
    generated_at: datetime


class SubmissionAnnotationBase(SQLModel):
    label: str = Field(min_length=1, max_length=100)
    status: SubmissionAnnotationStatus = SubmissionAnnotationStatus.NEEDS_REVIEW
    page_number: int = Field(default=1, ge=1)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)
    score: float | None = Field(default=None, ge=0)
    max_score: float | None = Field(default=None, ge=0)
    comment: str | None = Field(default=None, max_length=2000)
    ocr_text: str | None = Field(default=None, max_length=8000)
    ocr_confidence: float | None = Field(default=None, ge=0, le=1)
    ocr_status: str = Field(default="not_started", max_length=50)
    ocr_engine: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_bounds(self) -> "SubmissionAnnotationBase":
        if self.x + self.width > 1:
            raise ValueError("Annotation x + width must be less than or equal to 1")
        if self.y + self.height > 1:
            raise ValueError("Annotation y + height must be less than or equal to 1")
        return self


class SubmissionAnnotationCreate(SubmissionAnnotationBase):
    exam_region_id: uuid.UUID | None = None


class SubmissionAnnotationUpdate(SQLModel):
    label: str | None = Field(default=None, min_length=1, max_length=100)
    status: SubmissionAnnotationStatus | None = None
    page_number: int | None = Field(default=None, ge=1)
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    width: float | None = Field(default=None, gt=0, le=1)
    height: float | None = Field(default=None, gt=0, le=1)
    score: float | None = Field(default=None, ge=0)
    max_score: float | None = Field(default=None, ge=0)
    comment: str | None = Field(default=None, max_length=2000)
    audit_reason: str | None = Field(default=None, max_length=1000)


class SubmissionAnnotation(SubmissionAnnotationBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    status: SubmissionAnnotationStatus = Field(
        default=SubmissionAnnotationStatus.NEEDS_REVIEW,
        sa_column=Column(
            SAEnum(
                SubmissionAnnotationStatus,
                name="submissionannotationstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    submission_id: uuid.UUID = Field(
        foreign_key="studentsubmission.id", nullable=False, ondelete="CASCADE"
    )
    exam_region_id: uuid.UUID | None = Field(
        default=None, foreign_key="examregion.id", nullable=True, ondelete="SET NULL"
    )
    suggested_score: float | None = Field(default=None, ge=0)
    suggested_comment: str | None = Field(default=None, max_length=2000)
    grading_confidence: float | None = Field(default=None, ge=0, le=1)
    grading_reasons: list[dict] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    grading_status: AnnotationGradingStatus = Field(
        default=AnnotationGradingStatus.NOT_STARTED,
        sa_column=Column(
            SAEnum(
                AnnotationGradingStatus,
                name="annotationgradingstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    answer_key_updated_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    score_source: str | None = Field(default=None, max_length=50)
    model_score: float | None = Field(default=None, ge=0)
    model_confidence: float | None = Field(default=None, ge=0, le=1)
    grading_version: str | None = Field(default=None, max_length=100)
    grading_evidence: list[dict] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    auto_published_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    submission: StudentSubmission | None = Relationship(back_populates="annotations")


class SubmissionAnnotationPublic(SubmissionAnnotationBase):
    id: uuid.UUID
    submission_id: uuid.UUID
    exam_region_id: uuid.UUID | None = None
    suggested_score: float | None = None
    suggested_comment: str | None = None
    grading_confidence: float | None = None
    grading_reasons: list[dict] = Field(default_factory=list)
    grading_status: AnnotationGradingStatus = AnnotationGradingStatus.NOT_STARTED
    answer_key_updated_at: datetime | None = None
    score_source: str | None = None
    model_score: float | None = None
    model_confidence: float | None = None
    grading_version: str | None = None
    grading_evidence: list[dict] = Field(default_factory=list)
    auto_published_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SubmissionAnnotationsPublic(SQLModel):
    data: list[SubmissionAnnotationPublic]
    count: int


class ProcessingTaskBase(SQLModel):
    task_type: str = Field(min_length=1, max_length=100)
    status: ProcessingTaskStatus = ProcessingTaskStatus.QUEUED
    progress: int = Field(default=0, ge=0, le=100)
    error_message: str | None = Field(default=None, max_length=1000)


class ProcessingTaskCreate(SQLModel):
    task_type: str = Field(default="test", min_length=1, max_length=100)


class ProcessingTask(ProcessingTaskBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    status: ProcessingTaskStatus = Field(
        default=ProcessingTaskStatus.QUEUED,
        sa_column=Column(
            SAEnum(
                ProcessingTaskStatus,
                name="processingtaskstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    input_ref: dict | None = Field(default=None, sa_column=Column(JSONB))
    output_ref: dict | None = Field(default=None, sa_column=Column(JSONB))
    created_by_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    created_by: User | None = Relationship(back_populates="processing_tasks")


class ProcessingTaskPublic(ProcessingTaskBase):
    id: uuid.UUID
    created_by_id: uuid.UUID
    input_ref: dict | None = None
    output_ref: dict | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GradingRunCreate(SQLModel):
    exam_id: uuid.UUID
    submission_ids: list[uuid.UUID] = Field(default_factory=list)
    # None = 未显式指定，创建 run 时回落系统设置（services/system_config）
    review_threshold: float | None = Field(default=None, ge=0, le=1)
    max_concurrency: int | None = Field(default=None, ge=1, le=32)
    max_parallel_submissions: int | None = Field(default=None, ge=1, le=8)
    max_concurrency_per_submission: int | None = Field(default=None, ge=1, le=8)
    recognition_run_id: uuid.UUID | None = None


class RecognitionRunCreate(SQLModel):
    exam_id: uuid.UUID
    submission_id: uuid.UUID
    max_concurrency: int = Field(default=8, ge=1, le=8)
    verification_mode: Literal["fast", "selective", "evidence"] = "selective"


class RecognitionItemPublic(SQLModel):
    item_id: uuid.UUID
    submission_id: uuid.UUID
    exam_region_id: uuid.UUID
    label: str
    status: GradingItemStatus
    question_text: str | None = None
    student_answer: str | None = None
    final_answer: str | None = None
    confidence: float | None = None
    notes: list[str] = Field(default_factory=list)
    printed_question_marks: list[dict[str, str]] = Field(default_factory=list)
    answer_entries: list[dict[str, Any]] = Field(default_factory=list)
    unassigned_evidence: list[str] = Field(default_factory=list)
    grading_answer: str | None = None
    grading_eligible: bool = False
    answer_verification: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None


class RecognitionItemUpdate(SQLModel):
    question_text: str | None = Field(default=None, max_length=12000)
    student_answer: str | None = Field(default=None, max_length=8000)
    final_answer: str | None = Field(default=None, max_length=2000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    notes: list[str] | None = None
    approve_for_grading: bool | None = None
    approval_source: str | None = Field(default=None, max_length=50)


class GradingRun(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    exam_id: uuid.UUID = Field(
        foreign_key="exam.id", nullable=False, ondelete="CASCADE", index=True
    )
    created_by_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    provider: str = Field(max_length=100)
    model: str = Field(max_length=200)
    fallback_models: list[str] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    answer_version: int = Field(default=1, ge=1)
    status: GradingRunStatus = Field(
        default=GradingRunStatus.QUEUED,
        sa_column=Column(
            SAEnum(
                GradingRunStatus,
                name="gradingrunstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    total_submissions: int = Field(default=0, ge=0)
    completed_count: int = Field(default=0, ge=0)
    review_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    total_items: int = Field(default=0, ge=0)
    completed_items: int = Field(default=0, ge=0)
    extracted_items: int = Field(default=0, ge=0)
    objective_items: int = Field(default=0, ge=0)
    subjective_items: int = Field(default=0, ge=0)
    current_concurrency: int = Field(default=0, ge=0)
    throttle_count: int = Field(default=0, ge=0)
    config_snapshot: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    error_message: str | None = Field(default=None, max_length=2000)
    estimated_microcredits: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    reserved_microcredits: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    settled_microcredits: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    billing_status: str = Field(default="unmetered", max_length=30)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    started_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    completed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore


class GradingRunPublic(SQLModel):
    id: uuid.UUID
    exam_id: uuid.UUID
    created_by_id: uuid.UUID
    provider: str
    model: str
    fallback_models: list[str]
    answer_version: int
    status: GradingRunStatus
    total_submissions: int
    completed_count: int
    review_count: int
    failed_count: int
    average_confidence: float | None = None
    total_items: int = 0
    completed_items: int = 0
    extracted_items: int = 0
    objective_items: int = 0
    subjective_items: int = 0
    current_concurrency: int = 0
    throttle_count: int = 0
    config_snapshot: dict
    timing: dict = Field(default_factory=dict)
    error_message: str | None = None
    estimated_credits: float = 0
    reserved_credits: float = 0
    settled_credits: float = 0
    billing_status: str = "unmetered"
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class GradingRunsPublic(SQLModel):
    data: list[GradingRunPublic]
    count: int


class GradingItem(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "grading_run_id",
            "submission_id",
            "exam_region_id",
            name="uq_gradingitem_run_submission_region",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    grading_run_id: uuid.UUID = Field(
        foreign_key="gradingrun.id", nullable=False, ondelete="CASCADE", index=True
    )
    submission_id: uuid.UUID = Field(
        foreign_key="studentsubmission.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    exam_region_id: uuid.UUID = Field(
        foreign_key="examregion.id", nullable=False, ondelete="CASCADE"
    )
    question_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="examquestion.id",
        nullable=True,
        ondelete="SET NULL",
        index=True,
    )
    answer_revision_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="standardanswerrevision.id",
        nullable=True,
        ondelete="SET NULL",
        index=True,
    )
    annotation_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="submissionannotation.id",
        nullable=True,
        ondelete="SET NULL",
    )
    status: GradingItemStatus = Field(
        default=GradingItemStatus.QUEUED,
        sa_column=Column(
            SAEnum(
                GradingItemStatus,
                name="gradingitemstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    attempts: int = Field(default=0, ge=0)
    extraction_result: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    grading_result: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    error_message: str | None = Field(default=None, max_length=2000)
    started_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    completed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore


class GradingAuditEvent(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    grading_run_id: uuid.UUID | None = Field(
        default=None, foreign_key="gradingrun.id", nullable=True, ondelete="SET NULL"
    )
    submission_id: uuid.UUID = Field(
        foreign_key="studentsubmission.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    annotation_id: uuid.UUID = Field(
        foreign_key="submissionannotation.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    operator_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", nullable=True, ondelete="SET NULL"
    )
    source: str = Field(max_length=50)
    old_score: float | None = None
    new_score: float | None = None
    old_comment: str | None = Field(default=None, max_length=2000)
    new_comment: str | None = Field(default=None, max_length=2000)
    reason: str | None = Field(default=None, max_length=1000)
    metadata_json: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class GradingAuditEventPublic(SQLModel):
    id: uuid.UUID
    grading_run_id: uuid.UUID | None = None
    submission_id: uuid.UUID
    annotation_id: uuid.UUID
    operator_id: uuid.UUID | None = None
    source: str
    old_score: float | None = None
    new_score: float | None = None
    old_comment: str | None = None
    new_comment: str | None = None
    reason: str | None = None
    metadata_json: dict
    created_at: datetime


class GradingReviewItem(SQLModel):
    submission_id: uuid.UUID
    student_name: str | None = None
    student_identifier: str | None = None
    annotation_id: uuid.UUID | None = None
    label: str | None = None
    score: float | None = None
    max_score: float | None = None
    confidence: float | None = None
    risk: str
    priority: int


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


# ---------------------------------------------------------------------------
# 班级 / 学生实体（整改计划阶段 2）
# ---------------------------------------------------------------------------
class ClassGroupBase(SQLModel):
    name: str = Field(min_length=1, max_length=100)
    grade_level: str | None = Field(default=None, max_length=100)


class ClassGroupCreate(ClassGroupBase):
    # 仅 schema 字段：平台角色创建班级时必须显式指定归属学校；
    # 学校角色忽略该字段，班级一律归入本人所在学校
    org_id: uuid.UUID | None = None


class ClassGroupUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    grade_level: str | None = Field(default=None, max_length=100)


class ClassGroup(ClassGroupBase, table=True):
    __table_args__ = (
        # 班级名学校内唯一；跨校允许同名班
        UniqueConstraint("org_id", "name", name="uq_classgroup_org_name"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="RESTRICT"
    )
    # 班级归属的学校（学校内共享，跨校不可见），回填默认学校后 NOT NULL
    org_id: uuid.UUID = Field(foreign_key="organization.id", nullable=False, index=True)
    owner: User | None = Relationship(back_populates="class_groups")
    students: list["Student"] = Relationship(
        back_populates="class_group", cascade_delete=True
    )
    exam_links: list["ExamClassLink"] = Relationship(
        back_populates="class_group", cascade_delete=True
    )


class ClassGroupPublic(ClassGroupBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    org_id: uuid.UUID
    created_at: datetime | None = None
    student_count: int = 0


class ClassGroupsPublic(SQLModel):
    data: list[ClassGroupPublic]
    count: int


class StudentBase(SQLModel):
    name: str = Field(min_length=1, max_length=100)
    student_no: str | None = Field(default=None, max_length=50)


class StudentCreate(StudentBase):
    pass


class StudentUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    student_no: str | None = Field(default=None, max_length=50)


class Student(StudentBase, table=True):
    __table_args__ = (
        UniqueConstraint("class_id", "name", name="uq_student_class_name"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    class_id: uuid.UUID = Field(
        foreign_key="classgroup.id", nullable=False, ondelete="CASCADE"
    )
    user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", nullable=True, ondelete="SET NULL"
    )
    class_group: ClassGroup | None = Relationship(back_populates="students")
    submissions: list["StudentSubmission"] = Relationship(
        back_populates="student",
        sa_relationship_kwargs={"foreign_keys": "StudentSubmission.student_id"},
    )


class StudentPublic(StudentBase):
    id: uuid.UUID
    class_id: uuid.UUID
    user_id: uuid.UUID | None = None
    account_email: str | None = None
    created_at: datetime | None = None


class StudentsPublic(SQLModel):
    data: list[StudentPublic]
    count: int


class StudentBatchRow(SQLModel):
    """花名册批量导入的单行（前端把 CSV/粘贴文本解析成 rows 传入）。"""

    name: str = Field(max_length=100)
    student_no: str | None = Field(default=None, max_length=50)


class StudentBatchCreate(SQLModel):
    rows: list[StudentBatchRow] = Field(min_length=1)
    # 同时为学生创建登录账号（学号@school.local），需学校管理角色
    create_accounts: bool = False
    # 预览模式：只校验不落库
    dry_run: bool = False


class StudentBatchRowResult(SQLModel):
    name: str
    student_no: str | None = None
    # create=将创建/已创建；skip_exists=同名已存在跳过；error=校验失败
    action: str
    message: str | None = None


class StudentBatchResult(SQLModel):
    created: int = 0
    skipped: int = 0
    accounts_created: int = 0
    rows: list[StudentBatchRowResult] = Field(default_factory=list)
    errors: list[StudentBatchRowResult] = Field(default_factory=list)


class StudentBindAccount(SQLModel):
    user_id: uuid.UUID


class ExamClassLink(SQLModel, table=True):
    exam_id: uuid.UUID = Field(
        foreign_key="exam.id", primary_key=True, ondelete="CASCADE"
    )
    class_id: uuid.UUID = Field(
        foreign_key="classgroup.id", primary_key=True, ondelete="CASCADE"
    )
    class_group: ClassGroup | None = Relationship(back_populates="exam_links")


# ---------------------------------------------------------------------------
# 任教档案（教师 ↔ 班级/学科）与共享批卷分配
# ---------------------------------------------------------------------------
class TeacherClassLink(SQLModel, table=True):
    """任教档案：教师任教的班级（联合主键去重）。"""

    user_id: uuid.UUID = Field(
        foreign_key="user.id", primary_key=True, ondelete="CASCADE"
    )
    class_id: uuid.UUID = Field(
        foreign_key="classgroup.id", primary_key=True, ondelete="CASCADE"
    )


class TeachingProfilePublic(SQLModel):
    class_ids: list[uuid.UUID] = Field(default_factory=list)
    class_names: list[str] = Field(default_factory=list)
    subjects: list[str] = Field(default_factory=list)


class TeachingProfileUpdate(SQLModel):
    class_ids: list[uuid.UUID] = Field(default_factory=list)
    subjects: list[str] = Field(default_factory=list, max_length=20)


# ---------------------------------------------------------------------------
# 老师批量导入（花名册）
# ---------------------------------------------------------------------------
class TeacherBatchRow(SQLModel):
    # name/email 逻辑上必填，但校验放在端点里逐行报错，避免整单 422
    name: str | None = Field(default=None, max_length=255)
    employee_no: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=255)
    # 逗号分隔的学科标签，落库时拆分存 User.subjects
    subjects: str | None = None
    # 逗号分隔的班级名，逐个匹配本校班级建 TeacherClassLink
    class_names: str | None = None


class TeacherBatchCreate(SQLModel):
    rows: list[TeacherBatchRow] = Field(min_length=1)
    dry_run: bool = False


class TeacherBatchRowResult(SQLModel):
    name: str | None = None
    email: str | None = None
    action: str  # create | skip_exists | error
    message: str | None = None


class TeacherBatchResult(SQLModel):
    created: int = 0
    skipped: int = 0
    rows: list[TeacherBatchRowResult] = Field(default_factory=list)
    errors: list[TeacherBatchRowResult] = Field(default_factory=list)


class GradingAssignment(SQLModel, table=True):
    """共享批卷分配：考试内按班级指派批卷老师，exam_id+class_id 唯一。"""

    __table_args__ = (
        UniqueConstraint("exam_id", "class_id", name="uq_gradingassignment_exam_class"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    exam_id: uuid.UUID = Field(
        foreign_key="exam.id", nullable=False, ondelete="CASCADE", index=True
    )
    class_id: uuid.UUID = Field(
        foreign_key="classgroup.id", nullable=False, ondelete="CASCADE"
    )
    user_id: uuid.UUID = Field(foreign_key="user.id", nullable=False)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class GradingAssignmentItemPublic(SQLModel):
    class_id: uuid.UUID
    class_name: str
    user_id: uuid.UUID
    user_name: str | None = None


class GradingAssignmentClassPublic(SQLModel):
    class_id: uuid.UUID
    class_name: str


class GradingAssigneePublic(SQLModel):
    user_id: uuid.UUID
    user_name: str
    class_ids: list[uuid.UUID] = Field(default_factory=list)


class GradingAssignmentsPublic(SQLModel):
    enabled: bool
    assignments: list[GradingAssignmentItemPublic] = Field(default_factory=list)
    # 有答卷但尚未分配老师的班级
    unassigned: list[GradingAssignmentClassPublic] = Field(default_factory=list)
    # 仅有分配权限的人可见，避免前端额外读取学校用户目录。
    candidates: list[GradingAssigneePublic] = Field(default_factory=list)


class GradingAssignmentEntry(SQLModel):
    class_id: uuid.UUID
    user_id: uuid.UUID


class GradingAssignmentsUpdate(SQLModel):
    enabled: bool
    assignments: list[GradingAssignmentEntry] = Field(default_factory=list)


# 学生端只读视图模型（/students/me/*）


class StudentExamListItemPublic(SQLModel):
    exam_id: uuid.UUID
    title: str
    subject: str | None = None
    grade_level: str | None = None
    exam_date: date | None = None
    class_name: str | None = None
    total_score: float | None = None
    total_max_score: float | None = None
    class_rank: int | None = None
    class_size: int = 0
    question_count: int = 0
    pending_review_count: int = 0


class StudentExamListPublic(SQLModel):
    data: list[StudentExamListItemPublic]
    count: int


class StudentExamReportQuestion(SQLModel):
    label: str
    score: float | None = None
    max_score: float | None = None
    # "final" = 教师复核后的最终分，"ai_suggested" = AI 建议分
    score_source: str | None = None
    comment: str | None = None
    suggested_comment: str | None = None
    # 指向错题本条目，学生可从成绩报告直接进到「为什么错」
    entry_id: uuid.UUID | None = None
    knowledge_point_names: list[str] = Field(default_factory=list)
    has_image: bool = False


class StudentExamReportPublic(SQLModel):
    exam_id: uuid.UUID
    title: str
    subject: str | None = None
    grade_level: str | None = None
    exam_date: date | None = None
    class_name: str | None = None
    student_name: str | None = None
    total_score: float | None = None
    total_max_score: float | None = None
    class_rank: int | None = None
    class_size: int = 0
    questions: list[StudentExamReportQuestion] = Field(default_factory=list)


class ScoreRelease(SQLModel, table=True):
    """Immutable teacher-published score snapshot for one exam."""

    __table_args__ = (
        UniqueConstraint("exam_id", "version", name="uq_score_release_exam_version"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    exam_id: uuid.UUID = Field(
        foreign_key="exam.id", nullable=False, index=True, ondelete="CASCADE"
    )
    version: int = Field(ge=1)
    status: ScoreReleaseStatus = Field(
        default=ScoreReleaseStatus.PUBLISHED,
        sa_column=Column(
            SAEnum(
                ScoreReleaseStatus,
                name="scorereleasestatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    published_by_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    reason: str = Field(default="教师确认整场成绩", max_length=500)
    published_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True), index=True
    )  # type: ignore
    exam: Exam | None = Relationship(back_populates="score_releases")
    items: list["ScoreReleaseItem"] = Relationship(
        back_populates="release", cascade_delete=True
    )


class ScoreReleaseItem(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "release_id", "submission_id", "label", name="uq_score_release_item"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    release_id: uuid.UUID = Field(
        foreign_key="scorerelease.id", nullable=False, index=True, ondelete="CASCADE"
    )
    submission_id: uuid.UUID = Field(
        foreign_key="studentsubmission.id",
        nullable=False,
        index=True,
        ondelete="RESTRICT",
    )
    annotation_id: uuid.UUID | None = Field(
        default=None, foreign_key="submissionannotation.id", ondelete="SET NULL"
    )
    label: str = Field(max_length=100)
    score: float | None = Field(default=None, ge=0)
    max_score: float | None = Field(default=None, ge=0)
    comment: str | None = Field(default=None, max_length=2000)
    source: str = Field(default="suggested", max_length=30)
    release: ScoreRelease | None = Relationship(back_populates="items")


class ScoreReleasePublic(SQLModel):
    id: uuid.UUID
    exam_id: uuid.UUID
    version: int
    status: ScoreReleaseStatus
    item_count: int = 0
    published_by_id: uuid.UUID | None = None
    reason: str
    published_at: datetime


class ScoreReleaseCreate(SQLModel):
    reason: str = Field(default="教师确认整场成绩", min_length=1, max_length=500)


class WrongQuestionEntryStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class WrongQuestionSource(SQLModel, table=True):
    """错题本的题面快照，每次成绩发布的每道题一行。

    删除考试会级联清空题目、批注和成绩发布记录，因此这里必须自带题干、标准答案和
    评分点，对来源只保留 `ON DELETE SET NULL` 弱引用（见 D-027）。
    """

    __table_args__ = (
        UniqueConstraint(
            "release_id", "question_label", name="uq_wrongquestionsource_release_label"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    exam_id: uuid.UUID | None = Field(
        default=None, foreign_key="exam.id", nullable=True, ondelete="SET NULL"
    )
    question_id: uuid.UUID | None = Field(
        default=None, foreign_key="examquestion.id", nullable=True, ondelete="SET NULL"
    )
    release_id: uuid.UUID | None = Field(
        default=None, foreign_key="scorerelease.id", nullable=True, ondelete="SET NULL"
    )
    release_version: int = Field(default=1, ge=1)
    exam_title: str = Field(max_length=255)
    subject: str | None = Field(default=None, max_length=100, index=True)
    grade_level: str | None = Field(default=None, max_length=100)
    exam_date: date | None = Field(default=None)
    question_label: str = Field(max_length=100)
    question_text: str | None = Field(default=None, max_length=20000)
    question_type: str | None = Field(default=None, max_length=50)
    max_score: float | None = Field(default=None, ge=0)
    standard_answer_text: str | None = Field(default=None, max_length=20000)
    scoring_points: list[dict] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    knowledge_point_names: list[str] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    released_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
        index=True,
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class WrongQuestionEntry(SQLModel, table=True):
    """学生个人的逐题结果快照。

    满分题也建行（`is_wrong=false`）：掌握度需要分母，而 `ScoreRelease` 会随考试
    删除一起消失，分母必须自带。裁切图只对错题复制。
    """

    __table_args__ = (
        UniqueConstraint(
            "release_id",
            "submission_id",
            "question_label",
            name="uq_wrongquestionentry_release_submission_label",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    source_id: uuid.UUID = Field(
        foreign_key="wrongquestionsource.id",
        nullable=False,
        index=True,
        ondelete="CASCADE",
    )
    # 归属保留两个弱引用：学校侧档案会因升班或删除而失效，
    # 登录账号是当前唯一稳定的锚点（终身身份见 AEG-068）。
    student_id: uuid.UUID | None = Field(
        default=None, foreign_key="student.id", nullable=True, ondelete="SET NULL"
    )
    student_user_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="user.id",
        nullable=True,
        index=True,
        ondelete="SET NULL",
    )
    student_name: str | None = Field(default=None, max_length=255)
    class_name_at_time: str | None = Field(default=None, max_length=100)
    submission_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="studentsubmission.id",
        nullable=True,
        ondelete="SET NULL",
    )
    annotation_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="submissionannotation.id",
        nullable=True,
        ondelete="SET NULL",
    )
    release_id: uuid.UUID | None = Field(
        default=None, foreign_key="scorerelease.id", nullable=True, ondelete="SET NULL"
    )
    release_version: int = Field(default=1, ge=1)
    question_label: str = Field(max_length=100)
    score: float | None = Field(default=None, ge=0)
    max_score: float | None = Field(default=None, ge=0)
    is_wrong: bool = Field(default=True, index=True)
    student_answer_text: str | None = Field(default=None, max_length=12000)
    missed_points: list[dict] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    teacher_comment: str | None = Field(default=None, max_length=2000)
    score_source: str | None = Field(default=None, max_length=30)
    image_storage_key: str | None = Field(default=None, max_length=1024)
    status: WrongQuestionEntryStatus = Field(
        default=WrongQuestionEntryStatus.ACTIVE,
        sa_column=Column(
            SAEnum(
                WrongQuestionEntryStatus,
                name="wrongquestionentrystatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    released_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
        index=True,
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class WrongbookEntryListItem(SQLModel):
    entry_id: uuid.UUID
    exam_id: uuid.UUID | None = None
    exam_title: str
    subject: str | None = None
    exam_date: date | None = None
    question_label: str
    score: float | None = None
    max_score: float | None = None
    is_wrong: bool = True
    knowledge_point_names: list[str] = Field(default_factory=list)
    has_image: bool = False
    released_at: datetime


class WrongbookEntriesPublic(SQLModel):
    data: list[WrongbookEntryListItem]
    count: int
    subjects: list[str] = Field(default_factory=list)
    knowledge_points: list[str] = Field(default_factory=list)


class WrongbookEntryDetail(SQLModel):
    entry_id: uuid.UUID
    exam_id: uuid.UUID | None = None
    exam_title: str
    subject: str | None = None
    grade_level: str | None = None
    exam_date: date | None = None
    class_name_at_time: str | None = None
    question_label: str
    question_text: str | None = None
    question_type: str | None = None
    score: float | None = None
    max_score: float | None = None
    is_wrong: bool = True
    standard_answer_text: str | None = None
    scoring_points: list[dict] = Field(default_factory=list)
    student_answer_text: str | None = None
    missed_points: list[dict] = Field(default_factory=list)
    teacher_comment: str | None = None
    knowledge_point_names: list[str] = Field(default_factory=list)
    has_image: bool = False
    released_at: datetime


# 平台级系统配置（仅 platform_superuser 可写）：模型与批改默认值，
# DB 无记录时回落到 env 设置（见 services/system_config.py）。
class SystemConfig(SQLModel, table=True):
    key: str = Field(primary_key=True, max_length=100)
    value: Any = Field(default=None, sa_column=Column(JSONB, nullable=False))
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class ProviderStatus(SQLModel):
    name: str
    configured: bool


class SystemConfigPublic(SQLModel):
    vision_provider: str
    vision_model: str
    grading_provider: str
    grading_model: str
    region_provider: str
    region_model: str
    recognition_provider: str
    recognition_model: str
    fallback_models: list[str]
    vision_fallback_models: list[str]
    reasoning_fallback_models: list[str]
    review_threshold: float
    max_concurrency: int
    providers: list[ProviderStatus]


class SystemConfigUpdate(SQLModel):
    vision_provider: str | None = Field(default=None, max_length=100)
    vision_model: str | None = Field(default=None, max_length=200)
    grading_provider: str | None = Field(default=None, max_length=100)
    grading_model: str | None = Field(default=None, max_length=200)
    region_provider: str | None = Field(default=None, max_length=100)
    region_model: str | None = Field(default=None, max_length=200)
    recognition_provider: str | None = Field(default=None, max_length=100)
    recognition_model: str | None = Field(default=None, max_length=200)
    fallback_models: list[str] | None = None
    vision_fallback_models: list[str] | None = None
    reasoning_fallback_models: list[str] | None = None
    review_threshold: float | None = Field(default=None, ge=0, le=1)
    max_concurrency: int | None = Field(default=None, ge=1, le=32)


# ---------- SaaS 合同、积分与模型调用计量 ----------


class BillingRateVersion(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    version: str = Field(unique=True, index=True, max_length=50)
    effective_at: datetime = Field(sa_type=DateTime(timezone=True))  # type: ignore
    input_microcredits_per_million: int = Field(
        sa_column=Column(BigInteger, nullable=False)
    )
    output_microcredits_per_million: int = Field(
        sa_column=Column(BigInteger, nullable=False)
    )
    image_microcredits_per_million: int = Field(
        sa_column=Column(BigInteger, nullable=False)
    )
    internal_input_micrormb_per_million: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    internal_output_micrormb_per_million: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    internal_image_micrormb_per_million: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore


class OrganizationSubscription(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    org_id: uuid.UUID = Field(foreign_key="organization.id", nullable=False, index=True)
    contract_no: str = Field(unique=True, index=True, max_length=100)
    plan_code: str = Field(max_length=50)
    status: SubscriptionStatus = Field(
        default=SubscriptionStatus.DRAFT,
        sa_column=Column(
            SAEnum(
                SubscriptionStatus,
                name="subscriptionstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    starts_at: datetime = Field(sa_type=DateTime(timezone=True))  # type: ignore
    ends_at: datetime = Field(sa_type=DateTime(timezone=True))  # type: ignore
    rate_version_id: uuid.UUID = Field(
        foreign_key="billingrateversion.id", nullable=False
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore
    updated_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore


class PlanVersion(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    code: str = Field(index=True, min_length=1, max_length=50)
    version: int = Field(ge=1)
    display_name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    annual_price_cents: int = Field(ge=0, sa_column=Column(BigInteger, nullable=False))
    included_answers: int = Field(ge=0)
    validity_days: int = Field(default=365, ge=1, le=3660)
    published: bool = False
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore

    __table_args__ = (UniqueConstraint("code", "version", name="uq_plan_version"),)


class AddonSku(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    code: str = Field(unique=True, index=True, min_length=1, max_length=50)
    display_name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    answer_quota: int = Field(gt=0)
    price_cents: int = Field(gt=0, sa_column=Column(BigInteger, nullable=False))
    validity_days: int = Field(default=365, ge=1, le=3660)
    published: bool = False
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore


class CommerceOrder(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    order_no: str = Field(unique=True, index=True, max_length=64)
    org_id: uuid.UUID = Field(foreign_key="organization.id", nullable=False, index=True)
    status: CommerceOrderStatus = Field(
        default=CommerceOrderStatus.PENDING_PAYMENT,
        sa_column=Column(
            SAEnum(
                CommerceOrderStatus,
                name="commerceorderstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    amount_cents: int = Field(ge=0, sa_column=Column(BigInteger, nullable=False))
    currency: str = Field(default="CNY", max_length=3)
    idempotency_key: str = Field(unique=True, index=True, max_length=128)
    created_by_id: uuid.UUID = Field(foreign_key="user.id", nullable=False)
    paid_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    fulfilled_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True), index=True
    )  # type: ignore
    updated_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore


class OrderItem(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    order_id: uuid.UUID = Field(
        foreign_key="commerceorder.id", nullable=False, index=True, ondelete="CASCADE"
    )
    item_type: str = Field(max_length=20)
    sku_code: str = Field(max_length=50)
    display_name: str = Field(max_length=100)
    quantity: int = Field(default=1, ge=1)
    unit_price_cents: int = Field(ge=0, sa_column=Column(BigInteger, nullable=False))
    answer_quota: int = Field(default=0, ge=0)
    validity_days: int = Field(default=365, ge=1)
    metadata_json: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )


class PaymentAttempt(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    order_id: uuid.UUID = Field(
        foreign_key="commerceorder.id", nullable=False, index=True
    )
    method: PaymentMethod = Field(
        sa_column=Column(
            SAEnum(
                PaymentMethod,
                name="paymentmethod",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        )
    )
    status: PaymentStatus = Field(
        default=PaymentStatus.PENDING,
        sa_column=Column(
            SAEnum(
                PaymentStatus,
                name="paymentstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    provider_transaction_id: str | None = Field(
        default=None, unique=True, max_length=128
    )
    request_id: str | None = Field(default=None, max_length=128)
    code_url: str | None = Field(default=None, max_length=1000)
    amount_cents: int = Field(ge=0, sa_column=Column(BigInteger, nullable=False))
    raw_response: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True), index=True
    )  # type: ignore
    succeeded_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore


class PaymentWebhookEvent(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    event_id: str = Field(unique=True, index=True, max_length=128)
    provider: str = Field(default="wechat_pay", max_length=30)
    event_type: str = Field(max_length=100)
    signature_verified: bool = False
    payload: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    processed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    processing_error: str | None = Field(default=None, max_length=1000)
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True), index=True
    )  # type: ignore


class InvoiceApplication(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    order_id: uuid.UUID = Field(
        foreign_key="commerceorder.id", nullable=False, index=True, unique=True
    )
    org_id: uuid.UUID = Field(foreign_key="organization.id", nullable=False, index=True)
    title: str = Field(max_length=200)
    tax_number: str = Field(max_length=50)
    email: str = Field(max_length=255)
    amount_cents: int = Field(gt=0, sa_column=Column(BigInteger, nullable=False))
    status: InvoiceStatus = Field(
        default=InvoiceStatus.SUBMITTED,
        sa_column=Column(
            SAEnum(
                InvoiceStatus,
                name="invoicestatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    invoice_no: str | None = Field(default=None, max_length=100)
    reject_reason: str | None = Field(default=None, max_length=500)
    created_by_id: uuid.UUID = Field(foreign_key="user.id", nullable=False)
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True), index=True
    )  # type: ignore
    updated_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore


class RefundRequest(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    order_id: uuid.UUID = Field(
        foreign_key="commerceorder.id", nullable=False, index=True, unique=True
    )
    org_id: uuid.UUID = Field(foreign_key="organization.id", nullable=False, index=True)
    amount_cents: int = Field(gt=0, sa_column=Column(BigInteger, nullable=False))
    reason: str = Field(min_length=1, max_length=500)
    status: RefundStatus = Field(
        default=RefundStatus.REQUESTED,
        sa_column=Column(
            SAEnum(
                RefundStatus,
                name="refundstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    requested_by_id: uuid.UUID = Field(foreign_key="user.id", nullable=False)
    reviewed_by_id: uuid.UUID | None = Field(default=None, foreign_key="user.id")
    review_note: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True), index=True
    )  # type: ignore
    updated_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore


class OutboxEvent(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    event_type: str = Field(index=True, max_length=100)
    aggregate_type: str = Field(max_length=50)
    aggregate_id: str = Field(max_length=100)
    idempotency_key: str = Field(unique=True, index=True, max_length=200)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    attempts: int = Field(default=0, ge=0)
    available_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True), index=True
    )  # type: ignore
    processed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    last_error: str | None = Field(default=None, max_length=1000)
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore


class CreditGrant(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    org_id: uuid.UUID = Field(foreign_key="organization.id", nullable=False, index=True)
    subscription_id: uuid.UUID | None = Field(
        default=None, foreign_key="organizationsubscription.id", index=True
    )
    source: CreditGrantSource = Field(
        sa_column=Column(
            SAEnum(
                CreditGrantSource,
                name="creditgrantsource",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        )
    )
    total_microcredits: int = Field(sa_column=Column(BigInteger, nullable=False))
    reserved_microcredits: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    consumed_microcredits: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    expires_at: datetime = Field(sa_type=DateTime(timezone=True))  # type: ignore
    note: str | None = Field(default=None, max_length=500)
    created_by_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore


class CreditReservation(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    org_id: uuid.UUID = Field(foreign_key="organization.id", nullable=False, index=True)
    grading_run_id: uuid.UUID | None = Field(
        default=None, foreign_key="gradingrun.id", index=True
    )
    task_type: str = Field(max_length=50)
    resource_id: str = Field(max_length=100)
    idempotency_key: str = Field(unique=True, index=True, max_length=255)
    estimated_microcredits: int = Field(sa_column=Column(BigInteger, nullable=False))
    authorized_microcredits: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    settled_microcredits: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    status: CreditReservationStatus = Field(
        sa_column=Column(
            SAEnum(
                CreditReservationStatus,
                name="creditreservationstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        )
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore
    settled_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore


class CreditReservationAllocation(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("reservation_id", "grant_id", name="uq_reservation_grant"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    reservation_id: uuid.UUID = Field(
        foreign_key="creditreservation.id",
        nullable=False,
        index=True,
        ondelete="CASCADE",
    )
    grant_id: uuid.UUID = Field(
        foreign_key="creditgrant.id", nullable=False, index=True
    )
    reserved_microcredits: int = Field(sa_column=Column(BigInteger, nullable=False))
    consumed_microcredits: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )


class CreditLedgerEntry(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    org_id: uuid.UUID = Field(foreign_key="organization.id", nullable=False, index=True)
    grant_id: uuid.UUID | None = Field(
        default=None, foreign_key="creditgrant.id", index=True
    )
    reservation_id: uuid.UUID | None = Field(
        default=None, foreign_key="creditreservation.id", index=True
    )
    entry_type: str = Field(max_length=30, index=True)
    amount_microcredits: int = Field(sa_column=Column(BigInteger, nullable=False))
    balance_after_microcredits: int = Field(
        sa_column=Column(BigInteger, nullable=False)
    )
    actor_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    note: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True), index=True
    )  # type: ignore


class AnswerQuotaGrant(SQLModel, table=True):
    """Customer-facing answer-sheet quota purchased by one school."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    org_id: uuid.UUID = Field(foreign_key="organization.id", nullable=False, index=True)
    subscription_id: uuid.UUID | None = Field(
        default=None, foreign_key="organizationsubscription.id", index=True
    )
    order_id: uuid.UUID | None = Field(
        default=None, foreign_key="commerceorder.id", index=True, ondelete="RESTRICT"
    )
    source: CreditGrantSource = Field(
        sa_column=Column(
            SAEnum(
                CreditGrantSource,
                name="creditgrantsource",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        )
    )
    total_answers: int = Field(ge=1)
    reserved_answers: int = Field(default=0, ge=0)
    consumed_answers: int = Field(default=0, ge=0)
    expires_at: datetime = Field(sa_type=DateTime(timezone=True))  # type: ignore
    note: str | None = Field(default=None, max_length=500)
    created_by_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore


class AnswerQuotaReservation(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    org_id: uuid.UUID = Field(foreign_key="organization.id", nullable=False, index=True)
    exam_id: uuid.UUID = Field(foreign_key="exam.id", nullable=False, index=True)
    grading_run_id: uuid.UUID = Field(
        foreign_key="gradingrun.id", nullable=False, index=True
    )
    idempotency_key: str = Field(unique=True, index=True, max_length=255)
    reserved_answers: int = Field(ge=0)
    settled_answers: int = Field(default=0, ge=0)
    status: CreditReservationStatus = Field(
        sa_column=Column(
            SAEnum(
                CreditReservationStatus,
                name="creditreservationstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        )
    )
    identities: list[str] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore
    settled_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore


class AnswerQuotaAllocation(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "reservation_id", "grant_id", name="uq_answer_quota_reservation_grant"
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    reservation_id: uuid.UUID = Field(
        foreign_key="answerquotareservation.id",
        nullable=False,
        index=True,
        ondelete="CASCADE",
    )
    grant_id: uuid.UUID = Field(
        foreign_key="answerquotagrant.id", nullable=False, index=True
    )
    reserved_answers: int = Field(ge=0)
    consumed_answers: int = Field(default=0, ge=0)


class BillableAnswerSheet(SQLModel, table=True):
    """Exactly-once commercial charge for one student in one exam."""

    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "exam_id",
            "billing_identity",
            name="uq_billable_answer_sheet_identity",
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    org_id: uuid.UUID = Field(foreign_key="organization.id", nullable=False, index=True)
    exam_id: uuid.UUID = Field(foreign_key="exam.id", nullable=False, index=True)
    grading_run_id: uuid.UUID = Field(
        foreign_key="gradingrun.id", nullable=False, index=True
    )
    reservation_id: uuid.UUID | None = Field(
        default=None, foreign_key="answerquotareservation.id", index=True
    )
    billing_identity: str = Field(max_length=255)
    student_name: str | None = Field(default=None, max_length=100)
    class_name: str | None = Field(default=None, max_length=100)
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True), index=True
    )  # type: ignore


class ProviderChannel(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    code: str = Field(unique=True, index=True, min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    kind: ProviderChannelKind = Field(
        sa_column=Column(
            SAEnum(
                ProviderChannelKind,
                name="providerchannelkind",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        )
    )
    protocol: ProviderProtocol = Field(
        sa_column=Column(
            SAEnum(
                ProviderProtocol,
                name="providerprotocol",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        )
    )
    base_url: str = Field(max_length=500)
    status: ProviderChannelStatus = Field(
        default=ProviderChannelStatus.DRAFT,
        sa_column=Column(
            SAEnum(
                ProviderChannelStatus,
                name="providerchannelstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    # `enabled` is retained during the rollout for old clients and migrations.
    enabled: bool = False
    risk_acknowledged: bool = False
    priority: int = Field(default=100, ge=0, le=10000)
    weight: int = Field(default=100, ge=1, le=10000)
    max_concurrency: int = Field(default=8, ge=1, le=128)
    timeout_seconds: int = Field(default=180, ge=5, le=600)
    created_by_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore
    updated_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore


class ProviderCredential(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    channel_id: uuid.UUID = Field(
        foreign_key="providerchannel.id", unique=True, index=True, ondelete="CASCADE"
    )
    ciphertext: str
    nonce: str = Field(max_length=100)
    key_version: int = Field(default=1, ge=1)
    fingerprint: str = Field(max_length=32)
    last_four: str = Field(max_length=4)
    billing_ciphertext: str | None = None
    billing_nonce: str | None = Field(default=None, max_length=100)
    billing_key_version: int = Field(default=1, ge=1)
    billing_fingerprint: str | None = Field(default=None, max_length=32)
    billing_last_four: str | None = Field(default=None, max_length=4)
    billing_user_id: int | None = Field(default=None, ge=1)
    rotated_by_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    rotated_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore


class ProviderModelMapping(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "channel_id", "canonical_model", name="uq_provider_channel_model"
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    channel_id: uuid.UUID = Field(
        foreign_key="providerchannel.id", index=True, ondelete="CASCADE"
    )
    canonical_model: str = Field(index=True, max_length=200)
    upstream_model: str = Field(max_length=200)
    supports_vision: bool = True
    supports_structured_output: bool = True
    usage_metering_verified: bool = False
    usage_verified_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )  # type: ignore
    enabled: bool = True
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore
    updated_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore


class StandardModel(SQLModel, table=True):
    """Provider-neutral model identity used by routes and public offerings."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    code: str = Field(unique=True, index=True, min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=200)
    supports_vision: bool = True
    supports_structured_output: bool = True
    requires_usage: bool = True
    production_ready: bool = False
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore
    updated_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore


class PlatformModelOffering(SQLModel, table=True):
    """学校可选择的公开模型；真实渠道和上游模型仅平台侧可见。"""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    code: str = Field(unique=True, index=True, min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=300)
    scope: SchoolModelScope = Field(
        sa_column=Column(
            SAEnum(
                SchoolModelScope,
                name="schoolmodelscope",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        )
    )
    provider_code: str = Field(max_length=100)
    canonical_model: str = Field(index=True, max_length=200)
    standard_model_id: uuid.UUID | None = Field(
        default=None, foreign_key="standardmodel.id", index=True, ondelete="RESTRICT"
    )
    published: bool = False
    school_selectable: bool = True
    sort_order: int = Field(default=100, ge=0, le=10000)
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore
    updated_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore


class OrganizationModelSelection(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("org_id", "scope", name="uq_org_model_selection_scope"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    org_id: uuid.UUID = Field(
        foreign_key="organization.id", index=True, ondelete="CASCADE"
    )
    scope: SchoolModelScope = Field(
        sa_column=Column(
            SAEnum(
                SchoolModelScope,
                name="schoolmodelscope",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        )
    )
    offering_id: uuid.UUID = Field(
        foreign_key="platformmodeloffering.id", index=True, ondelete="CASCADE"
    )
    updated_by_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore


class ModelRoutePolicy(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("purpose", "canonical_model", name="uq_route_purpose_model"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    purpose: str = Field(index=True, max_length=50)
    canonical_model: str = Field(index=True, max_length=200)
    enabled: bool = True
    max_attempts: int = Field(default=3, ge=1, le=10)
    routing_mode: str = Field(default="balanced", max_length=20)
    sticky_scope: str = Field(default="business_revision", max_length=50)
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore
    updated_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore


class FunctionModelAssignment(SQLModel, table=True):
    """平台为业务功能指定的默认标准模型；可用模型由已发布路由决定。"""

    purpose: str = Field(primary_key=True, max_length=50)
    default_canonical_model: str = Field(index=True, max_length=200)
    updated_by_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore


class ModelRouteTarget(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("policy_id", "mapping_id", name="uq_route_policy_mapping"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    policy_id: uuid.UUID = Field(
        foreign_key="modelroutepolicy.id", index=True, ondelete="CASCADE"
    )
    mapping_id: uuid.UUID = Field(
        foreign_key="providermodelmapping.id", index=True, ondelete="CASCADE"
    )
    priority: int = Field(default=100, ge=0, le=10000)
    weight: int = Field(default=100, ge=1, le=10000)
    enabled: bool = True


class ModelRouteVersion(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("policy_id", "version", name="uq_route_policy_version"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    policy_id: uuid.UUID = Field(
        foreign_key="modelroutepolicy.id", index=True, ondelete="CASCADE"
    )
    version: int = Field(ge=1)
    status: ModelRouteVersionStatus = Field(
        default=ModelRouteVersionStatus.DRAFT,
        sa_column=Column(
            SAEnum(
                ModelRouteVersionStatus,
                name="modelrouteversionstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    max_attempts: int = Field(default=3, ge=1, le=10)
    routing_mode: str = Field(default="balanced", max_length=20)
    sticky_scope: str = Field(default="business_revision", max_length=50)
    created_by_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    published_by_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore
    published_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore


class ModelRouteVersionTarget(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "route_version_id", "mapping_id", name="uq_route_version_mapping"
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    route_version_id: uuid.UUID = Field(
        foreign_key="modelrouteversion.id", index=True, ondelete="CASCADE"
    )
    mapping_id: uuid.UUID = Field(
        foreign_key="providermodelmapping.id", index=True, ondelete="RESTRICT"
    )
    channel_id: uuid.UUID = Field(
        foreign_key="providerchannel.id", index=True, ondelete="RESTRICT"
    )
    channel_code: str = Field(max_length=100)
    canonical_model: str = Field(index=True, max_length=200)
    upstream_model: str = Field(max_length=200)
    protocol: ProviderProtocol = Field(
        sa_column=Column(
            SAEnum(
                ProviderProtocol,
                name="providerprotocol",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        )
    )
    base_url: str = Field(max_length=500)
    internal_rate_version_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="providerinternalrateversion.id",
        ondelete="RESTRICT",
    )
    cost_micrormb_per_million: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    tier: int = Field(default=1, ge=1, le=10)
    weight: int = Field(default=100, ge=1, le=10000)
    enabled: bool = True


class ProviderHealthState(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "channel_id", "canonical_model", name="uq_health_channel_model"
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    channel_id: uuid.UUID = Field(
        foreign_key="providerchannel.id", index=True, ondelete="CASCADE"
    )
    canonical_model: str = Field(index=True, max_length=200)
    status: ProviderHealthStatus = Field(
        default=ProviderHealthStatus.UNKNOWN,
        sa_column=Column(
            SAEnum(
                ProviderHealthStatus,
                name="providerhealthstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    consecutive_failures: int = Field(default=0, ge=0)
    consecutive_missing_usage: int = Field(default=0, ge=0)
    success_count: int = Field(default=0, ge=0)
    failure_count: int = Field(default=0, ge=0)
    latency_ewma_ms: float | None = Field(default=None, ge=0)
    circuit_open_until: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )  # type: ignore
    last_http_status: int | None = Field(default=None, ge=100, le=599)
    last_error_code: str | None = Field(default=None, max_length=100)
    last_checked_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )  # type: ignore
    updated_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore


class ProviderInternalRateVersion(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "channel_id", "canonical_model", "version", name="uq_provider_rate_version"
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    channel_id: uuid.UUID = Field(
        foreign_key="providerchannel.id", index=True, ondelete="CASCADE"
    )
    canonical_model: str = Field(index=True, max_length=200)
    version: str = Field(max_length=50)
    effective_at: datetime = Field(sa_type=DateTime(timezone=True))  # type: ignore
    input_micrormb_per_million: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    output_micrormb_per_million: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    image_micrormb_per_million: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    cached_input_micrormb_per_million: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore


class OfferingRateVersion(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("offering_id", "version", name="uq_offering_rate_version"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    offering_id: uuid.UUID = Field(
        foreign_key="platformmodeloffering.id", index=True, ondelete="CASCADE"
    )
    version: str = Field(max_length=50)
    effective_at: datetime = Field(sa_type=DateTime(timezone=True))  # type: ignore
    input_microcredits_per_million: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    output_microcredits_per_million: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    image_microcredits_per_million: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    target_margin_bps: int = Field(default=4000, ge=0, le=9900)
    minimum_margin_bps: int = Field(default=2500, ge=0, le=9900)
    created_by_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore


class OrganizationUsagePolicy(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    org_id: uuid.UUID = Field(
        foreign_key="organization.id", unique=True, index=True, ondelete="CASCADE"
    )
    risk_state: OrganizationRiskState = Field(
        default=OrganizationRiskState.NORMAL,
        sa_column=Column(
            SAEnum(
                OrganizationRiskState,
                name="organizationriskstate",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    calls_per_minute: int = Field(default=120, ge=1, le=100000)
    max_running_jobs: int = Field(default=8, ge=1, le=1000)
    max_model_concurrency: int = Field(default=8, ge=1, le=128)
    max_job_microcredits: int = Field(
        default=100_000_000, sa_column=Column(BigInteger, nullable=False)
    )
    daily_microcredit_cap: int = Field(
        default=1_000_000_000, sa_column=Column(BigInteger, nullable=False)
    )
    monthly_microcredit_cap: int = Field(
        default=20_000_000_000, sa_column=Column(BigInteger, nullable=False)
    )
    reason: str | None = Field(default=None, max_length=500)
    updated_by_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore


class OrganizationJobLease(SQLModel, table=True):
    """Cross-worker lease for enforcing a school's running-job limit."""

    __table_args__ = (
        UniqueConstraint("task_type", "resource_id", name="uq_org_job_resource"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    org_id: uuid.UUID = Field(
        foreign_key="organization.id", nullable=False, index=True, ondelete="CASCADE"
    )
    task_type: str = Field(max_length=50)
    resource_id: str = Field(max_length=100)
    lease_token: uuid.UUID = Field(default_factory=uuid.uuid4, unique=True, index=True)
    acquired_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore
    heartbeat_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore
    expires_at: datetime = Field(sa_type=DateTime(timezone=True), index=True)  # type: ignore


class ProviderReconciliationBatch(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    channel_id: uuid.UUID = Field(
        foreign_key="providerchannel.id", index=True, ondelete="CASCADE"
    )
    source: str = Field(max_length=30)
    period_start: datetime = Field(sa_type=DateTime(timezone=True))  # type: ignore
    period_end: datetime = Field(sa_type=DateTime(timezone=True))  # type: ignore
    imported_by_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    row_count: int = Field(default=0, ge=0)
    fetched_count: int = Field(default=0, ge=0)
    ignored_count: int = Field(default=0, ge=0)
    matched_count: int = Field(default=0, ge=0)
    mismatch_count: int = Field(default=0, ge=0)
    upstream_system_name: str | None = Field(default=None, max_length=100)
    upstream_version: str | None = Field(default=None, max_length=100)
    upstream_total_granted_quota: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    upstream_total_used_quota: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    upstream_total_available_quota: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    upstream_total_used_micrormb: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    quota_per_unit: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    usd_exchange_rate: float = Field(default=0, ge=0)
    unlimited_quota: bool = False
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore


class ProviderReconciliationItem(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    batch_id: uuid.UUID = Field(
        foreign_key="providerreconciliationbatch.id", index=True, ondelete="CASCADE"
    )
    usage_event_id: uuid.UUID | None = Field(
        default=None, foreign_key="modelusageevent.id", index=True, ondelete="SET NULL"
    )
    upstream_request_id: str | None = Field(default=None, index=True, max_length=255)
    upstream_input_tokens: int = Field(default=0, ge=0)
    upstream_output_tokens: int = Field(default=0, ge=0)
    upstream_cost_micrormb: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    status: UsageReconciliationStatus = Field(
        default=UsageReconciliationStatus.PENDING,
        sa_column=Column(
            SAEnum(
                UsageReconciliationStatus,
                name="usagereconciliationstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    details: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )


class ProviderAuditLog(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    channel_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="providerchannel.id",
        index=True,
        ondelete="SET NULL",
    )
    actor_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    action: str = Field(index=True, max_length=50)
    details: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True), index=True
    )  # type: ignore


class ModelUsageEvent(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    org_id: uuid.UUID = Field(foreign_key="organization.id", nullable=False, index=True)
    exam_id: uuid.UUID | None = Field(
        default=None, foreign_key="exam.id", index=True, ondelete="SET NULL"
    )
    grading_run_id: uuid.UUID | None = Field(
        default=None, foreign_key="gradingrun.id", index=True, ondelete="SET NULL"
    )
    reservation_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="creditreservation.id",
        index=True,
        ondelete="SET NULL",
    )
    resource_id: str = Field(max_length=100)
    workflow_purpose: str = Field(max_length=50, index=True)
    requested_provider: str = Field(max_length=100)
    requested_model: str = Field(max_length=200)
    actual_provider: str | None = Field(default=None, max_length=100)
    actual_model: str | None = Field(default=None, max_length=200)
    channel_id: uuid.UUID | None = Field(
        default=None, foreign_key="providerchannel.id", index=True, ondelete="SET NULL"
    )
    route_policy_id: uuid.UUID | None = Field(
        default=None, foreign_key="modelroutepolicy.id", index=True, ondelete="SET NULL"
    )
    route_version_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="modelrouteversion.id",
        index=True,
        ondelete="SET NULL",
    )
    attempt_number: int = Field(default=1, ge=1)
    attempt_kind: str = Field(default="primary", max_length=30)
    upstream_request_id: str | None = Field(default=None, max_length=255)
    http_status: int | None = Field(default=None, ge=100, le=599)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    image_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    status: ModelUsageStatus = Field(
        sa_column=Column(
            SAEnum(
                ModelUsageStatus,
                name="modelusagestatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        )
    )
    fallback_used: bool = False
    error_code: str | None = Field(default=None, max_length=100)
    customer_microcredits: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    internal_cost_micrormb: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False)
    )
    upstream_cost_micrormb: int | None = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    upstream_billed_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )  # type: ignore
    billing_key: str = Field(unique=True, index=True, max_length=255)
    rate_version_id: uuid.UUID | None = Field(
        default=None, foreign_key="billingrateversion.id"
    )
    internal_rate_version_id: uuid.UUID | None = Field(
        default=None, foreign_key="providerinternalrateversion.id"
    )
    offering_rate_version_id: uuid.UUID | None = Field(
        default=None, foreign_key="offeringrateversion.id"
    )
    reconciliation_status: UsageReconciliationStatus = Field(
        default=UsageReconciliationStatus.PENDING,
        sa_column=Column(
            SAEnum(
                UsageReconciliationStatus,
                name="usagereconciliationstatus",
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
        ),
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True), index=True
    )  # type: ignore


class BillingRateVersionCreate(SQLModel):
    version: str = Field(min_length=1, max_length=50)
    effective_at: datetime
    input_credits_per_million: float = Field(ge=0)
    output_credits_per_million: float = Field(ge=0)
    image_credits_per_million: float = Field(ge=0)
    internal_input_rmb_per_million: float = Field(default=0, ge=0)
    internal_output_rmb_per_million: float = Field(default=0, ge=0)
    internal_image_rmb_per_million: float = Field(default=0, ge=0)


class SubscriptionUpsert(SQLModel):
    contract_no: str = Field(min_length=1, max_length=100)
    plan_code: str = Field(min_length=1, max_length=50)
    status: SubscriptionStatus
    starts_at: datetime
    ends_at: datetime
    rate_version_id: uuid.UUID


class CreditGrantCreate(SQLModel):
    credits: float = Field(gt=0)
    source: CreditGrantSource = CreditGrantSource.TOP_UP
    note: str | None = Field(default=None, max_length=500)


class AnswerQuotaGrantCreate(SQLModel):
    answers: int = Field(gt=0, le=10_000_000)
    source: CreditGrantSource = CreditGrantSource.TOP_UP
    note: str | None = Field(default=None, max_length=500)


class BillingSubscriptionPublic(SQLModel):
    id: uuid.UUID
    contract_no: str
    plan_code: str
    status: SubscriptionStatus
    starts_at: datetime
    ends_at: datetime
    rate_version_id: uuid.UUID


class BillingSummaryPublic(SQLModel):
    entitlement: Literal["available", "insufficient", "expired", "not_configured"]
    subscription: BillingSubscriptionPublic | None = None
    available_credits: float = 0
    reserved_credits: float = 0
    consumed_credits: float = 0
    input_tokens: int = 0
    output_tokens: int = 0
    image_tokens: int = 0
    total_tokens: int = 0
    available_answers: int = 0
    reserved_answers: int = 0
    consumed_answers: int = 0


class CreditLedgerItemPublic(SQLModel):
    id: uuid.UUID
    entry_type: str
    amount_credits: float
    balance_after_credits: float
    note: str | None = None
    created_at: datetime


class CreditLedgerPublic(SQLModel):
    data: list[CreditLedgerItemPublic]
    count: int


class BillingEntitlementPublic(SQLModel):
    status: Literal["available", "insufficient", "expired", "not_configured"]


class CatalogItemPublic(SQLModel):
    item_type: Literal["plan", "addon"]
    code: str
    display_name: str
    description: str | None = None
    price_cents: int
    answer_quota: int
    validity_days: int


class CommerceCatalogPublic(SQLModel):
    data: list[CatalogItemPublic]


class CommerceOrderLineCreate(SQLModel):
    item_type: Literal["plan", "addon"]
    code: str = Field(min_length=1, max_length=50)
    quantity: int = Field(default=1, ge=1, le=100)


class CommerceOrderCreate(SQLModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    items: list[CommerceOrderLineCreate] = Field(min_length=1, max_length=20)


class CommerceOrderItemPublic(SQLModel):
    item_type: str
    sku_code: str
    display_name: str
    quantity: int
    unit_price_cents: int
    answer_quota: int
    validity_days: int


class CommerceOrderPublic(SQLModel):
    id: uuid.UUID
    order_no: str
    org_id: uuid.UUID
    status: CommerceOrderStatus
    amount_cents: int
    currency: str
    items: list[CommerceOrderItemPublic] = Field(default_factory=list)
    created_at: datetime
    paid_at: datetime | None = None
    fulfilled_at: datetime | None = None


class AdminCommerceOrderPublic(CommerceOrderPublic):
    org_name: str


class BankTransferConfirm(SQLModel):
    transaction_reference: str = Field(min_length=1, max_length=128)
    paid_at: datetime | None = None


class InvoiceApplicationCreate(SQLModel):
    order_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    tax_number: str = Field(min_length=1, max_length=50)
    email: EmailStr


class PlanVersionCreate(SQLModel):
    code: str = Field(regex=r"^[a-z][a-z0-9_-]*$", min_length=1, max_length=50)
    version: int = Field(ge=1)
    display_name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    annual_price_cents: int = Field(ge=0)
    included_answers: int = Field(ge=0)
    validity_days: int = Field(default=365, ge=1, le=3660)
    published: bool = False


class CatalogPublicationUpdate(SQLModel):
    published: bool


class AddonSkuCreate(SQLModel):
    code: str = Field(regex=r"^[a-z][a-z0-9_-]*$", min_length=1, max_length=50)
    display_name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    answer_quota: int = Field(gt=0)
    price_cents: int = Field(gt=0)
    validity_days: int = Field(default=365, ge=1, le=3660)
    published: bool = False


class InvoiceReview(SQLModel):
    status: Literal["approved", "issued", "rejected"]
    invoice_no: str | None = Field(default=None, max_length=100)
    reject_reason: str | None = Field(default=None, max_length=500)


class RefundRequestCreate(SQLModel):
    order_id: uuid.UUID
    amount_cents: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=500)


class RefundRequestPublic(SQLModel):
    id: uuid.UUID
    order_id: uuid.UUID
    org_id: uuid.UUID
    amount_cents: int
    reason: str
    status: RefundStatus
    review_note: str | None = None
    created_at: datetime


class RefundReview(SQLModel):
    status: Literal["approved", "rejected", "processing", "succeeded", "failed"]
    review_note: str | None = Field(default=None, max_length=500)


class InvoiceApplicationPublic(SQLModel):
    id: uuid.UUID
    order_id: uuid.UUID
    org_id: uuid.UUID
    title: str
    tax_number: str
    email: str
    amount_cents: int
    status: InvoiceStatus
    invoice_no: str | None = None
    reject_reason: str | None = None
    created_at: datetime


class ExamWorkflowStepPublic(SQLModel):
    code: str
    label: str
    status: Literal["pending", "active", "completed", "blocked"]
    count: int = 0


class ExamWorkflowSummaryPublic(SQLModel):
    exam_id: uuid.UUID
    next_action: str
    next_label: str
    next_path: str
    message: str
    steps: list[ExamWorkflowStepPublic]


class BillingUsageItemPublic(SQLModel):
    id: uuid.UUID
    exam_id: uuid.UUID | None = None
    grading_run_id: uuid.UUID | None = None
    workflow_purpose: str
    input_tokens: int
    output_tokens: int
    image_tokens: int
    total_tokens: int
    credits: float
    status: ModelUsageStatus
    created_at: datetime


class BillingUsagePublic(SQLModel):
    data: list[BillingUsageItemPublic]
    count: int


class PlatformModelUsageSummaryPublic(SQLModel):
    calls: int = 0
    succeeded_calls: int = 0
    failed_calls: int = 0
    missing_usage_calls: int = 0
    success_rate: float = 0
    input_tokens: int = 0
    output_tokens: int = 0
    image_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    customer_credits: float = 0
    internal_cost_rmb: float = 0
    upstream_cost_rmb: float = 0
    reconciled_internal_cost_rmb: float = 0
    cost_variance_rmb: float = 0
    reconciled_calls: int = 0
    unreconciled_calls: int = 0
    average_latency_ms: float = 0
    fallback_calls: int = 0


class PlatformModelUsageBreakdownItem(SQLModel):
    key: str
    label: str
    org_id: uuid.UUID | None = None
    calls: int = 0
    failed_calls: int = 0
    total_tokens: int = 0
    customer_credits: float = 0
    internal_cost_rmb: float = 0
    upstream_cost_rmb: float = 0
    reconciled_calls: int = 0
    average_latency_ms: float = 0


class PlatformModelUsageOverviewPublic(SQLModel):
    days: int
    since: datetime
    summary: PlatformModelUsageSummaryPublic
    organizations: list[PlatformModelUsageBreakdownItem]
    purposes: list[PlatformModelUsageBreakdownItem]
    models: list[PlatformModelUsageBreakdownItem]
    daily: list[PlatformModelUsageBreakdownItem]


class PlatformModelUsageEventPublic(SQLModel):
    id: uuid.UUID
    org_id: uuid.UUID
    org_name: str
    exam_id: uuid.UUID | None = None
    grading_run_id: uuid.UUID | None = None
    resource_id: str
    workflow_purpose: str
    purpose_label: str
    requested_provider: str
    requested_model: str
    actual_provider: str | None = None
    actual_model: str | None = None
    channel_id: uuid.UUID | None = None
    channel_name: str | None = None
    attempt_number: int
    attempt_kind: str
    fallback_used: bool
    http_status: int | None = None
    error_code: str | None = None
    input_tokens: int
    output_tokens: int
    image_tokens: int
    cached_input_tokens: int
    reasoning_tokens: int
    total_tokens: int
    latency_ms: int
    status: ModelUsageStatus
    customer_credits: float
    internal_cost_rmb: float
    upstream_cost_rmb: float | None = None
    cost_variance_rmb: float | None = None
    reconciliation_status: UsageReconciliationStatus
    created_at: datetime


class PlatformModelUsageEventsPublic(SQLModel):
    data: list[PlatformModelUsageEventPublic]
    count: int


class ProviderChannelCreate(SQLModel):
    code: str = Field(regex=r"^[a-z][a-z0-9_-]*$", min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    kind: ProviderChannelKind
    protocol: ProviderProtocol = ProviderProtocol.OPENAI_CHAT
    base_url: str = Field(min_length=8, max_length=500)
    api_key: str | None = Field(default=None, min_length=1, max_length=4000)
    status: ProviderChannelStatus | None = None
    enabled: bool = False
    risk_acknowledged: bool = False
    priority: int = Field(default=100, ge=0, le=10000)
    weight: int = Field(default=100, ge=1, le=10000)
    max_concurrency: int = Field(default=8, ge=1, le=128)
    timeout_seconds: int = Field(default=180, ge=5, le=600)


class ProviderChannelUpdate(SQLModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: ProviderChannelKind | None = None
    protocol: ProviderProtocol | None = None
    base_url: str | None = Field(default=None, min_length=8, max_length=500)
    status: ProviderChannelStatus | None = None
    enabled: bool | None = None
    risk_acknowledged: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=10000)
    weight: int | None = Field(default=None, ge=1, le=10000)
    max_concurrency: int | None = Field(default=None, ge=1, le=128)
    timeout_seconds: int | None = Field(default=None, ge=5, le=600)


class ProviderCredentialUpdate(SQLModel):
    api_key: str = Field(min_length=1, max_length=4000)


class ProviderBillingCredentialUpdate(SQLModel):
    access_token: str = Field(min_length=1, max_length=4000)
    user_id: int | None = Field(default=None, ge=1)


class ProviderChannelPublic(SQLModel):
    id: uuid.UUID
    code: str
    display_name: str
    kind: ProviderChannelKind
    protocol: ProviderProtocol
    base_url: str
    status: ProviderChannelStatus
    enabled: bool
    risk_acknowledged: bool
    priority: int
    weight: int
    max_concurrency: int
    timeout_seconds: int
    credential_configured: bool = False
    credential_fingerprint: str | None = None
    credential_last_four: str | None = None
    billing_credential_configured: bool = False
    billing_credential_last_four: str | None = None
    billing_user_id: int | None = None
    health_status: ProviderHealthStatus = ProviderHealthStatus.UNKNOWN
    created_at: datetime
    updated_at: datetime


class ProviderChannelsPublic(SQLModel):
    data: list[ProviderChannelPublic]
    count: int


class ProviderModelDiscoveryResult(SQLModel):
    channel_id: uuid.UUID
    models: list[str]
    count: int


class ProviderModelMappingCreate(SQLModel):
    canonical_model: str = Field(min_length=1, max_length=200)
    upstream_model: str = Field(min_length=1, max_length=200)
    supports_vision: bool = True
    supports_structured_output: bool = True
    enabled: bool = True


class ProviderModelMappingUpdate(SQLModel):
    upstream_model: str | None = Field(default=None, min_length=1, max_length=200)
    supports_vision: bool | None = None
    supports_structured_output: bool | None = None
    enabled: bool | None = None


class ProviderModelMappingPublic(SQLModel):
    id: uuid.UUID
    channel_id: uuid.UUID
    canonical_model: str
    upstream_model: str
    supports_vision: bool
    supports_structured_output: bool
    usage_metering_verified: bool
    usage_verified_at: datetime | None = None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class PlatformModelOfferingCreate(SQLModel):
    code: str = Field(regex=r"^[a-z][a-z0-9_-]*$", min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=300)
    scope: SchoolModelScope
    provider_code: str = Field(default="route", min_length=1, max_length=100)
    canonical_model: str = Field(min_length=1, max_length=200)
    published: bool = False
    school_selectable: bool = True
    sort_order: int = Field(default=100, ge=0, le=10000)


class PlatformModelOfferingUpdate(SQLModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=300)
    scope: SchoolModelScope | None = None
    provider_code: str | None = Field(default=None, min_length=1, max_length=100)
    canonical_model: str | None = Field(default=None, min_length=1, max_length=200)
    published: bool | None = None
    school_selectable: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10000)


class PlatformModelOfferingPublic(SQLModel):
    id: uuid.UUID
    code: str
    display_name: str
    description: str | None = None
    scope: SchoolModelScope
    provider_code: str
    canonical_model: str
    published: bool
    school_selectable: bool
    sort_order: int
    mapped_channel_count: int = 0
    route_purposes: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class PlatformModelOfferingsPublic(SQLModel):
    data: list[PlatformModelOfferingPublic]
    count: int


class SchoolModelOptionPublic(SQLModel):
    id: uuid.UUID
    code: str
    display_name: str
    description: str | None = None
    scope: SchoolModelScope


class SchoolModelScopePublic(SQLModel):
    scope: SchoolModelScope
    selected_option_id: uuid.UUID | None = None
    options: list[SchoolModelOptionPublic] = Field(default_factory=list)


class SchoolModelSettingsPublic(SQLModel):
    scopes: list[SchoolModelScopePublic]


class SchoolModelSelectionUpdate(SQLModel):
    offering_id: uuid.UUID


class ModelRouteTargetInput(SQLModel):
    mapping_id: uuid.UUID
    priority: int = Field(default=100, ge=0, le=10000)
    weight: int = Field(default=100, ge=1, le=10000)
    enabled: bool = True


class ModelRoutePolicyUpsert(SQLModel):
    canonical_model: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    max_attempts: int = Field(default=3, ge=1, le=10)
    routing_mode: Literal["balanced", "cost_first", "latency_first"] = "balanced"
    targets: list[ModelRouteTargetInput] = Field(min_length=1, max_length=20)


class ModelRouteTargetPublic(SQLModel):
    id: uuid.UUID
    mapping_id: uuid.UUID
    channel_id: uuid.UUID
    channel_code: str
    canonical_model: str
    upstream_model: str
    protocol: ProviderProtocol
    base_url: str
    priority: int
    weight: int
    enabled: bool
    cost_rmb_per_million: float | None = None


class ModelRoutePolicyPublic(SQLModel):
    id: uuid.UUID
    purpose: str
    canonical_model: str
    enabled: bool
    max_attempts: int
    routing_mode: str
    sticky_scope: str
    targets: list[ModelRouteTargetPublic]


class ModelRouteVersionPublic(SQLModel):
    id: uuid.UUID
    policy_id: uuid.UUID
    version: int
    status: ModelRouteVersionStatus
    max_attempts: int
    routing_mode: str
    sticky_scope: str
    created_at: datetime
    published_at: datetime | None = None
    targets: list[ModelRouteTargetPublic] = Field(default_factory=list)


class FunctionModelAssignmentUpdate(SQLModel):
    canonical_model: str = Field(min_length=1, max_length=200)


class FunctionModelAssignmentPublic(SQLModel):
    purpose: str
    default_canonical_model: str
    updated_at: datetime


class OrganizationUsagePolicyUpdate(SQLModel):
    risk_state: OrganizationRiskState | None = None
    calls_per_minute: int | None = Field(default=None, ge=1, le=100000)
    max_running_jobs: int | None = Field(default=None, ge=1, le=1000)
    max_model_concurrency: int | None = Field(default=None, ge=1, le=128)
    max_job_credits: float | None = Field(default=None, gt=0)
    daily_credit_cap: float | None = Field(default=None, gt=0)
    monthly_credit_cap: float | None = Field(default=None, gt=0)
    reason: str | None = Field(default=None, max_length=500)


class OrganizationUsagePolicyPublic(SQLModel):
    org_id: uuid.UUID
    risk_state: OrganizationRiskState
    calls_per_minute: int
    max_running_jobs: int
    max_model_concurrency: int
    max_job_credits: float
    daily_credit_cap: float
    monthly_credit_cap: float
    reason: str | None = None
    updated_at: datetime


class OfferingRateVersionCreate(SQLModel):
    version: str = Field(min_length=1, max_length=50)
    effective_at: datetime
    input_credits_per_million: float = Field(ge=0)
    output_credits_per_million: float = Field(ge=0)
    image_credits_per_million: float = Field(ge=0)
    target_margin_percent: float = Field(default=40, ge=0, lt=100)
    minimum_margin_percent: float = Field(default=25, ge=0, lt=100)


class OfferingRateVersionPublic(SQLModel):
    id: uuid.UUID
    offering_id: uuid.UUID
    version: str
    effective_at: datetime
    input_credits_per_million: float
    output_credits_per_million: float
    image_credits_per_million: float
    target_margin_percent: float
    minimum_margin_percent: float
    margin_valid: bool
    created_at: datetime


class ReconciliationRowInput(SQLModel):
    upstream_request_id: str = Field(min_length=1, max_length=255)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_rmb: float = Field(default=0, ge=0)


class ReconciliationImport(SQLModel):
    source: Literal["api", "csv"]
    period_start: datetime
    period_end: datetime
    rows: list[ReconciliationRowInput] = Field(min_length=1, max_length=10000)


class ReconciliationBatchPublic(SQLModel):
    id: uuid.UUID
    channel_id: uuid.UUID
    source: str
    period_start: datetime
    period_end: datetime
    row_count: int
    fetched_count: int
    ignored_count: int
    matched_count: int
    mismatch_count: int
    upstream_system_name: str | None = None
    upstream_version: str | None = None
    upstream_total_granted_quota: int
    upstream_total_used_quota: int
    upstream_total_available_quota: int
    upstream_total_used_rmb: float
    quota_per_unit: int
    usd_exchange_rate: float
    unlimited_quota: bool
    created_at: datetime


class NewApiBillingSyncPublic(SQLModel):
    batch: ReconciliationBatchPublic
    message: str


class ProviderInternalRateVersionCreate(SQLModel):
    canonical_model: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=50)
    effective_at: datetime
    input_rmb_per_million: float = Field(default=0, ge=0)
    output_rmb_per_million: float = Field(default=0, ge=0)
    image_rmb_per_million: float = Field(default=0, ge=0)
    cached_input_rmb_per_million: float = Field(default=0, ge=0)


class ProviderInternalRateVersionPublic(SQLModel):
    id: uuid.UUID
    channel_id: uuid.UUID
    canonical_model: str
    version: str
    effective_at: datetime
    input_rmb_per_million: float
    output_rmb_per_million: float
    image_rmb_per_million: float
    cached_input_rmb_per_million: float
    created_at: datetime


class ProviderChannelTestRequest(SQLModel):
    canonical_model: str = Field(min_length=1, max_length=200)


class ProviderChannelTestResult(SQLModel):
    ok: bool
    channel_id: uuid.UUID
    canonical_model: str
    upstream_model: str | None = None
    latency_ms: int = 0
    usage_present: bool = False
    error: str | None = None
