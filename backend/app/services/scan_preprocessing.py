from __future__ import annotations

import base64
from typing import Any

import cv2
import httpx
import numpy as np

from app.core.config import settings
from app.services.exam_photo_preprocessing import (
    PhotoPreprocessingError,
    PreprocessedExamPhoto,
    PreprocessedPage,
    QualityWarning,
    SplitMetadata,
    encode_pdf,
    preprocess_exam_photo_bytes,
    stitch_debug_spread,
)


def preprocess_scan_photo_bytes(
    contents: bytes,
    *,
    filename: str = "scan-photo.jpg",
    content_type: str = "image/jpeg",
) -> PreprocessedExamPhoto:
    if settings.SCAN_ENGINE == "opencv_v1":
        return preprocess_exam_photo_bytes(contents)
    return preprocess_scan_photo_http(
        contents,
        filename=filename,
        content_type=content_type,
    )


def preprocess_scan_photo_http(
    contents: bytes,
    *,
    filename: str,
    content_type: str,
) -> PreprocessedExamPhoto:
    try:
        response = httpx.post(
            settings.SCAN_HTTP_URL,
            files={"file": (filename, contents, content_type)},
            data={"mode": "exam_scan", "engine": "paddlex_doc_preprocessor_v1"},
            timeout=settings.SCAN_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (ValueError, httpx.HTTPError) as exc:
        raise PhotoPreprocessingError(f"scan-service request failed: {exc}")
    if not isinstance(payload, dict):
        raise PhotoPreprocessingError("scan-service returned an invalid response")

    pages = decode_scan_service_pages(payload.get("pages"))
    if not pages:
        raise PhotoPreprocessingError("scan-service returned no pages")

    enhanced_spread = stitch_debug_spread(pages)
    mask = np.zeros(enhanced_spread.shape[:2], dtype=np.uint8)
    quality = payload.get("quality") if isinstance(payload.get("quality"), dict) else {}
    split = build_split_metadata_from_payload(payload, pages)
    pdf_bytes = encode_pdf(pages)
    return PreprocessedExamPhoto(
        pdf_bytes=pdf_bytes,
        pages=pages,
        detected_quad=payload.get("detected_quad") or [],
        spread_size=(enhanced_spread.shape[1], enhanced_spread.shape[0]),
        split=split,
        quality_status=str(quality.get("status") or "review"),
        quality_warnings=decode_quality_warnings(quality.get("warnings")),
        mask=mask,
        warped_spread=enhanced_spread,
        enhanced_spread=enhanced_spread,
    )


def decode_scan_service_pages(value: Any) -> list[PreprocessedPage]:
    if not isinstance(value, list):
        return []

    pages: list[PreprocessedPage] = []
    current_x = 0
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        image = decode_base64_image(str(item.get("image_base64") or ""))
        if image is None:
            raise PhotoPreprocessingError("scan-service returned an invalid page image")
        name = str(item.get("name") or f"page_{index}.jpg")
        width = image.shape[1]
        x_start = int(item.get("x_start") or current_x)
        x_end = int(item.get("x_end") or x_start + width)
        pages.append(
            PreprocessedPage(
                name=name,
                image=image,
                x_start=x_start,
                x_end=x_end,
            )
        )
        current_x = x_end
    return pages


def decode_base64_image(value: str) -> np.ndarray | None:
    try:
        raw = base64.b64decode(value, validate=True)
    except ValueError:
        return None
    buffer = np.frombuffer(raw, dtype=np.uint8)
    return cv2.imdecode(buffer, cv2.IMREAD_COLOR)


def decode_quality_warnings(value: Any) -> list[QualityWarning]:
    if not isinstance(value, list):
        return []
    warnings: list[QualityWarning] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        warnings.append(
            QualityWarning(
                code=str(item.get("code") or "scan_service_warning"),
                severity=str(item.get("severity") or "warning"),
                message=str(item.get("message") or "scan-service flagged this scan"),
            )
        )
    return warnings


def build_split_metadata_from_payload(
    payload: dict[str, Any], pages: list[PreprocessedPage]
) -> SplitMetadata:
    split = payload.get("split") if isinstance(payload.get("split"), dict) else {}
    strategy = str(split.get("strategy") or "scan_service")
    gutter_ratio = split.get("gutter_ratio")
    gutter_confidence = split.get("gutter_confidence")
    return SplitMetadata(
        strategy=strategy,
        gutter_ratio=float(gutter_ratio) if isinstance(gutter_ratio, int | float) else None,
        gutter_confidence=(
            float(gutter_confidence)
            if isinstance(gutter_confidence, int | float)
            else None
        ),
        overlap_pixels=int(split.get("overlap_pixels") or 0) if len(pages) > 1 else 0,
    )
