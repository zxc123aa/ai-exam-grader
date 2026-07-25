import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Optional

from pydantic import EmailStr, field_validator, model_validator
from sqlalchemy import Column, DateTime, Numeric, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


class UserRole(StrEnum):
    # 平台侧角色（org_id 为 NULL）
    PLATFORM_SUPERUSER = "platform_superuser"
    PLATFORM_SUPPORT = "platform_support"
    # 学校侧角色（org_id 指向 Organization）
    SCHOOL_OWNER = "school_owner"
    SCHOOL_ADMIN = "school_admin"
    TEACHER = "teacher"
    STUDENT = "student"


# 组织（学校）。平台角色用户不属于任何组织。
class OrganizationBase(SQLModel):
    name: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=50)
    status: str = Field(default="active", max_length=20)
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
    status: str | None = Field(default=None, max_length=20)
    exam_sharing_enabled: bool | None = None
    contact_name: str | None = Field(default=None, max_length=100)


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
    status: str | None = Field(default=None, max_length=20)
    contact_name: str | None = Field(default=None, max_length=100)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is not None and value not in ("active", "suspended"):
            raise ValueError("status must be 'active' or 'suspended'")
        return value


class PlatformOrgListItem(SQLModel):
    id: uuid.UUID
    name: str
    code: str
    status: str
    exam_count: int = 0
    student_count: int = 0
    teacher_count: int = 0
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
    status: str
    exam_sharing_enabled: bool
    contact_name: str | None = None
    created_at: datetime | None = None
    exam_count: int = 0
    student_count: int = 0
    teacher_count: int = 0
    users: list[PlatformOrgUserItem] = Field(default_factory=list)


# 学校设置端点 schema（/org/settings）
class OrgSettingsPublic(SQLModel):
    name: str
    code: str
    exam_sharing_enabled: bool
    contact_name: str | None = None


class OrgSettingsUpdate(SQLModel):
    contact_name: str | None = Field(default=None, max_length=100)
    exam_sharing_enabled: bool | None = None


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


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


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
    exams: list["Exam"] = Relationship(back_populates="owner", cascade_delete=True)
    class_groups: list["ClassGroup"] = Relationship(
        back_populates="owner", cascade_delete=True
    )
    files: list["StoredFile"] = Relationship(
        back_populates="uploaded_by", cascade_delete=True
    )
    processing_tasks: list["ProcessingTask"] = Relationship(
        back_populates="created_by", cascade_delete=True
    )


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
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


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
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    # 考试归属的学校（多租户隔离维度），回填默认学校后 NOT NULL
    org_id: uuid.UUID = Field(
        foreign_key="organization.id", nullable=False, index=True
    )
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
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
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


class QuestionRecognitionRun(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    exam_id: uuid.UUID = Field(
        foreign_key="exam.id", nullable=False, ondelete="CASCADE", index=True
    )
    created_by_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
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
    provider: str = Field(default="pomoai", max_length=100)
    model: str = Field(default="gpt-5.6-sol", max_length=200)


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
    vision_provider: str | None = Field(default=None, max_length=100)
    vision_model: str | None = Field(default=None, max_length=200)
    provider: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=200)
    fallback_models: list[str] = Field(default_factory=list)
    submission_ids: list[uuid.UUID] = Field(default_factory=list)
    # None = 未显式指定，创建 run 时回落系统设置（services/system_config）
    review_threshold: float | None = Field(default=None, ge=0, le=1)
    max_concurrency: int | None = Field(default=None, ge=1, le=8)
    max_parallel_submissions: int | None = Field(default=None, ge=1, le=8)
    max_concurrency_per_submission: int | None = Field(default=None, ge=1, le=8)
    recognition_run_id: uuid.UUID | None = None


class RecognitionRunCreate(SQLModel):
    exam_id: uuid.UUID
    submission_id: uuid.UUID
    provider: str = Field(default="fluxnode_gemini", max_length=100)
    model: str = Field(default="gemini-3.5-flash", max_length=200)
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
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    # 班级归属的学校（学校内共享，跨校不可见），回填默认学校后 NOT NULL
    org_id: uuid.UUID = Field(
        foreign_key="organization.id", nullable=False, index=True
    )
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
        UniqueConstraint(
            "exam_id", "class_id", name="uq_gradingassignment_exam_class"
        ),
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


class GradingAssignmentsPublic(SQLModel):
    enabled: bool
    assignments: list[GradingAssignmentItemPublic] = Field(default_factory=list)
    # 有答卷但尚未分配老师的班级
    unassigned: list[GradingAssignmentClassPublic] = Field(default_factory=list)


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
    review_threshold: float | None = Field(default=None, ge=0, le=1)
    max_concurrency: int | None = Field(default=None, ge=1, le=8)
