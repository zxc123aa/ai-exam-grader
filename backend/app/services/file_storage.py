import hashlib
from collections.abc import Iterable
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlmodel import Session

from app.core.config import settings
from app.models import StoredFile, User

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
UPLOAD_CHUNK_SIZE = 1024 * 1024
EXAM_FILE_CONTENT_TYPES = {"application/pdf", "image/jpeg", "image/png"}
EXAM_FILE_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}


def get_stored_file_path(stored_file: StoredFile) -> Path:
    return settings.LOCAL_UPLOAD_DIR / stored_file.storage_key


def cleanup_stored_file_path(path: Path) -> None:
    path.unlink(missing_ok=True)
    try:
        path.parent.rmdir()
    except OSError:
        pass


def validate_exam_upload_file(file: UploadFile) -> None:
    original_name = file.filename or "upload.bin"
    extension = Path(original_name).suffix.lower()
    if extension not in EXAM_FILE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF, JPG, and PNG files are supported",
        )
    if file.content_type not in EXAM_FILE_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF, JPG, and PNG files are supported",
        )


def assert_allowed_signature(
    *, contents_start: bytes, allowed_content_types: Iterable[str], content_type: str | None
) -> None:
    if content_type == "application/pdf" and contents_start.startswith(b"%PDF-"):
        return
    if content_type == "image/png" and contents_start.startswith(b"\x89PNG\r\n\x1a\n"):
        return
    if content_type == "image/jpeg" and contents_start.startswith(b"\xff\xd8\xff"):
        return

    if content_type in allowed_content_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Uploaded file content does not match its declared type",
        )


async def store_upload_file(
    *,
    session: Session,
    current_user: User,
    file: UploadFile,
    owner_id: uuid.UUID | None = None,
    commit: bool = True,
    validate_exam_file: bool = False,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> StoredFile:
    if validate_exam_file:
        validate_exam_upload_file(file)

    owner = owner_id or current_user.id
    digest = hashlib.sha256()
    file_id = uuid.uuid4()
    original_name = file.filename or "upload.bin"
    storage_key = f"{owner}/{file_id}-{Path(original_name).name}"
    target_path = settings.LOCAL_UPLOAD_DIR / storage_key
    target_path.parent.mkdir(parents=True, exist_ok=True)

    size = 0
    contents_start = b""
    try:
        with target_path.open("wb") as buffer:
            while chunk := await file.read(UPLOAD_CHUNK_SIZE):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail="Uploaded file is too large",
                    )
                if len(contents_start) < 16:
                    contents_start = (contents_start + chunk)[:16]
                digest.update(chunk)
                buffer.write(chunk)

        if validate_exam_file:
            assert_allowed_signature(
                contents_start=contents_start,
                allowed_content_types=EXAM_FILE_CONTENT_TYPES,
                content_type=file.content_type,
            )
    except Exception:
        cleanup_stored_file_path(target_path)
        raise

    stored_file = StoredFile(
        id=file_id,
        original_filename=original_name,
        content_type=file.content_type,
        storage_key=storage_key,
        size_bytes=size,
        sha256=digest.hexdigest(),
        uploaded_by_id=owner,
    )
    session.add(stored_file)
    if commit:
        try:
            session.commit()
            session.refresh(stored_file)
        except Exception:
            cleanup_stored_file_path(target_path)
            raise
    return stored_file
