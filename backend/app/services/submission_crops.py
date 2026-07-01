from __future__ import annotations

import uuid
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.models import ExamRegion, StoredFile
from app.services.file_storage import get_stored_file_path
from app.services.pdf_rendering import InvalidPdfError, render_pdf_page_png


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


def crop_region_image(*, stored_file: StoredFile, region: ExamRegion) -> Image.Image:
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
            raise SubmissionCropError("Region crop is empty")
        return image.crop((left, top, right, bottom))
    finally:
        image.close()


def crop_region_png(*, stored_file: StoredFile, region: ExamRegion) -> bytes:
    cropped = crop_region_image(stored_file=stored_file, region=region)
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
    upload_dir: Path,
) -> dict:
    cropped = crop_region_image(stored_file=stored_file, region=region)
    try:
        storage_key = build_region_crop_storage_key(
            owner_id=owner_id,
            submission_id=submission_id,
            region_id=region.id,
        )
        target_path = upload_dir / storage_key
        target_path.parent.mkdir(parents=True, exist_ok=True)
        cropped.save(target_path, format="PNG")
        width, height = cropped.size
        return {
            "region_id": str(region.id),
            "label": region.label,
            "page_number": region.page_number,
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
