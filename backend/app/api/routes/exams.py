import uuid
from io import BytesIO
from typing import Any

import jwt
from fastapi import APIRouter, Form, Header, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.responses import Response
from jwt.exceptions import InvalidTokenError
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.core import security
from app.core.config import settings
from app.models import (
    Exam,
    ExamCreate,
    ExamDocument,
    ExamDocumentPublic,
    ExamDocumentsPublic,
    ExamDocumentType,
    ExamPublic,
    ExamRegion,
    ExamRegionCreate,
    ExamRegionPublic,
    ExamRegionsPublic,
    ExamRegionUpdate,
    ExamsPublic,
    ExamUpdate,
    Message,
    StoredFile,
    StoredFilePublic,
    StudentSubmission,
    StudentSubmissionPublic,
    StudentSubmissionsPublic,
    StudentSubmissionStatus,
    TokenPayload,
    User,
    get_datetime_utc,
)
from app.services.file_storage import (
    cleanup_stored_file_path,
    get_stored_file_path,
    store_upload_file,
)
from app.services.pdf_rendering import (
    InvalidPdfError,
    get_pdf_page_count,
    render_pdf_page_png,
)

router = APIRouter(prefix="/exams", tags=["exams"])


def get_exam_for_user(
    *, session: SessionDep, current_user: CurrentUser, exam_id: uuid.UUID
) -> Exam:
    exam = session.get(Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    if not current_user.is_superuser and exam.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return exam


def get_stored_file_page_count(stored_file: StoredFile) -> int:
    page_count = 1
    path = get_stored_file_path(stored_file)
    if stored_file.content_type == "application/pdf" and path.exists():
        try:
            page_count = get_pdf_page_count(path)
        except InvalidPdfError:
            page_count = 1
    return page_count


def validate_uploaded_pdf(stored_file: StoredFile) -> None:
    if stored_file.content_type != "application/pdf":
        return
    try:
        get_pdf_page_count(get_stored_file_path(stored_file))
    except InvalidPdfError:
        cleanup_stored_file_path(get_stored_file_path(stored_file))
        raise HTTPException(
            status_code=415,
            detail="Uploaded PDF could not be opened",
        )


def build_exam_document_public(
    *, exam_document: ExamDocument, stored_file: StoredFile
) -> ExamDocumentPublic:
    return ExamDocumentPublic(
        id=exam_document.id,
        exam_id=exam_document.exam_id,
        stored_file_id=exam_document.stored_file_id,
        document_type=exam_document.document_type,
        created_at=exam_document.created_at,
        stored_file=StoredFilePublic.model_validate(stored_file),
        page_count=get_stored_file_page_count(stored_file),
    )


def build_student_submission_public(
    *, submission: StudentSubmission, stored_file: StoredFile
) -> StudentSubmissionPublic:
    return StudentSubmissionPublic(
        id=submission.id,
        exam_id=submission.exam_id,
        stored_file_id=submission.stored_file_id,
        student_name=submission.student_name,
        student_identifier=submission.student_identifier,
        status=submission.status,
        created_at=submission.created_at,
        updated_at=submission.updated_at,
        stored_file=StoredFilePublic.model_validate(stored_file),
        page_count=get_stored_file_page_count(stored_file),
    )


def get_exam_document_for_user(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    document_id: uuid.UUID,
) -> tuple[ExamDocument, StoredFile]:
    get_exam_for_user(session=session, current_user=current_user, exam_id=exam_id)
    statement = (
        select(ExamDocument, StoredFile)
        .join(StoredFile, ExamDocument.stored_file_id == StoredFile.id)
        .where(ExamDocument.id == document_id, ExamDocument.exam_id == exam_id)
    )
    row = session.exec(statement).first()
    if not row:
        raise HTTPException(status_code=404, detail="Exam file not found")
    return row


def get_student_submission_for_user(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    submission_id: uuid.UUID,
) -> tuple[StudentSubmission, StoredFile]:
    get_exam_for_user(session=session, current_user=current_user, exam_id=exam_id)
    statement = (
        select(StudentSubmission, StoredFile)
        .join(StoredFile, StudentSubmission.stored_file_id == StoredFile.id)
        .where(
            StudentSubmission.id == submission_id,
            StudentSubmission.exam_id == exam_id,
        )
    )
    row = session.exec(statement).first()
    if not row:
        raise HTTPException(status_code=404, detail="Student submission not found")
    return row


def get_exam_region_for_user(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    region_id: uuid.UUID,
) -> ExamRegion:
    get_exam_for_user(session=session, current_user=current_user, exam_id=exam_id)
    region = session.get(ExamRegion, region_id)
    if not region or region.exam_id != exam_id:
        raise HTTPException(status_code=404, detail="Exam region not found")
    return region


def build_page_image_response(*, stored_file: StoredFile, page_number: int) -> Response:
    path = get_stored_file_path(stored_file)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Stored file not found")
    if page_number < 1:
        raise HTTPException(status_code=422, detail="Page number must be at least 1")

    if stored_file.content_type == "application/pdf":
        try:
            contents = render_pdf_page_png(path, page_number)
        except InvalidPdfError:
            raise HTTPException(status_code=415, detail="Stored PDF could not be opened")
        except IndexError:
            raise HTTPException(status_code=404, detail="PDF page not found")
        return Response(content=contents, media_type="image/png")

    if page_number != 1:
        raise HTTPException(status_code=404, detail="Image file has only one page")
    return FileResponse(
        path=path,
        media_type=stored_file.content_type or "application/octet-stream",
        filename=stored_file.original_filename,
    )


def render_stored_file_page_image(*, stored_file: StoredFile, page_number: int) -> Image.Image:
    path = get_stored_file_path(stored_file)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Stored file not found")
    if page_number < 1:
        raise HTTPException(status_code=422, detail="Page number must be at least 1")

    if stored_file.content_type == "application/pdf":
        try:
            contents = render_pdf_page_png(path, page_number)
        except InvalidPdfError:
            raise HTTPException(status_code=415, detail="Stored PDF could not be opened")
        except IndexError:
            raise HTTPException(status_code=404, detail="PDF page not found")
        return Image.open(BytesIO(contents)).convert("RGB")

    if page_number != 1:
        raise HTTPException(status_code=404, detail="Image file has only one page")
    try:
        return Image.open(path).convert("RGB")
    except UnidentifiedImageError:
        raise HTTPException(status_code=415, detail="Stored image could not be opened")


def crop_region_from_stored_file(
    *, stored_file: StoredFile, region: ExamRegion
) -> bytes:
    image = render_stored_file_page_image(
        stored_file=stored_file, page_number=region.page_number
    )
    try:
        image_width, image_height = image.size
        left = round(region.x * image_width)
        top = round(region.y * image_height)
        right = round((region.x + region.width) * image_width)
        bottom = round((region.y + region.height) * image_height)
        if right <= left or bottom <= top:
            raise HTTPException(status_code=422, detail="Region crop is empty")
        cropped = image.crop((left, top, right, bottom))
        buffer = BytesIO()
        cropped.save(buffer, format="PNG")
        return buffer.getvalue()
    finally:
        image.close()


def get_user_from_authorization_header(
    *, session: SessionDep, authorization: str | None = None
) -> User:
    token = None
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value:
            token = value
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    user = session.get(User, token_data.sub)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


@router.get("/", response_model=ExamsPublic)
def read_exams(
    session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 100
) -> Any:
    if current_user.is_superuser:
        count_statement = select(func.count()).select_from(Exam)
        statement = (
            select(Exam).order_by(col(Exam.created_at).desc()).offset(skip).limit(limit)
        )
    else:
        count_statement = (
            select(func.count()).select_from(Exam).where(Exam.owner_id == current_user.id)
        )
        statement = (
            select(Exam)
            .where(Exam.owner_id == current_user.id)
            .order_by(col(Exam.created_at).desc())
            .offset(skip)
            .limit(limit)
        )

    count = session.exec(count_statement).one()
    exams = session.exec(statement).all()
    return ExamsPublic(data=[ExamPublic.model_validate(exam) for exam in exams], count=count)


@router.post("/", response_model=ExamPublic)
def create_exam(
    *, session: SessionDep, current_user: CurrentUser, exam_in: ExamCreate
) -> Any:
    exam = Exam.model_validate(exam_in, update={"owner_id": current_user.id})
    session.add(exam)
    session.commit()
    session.refresh(exam)
    return exam


@router.get("/{exam_id}", response_model=ExamPublic)
def read_exam(
    session: SessionDep, current_user: CurrentUser, exam_id: uuid.UUID
) -> Any:
    return get_exam_for_user(
        session=session, current_user=current_user, exam_id=exam_id
    )


@router.post("/{exam_id}/files", response_model=ExamDocumentPublic)
async def upload_exam_file(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    file: UploadFile,
    document_type: ExamDocumentType = Form(default=ExamDocumentType.BLANK_EXAM),
) -> Any:
    exam = get_exam_for_user(
        session=session, current_user=current_user, exam_id=exam_id
    )
    stored_file = await store_upload_file(
        session=session,
        current_user=current_user,
        file=file,
        owner_id=exam.owner_id,
        commit=False,
        validate_exam_file=True,
    )
    try:
        validate_uploaded_pdf(stored_file)
    except HTTPException:
        session.rollback()
        raise
    try:
        exam_document = ExamDocument(
            exam_id=exam.id,
            stored_file_id=stored_file.id,
            document_type=document_type,
        )
        session.add(exam_document)
        session.commit()
    except Exception:
        session.rollback()
        cleanup_stored_file_path(get_stored_file_path(stored_file))
        raise
    session.refresh(exam_document)
    session.refresh(stored_file)
    return build_exam_document_public(
        exam_document=exam_document, stored_file=stored_file
    )


@router.get("/{exam_id}/files", response_model=ExamDocumentsPublic)
def read_exam_files(
    session: SessionDep, current_user: CurrentUser, exam_id: uuid.UUID
) -> Any:
    get_exam_for_user(session=session, current_user=current_user, exam_id=exam_id)

    count_statement = (
        select(func.count()).select_from(ExamDocument).where(ExamDocument.exam_id == exam_id)
    )
    statement = (
        select(ExamDocument, StoredFile)
        .join(StoredFile, ExamDocument.stored_file_id == StoredFile.id)
        .where(ExamDocument.exam_id == exam_id)
        .order_by(col(ExamDocument.created_at).desc())
    )

    count = session.exec(count_statement).one()
    rows = session.exec(statement).all()
    documents = [
        build_exam_document_public(exam_document=exam_document, stored_file=stored_file)
        for exam_document, stored_file in rows
    ]
    return ExamDocumentsPublic(data=documents, count=count)


@router.get("/{exam_id}/files/{document_id}/content")
def read_exam_file_content(
    session: SessionDep,
    exam_id: uuid.UUID,
    document_id: uuid.UUID,
    authorization: str | None = Header(default=None),
) -> FileResponse:
    user = get_user_from_authorization_header(
        session=session, authorization=authorization
    )
    _exam_document, stored_file = get_exam_document_for_user(
        session=session,
        current_user=user,
        exam_id=exam_id,
        document_id=document_id,
    )
    path = get_stored_file_path(stored_file)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Stored file not found")

    return FileResponse(
        path=path,
        media_type=stored_file.content_type or "application/octet-stream",
        filename=stored_file.original_filename,
    )


@router.get("/{exam_id}/files/{document_id}/pages/{page_number}/image")
def read_exam_file_page_image(
    session: SessionDep,
    exam_id: uuid.UUID,
    document_id: uuid.UUID,
    page_number: int,
    authorization: str | None = Header(default=None),
) -> Response:
    user = get_user_from_authorization_header(
        session=session, authorization=authorization
    )
    _exam_document, stored_file = get_exam_document_for_user(
        session=session,
        current_user=user,
        exam_id=exam_id,
        document_id=document_id,
    )
    return build_page_image_response(stored_file=stored_file, page_number=page_number)


@router.post("/{exam_id}/submissions", response_model=StudentSubmissionPublic)
async def upload_student_submission(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    file: UploadFile,
    student_name: str | None = Form(default=None),
    student_identifier: str | None = Form(default=None),
) -> Any:
    exam = get_exam_for_user(
        session=session, current_user=current_user, exam_id=exam_id
    )
    stored_file = await store_upload_file(
        session=session,
        current_user=current_user,
        file=file,
        owner_id=exam.owner_id,
        commit=False,
        validate_exam_file=True,
    )
    try:
        validate_uploaded_pdf(stored_file)
    except HTTPException:
        session.rollback()
        raise
    try:
        submission = StudentSubmission(
            exam_id=exam.id,
            stored_file_id=stored_file.id,
            student_name=student_name,
            student_identifier=student_identifier,
            status=StudentSubmissionStatus.REGISTRATION_PENDING,
        )
        session.add(submission)
        session.commit()
    except Exception:
        session.rollback()
        cleanup_stored_file_path(get_stored_file_path(stored_file))
        raise
    session.refresh(submission)
    session.refresh(stored_file)
    return build_student_submission_public(
        submission=submission, stored_file=stored_file
    )


@router.get("/{exam_id}/submissions", response_model=StudentSubmissionsPublic)
def read_student_submissions(
    session: SessionDep, current_user: CurrentUser, exam_id: uuid.UUID
) -> Any:
    get_exam_for_user(session=session, current_user=current_user, exam_id=exam_id)
    count_statement = (
        select(func.count())
        .select_from(StudentSubmission)
        .where(StudentSubmission.exam_id == exam_id)
    )
    statement = (
        select(StudentSubmission, StoredFile)
        .join(StoredFile, StudentSubmission.stored_file_id == StoredFile.id)
        .where(StudentSubmission.exam_id == exam_id)
        .order_by(col(StudentSubmission.created_at).desc())
    )
    count = session.exec(count_statement).one()
    rows = session.exec(statement).all()
    submissions = [
        build_student_submission_public(submission=submission, stored_file=stored_file)
        for submission, stored_file in rows
    ]
    return StudentSubmissionsPublic(data=submissions, count=count)


@router.get(
    "/{exam_id}/submissions/{submission_id}",
    response_model=StudentSubmissionPublic,
)
def read_student_submission(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    submission_id: uuid.UUID,
) -> Any:
    submission, stored_file = get_student_submission_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        submission_id=submission_id,
    )
    return build_student_submission_public(
        submission=submission, stored_file=stored_file
    )


@router.get("/{exam_id}/submissions/{submission_id}/pages/{page_number}/image")
def read_student_submission_page_image(
    session: SessionDep,
    exam_id: uuid.UUID,
    submission_id: uuid.UUID,
    page_number: int,
    authorization: str | None = Header(default=None),
) -> Response:
    user = get_user_from_authorization_header(
        session=session, authorization=authorization
    )
    _submission, stored_file = get_student_submission_for_user(
        session=session,
        current_user=user,
        exam_id=exam_id,
        submission_id=submission_id,
    )
    return build_page_image_response(stored_file=stored_file, page_number=page_number)


@router.get(
    "/{exam_id}/submissions/{submission_id}/regions",
    response_model=ExamRegionsPublic,
)
def read_student_submission_template_regions(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    submission_id: uuid.UUID,
    page_number: int | None = None,
) -> Any:
    get_student_submission_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        submission_id=submission_id,
    )
    statement = (
        select(ExamRegion)
        .where(ExamRegion.exam_id == exam_id)
        .order_by(col(ExamRegion.created_at).asc())
    )
    if page_number is not None:
        if page_number < 1:
            raise HTTPException(status_code=422, detail="Page number must be at least 1")
        statement = statement.where(ExamRegion.page_number == page_number)
    regions = session.exec(statement).all()
    return ExamRegionsPublic(
        data=[ExamRegionPublic.model_validate(region) for region in regions],
        count=len(regions),
    )


@router.get("/{exam_id}/submissions/{submission_id}/regions/{region_id}/crop")
def read_student_submission_region_crop(
    session: SessionDep,
    exam_id: uuid.UUID,
    submission_id: uuid.UUID,
    region_id: uuid.UUID,
    authorization: str | None = Header(default=None),
) -> Response:
    user = get_user_from_authorization_header(
        session=session, authorization=authorization
    )
    _submission, stored_file = get_student_submission_for_user(
        session=session,
        current_user=user,
        exam_id=exam_id,
        submission_id=submission_id,
    )
    region = get_exam_region_for_user(
        session=session,
        current_user=user,
        exam_id=exam_id,
        region_id=region_id,
    )
    return Response(
        content=crop_region_from_stored_file(
            stored_file=stored_file, region=region
        ),
        media_type="image/png",
    )


@router.get("/{exam_id}/regions", response_model=ExamRegionsPublic)
def read_exam_regions(
    session: SessionDep, current_user: CurrentUser, exam_id: uuid.UUID
) -> Any:
    get_exam_for_user(session=session, current_user=current_user, exam_id=exam_id)
    statement = (
        select(ExamRegion)
        .where(ExamRegion.exam_id == exam_id)
        .order_by(col(ExamRegion.created_at).asc())
    )
    regions = session.exec(statement).all()
    return ExamRegionsPublic(
        data=[ExamRegionPublic.model_validate(region) for region in regions],
        count=len(regions),
    )


@router.post("/{exam_id}/regions", response_model=ExamRegionPublic)
def create_exam_region(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    region_in: ExamRegionCreate,
) -> Any:
    exam = get_exam_for_user(
        session=session, current_user=current_user, exam_id=exam_id
    )
    region = ExamRegion.model_validate(region_in, update={"exam_id": exam.id})
    session.add(region)
    session.commit()
    session.refresh(region)
    return region


@router.patch("/{exam_id}/regions/{region_id}", response_model=ExamRegionPublic)
def update_exam_region(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    region_id: uuid.UUID,
    region_in: ExamRegionUpdate,
) -> Any:
    region = get_exam_region_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        region_id=region_id,
    )
    update_data = region_in.model_dump(exclude_unset=True)
    next_x = update_data.get("x", region.x)
    next_y = update_data.get("y", region.y)
    next_width = update_data.get("width", region.width)
    next_height = update_data.get("height", region.height)
    if next_x + next_width > 1 or next_y + next_height > 1:
        raise HTTPException(
            status_code=422,
            detail="Region bounds must stay within normalized page coordinates",
        )
    region.sqlmodel_update(update_data)
    region.updated_at = get_datetime_utc()
    session.add(region)
    session.commit()
    session.refresh(region)
    return region


@router.delete("/{exam_id}/regions/{region_id}")
def delete_exam_region(
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    region_id: uuid.UUID,
) -> Message:
    region = get_exam_region_for_user(
        session=session,
        current_user=current_user,
        exam_id=exam_id,
        region_id=region_id,
    )
    session.delete(region)
    session.commit()
    return Message(message="Exam region deleted successfully")


@router.patch("/{exam_id}", response_model=ExamPublic)
def update_exam(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    exam_id: uuid.UUID,
    exam_in: ExamUpdate,
) -> Any:
    exam = get_exam_for_user(
        session=session, current_user=current_user, exam_id=exam_id
    )
    exam.sqlmodel_update(exam_in.model_dump(exclude_unset=True))
    session.add(exam)
    session.commit()
    session.refresh(exam)
    return exam


@router.delete("/{exam_id}")
def delete_exam(
    session: SessionDep, current_user: CurrentUser, exam_id: uuid.UUID
) -> Message:
    exam = get_exam_for_user(
        session=session, current_user=current_user, exam_id=exam_id
    )
    session.delete(exam)
    session.commit()
    return Message(message="Exam deleted successfully")
