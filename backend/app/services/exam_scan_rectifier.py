from __future__ import annotations

import time
from dataclasses import dataclass

import cv2
import numpy as np

from app.services.exam_photo_preprocessing import (
    PhotoPreprocessingError,
    PreprocessedExamPhoto,
    PreprocessedPage,
    QualityWarning,
    SplitMetadata,
    build_page_quality_warnings,
    encode_pdf,
    estimate_horizontal_text_skew,
    estimate_sharpness,
    quad_edge_angle_metadata,
)


@dataclass(frozen=True)
class SkillDetectedPage:
    label: str
    quad: np.ndarray
    confidence: float
    debug: dict[str, object]


# The following core functions are a faithful project port of
# exam_scan_rectifier_skill/rectify_exam.py. Keep their thresholds and geometry
# semantics aligned with that file; put project-specific behavior in the
# adapter functions below instead.


def order_points(points: np.ndarray) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float32).reshape(4, 2)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array(
        [
            pts[np.argmin(s)],  # top-left
            pts[np.argmin(d)],  # top-right
            pts[np.argmax(s)],  # bottom-right
            pts[np.argmax(d)],  # bottom-left
        ],
        dtype=np.float32,
    )


def paper_mask(image: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    lightness, a, b = cv2.split(lab)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    _, s, v = cv2.split(hsv)

    # Bright, relatively low-saturation regions are likely paper.
    l_thr = max(120, int(np.percentile(lightness, 45)))
    v_thr = max(110, int(np.percentile(v, 40)))
    mask = ((lightness > l_thr) & (v > v_thr) & (s < 150)).astype(np.uint8) * 255

    h, w = mask.shape
    k = max(9, int(min(h, w) * 0.015) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8), iterations=1)
    return mask


def largest_contour(mask: np.ndarray) -> np.ndarray | None:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    return max(contours, key=cv2.contourArea)


def contour_to_quad(contour: np.ndarray) -> np.ndarray:
    hull = cv2.convexHull(contour)
    peri = cv2.arcLength(hull, True)
    for eps in np.linspace(0.015, 0.08, 20):
        approx = cv2.approxPolyDP(hull, eps * peri, True)
        if len(approx) == 4:
            return order_points(approx.reshape(4, 2))

    # Robust fallback: minimum-area rectangle.
    rect = cv2.minAreaRect(hull)
    box = cv2.boxPoints(rect)
    return order_points(box)


def find_spread_bbox(mask: np.ndarray) -> tuple[int, int, int, int]:
    contour = largest_contour(mask)
    if contour is None:
        return 0, 0, mask.shape[1], mask.shape[0]
    x, y, w, h = cv2.boundingRect(contour)
    pad_x = int(w * 0.02)
    pad_y = int(h * 0.02)
    return (
        max(0, x - pad_x),
        max(0, y - pad_y),
        min(mask.shape[1], x + w + pad_x),
        min(mask.shape[0], y + h + pad_y),
    )


def estimate_gutter(image: np.ndarray, bbox: tuple[int, int, int, int]) -> int:
    x0, y0, x1, y1 = bbox
    gray = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    # Ignore page margins and look around the central 30%.
    c0, c1 = int(w * 0.35), int(w * 0.65)
    band = gray[int(h * 0.08) : int(h * 0.92), c0:c1]
    if band.size == 0:
        return x0 + w // 2
    # Gutter tends to be darker and/or have a strong vertical edge.
    darkness = 255.0 - band.mean(axis=0)
    gx = np.abs(cv2.Sobel(band, cv2.CV_32F, 1, 0, ksize=3)).mean(axis=0)
    score = cv2.GaussianBlur(
        (darkness + 0.35 * gx).reshape(1, -1), (31, 1), 0
    ).ravel()
    return x0 + c0 + int(np.argmax(score))


def detect_page_quad(
    image: np.ndarray, side: str, gutter_x: int, overlap_ratio: float = 0.05
) -> np.ndarray:
    h, w = image.shape[:2]
    overlap = int(w * overlap_ratio)
    if side == "left":
        xa, xb = 0, min(w, gutter_x + overlap)
    else:
        xa, xb = max(0, gutter_x - overlap), w

    crop = image[:, xa:xb]
    mask = paper_mask(crop)
    contour = largest_contour(mask)
    if contour is None or cv2.contourArea(contour) < crop.shape[0] * crop.shape[1] * 0.08:
        raise PhotoPreprocessingError(f"Could not find a reliable {side} page contour.")
    quad = contour_to_quad(contour)
    quad[:, 0] += xa
    return order_points(quad)


def warp_page_with_matrix(
    image: np.ndarray, quad: np.ndarray, max_side: int = 2400
) -> tuple[np.ndarray, np.ndarray]:
    tl, tr, br, bl = order_points(quad)
    width = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    height = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    if width < 100 or height < 100:
        raise PhotoPreprocessingError("Detected page geometry is too small.")

    scale = min(1.0, max_side / max(width, height))
    width = max(1, int(width * scale))
    height = max(1, int(height * scale))
    dst = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    src = order_points(quad)
    if scale != 1.0:
        # Homography target is scaled; source remains in original coordinates.
        pass
    matrix = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return warped, matrix


def warp_page(image: np.ndarray, quad: np.ndarray, max_side: int = 2400) -> np.ndarray:
    warped, _matrix = warp_page_with_matrix(image, quad, max_side)
    return warped


def enhance_document(image: np.ndarray) -> np.ndarray:
    # Conservative illumination correction in LAB, preserving handwriting and color marks.
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    lightness, a, b = cv2.split(lab)
    sigma = max(15, int(min(image.shape[:2]) * 0.03))
    bg = cv2.GaussianBlur(lightness, (0, 0), sigmaX=sigma, sigmaY=sigma)
    corrected = cv2.divide(lightness, np.maximum(bg, 1), scale=210)
    clahe = cv2.createCLAHE(clipLimit=1.6, tileGridSize=(8, 8))
    corrected = clahe.apply(corrected)
    out = cv2.cvtColor(cv2.merge([corrected, a, b]), cv2.COLOR_LAB2BGR)
    # Mild unsharp mask.
    blur = cv2.GaussianBlur(out, (0, 0), 1.0)
    return cv2.addWeighted(out, 1.15, blur, -0.15, 0)


def draw_preview(
    image: np.ndarray, left: np.ndarray, right: np.ndarray, gutter_x: int
) -> np.ndarray:
    preview = image.copy()
    cv2.polylines(preview, [left.astype(np.int32)], True, (0, 255, 0), 4)
    cv2.polylines(preview, [right.astype(np.int32)], True, (0, 0, 255), 4)
    cv2.line(preview, (gutter_x, 0), (gutter_x, image.shape[0] - 1), (255, 0, 0), 3)
    return preview


# Project adapter layer.


def spread_axis_from_bbox(bbox: tuple[int, int, int, int]) -> str:
    x0, y0, x1, y1 = bbox
    width = max(1, x1 - x0)
    height = max(1, y1 - y0)
    return "y" if height > width * 1.18 else "x"


def rotate_clockwise_with_map(image: np.ndarray) -> tuple[np.ndarray, callable]:
    height = image.shape[0]
    rotated = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)

    def map_quad_back(rotated_quad: np.ndarray) -> np.ndarray:
        mapped = np.zeros_like(rotated_quad, dtype=np.float32)
        mapped[:, 0] = rotated_quad[:, 1]
        mapped[:, 1] = height - 1 - rotated_quad[:, 0]
        return order_points(mapped)

    return rotated, map_quad_back


def detect_left_right_pages(image: np.ndarray) -> tuple[list[SkillDetectedPage], dict[str, object]]:
    mask = paper_mask(image)
    bbox = find_spread_bbox(mask)
    gutter_x = estimate_gutter(image, bbox)
    left = detect_page_quad(image, "left", gutter_x)
    right = detect_page_quad(image, "right", gutter_x)
    return [
        SkillDetectedPage(
            label="page_1_left",
            quad=left,
            confidence=1.0,
            debug={"side": "left", "source": "skill.detect_page_quad"},
        ),
        SkillDetectedPage(
            label="page_2_right",
            quad=right,
            confidence=1.0,
            debug={"side": "right", "source": "skill.detect_page_quad"},
        ),
    ], {
        "axis": "x",
        "bbox": [int(value) for value in bbox],
        "gutter": int(gutter_x),
        "gutter_ratio": round(float(gutter_x / max(1, image.shape[1])), 4),
    }


def detect_top_bottom_pages_by_rotation(
    image: np.ndarray,
) -> tuple[list[SkillDetectedPage], dict[str, object]]:
    rotated, map_quad_back = rotate_clockwise_with_map(image)
    detected, debug = detect_left_right_pages(rotated)
    mapped = [
        SkillDetectedPage(
            label="page_1_top",
            quad=map_quad_back(detected[1].quad),
            confidence=detected[1].confidence,
            debug={
                **detected[1].debug,
                "source": "skill.detect_page_quad_on_rotated_image",
                "mapped_from": detected[1].label,
            },
        ),
        SkillDetectedPage(
            label="page_2_bottom",
            quad=map_quad_back(detected[0].quad),
            confidence=detected[0].confidence,
            debug={
                **detected[0].debug,
                "source": "skill.detect_page_quad_on_rotated_image",
                "mapped_from": detected[0].label,
            },
        ),
    ]
    gutter_y = image.shape[0] - 1 - int(debug["gutter"])
    return mapped, {
        "axis": "y",
        "bbox": debug["bbox"],
        "rotated_detection": debug,
        "gutter": int(gutter_y),
        "gutter_ratio": round(float(gutter_y / max(1, image.shape[0])), 4),
    }


def stitch_pages(pages: list[PreprocessedPage], *, axis: str) -> np.ndarray:
    if len(pages) == 1:
        return pages[0].image
    if axis == "y":
        max_width = max(page.image.shape[1] for page in pages)
        resized = []
        for page in pages:
            height, width = page.image.shape[:2]
            if width == max_width:
                resized.append(page.image)
            else:
                resized.append(
                    cv2.resize(page.image, (max_width, max(1, int(height * max_width / width))))
                )
        return cv2.vconcat(resized)

    max_height = max(page.image.shape[0] for page in pages)
    resized = []
    for page in pages:
        height, width = page.image.shape[:2]
        if height == max_height:
            resized.append(page.image)
        else:
            resized.append(
                cv2.resize(page.image, (max(1, int(width * max_height / height)), max_height))
            )
    return cv2.hconcat(resized)


def preprocess_exam_scan_rectifier_bytes(contents: bytes) -> PreprocessedExamPhoto:
    total_started = time.perf_counter()
    image_buffer = np.frombuffer(contents, dtype=np.uint8)
    image = cv2.imdecode(image_buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise PhotoPreprocessingError("Could not decode scan image")

    detection_started = time.perf_counter()
    mask = paper_mask(image)
    bbox = find_spread_bbox(mask)
    axis = spread_axis_from_bbox(bbox)
    if axis == "y":
        detected_pages, split_debug = detect_top_bottom_pages_by_rotation(image)
    else:
        detected_pages, split_debug = detect_left_right_pages(image)
    detection_ms = round((time.perf_counter() - detection_started) * 1000, 1)

    pages: list[PreprocessedPage] = []
    warnings: list[QualityWarning] = []
    current_x = 0
    warp_started = time.perf_counter()
    for index, detected in enumerate(detected_pages, start=1):
        page_started = time.perf_counter()
        warped, matrix = warp_page_with_matrix(image, detected.quad)
        enhanced = enhance_document(warped)
        skew_angle, skew_debug = estimate_horizontal_text_skew(enhanced)
        sharpness = estimate_sharpness(enhanced)
        pages.append(
            PreprocessedPage(
                name=f"page_{index}.jpg",
                image=enhanced,
                x_start=current_x,
                x_end=current_x + enhanced.shape[1],
                source_quad=detected.quad.round(2).tolist(),
                homography=matrix.round(8).tolist(),
                quality={
                    "detector": "exam_scan_rectifier_v1",
                    "label": detected.label,
                    "confidence": round(detected.confidence, 4),
                    "sharpness": round(sharpness, 2),
                    "quad_edge_angles": quad_edge_angle_metadata(detected.quad),
                    "residual_horizontal_text_angle": None
                    if skew_angle is None
                    else round(float(skew_angle), 3),
                    "text_skew": skew_debug,
                    "elapsed_ms": round((time.perf_counter() - page_started) * 1000, 1),
                    "debug": detected.debug,
                },
            )
        )
        current_x += enhanced.shape[1]
    warp_ms = round((time.perf_counter() - warp_started) * 1000, 1)

    warnings.extend(build_page_quality_warnings(pages))
    combined = np.vstack([page.quad for page in detected_pages])
    detected_quad = cv2.boxPoints(cv2.minAreaRect(combined.astype("float32")))
    enhanced_spread = stitch_pages(pages, axis=axis)

    split_strategy = (
        "top_bottom_gutter_perspective_skill_port"
        if axis == "y"
        else "left_right_gutter_perspective_skill_port"
    )
    return PreprocessedExamPhoto(
        pdf_bytes=encode_pdf(pages),
        pages=pages,
        detected_quad=order_points(detected_quad).round(2).tolist(),
        spread_size=(int(image.shape[1]), int(image.shape[0])),
        split=SplitMetadata(
            strategy=split_strategy,
            gutter_ratio=split_debug.get("gutter_ratio"),
            gutter_confidence=None,
            overlap_pixels=int((image.shape[0] if axis == "y" else image.shape[1]) * 0.05),
        ),
        quality_status="review"
        if any(warning.severity == "warning" for warning in warnings)
        else "pass",
        quality_warnings=warnings,
        mask=mask,
        warped_spread=enhanced_spread,
        enhanced_spread=enhanced_spread,
        debug={
            "engine": "exam_scan_rectifier_v1",
            "source": "faithful_port_of_exam_scan_rectifier_skill_zip",
            "input_size": [int(image.shape[1]), int(image.shape[0])],
            "spread_bbox": [int(value) for value in bbox],
            "split_axis": axis,
            "split_debug": split_debug,
            "page_count": len(pages),
            "timings": {
                "skill_paper_mask_quad_split_ms": detection_ms,
                "skill_warp_enhance_measure_ms": warp_ms,
                "total_ms": round((time.perf_counter() - total_started) * 1000, 1),
            },
            "faithful_core_functions": [
                "order_points",
                "paper_mask",
                "largest_contour",
                "contour_to_quad",
                "find_spread_bbox",
                "estimate_gutter",
                "detect_page_quad",
                "warp_page",
                "enhance_document",
            ],
            "project_extensions": [
                "top_bottom_by_rotating_input_then_mapping_quads_back",
                "PreprocessedExamPhoto/PDF/metadata adapter",
                "quality metrics only; no geometry parameter changes",
            ],
        },
    )
