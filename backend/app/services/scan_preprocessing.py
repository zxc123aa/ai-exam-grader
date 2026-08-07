from __future__ import annotations

import base64
import time
from dataclasses import dataclass, replace
from pathlib import Path
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
    build_page_quality_warnings,
    encode_pdf,
    estimate_sharpness,
    preprocess_exam_photo_bytes,
    preprocess_exam_photo_with_page_quads,
    stitch_debug_spread,
)
from app.services.exam_scan_rectifier import preprocess_exam_scan_rectifier_bytes
from app.services.scan_stable_preprocessing import preprocess_scan_stable_bytes
from app.services.vision_grading import VisionGradingError, call_json_model

GEMINI_PAGE_POLYGON_PROMPT = """你是“手机拍摄试卷预处理”的页面边界检测器，不是 OCR，不要识别题目内容。

目标：给后续 OpenCV 透视变换提供可靠四角点。请检测真实纸张页面区域：
- 如果照片里是左右展开的两页试卷，必须返回两个 page polygon，label 分别为 left、right。
- 如果照片里只有一页，返回一个 page polygon，label 为 single。
- 不要把桌面、阴影、手、整张照片边框当成纸面。
- 不要把左右两页合并成一个大四边形。
- 不要把同一页重复返回两次。
- 四角顺序必须是：左上、右上、右下、左下。
- 坐标基于原始图片，归一化 0-1000，整数。
- 边界策略：宁可保留 1%~3% 的纸外背景，也不能裁掉页眉、题号、页脚、图像、手写答案。
- 如果纸边被遮挡、阴影覆盖、卷曲或贴近照片边界，请沿可见纸边趋势外推到完整纸面；不要沿文字区域内缩。
- 如果左右页中间有折痕/中缝，左右 polygon 可以在中缝附近轻微接触，但不能大面积重叠。

质量要求：
- confidence 表示你对该页面四角能否用于透视校正的置信度。
- 若页面边界不完整但仍可外推，confidence 不低于 0.70 并在 warnings 说明。
- 如果不确定是一页还是两页，根据纸张边界和页脚/中缝判断，不要根据题号数量猜。

只返回 JSON，不要 Markdown，不要解释。格式：
{
  "pageCount": 1或2,
  "orientation": 0或90或180或270,
  "pages": [
    {
      "label": "single|left|right",
      "confidence": 0到1,
      "points": [[x,y],[x,y],[x,y],[x,y]],
      "warnings": ["可为空"]
    }
  ],
  "globalWarnings": ["可为空"]
}"""


@dataclass(frozen=True)
class GeminiPagePolygonDetection:
    status: str
    quads: list[np.ndarray]
    confidences: list[float]
    labels: list[str]
    model: str | None
    elapsed_ms: int
    attempts: list[dict[str, Any]]
    rejection_reason: str | None = None


def preprocess_scan_photo_bytes(
    contents: bytes,
    *,
    filename: str = "scan-photo.jpg",
    content_type: str = "image/jpeg",
) -> PreprocessedExamPhoto:
    if settings.SCAN_ENGINE == "opencv_v1":
        return preprocess_exam_photo_bytes(contents)
    if settings.SCAN_ENGINE == "exam_scan_rectifier_v1":
        return preprocess_exam_scan_rectifier_bytes(contents)
    if settings.SCAN_ENGINE == "scan_stable_v1":
        return preprocess_scan_stable_bytes(contents)
    if settings.SCAN_ENGINE == "hybrid_v2":
        total_started = time.perf_counter()
        polygon_started = time.perf_counter()
        detection = detect_page_polygons_with_gemini(
            contents=contents,
            content_type=content_type,
        )
        polygon_ms = round((time.perf_counter() - polygon_started) * 1000, 1)
        baseline_ms = 0.0
        baseline: PreprocessedExamPhoto
        if detection.status == "accepted":
            try:
                baseline = preprocess_exam_photo_with_page_quads(
                    contents,
                    detection.quads,
                    detector=f"gemini:{detection.model}",
                    margin_mode="safe",
                )
                baseline = replace(
                    baseline,
                    debug={
                        **baseline.debug,
                        "vision_polygon_mode": "primary",
                        "vision_polygon_status": "accepted",
                        "vision_polygon_model": detection.model,
                        "vision_polygon_elapsed_ms": detection.elapsed_ms,
                        "vision_polygon_confidences": detection.confidences,
                        "vision_polygon_labels": detection.labels,
                        "vision_polygon_attempts": detection.attempts,
                        "vision_polygon_margin_mode": "safe",
                    },
                )
            except PhotoPreprocessingError as exc:
                baseline_started = time.perf_counter()
                baseline = preprocess_exam_photo_bytes(contents)
                baseline_ms = round((time.perf_counter() - baseline_started) * 1000, 1)
                baseline = replace(
                    baseline,
                    quality_status="review",
                    quality_warnings=[
                        *baseline.quality_warnings,
                        QualityWarning(
                            code="vision_page_polygon_transform_failed",
                            severity="warning",
                            message=(
                                "Gemini page polygons passed validation but "
                                f"homography failed; used OpenCV fallback: {exc}"
                            ),
                        ),
                    ],
                    debug={
                        **baseline.debug,
                        "vision_polygon_mode": "primary",
                        "vision_polygon_status": "transform_failed",
                        "vision_polygon_model": detection.model,
                        "vision_polygon_elapsed_ms": detection.elapsed_ms,
                        "vision_polygon_attempts": detection.attempts,
                    },
                )
        else:
            baseline_started = time.perf_counter()
            baseline = preprocess_exam_photo_bytes(contents)
            baseline_ms = round((time.perf_counter() - baseline_started) * 1000, 1)
            baseline = attach_gemini_detection_failure_debug(baseline, detection)
            baseline = refine_page_polygons_with_gemini(
                baseline,
                contents=contents,
                content_type=content_type,
                prior_detection=detection,
            )
        unwarping_started = time.perf_counter()
        result = refine_pages_with_doc_preprocessor(
            baseline,
            filename=filename,
        )
        unwarping_ms = round((time.perf_counter() - unwarping_started) * 1000, 1)
        return replace(
            result,
            debug={
                **result.debug,
                "timings": {
                    "opencv_page_detection_homography_ms": baseline_ms,
                    "gemini_page_polygon_ms": polygon_ms,
                    "doc_orientation_unwarping_ms": unwarping_ms,
                    "total_ms": round((time.perf_counter() - total_started) * 1000, 1),
                },
            },
        )
    return preprocess_scan_photo_http(
        contents,
        filename=filename,
        content_type=content_type,
    )


def refine_page_polygons_with_gemini(
    baseline: PreprocessedExamPhoto,
    *,
    contents: bytes,
    content_type: str,
    prior_detection: GeminiPagePolygonDetection | None = None,
) -> PreprocessedExamPhoto:
    needs_fallback = baseline.split.strategy in {
        "split_half_page_fallback",
        "center_fallback",
    } or bool(baseline.debug.get("full_frame_quad"))
    if not needs_fallback:
        return baseline
    if not settings.PROVIDER_FLUXNODE_GEMINI_API_KEY:
        return replace(
            baseline,
            debug={**baseline.debug, "vision_polygon_fallback": "not_configured"},
        )

    detection = prior_detection or detect_page_polygons_with_gemini(
        contents=contents,
        content_type=content_type,
    )
    if detection.status != "accepted":
        warning = QualityWarning(
            code="vision_page_polygon_rejected",
            severity="warning",
            message=(
                "Gemini page polygons failed geometry validation: "
                f"{detection.rejection_reason or detection.status}."
            ),
        )
        return replace(
            baseline,
            quality_status="review",
            quality_warnings=[*baseline.quality_warnings, warning],
            debug={
                **baseline.debug,
                "vision_polygon_fallback": detection.status,
                "vision_polygon_model": detection.model,
                "vision_polygon_elapsed_ms": detection.elapsed_ms,
                "vision_polygon_rejection_reason": detection.rejection_reason,
                "vision_polygon_attempts": detection.attempts,
            },
        )

    page_quads, polygon_margin_mode = fuse_page_quads_with_opencv_baseline(
        detection.quads,
        baseline=baseline,
    )
    try:
        refined = preprocess_exam_photo_with_page_quads(
            contents,
            page_quads,
            detector=f"gemini:{detection.model}",
            margin_mode=polygon_margin_mode,
        )
    except PhotoPreprocessingError:
        return baseline
    return replace(
        refined,
        debug={
            **refined.debug,
            "vision_polygon_fallback": "accepted",
            "vision_polygon_model": detection.model,
            "vision_polygon_elapsed_ms": detection.elapsed_ms,
            "vision_polygon_confidences": detection.confidences,
            "vision_polygon_labels": detection.labels,
            "vision_polygon_attempts": detection.attempts,
            "vision_polygon_margin_mode": polygon_margin_mode,
            "opencv_baseline": baseline.debug,
        },
    )


def detect_page_polygons_with_gemini(
    *,
    contents: bytes,
    content_type: str,
    expected_page_count: int | None = None,
) -> GeminiPagePolygonDetection:
    if not settings.PROVIDER_FLUXNODE_GEMINI_API_KEY:
        return GeminiPagePolygonDetection(
            status="not_configured",
            quads=[],
            confidences=[],
            labels=[],
            model=None,
            elapsed_ms=0,
            attempts=[],
            rejection_reason="fluxnode_gemini_not_configured",
        )

    image_buffer = np.frombuffer(contents, dtype=np.uint8)
    image = cv2.imdecode(image_buffer, cv2.IMREAD_COLOR)
    if image is None:
        return GeminiPagePolygonDetection(
            status="decode_failed",
            quads=[],
            confidences=[],
            labels=[],
            model=None,
            elapsed_ms=0,
            attempts=[],
            rejection_reason="could_not_decode_image",
        )
    height, width = image.shape[:2]
    expected_count = expected_page_count or (2 if width >= height * 1.2 else 1)
    mime = content_type if content_type in {"image/jpeg", "image/png"} else "image/jpeg"
    encoded = base64.b64encode(contents).decode("ascii")
    prompt = GEMINI_PAGE_POLYGON_PROMPT
    try:
        parsed, used_model, elapsed_ms = call_json_model(
            provider=settings.VISION_DEFAULT_PROVIDER,
            model=settings.VISION_DEFAULT_MODEL,
            fallback_models=[],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{encoded}"},
                        },
                    ],
                }
            ],
            # Perspective correction remains OpenCV-based. The model is only
            # used to identify page boundaries when the traditional detector
            # needs a visual judgment.
            workflow_purpose="region_detection",
        )
    except VisionGradingError as exc:
        return GeminiPagePolygonDetection(
            status="failed",
            quads=[],
            confidences=[],
            labels=[],
            model=settings.VISION_DEFAULT_MODEL,
            elapsed_ms=0,
            attempts=[],
            rejection_reason=str(exc),
        )

    page_quads, confidences, labels = extract_page_polygon_candidates(
        parsed,
        image_width=width,
        image_height=height,
    )
    rejection_reason = validate_page_polygon_set(
        page_quads,
        labels=labels,
        image_width=width,
        image_height=height,
        expected_page_count=expected_count,
    )
    attempt_debug = [
        build_polygon_attempt_debug(
            page_quads,
            labels=labels,
            confidences=confidences,
            rejection_reason=rejection_reason,
        )
    ]
    if rejection_reason is not None:
        retry_prompt = (
            f"{prompt}\n上一次候选未通过几何校验，原因：{rejection_reason}。"
            "请重新观察原图并修正。左右两页的中心必须明显分开，四边形只能少量接触或重叠；"
            "不要把同一页重复返回两次，也不要裁掉纸张边缘内容。"
        )
        try:
            retry_parsed, retry_model, retry_elapsed_ms = call_json_model(
                provider=settings.VISION_DEFAULT_PROVIDER,
                model=settings.VISION_DEFAULT_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": retry_prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{encoded}"},
                            },
                        ],
                    }
                ],
                workflow_purpose="region_detection",
            )
            retry_quads, retry_confidences, retry_labels = (
                extract_page_polygon_candidates(
                    retry_parsed,
                    image_width=width,
                    image_height=height,
                )
            )
            retry_rejection = validate_page_polygon_set(
                retry_quads,
                labels=retry_labels,
                image_width=width,
                image_height=height,
                expected_page_count=expected_count,
            )
            attempt_debug.append(
                build_polygon_attempt_debug(
                    retry_quads,
                    labels=retry_labels,
                    confidences=retry_confidences,
                    rejection_reason=retry_rejection,
                )
            )
            elapsed_ms += retry_elapsed_ms
            used_model = retry_model
            if retry_rejection is None:
                page_quads = retry_quads
                confidences = retry_confidences
                labels = retry_labels
                rejection_reason = None
            else:
                rejection_reason = retry_rejection
        except VisionGradingError:
            attempt_debug.append(
                {"status": "retry_failed", "rejection_reason": rejection_reason}
            )
    if rejection_reason is not None:
        return GeminiPagePolygonDetection(
            status="rejected",
            quads=page_quads,
            confidences=confidences,
            labels=labels,
            model=used_model,
            elapsed_ms=elapsed_ms,
            attempts=attempt_debug,
            rejection_reason=rejection_reason,
        )
    return GeminiPagePolygonDetection(
        status="accepted",
        quads=page_quads,
        confidences=confidences,
        labels=labels,
        model=used_model,
        elapsed_ms=elapsed_ms,
        attempts=attempt_debug,
    )


def attach_gemini_detection_failure_debug(
    baseline: PreprocessedExamPhoto,
    detection: GeminiPagePolygonDetection,
) -> PreprocessedExamPhoto:
    if detection.status == "not_configured":
        return replace(
            baseline,
            debug={**baseline.debug, "vision_polygon_mode": "primary_not_configured"},
        )
    warning = QualityWarning(
        code="vision_page_polygon_primary_failed",
        severity="warning",
        message=(
            "Gemini-first page polygon detection failed; used OpenCV fallback: "
            f"{detection.rejection_reason or detection.status}."
        ),
    )
    return replace(
        baseline,
        quality_status="review",
        quality_warnings=[*baseline.quality_warnings, warning],
        debug={
            **baseline.debug,
            "vision_polygon_mode": "primary",
            "vision_polygon_status": detection.status,
            "vision_polygon_model": detection.model,
            "vision_polygon_elapsed_ms": detection.elapsed_ms,
            "vision_polygon_rejection_reason": detection.rejection_reason,
            "vision_polygon_attempts": detection.attempts,
        },
    )


def fuse_page_quads_with_opencv_baseline(
    page_quads: list[np.ndarray],
    *,
    baseline: PreprocessedExamPhoto,
) -> tuple[list[np.ndarray], str]:
    """Use Gemini for the gutter and OpenCV for the visible outer paper edges."""
    if len(page_quads) != 2 or len(baseline.pages) != 2:
        return page_quads, "conservative"
    try:
        baseline_quads = [
            order_page_points(np.asarray(page.source_quad, dtype="float32"))
            for page in baseline.pages
        ]
    except (TypeError, ValueError):
        return page_quads, "conservative"
    if any(quad.shape != (4, 2) for quad in baseline_quads):
        return page_quads, "conservative"
    vision = sorted(page_quads, key=lambda quad: float(quad[:, 0].mean()))
    opencv = sorted(baseline_quads, key=lambda quad: float(quad[:, 0].mean()))
    left_vision, right_vision = vision
    left_base, right_base = opencv
    left = np.array(
        [
            left_base[0],
            [left_vision[1, 0], min(left_base[1, 1], left_vision[1, 1])],
            [left_vision[2, 0], max(left_base[2, 1], left_vision[2, 1])],
            left_base[3],
        ],
        dtype="float32",
    )
    right = np.array(
        [
            [right_vision[0, 0], min(right_base[0, 1], right_vision[0, 1])],
            right_base[1],
            right_base[2],
            [right_vision[3, 0], max(right_base[3, 1], right_vision[3, 1])],
        ],
        dtype="float32",
    )
    return [left, right], "minimal"


def order_page_points(points: np.ndarray) -> np.ndarray:
    ordered = np.zeros((4, 2), dtype="float32")
    summed = points.sum(axis=1)
    differences = np.diff(points, axis=1)
    ordered[0] = points[np.argmin(summed)]
    ordered[1] = points[np.argmin(differences)]
    ordered[2] = points[np.argmax(summed)]
    ordered[3] = points[np.argmax(differences)]
    return ordered


def extract_page_polygon_candidates(
    parsed: Any,
    *,
    image_width: int,
    image_height: int,
) -> tuple[list[np.ndarray], list[float], list[str]]:
    raw_pages = parsed.get("pages") if isinstance(parsed, dict) else None
    page_quads: list[np.ndarray] = []
    confidences: list[float] = []
    labels: list[str] = []
    if not isinstance(raw_pages, list):
        return page_quads, confidences, labels

    for item in raw_pages[:2]:
        if not isinstance(item, dict) or not isinstance(item.get("points"), list):
            continue
        try:
            points = np.array(item["points"], dtype="float32")
            confidence = float(item.get("confidence") or 0)
        except (TypeError, ValueError):
            continue
        if points.shape != (4, 2) or not np.isfinite(points).all():
            continue
        points[:, 0] = points[:, 0] / 1000 * image_width
        points[:, 1] = points[:, 1] / 1000 * image_height
        points[:, 0] = np.clip(points[:, 0], 0, image_width - 1)
        points[:, 1] = np.clip(points[:, 1], 0, image_height - 1)
        points = order_page_points(points)
        area_ratio = abs(cv2.contourArea(points)) / max(1, image_width * image_height)
        if (
            area_ratio < 0.12
            or confidence < 0.7
            or not cv2.isContourConvex(points.astype("int32"))
        ):
            continue
        page_quads.append(points)
        confidences.append(confidence)
        labels.append(str(item.get("label") or "").strip().lower())
    return page_quads, confidences, labels


def build_polygon_attempt_debug(
    page_quads: list[np.ndarray],
    *,
    labels: list[str],
    confidences: list[float],
    rejection_reason: str | None,
) -> dict[str, Any]:
    return {
        "status": "accepted" if rejection_reason is None else "rejected",
        "rejection_reason": rejection_reason,
        "labels": labels,
        "confidences": confidences,
        "page_quads": [quad.round(1).tolist() for quad in page_quads],
    }


def polygon_overlap_ratio(first: np.ndarray, second: np.ndarray) -> float:
    first = first.astype("float32")
    second = second.astype("float32")
    intersection_area, _intersection = cv2.intersectConvexConvex(first, second)
    smaller_area = min(abs(cv2.contourArea(first)), abs(cv2.contourArea(second)))
    if smaller_area <= 0:
        return 1.0
    return float(intersection_area / smaller_area)


def validate_page_polygon_set(
    page_quads: list[np.ndarray],
    *,
    labels: list[str],
    image_width: int,
    image_height: int,
    expected_page_count: int,
) -> str | None:
    if len(page_quads) != expected_page_count:
        return (
            f"returned {len(page_quads)} valid pages; "
            f"expected {expected_page_count} for this image aspect ratio"
        )

    image_area = max(1, image_width * image_height)
    total_area_ratio = (
        sum(abs(cv2.contourArea(quad)) for quad in page_quads) / image_area
    )
    if total_area_ratio < (0.28 if len(page_quads) == 1 else 0.45):
        return f"page coverage is too small ({total_area_ratio:.2f})"

    if len(page_quads) == 1:
        label = labels[0] if labels else ""
        if label in {"left", "right"}:
            return f"single polygon is labelled {label}"
        return None

    centers = [float(quad[:, 0].mean()) for quad in page_quads]
    if abs(centers[0] - centers[1]) < image_width * 0.2:
        return "two page centers are not horizontally separated"
    if polygon_overlap_ratio(page_quads[0], page_quads[1]) > 0.16:
        return "two pages overlap excessively"
    if labels and set(labels) == {"single"}:
        return "two polygons are both labelled single"
    return None


def refine_pages_with_doc_preprocessor(
    baseline: PreprocessedExamPhoto,
    *,
    filename: str,
) -> PreprocessedExamPhoto:
    pages: list[PreprocessedPage] = []
    # Page-edge/aspect warnings must describe the final selected images, not
    # an intermediate Homography image that may later be replaced by UVDoc.
    page_warning_codes = {
        "page_aspect_outlier",
        "content_near_top_edge",
        "content_near_bottom_edge",
        "content_near_left_edge",
        "content_near_right_edge",
    }
    warnings = [
        warning
        for warning in baseline.quality_warnings
        if warning.code not in page_warning_codes
    ]
    current_x = 0
    applied_count = 0
    attempts: list[dict[str, Any]] = []
    for index, page in enumerate(baseline.pages, start=1):
        page_started = time.perf_counter()
        service_debug: dict[str, Any] = {}
        ok, encoded = cv2.imencode(
            ".png", page.image, [int(cv2.IMWRITE_PNG_COMPRESSION), 3]
        )
        if not ok:
            warnings.append(
                QualityWarning(
                    code="doc_unwarping_encode_failed",
                    severity="warning",
                    message=f"Could not encode {page.name} for document unwarping.",
                )
            )
            output = page.image
            applied = False
            reason = "encode_failed"
        else:
            try:
                refined = preprocess_scan_photo_http(
                    encoded.tobytes(),
                    filename=f"{Path(filename).stem}-page-{index}.png",
                    content_type="image/png",
                )
                service_debug = refined.debug
                if len(refined.pages) != 1:
                    raise PhotoPreprocessingError(
                        f"scan-service returned {len(refined.pages)} pages for one page input"
                    )
                candidate = refined.pages[0].image
                baseline_ratio = page.image.shape[1] / max(1, page.image.shape[0])
                candidate_ratio = candidate.shape[1] / max(1, candidate.shape[0])
                baseline_sharpness = estimate_sharpness(page.image)
                candidate_sharpness = estimate_sharpness(candidate)
                sharpness_ratio = candidate_sharpness / max(1.0, baseline_sharpness)
                geometry_safe = (
                    0.72 <= candidate_ratio / max(0.01, baseline_ratio) <= 1.28
                )
                # Quality-first: perspective/dewarp interpolation may soften a
                # page slightly, but losing more than 28% of edge detail is a
                # visible OCR regression and must fall back to Homography.
                sharpness_safe = candidate_sharpness >= 12.0 and sharpness_ratio >= 0.72
                service_safe = (
                    refined.quality_status == "pass"
                    and not refined.quality_warnings
                    and refined.debug.get("doc_preprocessor_available") is not False
                )
                if geometry_safe and sharpness_safe and service_safe:
                    output = candidate
                    applied = True
                    reason = "uvdoc_accepted"
                    applied_count += 1
                else:
                    output = page.image
                    applied = False
                    reason = (
                        "uvdoc_service_warning"
                        if not service_safe
                        else "uvdoc_quality_gate_rejected"
                    )
                    if refined.quality_warnings:
                        warnings.extend(refined.quality_warnings)
                    else:
                        warnings.append(
                            QualityWarning(
                                code="doc_unwarping_quality_rejected",
                                severity="warning",
                                message=f"UVDoc output for {page.name} failed service, geometry, or sharpness checks; kept homography output.",
                            )
                        )
            except PhotoPreprocessingError as exc:
                output = page.image
                applied = False
                reason = "service_unavailable"
                warnings.append(
                    QualityWarning(
                        code="doc_unwarping_unavailable",
                        severity="warning",
                        message=f"UVDoc unavailable for {page.name}; kept homography output: {exc}",
                    )
                )
        width = output.shape[1]
        pages.append(
            PreprocessedPage(
                name=page.name,
                image=output,
                x_start=current_x,
                x_end=current_x + width,
                source_quad=page.source_quad,
                homography=page.homography,
                quality={**page.quality, "doc_unwarping_applied": applied},
            )
        )
        attempts.append(
            {
                "page": page.name,
                "applied": applied,
                "reason": reason,
                "elapsed_ms": round((time.perf_counter() - page_started) * 1000, 1),
                "service_debug": service_debug,
                "baseline_sharpness": round(estimate_sharpness(page.image), 2),
                "output_sharpness": round(estimate_sharpness(output), 2),
            }
        )
        current_x += width

    warnings.extend(build_page_quality_warnings(pages))
    enhanced_spread = stitch_debug_spread(pages)
    return PreprocessedExamPhoto(
        pdf_bytes=encode_pdf(pages),
        pages=pages,
        detected_quad=baseline.detected_quad,
        spread_size=(enhanced_spread.shape[1], enhanced_spread.shape[0]),
        split=baseline.split,
        quality_status="review"
        if any(warning.severity == "warning" for warning in warnings)
        else "pass",
        quality_warnings=warnings,
        mask=baseline.mask,
        warped_spread=baseline.warped_spread,
        enhanced_spread=enhanced_spread,
        debug={
            **baseline.debug,
            "engine": "hybrid_v2",
            "doc_unwarping_attempted": len(baseline.pages),
            "doc_unwarping_applied": applied_count,
            "doc_unwarping_pages": attempts,
        },
    )


def preprocess_scan_photo_http(
    contents: bytes,
    *,
    filename: str,
    content_type: str,
) -> PreprocessedExamPhoto:
    try:
        # Internal service traffic must never be routed through the user's
        # internet proxy. In Compose, the ocr-service hostname resolves via the
        # Docker network; in local development the default URL is localhost.
        with httpx.Client(trust_env=False) as client:
            response = client.post(
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
        debug=payload.get("debug") if isinstance(payload.get("debug"), dict) else {},
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
        gutter_ratio=float(gutter_ratio)
        if isinstance(gutter_ratio, int | float)
        else None,
        gutter_confidence=(
            float(gutter_confidence)
            if isinstance(gutter_confidence, int | float)
            else None
        ),
        overlap_pixels=int(split.get("overlap_pixels") or 0) if len(pages) > 1 else 0,
    )
