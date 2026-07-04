import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import EmailStr, model_validator
from sqlalchemy import Column, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


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
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    exams: list["Exam"] = Relationship(back_populates="owner", cascade_delete=True)
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
    FAILED = "failed"


class SubmissionAnnotationStatus(StrEnum):
    NEEDS_REVIEW = "needs_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ExamBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    subject: str | None = Field(default=None, max_length=100)
    grade_level: str | None = Field(default=None, max_length=100)
    status: ExamStatus = ExamStatus.DRAFT


class ExamCreate(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    subject: str | None = Field(default=None, max_length=100)
    grade_level: str | None = Field(default=None, max_length=100)


class ExamUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    subject: str | None = Field(default=None, max_length=100)
    grade_level: str | None = Field(default=None, max_length=100)
    status: ExamStatus | None = None


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
    owner: User | None = Relationship(back_populates="exams")
    documents: list["ExamDocument"] = Relationship(
        back_populates="exam", cascade_delete=True
    )
    regions: list["ExamRegion"] = Relationship(
        back_populates="exam", cascade_delete=True
    )
    submissions: list["StudentSubmission"] = Relationship(
        back_populates="exam", cascade_delete=True
    )


class ExamPublic(ExamBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime | None = None


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
        back_populates="stored_file", cascade_delete=True
    )
    student_submissions: list["StudentSubmission"] = Relationship(
        back_populates="stored_file", cascade_delete=True
    )


class StoredFilePublic(StoredFileBase):
    id: uuid.UUID
    uploaded_by_id: uuid.UUID
    created_at: datetime | None = None


class ExamDocumentBase(SQLModel):
    document_type: ExamDocumentType = ExamDocumentType.BLANK_EXAM


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
    exam: Exam | None = Relationship(back_populates="documents")
    stored_file: StoredFile | None = Relationship(back_populates="exam_documents")


class ExamDocumentPublic(ExamDocumentBase):
    id: uuid.UUID
    exam_id: uuid.UUID
    stored_file_id: uuid.UUID
    stored_file: StoredFilePublic
    page_count: int = 1
    created_at: datetime | None = None


class ExamDocumentsPublic(SQLModel):
    data: list[ExamDocumentPublic]
    count: int


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
    pass


class ExamRegionUpdate(SQLModel):
    label: str | None = Field(default=None, min_length=1, max_length=100)
    region_type: ExamRegionType | None = None
    page_number: int | None = Field(default=None, ge=1)
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    width: float | None = Field(default=None, gt=0, le=1)
    height: float | None = Field(default=None, gt=0, le=1)


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
    exam: Exam | None = Relationship(back_populates="regions")


class ExamRegionPublic(ExamRegionBase):
    id: uuid.UUID
    exam_id: uuid.UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None


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


class StudentSubmissionBase(SQLModel):
    student_name: str | None = Field(default=None, max_length=255)
    student_identifier: str | None = Field(default=None, max_length=100)
    status: StudentSubmissionStatus = StudentSubmissionStatus.REGISTRATION_PENDING
    registration_status: SubmissionRegistrationStatus = (
        SubmissionRegistrationStatus.PENDING
    )
    registration_quality: float | None = Field(default=None, ge=0, le=1)
    registration_notes: str | None = Field(default=None, max_length=1000)


class StudentSubmissionCreate(SQLModel):
    student_name: str | None = Field(default=None, max_length=255)
    student_identifier: str | None = Field(default=None, max_length=100)


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
    registered_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    exam_id: uuid.UUID = Field(
        foreign_key="exam.id", nullable=False, ondelete="CASCADE"
    )
    stored_file_id: uuid.UUID = Field(
        foreign_key="storedfile.id", nullable=False, ondelete="CASCADE"
    )
    exam: Exam | None = Relationship(back_populates="submissions")
    stored_file: StoredFile | None = Relationship(back_populates="student_submissions")
    annotations: list["SubmissionAnnotation"] = Relationship(
        back_populates="submission", cascade_delete=True
    )


class StudentSubmissionPublic(StudentSubmissionBase):
    id: uuid.UUID
    exam_id: uuid.UUID
    stored_file_id: uuid.UUID
    stored_file: StoredFilePublic
    page_count: int = 1
    registration_homography: dict | None = None
    registered_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class StudentSubmissionsPublic(SQLModel):
    data: list[StudentSubmissionPublic]
    count: int


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
    submission: StudentSubmission | None = Relationship(back_populates="annotations")


class SubmissionAnnotationPublic(SubmissionAnnotationBase):
    id: uuid.UUID
    submission_id: uuid.UUID
    exam_region_id: uuid.UUID | None = None
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
