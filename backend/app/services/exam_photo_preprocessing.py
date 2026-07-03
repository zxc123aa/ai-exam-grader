from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import cv2
import numpy as np
from PIL import Image


class PhotoPreprocessingError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreprocessedPage:
    name: str
    image: np.ndarray
    x_start: int
    x_end: int


@dataclass(frozen=True)
class SplitMetadata:
    strategy: str
    gutter_ratio: float | None
    gutter_confidence: float | None
    overlap_pixels: int


@dataclass(frozen=True)
class PreprocessedExamPhoto:
    pdf_bytes: bytes
    pages: list[PreprocessedPage]
    detected_quad: list[list[float]]
    spread_size: tuple[int, int]
    split: SplitMetadata
    mask: np.ndarray
    warped_spread: np.ndarray
    enhanced_spread: np.ndarray


@dataclass(frozen=True)
class HalfPageFallback:
    pages: list[PreprocessedPage]
    detected_quad: np.ndarray
    warped_spread: np.ndarray
    enhanced_spread: np.ndarray


def order_points(points: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    summed = points.sum(axis=1)
    diff = np.diff(points, axis=1)
    rect[0] = points[np.argmin(summed)]
    rect[2] = points[np.argmax(summed)]
    rect[1] = points[np.argmin(diff)]
    rect[3] = points[np.argmax(diff)]
    return rect


def four_point_transform(image: np.ndarray, points: np.ndarray) -> np.ndarray:
    rect = order_points(points.astype("float32"))
    top_left, top_right, bottom_right, bottom_left = rect
    width_a = np.linalg.norm(bottom_right - bottom_left)
    width_b = np.linalg.norm(top_right - top_left)
    height_a = np.linalg.norm(top_right - bottom_right)
    height_b = np.linalg.norm(top_left - bottom_left)
    max_width = int(max(width_a, width_b))
    max_height = int(max(height_a, height_b))
    if max_width < 50 or max_height < 50:
        raise PhotoPreprocessingError("Detected document is too small")
    destination = np.array(
        [
            [0, 0],
            [max_width - 1, 0],
            [max_width - 1, max_height - 1],
            [0, max_height - 1],
        ],
        dtype="float32",
    )
    matrix = cv2.getPerspectiveTransform(rect, destination)
    return cv2.warpPerspective(image, matrix, (max_width, max_height))


def resize_for_detection(
    image: np.ndarray, max_width: int = 1200
) -> tuple[np.ndarray, float]:
    height, width = image.shape[:2]
    if width <= max_width:
        return image.copy(), 1.0
    scale = max_width / width
    resized = cv2.resize(image, (max_width, int(height * scale)))
    return resized, scale


def build_document_mask(resized: np.ndarray, *, relaxed: bool = False) -> np.ndarray:
    lab = cv2.cvtColor(resized, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    mask = np.zeros(l_channel.shape, dtype=np.uint8)

    if relaxed:
        mask[(l_channel > 125) & (a_channel > 116) & (b_channel > 116)] = 255
        close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (55, 35))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel, iterations=3)
    else:
        mask[(l_channel > 165) & (a_channel > 124) & (b_channel > 126)] = 255
        close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel, iterations=2)

    open_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, open_kernel, iterations=1)
    return mask


def find_quad_from_mask(mask: np.ndarray, *, scale: float) -> np.ndarray:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise PhotoPreprocessingError("No document-like bright region found")

    contours = sorted(contours, key=cv2.contourArea, reverse=True)
    image_area = mask.shape[0] * mask.shape[1]
    for contour in contours[:5]:
        area = cv2.contourArea(contour)
        if area < image_area * 0.15:
            continue
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.025 * perimeter, True)
        if len(approx) == 4:
            return (approx.reshape(4, 2) / scale).astype("float32")

    largest = contours[0]
    if cv2.contourArea(largest) < image_area * 0.15:
        raise PhotoPreprocessingError("Detected document region is too small")
    box = cv2.boxPoints(cv2.minAreaRect(largest))
    return (box / scale).astype("float32")


def find_document_quad(image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    resized, scale = resize_for_detection(image)
    mask = build_document_mask(resized)
    return find_quad_from_mask(mask, scale=scale), mask


def quad_bounds(points: np.ndarray) -> tuple[float, float, float, float]:
    min_x = float(points[:, 0].min())
    min_y = float(points[:, 1].min())
    max_x = float(points[:, 0].max())
    max_y = float(points[:, 1].max())
    return min_x, min_y, max_x, max_y


def add_content_preserving_margin(image: np.ndarray, quad: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    rect = order_points(quad).copy()
    top_left, top_right, bottom_right, bottom_left = rect

    is_landscape_spread = width >= height * 1.2
    top_y = min(float(top_left[1]), float(top_right[1]))
    top_ratio = 0.2 if is_landscape_spread and top_y > height * 0.08 else 0.06
    bottom_ratio = 0.025
    side_ratio = 0.015

    padded = np.array(
        [
            top_left
            + (top_left - bottom_left) * top_ratio
            + (top_left - top_right) * side_ratio,
            top_right
            + (top_right - bottom_right) * top_ratio
            + (top_right - top_left) * side_ratio,
            bottom_right
            + (bottom_right - top_right) * bottom_ratio
            + (bottom_right - bottom_left) * side_ratio,
            bottom_left
            + (bottom_left - top_left) * bottom_ratio
            + (bottom_left - bottom_right) * side_ratio,
        ],
        dtype="float32",
    )
    padded[:, 0] = np.clip(padded[:, 0], 0, width - 1)
    padded[:, 1] = np.clip(padded[:, 1], 0, height - 1)
    return padded


def is_partial_landscape_detection(image: np.ndarray, quad: np.ndarray) -> bool:
    height, width = image.shape[:2]
    if width < height * 1.25:
        return False

    min_x, _min_y, max_x, _max_y = quad_bounds(quad)
    quad_width_ratio = (max_x - min_x) / width
    center_ratio = ((min_x + max_x) / 2) / width
    return quad_width_ratio < 0.68 or center_ratio < 0.38 or center_ratio > 0.62


def find_relaxed_spread_quad(image: np.ndarray) -> np.ndarray | None:
    height, width = image.shape[:2]
    resized, scale = resize_for_detection(image)
    mask = build_document_mask(resized, relaxed=True)
    try:
        quad = find_quad_from_mask(mask, scale=scale)
    except PhotoPreprocessingError:
        return None

    min_x, min_y, max_x, max_y = quad_bounds(quad)
    quad_width = max_x - min_x
    quad_height = max_y - min_y
    if quad_width < width * 0.75 or quad_height < height * 0.55:
        return None
    if quad_width < quad_height * 1.15:
        return None
    return quad


def find_page_quad_in_roi(
    image: np.ndarray, *, x_start: int, x_end: int
) -> np.ndarray | None:
    roi = image[:, x_start:x_end]
    if roi.size == 0:
        return None

    try:
        quad, _mask = find_document_quad(roi)
    except PhotoPreprocessingError:
        resized, scale = resize_for_detection(roi)
        mask = build_document_mask(resized, relaxed=True)
        try:
            quad = find_quad_from_mask(mask, scale=scale)
        except PhotoPreprocessingError:
            return None

    quad[:, 0] += x_start
    return quad


def stitch_debug_spread(pages: list[PreprocessedPage]) -> np.ndarray:
    max_height = max(page.image.shape[0] for page in pages)
    resized_pages = []
    for page in pages:
        height, width = page.image.shape[:2]
        if height == max_height:
            resized_pages.append(page.image)
            continue
        scaled_width = max(1, int(width * (max_height / height)))
        resized_pages.append(cv2.resize(page.image, (scaled_width, max_height)))
    return cv2.hconcat(resized_pages)


def find_half_page_fallback(image: np.ndarray) -> HalfPageFallback | None:
    height, width = image.shape[:2]
    if width < height * 1.25:
        return None

    center = width // 2
    overlap = max(24, int(width * 0.06))
    left_quad = find_page_quad_in_roi(
        image, x_start=0, x_end=min(width, center + overlap)
    )
    right_quad = find_page_quad_in_roi(
        image, x_start=max(0, center - overlap), x_end=width
    )
    if left_quad is None or right_quad is None:
        return None

    left = enhance_page(four_point_transform(image, left_quad))
    right = enhance_page(four_point_transform(image, right_quad))
    left_page = PreprocessedPage(
        name="page_1_left.jpg",
        image=left,
        x_start=0,
        x_end=left.shape[1],
    )
    right_page = PreprocessedPage(
        name="page_2_right.jpg",
        image=right,
        x_start=left.shape[1],
        x_end=left.shape[1] + right.shape[1],
    )
    pages = [left_page, right_page]
    spread = stitch_debug_spread(pages)
    combined_quad = np.vstack([left_quad, right_quad])
    box = cv2.boxPoints(cv2.minAreaRect(combined_quad.astype("float32")))
    return HalfPageFallback(
        pages=pages,
        detected_quad=box.astype("float32"),
        warped_spread=spread,
        enhanced_spread=spread,
    )


def enhance_page(image: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced_l = clahe.apply(l_channel)
    enhanced = cv2.merge((enhanced_l, a_channel, b_channel))
    enhanced = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
    return cv2.fastNlMeansDenoisingColored(enhanced, None, 3, 3, 7, 21)


def detect_gutter_ratio(image: np.ndarray) -> tuple[float, float]:
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    top = int(height * 0.08)
    bottom = int(height * 0.92)
    central_page = gray[top:bottom, :]

    darkness = 255 - central_page
    projection = darkness.mean(axis=0).astype("float32")
    ink_density = (central_page < 150).mean(axis=0).astype("float32")
    window = max(9, int(width * 0.025))
    kernel = np.ones(window, dtype="float32") / window
    smoothed = np.convolve(projection, kernel, mode="same")
    smoothed_ink = np.convolve(ink_density, kernel, mode="same")

    left = int(width * 0.45)
    right = int(width * 0.55)
    if right <= left:
        return 0.5, 0.0

    search = smoothed[left:right]
    local_index = int(np.argmax(search))
    gutter_x = left + local_index
    dark_gutter_x = gutter_x

    blank_left = int(width * 0.45)
    blank_right = int(width * 0.58)
    blank_search = smoothed_ink[blank_left:blank_right]
    blank_x = blank_left + int(np.argmin(blank_search))
    dark_ink = float(smoothed_ink[dark_gutter_x])
    blank_ink = float(smoothed_ink[blank_x])
    if (
        dark_gutter_x < width * 0.5
        and blank_x > width * 0.52
        and blank_ink < dark_ink * 0.55
    ):
        gutter_x = blank_x

    baseline_left = int(width * 0.25)
    baseline_right = int(width * 0.75)
    baseline = smoothed[baseline_left:baseline_right]
    baseline_mean = float(baseline.mean())
    baseline_std = float(baseline.std())
    peak = float(smoothed[gutter_x])
    confidence = 0.0
    if baseline_std > 1e-6:
        confidence = max(0.0, min(1.0, (peak - baseline_mean) / (baseline_std * 4)))
    if gutter_x != dark_gutter_x and dark_ink > 1e-6:
        confidence = max(confidence, min(1.0, (dark_ink - blank_ink) / dark_ink))

    if confidence < 0.12:
        return 0.5, confidence
    return gutter_x / width, confidence


def split_spread(image: np.ndarray) -> tuple[list[PreprocessedPage], SplitMetadata]:
    height, width = image.shape[:2]
    if width < height * 1.2:
        return [
            PreprocessedPage(name="page_1.jpg", image=image, x_start=0, x_end=width)
        ], SplitMetadata(
            strategy="single_page",
            gutter_ratio=None,
            gutter_confidence=None,
            overlap_pixels=0,
        )

    gutter_ratio, confidence = detect_gutter_ratio(image)
    center = int(width * gutter_ratio)
    overlap = max(16, int(width * 0.025))
    left_start = 0
    left_end = min(width, center + overlap)
    right_start = max(0, center - overlap)
    right_end = width
    left = image[:, left_start:left_end]
    right = image[:, right_start:right_end]
    return [
        PreprocessedPage(name="page_1_left.jpg", image=left, x_start=left_start, x_end=left_end),
        PreprocessedPage(name="page_2_right.jpg", image=right, x_start=right_start, x_end=right_end),
    ], SplitMetadata(
        strategy="detected_gutter" if confidence >= 0.12 else "center_fallback",
        gutter_ratio=round(gutter_ratio, 4),
        gutter_confidence=round(confidence, 4),
        overlap_pixels=overlap,
    )


def encode_pdf(pages: list[PreprocessedPage]) -> bytes:
    pil_pages: list[Image.Image] = []
    for page in pages:
        rgb = cv2.cvtColor(page.image, cv2.COLOR_BGR2RGB)
        pil_pages.append(Image.fromarray(rgb).convert("RGB"))
    try:
        buffer = BytesIO()
        first, rest = pil_pages[0], pil_pages[1:]
        first.save(buffer, format="PDF", save_all=True, append_images=rest)
        return buffer.getvalue()
    finally:
        for page in pil_pages:
            page.close()


def preprocess_exam_photo_bytes(contents: bytes) -> PreprocessedExamPhoto:
    image_buffer = np.frombuffer(contents, dtype=np.uint8)
    image = cv2.imdecode(image_buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise PhotoPreprocessingError("Could not decode uploaded image")

    quad, mask = find_document_quad(image)
    partial_landscape = is_partial_landscape_detection(image, quad)
    if partial_landscape:
        relaxed_quad = find_relaxed_spread_quad(image)
        if relaxed_quad is not None:
            quad = relaxed_quad

    quad = add_content_preserving_margin(image, quad)
    warped = four_point_transform(image, quad)
    enhanced_spread = enhance_page(warped)
    pages, split = split_spread(enhanced_spread)
    if partial_landscape and len(pages) == 1:
        fallback = find_half_page_fallback(image)
        if fallback is not None:
            pages = fallback.pages
            split = SplitMetadata(
                strategy="split_half_page_fallback",
                gutter_ratio=0.5,
                gutter_confidence=0.0,
                overlap_pixels=0,
            )
            quad = fallback.detected_quad
            warped = fallback.warped_spread
            enhanced_spread = fallback.enhanced_spread

    pdf_bytes = encode_pdf(pages)
    return PreprocessedExamPhoto(
        pdf_bytes=pdf_bytes,
        pages=pages,
        detected_quad=quad.round(1).tolist(),
        spread_size=(warped.shape[1], warped.shape[0]),
        split=split,
        mask=mask,
        warped_spread=warped,
        enhanced_spread=enhanced_spread,
    )
