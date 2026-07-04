from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.models import ExamRegionCandidate, ExamRegionType

ENGINE_NAME = "layout_projection_v0"


@dataclass(frozen=True)
class CandidateBox:
    x: int
    y: int
    width: int
    height: int
    confidence: float
    reasons: list[str]


def decode_image(contents: bytes) -> np.ndarray:
    buffer = np.frombuffer(contents, dtype=np.uint8)
    image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not decode page image")
    return image


def find_question_region_candidates(
    image: np.ndarray, *, page_number: int
) -> list[ExamRegionCandidate]:
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
                source=ENGINE_NAME,
                reasons=box.reasons,
            )
        )
    return candidates


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
    block_mask = cv2.morphologyEx(block_mask, cv2.MORPH_CLOSE, close_kernel, iterations=1)

    contours, _ = cv2.findContours(block_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
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
    *, threshold: np.ndarray, box: tuple[int, int, int, int], image_shape: tuple[int, int]
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
    return max(0.0, min(1.0, width_score * 0.35 + height_score * 0.25 + density_score * 0.4))
