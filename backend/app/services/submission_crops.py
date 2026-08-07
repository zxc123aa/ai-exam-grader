from __future__ import annotations

import uuid
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from sqlmodel import Session, col, select

from app.models import ExamDocument, ExamDocumentType, ExamRegion, StoredFile
from app.services.file_storage import get_stored_file_path
from app.services.object_storage import put_storage_bytes
from app.services.pdf_rendering import (
    InvalidPdfError,
    get_pdf_page_count,
    render_pdf_page_png,
)


class SubmissionCropError(RuntimeError):
    pass


def render_stored_file_page_image(
    *, stored_file: StoredFile, page_number: int
) -> Image.Image:
    path = get_stored_file_path(stored_file)
    if not path.exists():
        raise SubmissionCropError("Stored file not found")
    if page_number < 1:
        raise SubmissionCropError("Page number must be at least 1")

    if stored_file.content_type == "application/pdf":
        try:
            contents = render_pdf_page_png(path, page_number)
        except InvalidPdfError:
            raise SubmissionCropError("Stored PDF could not be opened")
        except IndexError:
            raise SubmissionCropError("PDF page not found")
        return Image.open(BytesIO(contents)).convert("RGB")

    if page_number != 1:
        raise SubmissionCropError("Image file has only one page")
    try:
        return Image.open(path).convert("RGB")
    except UnidentifiedImageError:
        raise SubmissionCropError("Stored image could not be opened")


def stored_file_page_count(stored_file: StoredFile) -> int:
    page_count = 1
    path = get_stored_file_path(stored_file)
    if stored_file.content_type == "application/pdf" and path.exists():
        try:
            page_count = get_pdf_page_count(path)
        except InvalidPdfError:
            page_count = 1
    return page_count


def resolve_exam_region_paper_page(session: Session, region: ExamRegion) -> int:
    """Return the region's 1-based page number across the whole exam paper.

    ``ExamRegion.page_number`` is local to its blank-exam document; the global
    paper page is the sum of page counts of all blank-exam documents ordered
    before it (by sort_order, then created_at) plus the document-local page.
    """
    if region.exam_document_id is None:
        return region.page_number
    documents = session.exec(
        select(ExamDocument)
        .where(ExamDocument.exam_id == region.exam_id)
        .where(ExamDocument.document_type == ExamDocumentType.BLANK_EXAM)
        .order_by(col(ExamDocument.sort_order).asc(), col(ExamDocument.created_at).asc())
    ).all()
    page_offset = 0
    for document in documents:
        if document.id == region.exam_document_id:
            return page_offset + region.page_number
        if document.stored_file is not None:
            page_offset += stored_file_page_count(document.stored_file)
    return region.page_number


def crop_region_image(
    *,
    stored_file: StoredFile,
    region: ExamRegion,
    page_number: int | None = None,
    padding_ratio: float = 0.012,
) -> Image.Image:
    image = render_stored_file_page_image(
        stored_file=stored_file,
        page_number=page_number if page_number is not None else region.page_number,
    )
    try:
        image_width, image_height = image.size
        # 外扩一点余量，避免公式/图形边缘被裁掉（夹紧到页面边界内）
        pad_x = round(image_height * padding_ratio)
        pad_y = round(image_height * padding_ratio)
        left = max(0, round(region.x * image_width) - pad_x)
        top = max(0, round(region.y * image_height) - pad_y)
        right = min(image_width, round((region.x + region.width) * image_width) + pad_x)
        bottom = min(
            image_height, round((region.y + region.height) * image_height) + pad_y
        )
        if right <= left or bottom <= top:
            raise SubmissionCropError("Region crop is empty")
        return image.crop((left, top, right, bottom))
    finally:
        image.close()


def crop_region_png(
    *,
    stored_file: StoredFile,
    region: ExamRegion,
    page_number: int | None = None,
) -> bytes:
    cropped = crop_region_image(
        stored_file=stored_file, region=region, page_number=page_number
    )
    try:
        buffer = BytesIO()
        cropped.save(buffer, format="PNG")
        return buffer.getvalue()
    finally:
        cropped.close()


def build_region_crop_storage_key(
    *, owner_id: uuid.UUID, submission_id: uuid.UUID, region_id: uuid.UUID
) -> str:
    return f"{owner_id}/derived/submissions/{submission_id}/regions/{region_id}.png"


def save_region_crop(
    *,
    stored_file: StoredFile,
    region: ExamRegion,
    owner_id: uuid.UUID,
    submission_id: uuid.UUID,
    upload_dir: Path | None = None,
    page_number: int | None = None,
) -> dict:
    cropped = crop_region_image(
        stored_file=stored_file, region=region, page_number=page_number
    )
    resolved_page_number = (
        page_number if page_number is not None else region.page_number
    )
    try:
        storage_key = build_region_crop_storage_key(
            owner_id=owner_id,
            submission_id=submission_id,
            region_id=region.id,
        )
        buffer = BytesIO()
        cropped.save(buffer, format="PNG")
        if upload_dir is None:
            put_storage_bytes(storage_key, buffer.getvalue())
        else:
            target_path = upload_dir / storage_key
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(buffer.getvalue())
        width, height = cropped.size
        return {
            "region_id": str(region.id),
            "label": region.label,
            "page_number": resolved_page_number,
            "storage_key": storage_key,
            "width": width,
            "height": height,
            "coordinates": {
                "source": "identity_v1",
                "x": region.x,
                "y": region.y,
                "width": region.width,
                "height": region.height,
            },
        }
    finally:
        cropped.close()
