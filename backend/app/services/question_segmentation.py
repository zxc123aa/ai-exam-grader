from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import cv2
import httpx
import numpy as np

from app.core.config import settings
from app.models import ExamRegionCandidate, ExamRegionType

ENGINE_NAME = "layout_projection_v0"
OCR_ANCHOR_ENGINE_NAME = "layout_ocr_anchor_v1"
GEMINI_LAYOUT_ENGINE_NAME = "gemini_layout_v1"
QuestionSegmentationEngine = Literal[
    "layout_projection_v0", "layout_ocr_anchor_v1", "gemini_layout_v1"
]
QUESTION_ANCHOR_RE = re.compile(
    r"^\s*(?:"
    r"第\s*\d{1,2}\s*题|"
    r"\(?\s*\d{1,2}\s*[\.\u3001、\)\）]|"
    r"[一二三四五六七八九十]{1,3}\s*[\.\u3001、]"
    r")"
)


@dataclass(frozen=True)
class CandidateBox:
    x: int
    y: int
    width: int
    height: int
    confidence: float
    reasons: list[str]


@dataclass(frozen=True)
class OcrTextLine:
    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float | None


def decode_image(contents: bytes) -> np.ndarray:
    buffer = np.frombuffer(contents, dtype=np.uint8)
    image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not decode page image")
    return image


def find_question_region_candidates(
    image: np.ndarray,
    *,
    page_number: int,
    engine: QuestionSegmentationEngine = ENGINE_NAME,
) -> list[ExamRegionCandidate]:
    if engine == OCR_ANCHOR_ENGINE_NAME:
        boxes = find_ocr_anchor_candidate_boxes(image)
    else:
        boxes = find_layout_candidate_boxes(image)
    height, width = image.shape[:2]
    candidates: list[ExamRegionCandidate] = []
    for index, box in enumerate(boxes, start=1):
        candidates.append(
            ExamRegionCandidate(
                label=f"Q{index}",
                region_type=ExamRegionType.QUESTION,
                page_number=page_number,
                x=round(box.x / width, 4),
                y=round(box.y / height, 4),
                width=round(box.width / width, 4),
                height=round(box.height / height, 4),
                confidence=round(box.confidence, 4),
                source=engine,
                reasons=box.reasons,
            )
        )
    return candidates


def find_ocr_anchor_candidate_boxes(image: np.ndarray) -> list[CandidateBox]:
    lines = fetch_ocr_text_lines(image)
    if not lines:
        return []
    height, width = image.shape[:2]
    anchors = [line for line in lines if is_question_anchor(line.text)]
    if not anchors:
        return []
    anchors = sorted(anchors, key=lambda item: (item.y, item.x))
    has_left_anchor = any(anchor.x < width * 0.42 for anchor in anchors)
    has_right_anchor = any(anchor.x > width * 0.58 for anchor in anchors)
    use_two_columns = has_left_anchor and has_right_anchor
    boxes: list[CandidateBox] = []
    for anchor in anchors:
        column = get_anchor_column(
            anchor, image_width=width, use_two_columns=use_two_columns
        )
        same_column_anchors = [
            item
            for item in anchors
            if get_anchor_column(
                item, image_width=width, use_two_columns=use_two_columns
            )
            == column
        ]
        next_anchor = next(
            (item for item in same_column_anchors if item.y > anchor.y + anchor.height),
            None,
        )
        box = build_anchor_candidate_box(
            anchor=anchor,
            next_anchor=next_anchor,
            lines=lines,
            image_shape=(height, width),
            column=column,
        )
        if box is not None:
            boxes.append(box)
    return boxes


def fetch_ocr_text_lines(image: np.ndarray) -> list[OcrTextLine]:
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        return []
    try:
        response = httpx.post(
            settings.OCR_HTTP_URL,
            files={"file": ("page.png", buffer.tobytes(), "image/png")},
            timeout=settings.OCR_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (ValueError, httpx.HTTPError):
        return []
    raw = payload.get("raw") if isinstance(payload, dict) else None
    raw_lines = raw.get("lines") if isinstance(raw, dict) else None
    if not isinstance(raw_lines, list):
        return []
    lines: list[OcrTextLine] = []
    for item in raw_lines:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        box = item.get("box")
        if not text:
            continue
        if not isinstance(box, list | tuple) or len(box) < 4:
            box = box_from_polygon(item.get("polygon"))
        if not isinstance(box, list | tuple) or len(box) < 4:
            continue
        parsed_box = parse_ocr_box(box)
        if parsed_box is None:
            continue
        x1, y1, x2, y2 = parsed_box
        confidence = item.get("confidence")
        lines.append(
            OcrTextLine(
                text=text,
                x=min(x1, x2),
                y=min(y1, y2),
                width=max(1, abs(x2 - x1)),
                height=max(1, abs(y2 - y1)),
                confidence=parse_ocr_confidence(confidence),
            )
        )
    return sorted(lines, key=lambda item: (item.y, item.x))


def parse_finite_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if np.isfinite(number) else None


def parse_finite_int(value: object) -> int | None:
    number = parse_finite_float(value)
    return int(number) if number is not None else None


def parse_ocr_confidence(value: object) -> float | None:
    number = parse_finite_float(value)
    if number is None:
        return None
    return max(0.0, min(1.0, number))


def parse_ocr_box(box: list | tuple) -> tuple[int, int, int, int] | None:
    values = [parse_finite_int(value) for value in box[:4]]
    if any(value is None for value in values):
        return None
    x1, y1, x2, y2 = values
    if x1 == x2 or y1 == y2:
        return None
    return x1, y1, x2, y2


def box_from_polygon(polygon: object) -> list[int] | None:
    if not isinstance(polygon, list | tuple):
        return None
    x_values: list[int] = []
    y_values: list[int] = []
    for point in polygon:
        if not isinstance(point, list | tuple) or len(point) < 2:
            continue
        x = parse_finite_int(point[0])
        y = parse_finite_int(point[1])
        if x is not None and y is not None:
            x_values.append(x)
            y_values.append(y)
    if not x_values or not y_values:
        return None
    return [min(x_values), min(y_values), max(x_values), max(y_values)]


def is_question_anchor(text: str) -> bool:
    return QUESTION_ANCHOR_RE.match(text) is not None


def get_anchor_column(
    anchor: OcrTextLine, *, image_width: int, use_two_columns: bool
) -> tuple[int, int]:
    if not use_two_columns:
        return 0, image_width
    midpoint = image_width // 2
    if anchor.x + anchor.width / 2 < midpoint:
        return 0, midpoint
    return midpoint, image_width


def build_anchor_candidate_box(
    *,
    anchor: OcrTextLine,
    next_anchor: OcrTextLine | None,
    lines: list[OcrTextLine],
    image_shape: tuple[int, int],
    column: tuple[int, int],
) -> CandidateBox | None:
    image_height, image_width = image_shape
    column_left, column_right = column
    y_pad = max(8, int(image_height * 0.012))
    x_pad = max(10, int(image_width * 0.018))
    top = max(0, anchor.y - y_pad)
    if next_anchor is None:
        bottom_limit = image_height
    else:
        bottom_limit = max(anchor.y + anchor.height + y_pad, next_anchor.y - y_pad)
    region_lines = [
        line
        for line in lines
        if top <= line.y < bottom_limit
        and column_left <= line.x + line.width / 2 <= column_right
    ]
    if not region_lines:
        return None
    bottom = min(
        image_height,
        max(line.y + line.height for line in region_lines) + y_pad,
        bottom_limit,
    )
    if bottom - top < image_height * 0.025:
        return None
    left = max(0, column_left + x_pad)
    right = min(image_width, column_right - x_pad)
    confidences = [
        line.confidence for line in region_lines if line.confidence is not None
    ]
    confidence = sum(confidences) / len(confidences) if confidences else 0.75
    return CandidateBox(
        x=left,
        y=top,
        width=max(1, right - left),
        height=max(1, bottom - top),
        confidence=max(0.0, min(1.0, confidence)),
        reasons=["ocr-question-anchor", "ocr-layout-lines"],
    )


def find_layout_candidate_boxes(image: np.ndarray) -> list[CandidateBox]:
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    threshold = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        35,
        15,
    )
    threshold = clear_page_border_noise(threshold)

    horizontal_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (max(12, width // 55), max(3, height // 180)),
    )
    block_mask = cv2.dilate(threshold, horizontal_kernel, iterations=2)
    close_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (max(20, width // 35), max(6, height // 90)),
    )
    block_mask = cv2.morphologyEx(
        block_mask, cv2.MORPH_CLOSE, close_kernel, iterations=1
    )

    contours, _ = cv2.findContours(
        block_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    raw_boxes: list[tuple[int, int, int, int]] = []
    min_area = width * height * 0.002
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w * h < min_area:
            continue
        if w < width * 0.18 or h < height * 0.025:
            continue
        raw_boxes.append((x, y, w, h))

    merged = merge_vertical_neighbors(raw_boxes, image_shape=(height, width))
    boxes: list[CandidateBox] = []
    for x, y, w, h in merged:
        padded = pad_box(x, y, w, h, image_shape=(height, width))
        px, py, pw, ph = padded
        confidence = score_candidate_box(
            threshold=threshold,
            box=padded,
            image_shape=(height, width),
        )
        if confidence < 0.18:
            continue
        boxes.append(
            CandidateBox(
                x=px,
                y=py,
                width=pw,
                height=ph,
                confidence=confidence,
                reasons=["dark-layout-block", "projection-candidate"],
            )
        )
    return sorted(boxes, key=lambda item: (item.y, item.x))


def clear_page_border_noise(mask: np.ndarray) -> np.ndarray:
    cleaned = mask.copy()
    height, width = cleaned.shape[:2]
    y_margin = max(2, int(height * 0.015))
    x_margin = max(2, int(width * 0.01))
    cleaned[:y_margin, :] = 0
    cleaned[-y_margin:, :] = 0
    cleaned[:, :x_margin] = 0
    cleaned[:, -x_margin:] = 0
    return cleaned


def merge_vertical_neighbors(
    boxes: list[tuple[int, int, int, int]], *, image_shape: tuple[int, int]
) -> list[tuple[int, int, int, int]]:
    if not boxes:
        return []
    height, width = image_shape
    sorted_boxes = sorted(boxes, key=lambda item: (item[1], item[0]))
    merged: list[tuple[int, int, int, int]] = []
    for box in sorted_boxes:
        if not merged:
            merged.append(box)
            continue
        prev = merged[-1]
        px, py, pw, ph = prev
        x, y, w, h = box
        prev_bottom = py + ph
        gap = y - prev_bottom
        horizontal_overlap = min(px + pw, x + w) - max(px, x)
        overlap_ratio = horizontal_overlap / max(1, min(pw, w))
        should_merge = gap <= height * 0.018 and overlap_ratio > 0.25
        if should_merge:
            nx = min(px, x)
            ny = min(py, y)
            nr = max(px + pw, x + w)
            nb = max(py + ph, y + h)
            merged[-1] = (nx, ny, min(width - nx, nr - nx), min(height - ny, nb - ny))
        else:
            merged.append(box)
    return merged


def pad_box(
    x: int, y: int, width: int, height: int, *, image_shape: tuple[int, int]
) -> tuple[int, int, int, int]:
    image_height, image_width = image_shape
    x_pad = max(6, int(image_width * 0.015))
    y_pad = max(6, int(image_height * 0.012))
    left = max(0, x - x_pad)
    top = max(0, y - y_pad)
    right = min(image_width, x + width + x_pad)
    bottom = min(image_height, y + height + y_pad)
    return left, top, right - left, bottom - top


def score_candidate_box(
    *,
    threshold: np.ndarray,
    box: tuple[int, int, int, int],
    image_shape: tuple[int, int],
) -> float:
    image_height, image_width = image_shape
    x, y, width, height = box
    roi = threshold[y : y + height, x : x + width]
    if roi.size == 0:
        return 0.0
    ink_density = float((roi > 0).mean())
    width_score = min(1.0, width / (image_width * 0.55))
    height_score = min(1.0, height / (image_height * 0.12))
    density_score = min(1.0, ink_density / 0.08)
    return max(
        0.0, min(1.0, width_score * 0.35 + height_score * 0.25 + density_score * 0.4)
    )
