from __future__ import annotations

import time
from dataclasses import replace
from math import atan2, degrees, hypot

import cv2
import numpy as np

from app.services.exam_photo_preprocessing import (
    PhotoPreprocessingError,
    PreprocessedExamPhoto,
    PreprocessedPage,
    add_content_preserving_margin,
    build_page_quality_warnings,
    detect_gutter_ratio,
    encode_pdf,
    enhance_page,
    find_document_quad,
    find_relaxed_spread_quad,
    fine_deskew_page,
    four_point_transform_with_matrix,
    preprocess_exam_photo_with_page_quads,
    rotate_clockwise,
    stitch_debug_spread,
)


def encode_jpeg(image: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    if not ok:
        raise PhotoPreprocessingError("Could not encode rotated scan candidate")
    return buffer.tobytes()


def aspect_penalty(width: int, height: int) -> float:
    aspect = width / max(1, height)
    # Chinese exam pages after split can vary, but a correct page should not be
    # an extremely narrow strip or a wide landscape crop.
    if 0.55 <= aspect <= 1.05:
        return 0.0
    if 0.45 <= aspect <= 1.2:
        return 0.4
    return 1.5


def page_aspect_penalty(page: PreprocessedPage) -> float:
    height, width = page.image.shape[:2]
    return aspect_penalty(width, height)


def score_rectangle_candidate(result: PreprocessedExamPhoto) -> float:
    score = 0.0
    page_count = len(result.pages)
    if page_count == 2:
        score += 6.0
    elif page_count == 1:
        score += 1.0
    else:
        score -= 2.0

    score -= sum(page_aspect_penalty(page) for page in result.pages)
    if result.split.gutter_confidence is not None:
        score += min(1.5, max(0.0, result.split.gutter_confidence) * 1.5)
    if result.split.strategy == "detected_gutter":
        score += 1.0
    if result.quality_status == "pass":
        score += 0.5
    warning_count = sum(
        1 for warning in result.quality_warnings if warning.severity == "warning"
    )
    score -= min(1.5, warning_count * 0.25)
    return score


def score_spread_geometry(
    rectangle_debug: dict[str, object], *, image_area: int
) -> float:
    size = rectangle_debug.get("rectified_spread_size")
    if not isinstance(size, list) or len(size) != 2:
        return 0.0
    try:
        width = int(size[0])
        height = int(size[1])
    except (TypeError, ValueError):
        return 0.0
    if width <= 0 or height <= 0:
        return 0.0
    area_ratio = (width * height) / max(1, image_area)
    aspect = width / max(1, height)
    score = min(3.0, area_ratio * 5.0)
    if aspect >= 1.2:
        score += 1.5
    elif aspect < 0.95:
        score -= 1.0
    confidence = rectangle_debug.get("gutter_confidence")
    if isinstance(confidence, int | float):
        score += max(0.0, min(1.0, float(confidence)))
    return score


def map_warp_rect_to_source(
    inverse_matrix: np.ndarray, points: np.ndarray
) -> np.ndarray:
    mapped = cv2.perspectiveTransform(
        points.astype("float32").reshape(1, -1, 2), inverse_matrix
    ).reshape(-1, 2)
    return mapped.astype("float32")


def detect_fold_split_line(
    spread: np.ndarray, *, fallback_x: int
) -> tuple[float, float, dict[str, object]]:
    """Detect the slanted fold between two pages in the rectified spread.

    A whole-spread homography makes the outer paper frame rectangular, but a
    folded two-page answer sheet is not a single plane. The inner seam often
    remains a slanted line. A vertical gutter crop therefore leaks part of the
    opposite page. Prefer a long near-vertical Hough segment in the central
    spread; fall back to the projection gutter when no reliable fold is found.
    """

    height, width = spread.shape[:2]
    gray = cv2.cvtColor(spread, cv2.COLOR_BGR2GRAY)
    x0 = int(width * 0.18)
    x1 = int(width * 0.72)
    roi = gray[:, x0:x1]
    if roi.size == 0:
        return float(fallback_x), float(fallback_x), {"method": "fallback_empty_roi"}

    blurred = cv2.GaussianBlur(roi, (5, 5), 0)
    edges = cv2.Canny(blurred, 40, 120)
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=max(70, int(height * 0.08)),
        minLineLength=max(120, int(height * 0.55)),
        maxLineGap=max(30, int(height * 0.06)),
    )
    if lines is None:
        return float(fallback_x), float(fallback_x), {"method": "fallback_no_hough"}

    candidates: list[dict[str, float]] = []
    for raw_line in lines[:, 0]:
        x_start, y_start, x_end, y_end = [float(value) for value in raw_line]
        x_start += x0
        x_end += x0
        dx = x_end - x_start
        dy = y_end - y_start
        length = float(hypot(dx, dy))
        if abs(dy) < 1 or length < height * 0.55:
            continue
        angle = float(degrees(atan2(dy, dx)))
        if not 50 <= abs(angle) <= 88:
            continue
        x_top = x_start + (0 - y_start) * dx / dy
        x_bottom = x_start + (height - 1 - y_start) * dx / dy
        if not (-width * 0.05 <= x_top <= width * 0.85):
            continue
        if not (width * 0.25 <= x_bottom <= width * 0.85):
            continue
        avg_x = (x_top + x_bottom) / 2.0
        if not (width * 0.24 <= avg_x <= width * 0.62):
            continue
        # Penalize folds that start too far left or end before the central seam.
        # The visible fold can be shorter than the shadow edge; position is more
        # important than raw length, otherwise the left shadow boundary gets
        # selected and the page is cropped.
        score = length * 0.55
        score -= max(0.0, width * 0.24 - x_top) * 2.0
        score -= max(0.0, width * 0.45 - x_bottom) * 1.5
        score -= abs(avg_x - width * 0.40) * 2.0
        candidates.append(
            {
                "x_top": float(x_top),
                "x_bottom": float(x_bottom),
                "angle": angle,
                "length": length,
                "score": score,
                "x_start": x_start,
                "y_start": y_start,
                "x_end": x_end,
                "y_end": y_end,
            }
        )

    if not candidates:
        return float(fallback_x), float(fallback_x), {"method": "fallback_no_candidate"}

    best = max(candidates, key=lambda item: item["score"])
    return (
        best["x_top"],
        best["x_bottom"],
        {
            "method": "hough_fold_line",
            "x_top": round(best["x_top"], 2),
            "x_bottom": round(best["x_bottom"], 2),
            "angle": round(best["angle"], 3),
            "length": round(best["length"], 2),
            "score": round(best["score"], 2),
            "candidate_count": len(candidates),
        },
    )


def build_single_page_quads_from_spread(
    image: np.ndarray,
) -> tuple[list[np.ndarray], dict[str, object]]:
    spread_quad, _mask = find_document_quad(image)
    relaxed_quad = find_relaxed_spread_quad(image)
    if relaxed_quad is not None:
        base_area = abs(cv2.contourArea(spread_quad.astype("float32")))
        relaxed_area = abs(cv2.contourArea(relaxed_quad.astype("float32")))
        if relaxed_area >= base_area * 1.18:
            spread_quad = relaxed_quad
    spread_quad = add_content_preserving_margin(image, spread_quad)
    spread, matrix = four_point_transform_with_matrix(image, spread_quad)
    # detect_gutter_ratio expects a BGR image; use the original rectified spread
    # so its ink/darkness projection sees the real page seam and print.
    gutter_ratio, confidence = detect_gutter_ratio(spread)
    height, width = spread.shape[:2]
    gutter_x = int(width * gutter_ratio)
    fold_top_x, fold_bottom_x, fold_debug = detect_fold_split_line(
        spread,
        fallback_x=gutter_x,
    )
    if (
        fold_debug.get("method") == "hough_fold_line"
        and isinstance(fold_debug.get("angle"), int | float)
        and abs(float(fold_debug["angle"])) > 80
        and confidence < 0.12
    ):
        fold_debug = {
            **fold_debug,
            "method": "projection_gutter_after_text_line_rejection",
            "rejected_hough_reason": "near_vertical_low_gutter_confidence",
            "rejected_x_top": round(float(fold_top_x), 2),
            "rejected_x_bottom": round(float(fold_bottom_x), 2),
        }
        fold_top_x = float(gutter_x)
        fold_bottom_x = float(gutter_x)
    left_page_inner_margin = max(14, int(width * 0.016))
    right_page_inner_margin = max(6, int(width * 0.005))
    inverse = np.linalg.inv(matrix)
    left_rect = np.array(
        [
            [0, 0],
            [max(1, fold_top_x - left_page_inner_margin), 0],
            [max(1, fold_bottom_x - left_page_inner_margin), height - 1],
            [0, height - 1],
        ],
        dtype="float32",
    )
    right_rect = np.array(
        [
            [min(width - 2, fold_top_x + right_page_inner_margin), 0],
            [width - 1, 0],
            [width - 1, height - 1],
            [min(width - 2, fold_bottom_x + right_page_inner_margin), height - 1],
        ],
        dtype="float32",
    )
    return [
        map_warp_rect_to_source(inverse, left_rect),
        map_warp_rect_to_source(inverse, right_rect),
    ], {
        "spread_quad": spread_quad.round(2).tolist(),
        "rectified_spread_size": [int(width), int(height)],
        "gutter_ratio": round(float(gutter_ratio), 4),
        "gutter_confidence": round(float(confidence), 4),
        "gutter_x": int(gutter_x),
        "left_page_inner_margin_pixels": int(left_page_inner_margin),
        "right_page_inner_margin_pixels": int(right_page_inner_margin),
        "fold_line": fold_debug,
    }


def preprocess_rectangle_single_page_candidate(
    image: np.ndarray,
) -> tuple[PreprocessedExamPhoto, dict[str, object]]:
    page_quads, debug = build_single_page_quads_from_spread(image)
    result = preprocess_exam_photo_with_page_quads(
        encode_jpeg(image),
        page_quads,
        detector="rectangle_frame_spread_gutter_v1",
        margin_mode="conservative",
        allow_opposite_split=False,
    )
    return result, {
        **debug,
        "page_quads": [quad.round(2).tolist() for quad in page_quads],
    }


def build_single_page_quad(
    image: np.ndarray,
) -> tuple[list[np.ndarray], dict[str, object]]:
    """Build a one-page candidate for rotation/candidate selection.

    The spread detector intentionally partitions a wide frame into two
    candidates. That is useful for an actual open spread, but it can also
    split one portrait sheet after a 90-degree rotation. Keeping a genuine
    single-page candidate in the same scoring pool prevents that false split.
    """

    quad, _mask = find_document_quad(image)
    quad = add_content_preserving_margin(image, quad)
    return [quad], {
        "page_count": 1,
        "single_page_quad": quad.round(2).tolist(),
    }


def score_quads_geometry(
    image: np.ndarray,
    page_quads: list[np.ndarray],
    rectangle_debug: dict[str, object],
) -> tuple[float, list[list[int]]]:
    score = 6.0 if len(page_quads) == 2 else 1.0
    page_sizes: list[list[int]] = []
    for quad in page_quads:
        warped, _matrix = four_point_transform_with_matrix(image, quad)
        # Keep scoring deterministic and fast. Enhancement is local OpenCV only;
        # no orientation model is called at candidate-selection time.
        enhanced = enhance_page(warped)
        height, width = enhanced.shape[:2]
        page_sizes.append([int(width), int(height)])
        score -= aspect_penalty(width, height)
        page_aspect = width / max(1, height)
        if len(page_quads) == 2:
            # A genuine exam spread produces two portrait pages after the
            # homography. When a portrait single page is rotated into a
            # landscape frame, the false split usually creates square or
            # landscape "pages". Penalize that geometry strongly so the
            # rotation search does not turn one page into two.
            if page_aspect > 1.0:
                score -= (page_aspect - 1.0) * 12.0
            if page_aspect > 1.05:
                score -= 2.0
        else:
            # A normal exam sheet is portrait after correction. Give a
            # single-page portrait candidate enough prior weight to beat a
            # spurious two-way split of the same sheet.
            if 0.45 <= page_aspect <= 0.9:
                score += 5.0
            elif page_aspect > 1.0:
                score -= (page_aspect - 1.0) * 10.0
    score += score_spread_geometry(
        rectangle_debug,
        image_area=int(image.shape[0] * image.shape[1]),
    )
    return score, page_sizes


def paper_score_mask(image: np.ndarray) -> np.ndarray:
    """Return a conservative paper/background mask for already rectified pages.

    The auto-rectifier intentionally keeps extra content around the detected
    page quadrilateral to avoid cutting handwritten answers. That can leave the
    green/black desk visible after the perspective transform. This mask is used
    only as a post-processing crop on the rectified page image: paper is usually
    bright and low-saturation, while the desk/background is darker or much more
    saturated.
    """

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    _hue, saturation, value = cv2.split(hsv)
    return (
        ((value > 135) & (saturation < 70)) | ((value > 155) & (saturation < 95))
    ).astype("uint8")


def smooth_coverage(values: np.ndarray, window: int) -> np.ndarray:
    if window <= 1:
        return values
    kernel = np.ones(window, dtype="float32") / float(window)
    return np.convolve(values, kernel, mode="same")


def crop_page_background(
    image: np.ndarray,
) -> tuple[np.ndarray, dict[str, object]]:
    """Crop obvious non-paper background from a rectified single page.

    This is deliberately generic:
    - no filename, question number, or coordinate assumptions;
    - uses smoothed row/column paper coverage;
    - rejects the crop if it would remove too much of the page.
    """

    height, width = image.shape[:2]
    if height < 80 or width < 80:
        return image, {"status": "skipped_small_page"}

    mask = paper_score_mask(image)
    window = max(31, int(min(height, width) * 0.065))
    if window % 2 == 0:
        window += 1

    row_coverage = smooth_coverage(mask.mean(axis=1), window)
    col_coverage = smooth_coverage(mask.mean(axis=0), window)
    rows = np.where(row_coverage > 0.45)[0]
    cols = np.where(col_coverage > 0.45)[0]
    if rows.size == 0 or cols.size == 0:
        return image, {"status": "skipped_no_paper_band", "window": int(window)}

    pad_y = max(8, int(height * 0.015))
    pad_x = max(8, int(width * 0.015))
    y0 = max(0, int(rows[0]) - pad_y)
    y1 = min(height, int(rows[-1]) + pad_y + 1)
    x0 = max(0, int(cols[0]) - pad_x)
    x1 = min(width, int(cols[-1]) + pad_x + 1)

    crop_width = x1 - x0
    crop_height = y1 - y0
    if crop_width < width * 0.55 or crop_height < height * 0.55:
        return image, {
            "status": "rejected_too_small",
            "window": int(window),
            "bbox": [int(x0), int(y0), int(crop_width), int(crop_height)],
            "orig_size": [int(width), int(height)],
        }

    # Ignore no-op crops; keeping the original avoids accumulating JPEG/canvas
    # differences when the detector already produced a clean page.
    if (
        x0 <= width * 0.01
        and y0 <= height * 0.01
        and x1 >= width * 0.99
        and y1 >= height * 0.99
    ):
        return image, {
            "status": "skipped_negligible",
            "window": int(window),
            "bbox": [int(x0), int(y0), int(crop_width), int(crop_height)],
            "orig_size": [int(width), int(height)],
        }

    cropped = image[y0:y1, x0:x1].copy()
    return cropped, {
        "status": "cropped",
        "window": int(window),
        "bbox": [int(x0), int(y0), int(crop_width), int(crop_height)],
        "orig_size": [int(width), int(height)],
        "new_size": [int(cropped.shape[1]), int(cropped.shape[0])],
        "row_first_last": [int(rows[0]), int(rows[-1])],
        "col_first_last": [int(cols[0]), int(cols[-1])],
    }


def postprocess_rectified_pages(
    pages: list[PreprocessedPage],
) -> tuple[list[PreprocessedPage], list[dict[str, object]], float]:
    started = time.perf_counter()
    processed_pages: list[PreprocessedPage] = []
    crop_debug: list[dict[str, object]] = []
    current_x = 0
    for page in pages:
        cropped, crop_meta = crop_page_background(page.image)
        deskewed = cropped
        deskew_meta: dict[str, object] | None = None
        if crop_meta.get("status") == "cropped":
            deskewed, deskew_meta = fine_deskew_page(cropped)

        quality = {
            **page.quality,
            "paper_background_crop": crop_meta,
        }
        if deskew_meta is not None:
            quality["post_crop_deskew"] = deskew_meta

        width = deskewed.shape[1]
        processed_pages.append(
            replace(
                page,
                image=deskewed,
                x_start=current_x,
                x_end=current_x + width,
                quality=quality,
            )
        )
        current_x += width
        crop_debug.append(
            {
                "name": page.name,
                **crop_meta,
                "post_crop_deskew": deskew_meta,
            }
        )
    return (
        processed_pages,
        crop_debug,
        round((time.perf_counter() - started) * 1000, 1),
    )


def restore_page_reading_order(
    pages: list[PreprocessedPage],
    *,
    input_rotation: int,
) -> list[PreprocessedPage]:
    """Map page order back to the original camera reading direction."""

    ordered = list(reversed(pages)) if input_rotation == 180 else list(pages)
    restored: list[PreprocessedPage] = []
    current_x = 0
    for index, page in enumerate(ordered, start=1):
        restored.append(
            replace(
                page,
                name=f"page_{index}.jpg",
                x_start=current_x,
                x_end=current_x + page.image.shape[1],
            )
        )
        current_x += page.image.shape[1]
    return restored


def preprocess_exam_rectangle_rectifier_bytes(contents: bytes) -> PreprocessedExamPhoto:
    """Use the existing rectangle/quad homography pipeline with rotation search.

    This is intentionally not the experimental skill engine. It reuses the
    project's earlier OpenCV rectangle-frame correction and only adds a wrapper
    that tries the four coarse camera orientations before choosing the best
    two-page candidate.
    """

    total_started = time.perf_counter()
    image_buffer = np.frombuffer(contents, dtype=np.uint8)
    image = cv2.imdecode(image_buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise PhotoPreprocessingError("Could not decode scan image")

    candidates: list[dict[str, object]] = []
    source_portrait = image.shape[0] > image.shape[1] * 1.25
    best: (
        tuple[
            float,
            int,
            np.ndarray,
            list[np.ndarray],
            dict[str, object],
            str,
        ]
        | None
    ) = None
    for rotation in (0, 90, 270, 180):
        started = time.perf_counter()
        rotated = rotate_clockwise(image, rotation)
        candidates_for_rotation: list[
            tuple[str, list[np.ndarray], dict[str, object]]
        ] = []
        try:
            single_quads, single_debug = build_single_page_quad(rotated)
            candidates_for_rotation.append(("single_page", single_quads, single_debug))
        except (PhotoPreprocessingError, OSError):
            pass
        try:
            spread_quads, spread_debug = build_single_page_quads_from_spread(rotated)
            candidates_for_rotation.append(
                ("two_page_spread", spread_quads, spread_debug)
            )
        except (PhotoPreprocessingError, OSError):
            pass
        for candidate_kind, page_quads, rectangle_debug in candidates_for_rotation:
            score, page_sizes = score_quads_geometry(
                rotated,
                page_quads,
                rectangle_debug,
            )
            rejection_reason: str | None = None
            if (
                source_portrait
                and rotation in {90, 270}
                and candidate_kind == "two_page_spread"
            ):
                # A portrait upload can be a sideways single page. A
                # geometry-only split after rotating it by 90° is ambiguous,
                # so do not auto-promote that candidate. Such an input can
                # still be handled by the vision page-polygon route when the
                # page count is explicitly observed.
                score -= 100.0
                rejection_reason = "portrait_input_cross_axis_spread_requires_vision"
            candidates.append(
                {
                    "rotation": rotation,
                    "candidate_kind": candidate_kind,
                    "score": round(score, 4),
                    "rectangle_debug": rectangle_debug,
                    "page_count": len(page_quads),
                    "page_sizes": page_sizes,
                    **(
                        {"rejected_reason": rejection_reason}
                        if rejection_reason
                        else {}
                    ),
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                }
            )
            if best is None or score > best[0]:
                best = (
                    score,
                    rotation,
                    rotated,
                    page_quads,
                    rectangle_debug,
                    candidate_kind,
                )

    if best is None:
        raise PhotoPreprocessingError(
            "No rectangle-frame rectification candidate worked"
        )

    (
        best_score,
        best_rotation,
        best_image,
        best_quads,
        best_rectangle_debug,
        best_candidate_kind,
    ) = best
    result = preprocess_exam_photo_with_page_quads(
        encode_jpeg(best_image),
        best_quads,
        detector="rectangle_frame_spread_gutter_v1",
        margin_mode="conservative",
        allow_opposite_split=False,
    )
    pages, background_crop_debug, background_crop_ms = postprocess_rectified_pages(
        result.pages
    )
    pages = restore_page_reading_order(pages, input_rotation=best_rotation)
    warnings = build_page_quality_warnings(pages)
    enhanced_spread = stitch_debug_spread(pages)
    return replace(
        result,
        pdf_bytes=encode_pdf(pages),
        pages=pages,
        quality_status="review"
        if any(warning.severity == "warning" for warning in warnings)
        else result.quality_status,
        quality_warnings=warnings,
        enhanced_spread=enhanced_spread,
        debug={
            **result.debug,
            "engine": "rectangle_frame_rectifier_v1",
            "input_rotation": best_rotation,
            "candidate_kind": best_candidate_kind,
            "page_order": {
                "input_rotation": best_rotation,
                "reversed": best_rotation == 180,
            },
            "candidate_score": round(best_score, 4),
            "paper_background_crop": background_crop_debug,
            "selected_rectangle_debug": {
                **best_rectangle_debug,
                "page_quads": [quad.round(2).tolist() for quad in best_quads],
            },
            "rotation_candidates": candidates,
            "timings": {
                **(result.debug.get("timings") or {}),
                "paper_background_crop_ms": background_crop_ms,
                "total_rectangle_rectifier_ms": round(
                    (time.perf_counter() - total_started) * 1000, 1
                ),
            },
        },
    )
