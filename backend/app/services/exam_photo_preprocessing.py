from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from io import BytesIO

import cv2
import numpy as np
from PIL import Image

from app.core.config import settings
from app.services.vision_grading import VisionGradingError, call_json_model


class PhotoPreprocessingError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreprocessedPage:
    name: str
    image: np.ndarray
    x_start: int
    x_end: int
    source_quad: list[list[float]] = field(default_factory=list)
    homography: list[list[float]] = field(default_factory=list)
    quality: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SplitMetadata:
    strategy: str
    gutter_ratio: float | None
    gutter_confidence: float | None
    overlap_pixels: int


@dataclass(frozen=True)
class QualityWarning:
    code: str
    severity: str
    message: str


@dataclass(frozen=True)
class PreprocessedExamPhoto:
    pdf_bytes: bytes
    pages: list[PreprocessedPage]
    detected_quad: list[list[float]]
    spread_size: tuple[int, int]
    split: SplitMetadata
    quality_status: str
    quality_warnings: list[QualityWarning]
    mask: np.ndarray
    warped_spread: np.ndarray
    enhanced_spread: np.ndarray
    debug: dict = field(default_factory=dict)


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


def normalize_line_angle(angle: float) -> float:
    while angle > 90:
        angle -= 180
    while angle < -90:
        angle += 180
    return angle


def line_angle_degrees(start: np.ndarray, end: np.ndarray) -> float:
    return normalize_line_angle(
        float(
            np.degrees(np.arctan2(float(end[1] - start[1]), float(end[0] - start[0])))
        )
    )


def vertical_deviation_degrees(start: np.ndarray, end: np.ndarray) -> float:
    angle = line_angle_degrees(start, end)
    return angle - 90 if angle > 0 else angle + 90


def quad_edge_angle_metadata(points: np.ndarray) -> dict[str, object]:
    rect = order_points(points.astype("float32"))
    top_left, top_right, bottom_right, bottom_left = rect
    top_angle = line_angle_degrees(top_left, top_right)
    bottom_angle = line_angle_degrees(bottom_left, bottom_right)
    left_dev = vertical_deviation_degrees(top_left, bottom_left)
    right_dev = vertical_deviation_degrees(top_right, bottom_right)
    return {
        "top_angle": round(top_angle, 3),
        "bottom_angle": round(bottom_angle, 3),
        "left_vertical_dev": round(left_dev, 3),
        "right_vertical_dev": round(right_dev, 3),
        "mean_horizontal_angle": round(float(np.mean([top_angle, bottom_angle])), 3),
        "mean_vertical_dev": round(float(np.mean([left_dev, right_dev])), 3),
    }


def four_point_transform_with_matrix(
    image: np.ndarray, points: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
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
    return cv2.warpPerspective(image, matrix, (max_width, max_height)), matrix


def four_point_transform(image: np.ndarray, points: np.ndarray) -> np.ndarray:
    warped, _matrix = four_point_transform_with_matrix(image, points)
    return warped


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
    for contour in contours[:8]:
        area = cv2.contourArea(contour)
        if area < image_area * 0.15:
            continue
        hull = cv2.convexHull(contour)
        perimeter = cv2.arcLength(hull, True)
        for epsilon in (0.012, 0.018, 0.025, 0.03, 0.04, 0.055):
            approx = cv2.approxPolyDP(hull, epsilon * perimeter, True)
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


def quad_border_touch_count(
    image: np.ndarray, quad: np.ndarray, *, margin_ratio: float = 0.012
) -> int:
    height, width = image.shape[:2]
    margin_x = width * margin_ratio
    margin_y = height * margin_ratio
    min_x, min_y, max_x, max_y = quad_bounds(quad)
    return sum(
        (
            min_x <= margin_x,
            min_y <= margin_y,
            max_x >= width - 1 - margin_x,
            max_y >= height - 1 - margin_y,
        )
    )


def is_full_frame_quad(image: np.ndarray, quad: np.ndarray) -> bool:
    height, width = image.shape[:2]
    min_x, min_y, max_x, max_y = quad_bounds(quad)
    area_ratio = ((max_x - min_x) * (max_y - min_y)) / max(1, width * height)
    return area_ratio >= 0.94 and quad_border_touch_count(image, quad) >= 3


def add_content_preserving_margin(image: np.ndarray, quad: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    rect = order_points(quad).copy()
    top_left, top_right, bottom_right, bottom_left = rect

    is_landscape_spread = width >= height * 1.2
    top_y = min(float(top_left[1]), float(top_right[1]))
    quad_height = max(
        float(np.linalg.norm(top_left - bottom_left)),
        float(np.linalg.norm(top_right - bottom_right)),
        1.0,
    )
    if is_landscape_spread and top_y > height * 0.08:
        # A dim or shadowed page top often disappears from the color mask. Extend
        # the detected lower-page polygon back towards the camera-visible top
        # edge instead of silently cropping the question header.
        top_ratio = min(0.55, max(0.2, (top_y - height * 0.035) / quad_height))
    else:
        top_ratio = 0.06
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
    if is_full_frame_quad(image, quad):
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

    left_quad = add_content_preserving_margin(image, left_quad)
    right_quad = add_content_preserving_margin(image, right_quad)
    left_quad = order_points(left_quad)
    right_quad = order_points(right_quad)
    # Brightness masks commonly detect only the printed center of a shadowed
    # page. Preserve the complete gutter-facing answer area and make the top
    # page edge conservative before perspective warping.
    inner_overlap = max(20, int(width * 0.025))
    left_inner_x = min(width - 1, center + inner_overlap)
    right_inner_x = max(0, center - inner_overlap)
    conservative_top = max(
        0.0,
        min(
            float(left_quad[0][1]),
            float(left_quad[1][1]),
            float(right_quad[0][1]),
            float(right_quad[1][1]),
        ),
    )
    left_quad[0][1] = conservative_top
    left_quad[1] = [left_inner_x, conservative_top]
    left_quad[2][0] = left_inner_x
    right_quad[0] = [right_inner_x, conservative_top]
    right_quad[3][0] = right_inner_x
    right_quad[1][1] = conservative_top
    left_warped, left_matrix = four_point_transform_with_matrix(image, left_quad)
    right_warped, right_matrix = four_point_transform_with_matrix(image, right_quad)
    left = enhance_page(left_warped)
    right = enhance_page(right_warped)
    left_page = PreprocessedPage(
        name="page_1_left.jpg",
        image=left,
        x_start=0,
        x_end=left.shape[1],
        source_quad=left_quad.round(2).tolist(),
        homography=left_matrix.round(8).tolist(),
    )
    right_page = PreprocessedPage(
        name="page_2_right.jpg",
        image=right,
        x_start=left.shape[1],
        x_end=left.shape[1] + right.shape[1],
        source_quad=right_quad.round(2).tolist(),
        homography=right_matrix.round(8).tolist(),
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


def rotate_clockwise(image: np.ndarray, rotation: int) -> np.ndarray:
    if rotation == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    if rotation == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    if rotation == 270:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return image


def rotate_bound_with_background(
    image: np.ndarray,
    angle: float,
    *,
    background: tuple[int, int, int] = (255, 255, 255),
) -> np.ndarray:
    height, width = image.shape[:2]
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    cos = abs(matrix[0, 0])
    sin = abs(matrix[0, 1])
    next_width = int((height * sin) + (width * cos))
    next_height = int((height * cos) + (width * sin))
    matrix[0, 2] += (next_width / 2.0) - center[0]
    matrix[1, 2] += (next_height / 2.0) - center[1]
    return cv2.warpAffine(
        image,
        matrix,
        (next_width, next_height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=background,
    )


def estimate_horizontal_text_skew(
    image: np.ndarray,
) -> tuple[float | None, dict[str, object]]:
    """Estimate small residual skew from printed horizontal text/ruled lines.

    Perspective correction makes the paper rectangular, but manual corners and
    slightly curved pages can still leave text baselines tilted by a degree or
    two. Use only near-horizontal Hough segments and a length-weighted median so
    handwriting strokes and vertical separators do not dominate the estimate.
    """

    height, width = image.shape[:2]
    if width < 80 or height < 80:
        return None, {"status": "skipped", "reason": "image_too_small"}

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    scale = min(1200 / max(height, width), 1.0)
    if scale < 1.0:
        gray = cv2.resize(
            gray,
            (max(1, int(width * scale)), max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    gray_height, gray_width = gray.shape[:2]

    # Ignore page borders and dark outer margins; only text area contributes.
    top = int(gray_height * 0.04)
    bottom = int(gray_height * 0.96)
    left = int(gray_width * 0.04)
    right = int(gray_width * 0.96)
    roi = gray[top:bottom, left:right]
    if roi.size == 0:
        return None, {"status": "skipped", "reason": "empty_roi"}

    blurred = cv2.GaussianBlur(roi, (3, 3), 0)
    edges = cv2.Canny(blurred, 50, 150, apertureSize=3)
    min_line_length = max(45, int(gray_width * 0.08))
    max_line_gap = max(8, int(gray_width * 0.015))
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=max(35, int(gray_width * 0.035)),
        minLineLength=min_line_length,
        maxLineGap=max_line_gap,
    )
    if lines is None:
        return None, {
            "status": "skipped",
            "reason": "no_hough_lines",
            "line_count": 0,
        }

    weighted_angles: list[tuple[float, float]] = []
    for line in lines[:, 0]:
        x1, y1, x2, y2 = [float(value) for value in line]
        dx = x2 - x1
        dy = y2 - y1
        length = float(np.hypot(dx, dy))
        if length < min_line_length:
            continue
        angle = float(np.degrees(np.arctan2(dy, dx)))
        if angle > 90:
            angle -= 180
        if angle < -90:
            angle += 180
        if abs(angle) <= 8:
            # Long printed baselines are more reliable than short handwriting
            # strokes, but cap the weight to avoid one table line dominating.
            weighted_angles.append((angle, min(length, gray_width * 0.45)))

    if len(weighted_angles) < 4:
        return None, {
            "status": "skipped",
            "reason": "insufficient_horizontal_lines",
            "line_count": len(weighted_angles),
        }

    weighted_angles.sort(key=lambda item: item[0])
    total_weight = sum(weight for _angle, weight in weighted_angles)
    midpoint_weight = total_weight / 2.0
    accumulated = 0.0
    median_angle = weighted_angles[len(weighted_angles) // 2][0]
    for angle, weight in weighted_angles:
        accumulated += weight
        if accumulated >= midpoint_weight:
            median_angle = angle
            break

    # Report a robust spread for debugging. Very scattered line angles mean the
    # page contains too much handwriting/noise to trust deskew.
    raw_angles = np.array(
        [angle for angle, _weight in weighted_angles], dtype=np.float32
    )
    angle_iqr = float(np.percentile(raw_angles, 75) - np.percentile(raw_angles, 25))
    return median_angle, {
        "status": "estimated",
        "angle": round(float(median_angle), 3),
        "line_count": len(weighted_angles),
        "angle_iqr": round(angle_iqr, 3),
        "scale": round(scale, 4),
    }


def projection_deskew_score(image: np.ndarray) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]
    scale = min(1000 / max(height, width), 1.0)
    if scale < 1.0:
        gray = cv2.resize(
            gray,
            (max(1, int(width * scale)), max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    # Dark ink mask. When rows are horizontal, the horizontal projection has
    # sharper peaks and valleys, so its variance rises.
    _threshold, binary = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )
    height, width = binary.shape[:2]
    top = int(height * 0.05)
    bottom = int(height * 0.95)
    left = int(width * 0.04)
    right = int(width * 0.96)
    roi = binary[top:bottom, left:right]
    if roi.size == 0:
        return 0.0
    projection = roi.sum(axis=1).astype(np.float32)
    return float(projection.var() / (projection.mean() + 1e-6))


def estimate_projection_deskew_angle(
    image: np.ndarray,
    *,
    hough_angle: float | None,
    max_abs_angle: float = 3.0,
) -> tuple[float | None, dict[str, object]]:
    zero_score = projection_deskew_score(image)
    candidates: list[tuple[float, float]] = [(0.0, zero_score)]
    for angle in np.arange(-max_abs_angle, max_abs_angle + 0.001, 0.25):
        angle = float(round(float(angle), 3))
        if abs(angle) < 1e-6:
            continue
        rotated = rotate_bound_with_background(image, angle)
        candidates.append((angle, projection_deskew_score(rotated)))

    best_angle, best_score = max(candidates, key=lambda item: item[1])
    if hough_angle is not None and abs(hough_angle) >= 0.35:
        same_sign_candidates = [
            item
            for item in candidates
            if abs(item[0]) >= 0.35 and np.sign(item[0]) == np.sign(hough_angle)
        ]
        if same_sign_candidates:
            same_sign_angle, same_sign_score = max(
                same_sign_candidates,
                key=lambda item: item[1],
            )
            # Projection scores can be almost symmetric on dense Chinese text.
            # Prefer the Hough-supported sign only when it is essentially tied.
            if same_sign_score >= best_score * 0.97:
                best_angle, best_score = same_sign_angle, same_sign_score
    improvement = (best_score / zero_score) if zero_score > 1e-6 else 1.0
    metadata = {
        "zero_score": round(zero_score, 3),
        "best_score": round(best_score, 3),
        "best_angle": round(best_angle, 3),
        "improvement": round(improvement, 3),
        "candidate_count": len(candidates),
    }
    if abs(best_angle) < 0.35 or improvement < 1.08:
        return None, {
            **metadata,
            "status": "skipped",
            "reason": "weak_projection_improvement",
        }
    return best_angle, {
        **metadata,
        "status": "estimated",
    }


def estimate_vertical_line_skew(
    image: np.ndarray,
) -> tuple[float | None, dict[str, object]]:
    height, width = image.shape[:2]
    if width < 80 or height < 80:
        return None, {"status": "skipped", "reason": "image_too_small"}

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    scale = min(1200 / max(height, width), 1.0)
    if scale < 1.0:
        gray = cv2.resize(
            gray,
            (max(1, int(width * scale)), max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    gray_height, gray_width = gray.shape[:2]
    top = int(gray_height * 0.04)
    bottom = int(gray_height * 0.96)
    left = int(gray_width * 0.04)
    right = int(gray_width * 0.96)
    roi = gray[top:bottom, left:right]
    if roi.size == 0:
        return None, {"status": "skipped", "reason": "empty_roi"}

    blurred = cv2.GaussianBlur(roi, (3, 3), 0)
    edges = cv2.Canny(blurred, 50, 150, apertureSize=3)
    min_line_length = max(45, int(gray_height * 0.08))
    max_line_gap = max(8, int(gray_height * 0.015))
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=max(35, int(gray_height * 0.035)),
        minLineLength=min_line_length,
        maxLineGap=max_line_gap,
    )
    if lines is None:
        return None, {
            "status": "skipped",
            "reason": "no_hough_lines",
            "line_count": 0,
        }

    weighted_devs: list[tuple[float, float]] = []
    for line in lines[:, 0]:
        x1, y1, x2, y2 = [float(value) for value in line]
        dx = x2 - x1
        dy = y2 - y1
        length = float(np.hypot(dx, dy))
        if length < min_line_length:
            continue
        angle = float(np.degrees(np.arctan2(dy, dx)))
        if angle > 90:
            angle -= 180
        if angle < -90:
            angle += 180
        if abs(abs(angle) - 90) <= 8:
            dev = angle - 90 if angle > 0 else angle + 90
            weighted_devs.append((dev, min(length, gray_height * 0.45)))

    if len(weighted_devs) < 4:
        return None, {
            "status": "skipped",
            "reason": "insufficient_vertical_lines",
            "line_count": len(weighted_devs),
        }

    weighted_devs.sort(key=lambda item: item[0])
    total_weight = sum(weight for _dev, weight in weighted_devs)
    midpoint_weight = total_weight / 2.0
    accumulated = 0.0
    median_dev = weighted_devs[len(weighted_devs) // 2][0]
    for dev, weight in weighted_devs:
        accumulated += weight
        if accumulated >= midpoint_weight:
            median_dev = dev
            break

    raw_devs = np.array([dev for dev, _weight in weighted_devs], dtype=np.float32)
    dev_iqr = float(np.percentile(raw_devs, 75) - np.percentile(raw_devs, 25))
    return median_dev, {
        "status": "estimated",
        "dev": round(float(median_dev), 3),
        "line_count": len(weighted_devs),
        "dev_iqr": round(dev_iqr, 3),
        "scale": round(scale, 4),
    }


def apply_vertical_shear(
    image: np.ndarray,
    *,
    max_abs_dev: float = 3.0,
) -> tuple[np.ndarray, dict[str, object]]:
    started = time.perf_counter()
    dev, estimate_meta = estimate_vertical_line_skew(image)
    metadata: dict[str, object] = {
        **estimate_meta,
        "applied_factor": 0.0,
        "elapsed_ms": 0,
    }
    if dev is None:
        metadata["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        return image, metadata
    if abs(dev) < 0.35:
        metadata.update(
            {
                "status": "already_plumb",
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            }
        )
        return image, metadata
    if abs(dev) > max_abs_dev:
        metadata.update(
            {
                "status": "rejected",
                "reason": "dev_out_of_range",
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            }
        )
        return image, metadata

    factor = float(np.tan(np.deg2rad(dev)))
    height, width = image.shape[:2]
    new_width = int(width + abs(factor) * height) + 10
    matrix = np.array([[1.0, factor, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)
    if factor < 0:
        matrix[0, 2] = abs(factor) * height
    sheared = cv2.warpAffine(
        image,
        matrix,
        (new_width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )
    metadata.update(
        {
            "status": "applied",
            "applied_factor": round(factor, 5),
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
    )
    return sheared, metadata


def fine_deskew_page(image: np.ndarray) -> tuple[np.ndarray, dict[str, object]]:
    started = time.perf_counter()
    angle, estimate_meta = estimate_horizontal_text_skew(image)
    projection_angle, projection_meta = estimate_projection_deskew_angle(
        image,
        hough_angle=angle,
    )
    metadata: dict[str, object] = {
        **estimate_meta,
        "projection": projection_meta,
        "applied_angle": 0.0,
        "elapsed_ms": 0,
    }
    chosen_angle = projection_angle if projection_angle is not None else angle
    metadata["chosen_angle_source"] = (
        "projection" if projection_angle is not None else "hough"
    )
    if chosen_angle is None:
        rotated = image
        metadata["rotation_status"] = "skipped"
    elif abs(chosen_angle) < 0.35:
        rotated = image
        metadata["rotation_status"] = "already_level"
    elif abs(chosen_angle) > 6:
        metadata.update(
            {
                "status": "rejected",
                "reason": "angle_out_of_range",
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            }
        )
        return image, metadata
    else:
        candidates: list[tuple[float, np.ndarray, float]] = [
            (0.0, image, abs(chosen_angle))
        ]
        # Try the selected direction and one half-step. The half-step protects
        # against projection over-rotation on noisy handwritten pages.
        candidate_angles = [chosen_angle]
        if abs(chosen_angle) >= 0.8:
            candidate_angles.append(chosen_angle * 0.5)
        for candidate_angle in candidate_angles:
            candidate = rotate_bound_with_background(image, candidate_angle)
            residual, _residual_meta = estimate_horizontal_text_skew(candidate)
            candidates.append(
                (
                    candidate_angle,
                    candidate,
                    abs(float(residual))
                    if residual is not None
                    else abs(candidate_angle),
                )
            )

        applied_angle, rotated, residual_abs = min(candidates, key=lambda item: item[2])
        if applied_angle == 0.0 or residual_abs > abs(chosen_angle) - 0.2:
            rotated = image
            metadata.update(
                {
                    "rotation_status": "kept_original",
                    "residual_abs": round(residual_abs, 3),
                }
            )
        else:
            metadata.update(
                {
                    "rotation_status": "applied",
                    "applied_angle": round(float(applied_angle), 3),
                    "residual_abs": round(residual_abs, 3),
                }
            )

    sheared, shear_meta = apply_vertical_shear(rotated)
    metadata.update(
        {
            "status": "applied",
            "shear": shear_meta,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
    )
    return sheared, metadata


def encode_orientation_candidate(image: np.ndarray) -> str:
    height, width = image.shape[:2]
    scale = min(900 / max(height, width), 1.0)
    preview = image
    if scale < 1:
        preview = cv2.resize(
            image,
            (max(1, int(width * scale)), max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    ok, buffer = cv2.imencode(".jpg", preview, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
    if not ok:
        raise PhotoPreprocessingError("Could not encode orientation candidate")
    return base64.b64encode(buffer).decode("ascii")


def normalize_reading_orientation(
    image: np.ndarray,
) -> tuple[np.ndarray, dict[str, object]]:
    """Rotate a perspective-corrected page so Chinese horizontal text is readable.

    Four-corner homography only straightens the paper plane; it does not know
    which paper edge is the semantic top of the exam page. The reference JS
    algorithm solved this by showing four rotated candidates to the vision
    model. Keep the same approach here, with a stricter prompt that judges text
    reading direction instead of the paper outline.
    """

    started = time.perf_counter()
    metadata: dict[str, object] = {
        "rotation": 0,
        "status": "skipped",
        "elapsed_ms": 0,
    }
    if not settings.PROVIDER_FLUXNODE_GEMINI_API_KEY:
        metadata["reason"] = "fluxnode_gemini_not_configured"
        return image, metadata

    prompt = (
        "下面是同一张中文试卷页的 4 个旋转候选图。请只判断“中文横排文字是否能像正常试卷一样"
        "从左到右、从上到下阅读”。不要按纸张外框方向判断；如果标题或正文是竖着的、侧着的、"
        "倒着的，就不是正确方向。请选择唯一正确候选，返回 JSON："
        '{"rotation":0|90|180|270,"reason":"简短中文原因"}。'
        "rotation 是程序应该对当前图片顺时针旋转的角度。"
    )
    content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
    for rotation in (0, 90, 180, 270):
        candidate = rotate_clockwise(image, rotation)
        content.extend(
            [
                {"type": "text", "text": f"候选 {rotation}°"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/jpeg;base64,"
                        + encode_orientation_candidate(candidate)
                    },
                },
            ]
        )

    try:
        parsed, used_model, model_elapsed_ms = call_json_model(
            provider=settings.VISION_DEFAULT_PROVIDER,
            model=settings.VISION_DEFAULT_MODEL,
            fallback_models=[],
            messages=[{"role": "user", "content": content}],
            # Rotation is applied by OpenCV; only the optional reading-direction
            # judgment uses a visual model and follows the visual route policy.
            workflow_purpose="region_detection",
        )
    except (PhotoPreprocessingError, VisionGradingError) as exc:
        metadata.update(
            {
                "status": "failed",
                "reason": str(exc),
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            }
        )
        return image, metadata

    rotation = parsed.get("rotation", 0)
    try:
        rotation = int(rotation)
    except (TypeError, ValueError):
        rotation = 0
    if rotation not in {0, 90, 180, 270}:
        rotation = 0

    metadata.update(
        {
            "rotation": rotation,
            "status": "applied" if rotation else "already_upright",
            "reason": str(parsed.get("reason") or ""),
            "model": used_model,
            "model_elapsed_ms": model_elapsed_ms,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
    )
    return rotate_clockwise(image, rotation), metadata


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
    # Keep only a narrow seam buffer. The previous 2.5% overlap preserved
    # gutter-side handwriting but caused the opposite page's printed content to
    # leak into both crops on real photographed spreads. A small adaptive
    # overlap still protects answers written immediately beside the fold while
    # preventing cross-page OCR contamination.
    overlap = max(6, int(width * 0.004))
    left_start = 0
    left_end = min(width, center + overlap)
    right_start = max(0, center - overlap)
    right_end = width
    left = image[:, left_start:left_end]
    right = image[:, right_start:right_end]
    return [
        PreprocessedPage(
            name="page_1_left.jpg", image=left, x_start=left_start, x_end=left_end
        ),
        PreprocessedPage(
            name="page_2_right.jpg", image=right, x_start=right_start, x_end=right_end
        ),
    ], SplitMetadata(
        strategy="detected_gutter" if confidence >= 0.12 else "center_fallback",
        gutter_ratio=round(gutter_ratio, 4),
        gutter_confidence=round(confidence, 4),
        overlap_pixels=overlap,
    )


def apply_fine_deskew_to_pages(
    pages: list[PreprocessedPage],
) -> tuple[list[PreprocessedPage], list[dict[str, object]], float]:
    deskew_started = time.perf_counter()
    deskew_attempts: list[dict[str, object]] = []
    deskewed_pages: list[PreprocessedPage] = []
    for _index, page in enumerate(pages, start=1):
        deskewed, deskew_meta = fine_deskew_page(page.image)
        deskew_attempts.append(
            {
                "name": page.name,
                **deskew_meta,
            }
        )
        deskewed_pages.append(
            PreprocessedPage(
                name=page.name,
                image=deskewed,
                # These coordinates describe the crop in the source spread.
                # Fine deskew may change output width, but must not erase the
                # gutter overlap metadata used for traceability and tests.
                x_start=page.x_start,
                x_end=page.x_end,
                source_quad=page.source_quad,
                homography=page.homography,
                quality={
                    **page.quality,
                    "deskew": deskew_meta,
                },
            )
        )
    return (
        deskewed_pages,
        deskew_attempts,
        round((time.perf_counter() - deskew_started) * 1000, 1),
    )


def estimate_sharpness(image: np.ndarray) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def edge_ink_ratio(page: np.ndarray, *, side: str) -> float:
    gray = cv2.cvtColor(page, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]
    band = max(8, int(min(height, width) * 0.035))
    if side == "top":
        roi = gray[:band, :]
    elif side == "bottom":
        roi = gray[-band:, :]
    elif side == "left":
        roi = gray[:, :band]
    elif side == "right":
        roi = gray[:, -band:]
    else:
        raise ValueError(f"Unknown edge side: {side}")
    return float((roi < 80).mean())


def build_quality_warnings(
    *,
    original: np.ndarray,
    pages: list[PreprocessedPage],
    split: SplitMetadata,
    partial_landscape: bool,
) -> list[QualityWarning]:
    warnings: list[QualityWarning] = []
    sharpness = estimate_sharpness(original)
    if sharpness < 35:
        warnings.append(
            QualityWarning(
                code="low_sharpness",
                severity="warning",
                message="Uploaded photo appears blurry; OCR and registration may be unreliable.",
            )
        )

    if split.strategy == "center_fallback":
        warnings.append(
            QualityWarning(
                code="low_gutter_confidence",
                severity="warning",
                message="Two-page split used center fallback because gutter confidence was low.",
            )
        )
    elif (
        split.gutter_confidence is not None
        and split.gutter_confidence < 0.2
        and len(pages) == 2
    ):
        warnings.append(
            QualityWarning(
                code="low_gutter_confidence",
                severity="warning",
                message="Detected two-page gutter has low confidence.",
            )
        )

    if split.strategy == "split_half_page_fallback":
        warnings.append(
            QualityWarning(
                code="split_half_page_fallback",
                severity="warning",
                message="Initial spread detection was incomplete; pages were recovered from left/right halves.",
            )
        )
    elif partial_landscape:
        warnings.append(
            QualityWarning(
                code="partial_spread_recovered",
                severity="info",
                message="Initial landscape detection looked partial and was recovered with fallback detection.",
            )
        )

    warnings.extend(build_page_quality_warnings(pages))
    return warnings


def build_page_quality_warnings(
    pages: list[PreprocessedPage],
) -> list[QualityWarning]:
    warnings: list[QualityWarning] = []
    for page in pages:
        height, width = page.image.shape[:2]
        aspect_ratio = width / height
        if aspect_ratio < 0.45 or aspect_ratio > 1.05:
            warnings.append(
                QualityWarning(
                    code="page_aspect_outlier",
                    severity="warning",
                    message=f"{page.name} has unusual page aspect ratio {aspect_ratio:.2f}.",
                )
            )
        for side in ("top", "bottom", "left", "right"):
            if edge_ink_ratio(page.image, side=side) > 0.18:
                warnings.append(
                    QualityWarning(
                        code=f"content_near_{side}_edge",
                        severity="warning",
                        message=f"{page.name} has dark content near the {side} edge; crop should be reviewed.",
                    )
                )
                break

    return warnings


def quality_status_from_warnings(warnings: list[QualityWarning]) -> str:
    if any(warning.severity == "warning" for warning in warnings):
        return "review"
    return "pass"


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


def expand_page_quad(
    image: np.ndarray,
    quad: np.ndarray,
    *,
    page_index: int,
    page_count: int,
    split_axis: str = "horizontal",
    margin_mode: str = "conservative",
) -> np.ndarray:
    height, width = image.shape[:2]
    ordered = order_points(quad.astype("float32"))
    expanded = ordered.copy()
    if margin_mode == "minimal":
        vertical_margin = max(2.0, height * 0.004)
        outer_margin = max(2.0, width * 0.004)
        inner_margin = max(4.0, width * 0.004)
    elif margin_mode == "safe":
        vertical_margin = max(16.0, height * 0.06)
        outer_margin = max(16.0, width * 0.06)
        inner_margin = max(10.0, width * 0.015)
    else:
        vertical_margin = max(12.0, height * 0.045)
        outer_margin = max(12.0, width * 0.045)
        inner_margin = max(8.0, width * 0.008)
    expanded[[0, 1], 1] -= vertical_margin
    expanded[[2, 3], 1] += vertical_margin
    if page_count == 1:
        expanded[[0, 3], 0] -= outer_margin
        expanded[[1, 2], 0] += outer_margin
    elif split_axis == "vertical" and page_index == 0:
        expanded[[0, 1], 1] -= outer_margin
        expanded[[2, 3], 1] += inner_margin
        expanded[[0, 3], 0] -= outer_margin
        expanded[[1, 2], 0] += outer_margin
    elif split_axis == "vertical":
        expanded[[0, 1], 1] -= inner_margin
        expanded[[2, 3], 1] += outer_margin
        expanded[[0, 3], 0] -= outer_margin
        expanded[[1, 2], 0] += outer_margin
    elif page_index == 0:
        expanded[[0, 3], 0] -= outer_margin
        expanded[[1, 2], 0] += inner_margin
    else:
        expanded[[0, 3], 0] -= inner_margin
        expanded[[1, 2], 0] += outer_margin
    expanded[:, 0] = np.clip(expanded[:, 0], 0, width - 1)
    expanded[:, 1] = np.clip(expanded[:, 1], 0, height - 1)
    return expanded.astype("float32")


def infer_manual_split_axis(
    page_quads: list[np.ndarray],
) -> tuple[str, list[np.ndarray]]:
    if len(page_quads) <= 1:
        return "single", page_quads
    centers = [
        (float(quad[:, 0].mean()), float(quad[:, 1].mean()), quad)
        for quad in page_quads
    ]
    x_span = max(center[0] for center in centers) - min(center[0] for center in centers)
    y_span = max(center[1] for center in centers) - min(center[1] for center in centers)
    split_axis = "horizontal" if x_span >= y_span else "vertical"
    return split_axis, [
        item[2]
        for item in sorted(
            centers,
            key=lambda center: center[0] if split_axis == "horizontal" else center[1],
        )
    ]


def midpoint(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return ((a + b) / 2).astype("float32")


def build_opposite_manual_split(
    raw_quads: list[np.ndarray], split_axis: str
) -> tuple[str, list[np.ndarray]] | None:
    if len(raw_quads) != 2 or split_axis not in {"horizontal", "vertical"}:
        return None
    first = order_points(raw_quads[0])
    second = order_points(raw_quads[1])
    if split_axis == "horizontal":
        # Existing input claims left/right pages. Reconstruct the whole paper
        # from the outer edges and try a top/bottom split instead. This catches
        # portrait photos of a spread where the frontend/browser split along
        # the wrong axis.
        full = np.array([first[0], second[1], second[2], first[3]], dtype="float32")
        left_mid = midpoint(full[0], full[3])
        right_mid = midpoint(full[1], full[2])
        return "vertical", [
            np.array([full[0], full[1], right_mid, left_mid], dtype="float32"),
            np.array([left_mid, right_mid, full[2], full[3]], dtype="float32"),
        ]

    # Existing input claims top/bottom pages. Reconstruct the whole paper from
    # outer edges and try a left/right split.
    full = np.array([first[0], first[1], second[2], second[3]], dtype="float32")
    top_mid = midpoint(full[0], full[1])
    bottom_mid = midpoint(full[3], full[2])
    return "horizontal", [
        np.array([full[0], top_mid, bottom_mid, full[3]], dtype="float32"),
        np.array([top_mid, full[1], full[2], bottom_mid], dtype="float32"),
    ]


def manual_page_aspect_score(pages: list[PreprocessedPage]) -> float:
    score = 0.0
    for page in pages:
        height, width = page.image.shape[:2]
        aspect = width / max(1, height)
        if 0.45 <= aspect <= 1.05:
            score += 2.0
        elif 0.35 <= aspect <= 1.35:
            score += 0.5
        else:
            score -= 2.0
    return score


def build_manual_quad_pages(
    *,
    image: np.ndarray,
    raw_quads: list[np.ndarray],
    split_axis: str,
    detector: str,
    margin_mode: str,
) -> tuple[list[PreprocessedPage], list[np.ndarray], list[dict[str, object]], float]:
    ordered_quads = [
        expand_page_quad(
            image,
            quad,
            page_index=index,
            page_count=len(raw_quads),
            split_axis=split_axis,
            margin_mode=margin_mode,
        )
        for index, quad in enumerate(raw_quads)
    ]
    pages: list[PreprocessedPage] = []
    current_x = 0
    orientation_attempts: list[dict[str, object]] = []
    orientation_started = time.perf_counter()
    for index, quad in enumerate(ordered_quads, start=1):
        edge_angles = quad_edge_angle_metadata(quad)
        warped, matrix = four_point_transform_with_matrix(image, quad)
        enhanced = enhance_page(warped)
        oriented, orientation_meta = normalize_reading_orientation(enhanced)
        deskewed, deskew_meta = fine_deskew_page(oriented)
        orientation_attempts.append(
            {
                "name": f"page_{index}.jpg",
                **orientation_meta,
                "quad_edge_angles": edge_angles,
                "deskew": deskew_meta,
            }
        )
        width = deskewed.shape[1]
        pages.append(
            PreprocessedPage(
                name=f"page_{index}.jpg",
                image=deskewed,
                x_start=current_x,
                x_end=current_x + width,
                source_quad=quad.round(2).tolist(),
                homography=matrix.round(8).tolist(),
                quality={
                    "page_detector": detector,
                    "quad_edge_angles": edge_angles,
                    "orientation": orientation_meta,
                    "deskew": deskew_meta,
                },
            )
        )
        current_x += width
    return (
        pages,
        ordered_quads,
        orientation_attempts,
        round((time.perf_counter() - orientation_started) * 1000, 1),
    )


def preprocess_exam_photo_with_page_quads(
    contents: bytes,
    page_quads: list[np.ndarray],
    *,
    detector: str,
    margin_mode: str = "conservative",
    allow_opposite_split: bool = True,
) -> PreprocessedExamPhoto:
    total_started = time.perf_counter()
    image_buffer = np.frombuffer(contents, dtype=np.uint8)
    image = cv2.imdecode(image_buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise PhotoPreprocessingError("Could not decode uploaded image")
    if not page_quads:
        raise PhotoPreprocessingError("No page polygons were provided")

    split_axis, raw_quads = infer_manual_split_axis(page_quads)
    pages, ordered_quads, orientation_attempts, orientation_ms = (
        build_manual_quad_pages(
            image=image,
            raw_quads=raw_quads,
            split_axis=split_axis,
            detector=detector,
            margin_mode=margin_mode,
        )
    )
    chosen_score = manual_page_aspect_score(pages)
    split_axis_candidates = [
        {
            "axis": split_axis,
            "score": chosen_score,
            "page_aspects": [
                round(page.image.shape[1] / max(1, page.image.shape[0]), 3)
                for page in pages
            ],
        }
    ]
    fallback = (
        build_opposite_manual_split(raw_quads, split_axis)
        if allow_opposite_split
        else None
    )
    if fallback is not None and chosen_score < 1.0:
        fallback_axis, fallback_quads = fallback
        (
            fallback_pages,
            fallback_ordered_quads,
            fallback_orientation_attempts,
            fallback_orientation_ms,
        ) = build_manual_quad_pages(
            image=image,
            raw_quads=fallback_quads,
            split_axis=fallback_axis,
            detector=detector,
            margin_mode=margin_mode,
        )
        fallback_score = manual_page_aspect_score(fallback_pages)
        split_axis_candidates.append(
            {
                "axis": fallback_axis,
                "score": fallback_score,
                "page_aspects": [
                    round(page.image.shape[1] / max(1, page.image.shape[0]), 3)
                    for page in fallback_pages
                ],
            }
        )
        if fallback_score > chosen_score:
            split_axis = fallback_axis
            pages = fallback_pages
            ordered_quads = fallback_ordered_quads
            orientation_attempts = fallback_orientation_attempts
            orientation_ms += fallback_orientation_ms

    spread = stitch_debug_spread(pages)
    all_points = np.vstack(ordered_quads).astype("float32")
    outer_quad = cv2.boxPoints(cv2.minAreaRect(all_points))
    split = SplitMetadata(
        strategy="vision_page_polygons" if len(pages) > 1 else "vision_single_page",
        gutter_ratio=0.5 if len(pages) > 1 else None,
        gutter_confidence=1.0,
        overlap_pixels=0,
    )
    quality_warnings = build_quality_warnings(
        original=image,
        pages=pages,
        split=split,
        partial_landscape=False,
    )
    mask = np.zeros(image.shape[:2], dtype=np.uint8)
    return PreprocessedExamPhoto(
        pdf_bytes=encode_pdf(pages),
        pages=pages,
        detected_quad=outer_quad.round(1).tolist(),
        spread_size=(spread.shape[1], spread.shape[0]),
        split=split,
        quality_status=quality_status_from_warnings(quality_warnings),
        quality_warnings=quality_warnings,
        mask=mask,
        warped_spread=spread,
        enhanced_spread=spread,
        debug={
            "engine": "vision_polygon_homography_v1",
            "page_detector": detector,
            "page_count": len(pages),
            "split_axis": split_axis,
            "split_axis_candidates": split_axis_candidates,
            "timings": {
                "orientation_ms": orientation_ms,
                "total_ms": round((time.perf_counter() - total_started) * 1000, 1),
            },
            "orientation_attempts": orientation_attempts,
            "page_transforms": [
                {
                    "name": page.name,
                    "source_quad": page.source_quad,
                    "homography": page.homography,
                    "quad_edge_angles": page.quality.get("quad_edge_angles"),
                }
                for page in pages
            ],
        },
    )


def preprocess_exam_photo_bytes(contents: bytes) -> PreprocessedExamPhoto:
    image_buffer = np.frombuffer(contents, dtype=np.uint8)
    image = cv2.imdecode(image_buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise PhotoPreprocessingError("Could not decode uploaded image")

    quad, mask = find_document_quad(image)
    partial_landscape = is_partial_landscape_detection(image, quad)
    relaxed_rejected = False
    fallback = find_half_page_fallback(image) if partial_landscape else None
    if fallback is not None:
        pages = fallback.pages
        split = SplitMetadata(
            strategy="split_half_page_fallback",
            gutter_ratio=0.5,
            gutter_confidence=0.0,
            overlap_pixels=max(20, int(image.shape[1] * 0.025)),
        )
        quad = fallback.detected_quad
        warped = fallback.warped_spread
        enhanced_spread = fallback.enhanced_spread
        spread_matrix = np.eye(3, dtype="float32")
    else:
        if partial_landscape:
            relaxed_quad = find_relaxed_spread_quad(image)
            if relaxed_quad is not None:
                quad = relaxed_quad
            else:
                relaxed_rejected = True

        quad = add_content_preserving_margin(image, quad)
        warped, spread_matrix = four_point_transform_with_matrix(image, quad)
        enhanced_spread = enhance_page(warped)
        pages, split = split_spread(enhanced_spread)

    pages, deskew_attempts, deskew_ms = apply_fine_deskew_to_pages(pages)

    if split.strategy != "split_half_page_fallback":
        for page in pages:
            page.source_quad.extend(quad.round(2).tolist())
            page.homography.extend(spread_matrix.round(8).tolist())

    pdf_bytes = encode_pdf(pages)
    quality_warnings = build_quality_warnings(
        original=image,
        pages=pages,
        split=split,
        partial_landscape=partial_landscape,
    )
    return PreprocessedExamPhoto(
        pdf_bytes=pdf_bytes,
        pages=pages,
        detected_quad=quad.round(1).tolist(),
        spread_size=(warped.shape[1], warped.shape[0]),
        split=split,
        quality_status=quality_status_from_warnings(quality_warnings),
        quality_warnings=quality_warnings,
        mask=mask,
        warped_spread=warped,
        enhanced_spread=enhanced_spread,
        debug={
            "engine": "opencv_homography_v2",
            "partial_landscape": partial_landscape,
            "relaxed_spread_rejected": relaxed_rejected,
            "full_frame_quad": is_full_frame_quad(image, quad),
            "deskew_attempts": deskew_attempts,
            "timings": {
                "deskew_ms": deskew_ms,
            },
            "page_transforms": [
                {
                    "name": page.name,
                    "source_quad": page.source_quad,
                    "homography": page.homography,
                }
                for page in pages
            ],
        },
    )
