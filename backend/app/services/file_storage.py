import hashlib
import tempfile
import uuid
from collections.abc import Iterable
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlmodel import Session

from app.core.config import settings
from app.models import StoredFile, User
from app.services import billing as billing_service
from app.services.object_storage import (
    delete_storage_key,
    materialize_storage_key,
    put_storage_bytes,
    put_storage_file,
    storage_key_from_path,
)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_ZIP_UPLOAD_BYTES = 100 * 1024 * 1024
UPLOAD_CHUNK_SIZE = 1024 * 1024
ZIP_CONTENT_TYPES = {"application/zip", "application/x-zip-compressed"}
EXAM_FILE_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    *ZIP_CONTENT_TYPES,
}
EXAM_FILE_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".zip"}
SCAN_PHOTO_CONTENT_TYPES = {"image/jpeg", "image/png"}
SCAN_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def is_zip_upload(*, filename: str | None, content_type: str | None) -> bool:
    """按扩展名或 content_type 判断上传载体是否为 zip 答卷包。"""
    if content_type in ZIP_CONTENT_TYPES:
        return True
    return bool(filename) and Path(filename).suffix.lower() == ".zip"


def get_stored_file_path(stored_file: StoredFile) -> Path:
    return materialize_storage_key(stored_file.storage_key)


def cleanup_stored_file_path(path: Path) -> None:
    storage_key = storage_key_from_path(path)
    if storage_key is not None:
        delete_storage_key(storage_key)
        return
    path.unlink(missing_ok=True)


def validate_exam_upload_file(file: UploadFile) -> None:
    original_name = file.filename or "upload.bin"
    extension = Path(original_name).suffix.lower()
    if extension not in EXAM_FILE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF, JPG, PNG, and ZIP files are supported",
        )
    if file.content_type not in EXAM_FILE_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF, JPG, PNG, and ZIP files are supported",
        )


def validate_scan_photo_upload_file(file: UploadFile) -> None:
    original_name = file.filename or "upload.bin"
    extension = Path(original_name).suffix.lower()
    if extension not in SCAN_PHOTO_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only JPG and PNG scan photos are supported",
        )
    if file.content_type not in SCAN_PHOTO_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only JPG and PNG scan photos are supported",
        )


def assert_allowed_signature(
    *,
    contents_start: bytes,
    allowed_content_types: Iterable[str],
    content_type: str | None,
) -> None:
    if content_type == "application/pdf" and contents_start.startswith(b"%PDF-"):
        return
    if content_type == "image/png" and contents_start.startswith(b"\x89PNG\r\n\x1a\n"):
        return
    if content_type == "image/jpeg" and contents_start.startswith(b"\xff\xd8\xff"):
        return
    if content_type in ZIP_CONTENT_TYPES and contents_start.startswith(b"PK"):
        return

    if content_type in allowed_content_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Uploaded file content does not match its declared type",
        )


async def read_upload_file_bytes(
    *,
    file: UploadFile,
    max_bytes: int = MAX_UPLOAD_BYTES,
    too_large_status: int = status.HTTP_413_CONTENT_TOO_LARGE,
) -> bytes:
    size = 0
    buffer = BytesIO()
    while chunk := await file.read(UPLOAD_CHUNK_SIZE):
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(
                status_code=too_large_status,
                detail="Uploaded file is too large",
            )
        buffer.write(chunk)
    return buffer.getvalue()


async def store_upload_file(
    *,
    session: Session,
    current_user: User,
    file: UploadFile,
    owner_id: uuid.UUID | None = None,
    commit: bool = True,
    validate_exam_file: bool = False,
    max_bytes: int = MAX_UPLOAD_BYTES,
    too_large_status: int = status.HTTP_413_CONTENT_TOO_LARGE,
) -> StoredFile:
    if current_user.org_id:
        billing_service.require_model_entitlement(session, current_user.org_id)
    if validate_exam_file:
        validate_exam_upload_file(file)

    owner = owner_id or current_user.id
    digest = hashlib.sha256()
    file_id = uuid.uuid4()
    original_name = file.filename or "upload.bin"
    storage_key = f"{owner}/{file_id}-{Path(original_name).name}"
    settings.STORAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    size = 0
    contents_start = b""
    staged_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=settings.STORAGE_CACHE_DIR, prefix="upload-", delete=False
        ) as buffer:
            staged_path = Path(buffer.name)
            while chunk := await file.read(UPLOAD_CHUNK_SIZE):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=too_large_status,
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
        put_storage_file(storage_key, staged_path)
    except Exception:
        delete_storage_key(storage_key)
        raise
    finally:
        if staged_path is not None:
            staged_path.unlink(missing_ok=True)

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
            delete_storage_key(storage_key)
            raise
    return stored_file


def store_generated_file(
    *,
    session: Session,
    owner_id: uuid.UUID,
    original_filename: str,
    content_type: str,
    contents: bytes,
    commit: bool = True,
) -> StoredFile:
    digest = hashlib.sha256(contents).hexdigest()
    file_id = uuid.uuid4()
    storage_key = f"{owner_id}/{file_id}-{Path(original_filename).name}"
    try:
        put_storage_bytes(storage_key, contents)
        stored_file = StoredFile(
            id=file_id,
            original_filename=original_filename,
            content_type=content_type,
            storage_key=storage_key,
            size_bytes=len(contents),
            sha256=digest,
            uploaded_by_id=owner_id,
        )
        session.add(stored_file)
        if commit:
            session.commit()
            session.refresh(stored_file)
        return stored_file
    except Exception:
        delete_storage_key(storage_key)
        raise
