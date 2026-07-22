from __future__ import annotations

import time

import cv2
import numpy as np

from app.services.exam_photo_preprocessing import (
    PhotoPreprocessingError,
    PreprocessedExamPhoto,
    PreprocessedPage,
    SplitMetadata,
    build_page_quality_warnings,
    encode_pdf,
    estimate_horizontal_text_skew,
    estimate_sharpness,
    quad_edge_angle_metadata,
    quality_status_from_warnings,
)

EXPAND = 1.03
INSET_FRAC = (1 - 1 / EXPAND) / 2


def order_points(points: np.ndarray) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    summed = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).ravel()
    return np.array(
        [
            pts[np.argmin(summed)],
            pts[np.argmin(diff)],
            pts[np.argmax(summed)],
            pts[np.argmax(diff)],
        ],
        dtype=np.float32,
    )


def _resize_for_platform_detection(
    image: np.ndarray, *, target_width: int = 1000
) -> tuple[np.ndarray, float]:
    height, width = image.shape[:2]
    if width < 1:
        raise PhotoPreprocessingError("Invalid image width")
    scale = target_width / width
    if abs(scale - 1.0) < 1e-6:
        return image.copy(), 1.0
    resized = cv2.resize(
        image,
        (target_width, max(1, int(round(height * scale)))),
        interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC,
    )
    return resized, scale


def find_stable_paper_quad(image: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict]:
    """Detect the paper frame using the threshold-stability platform algorithm.

    This is a project adapter of ``scan_stable.py``. The core idea is unchanged:
    scan binary thresholds from Otsu upward, keep candidates whose area remains
    stable and rectangular, then use the midpoint of the longest stable run.
    """

    small, scale = _resize_for_platform_detection(image)
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    otsu_t, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    candidates: list[tuple[int, np.ndarray, float, float, np.ndarray]] = []
    for threshold in range(int(otsu_t), 246, 5):
        _ret, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
        binary = cv2.morphologyEx(
            binary, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8)
        )
        binary = cv2.morphologyEx(
            binary, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8)
        )
        contours, _hierarchy = cv2.findContours(
            binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            break
        contour = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(contour)
        frac = area / max(1, small.shape[0] * small.shape[1])
        (_center, (rect_w, rect_h), _angle) = cv2.minAreaRect(contour)
        rect = area / (rect_w * rect_h) if rect_w * rect_h > 0 else 0.0
        candidates.append((threshold, contour, frac, rect, binary))

    if not candidates:
        raise PhotoPreprocessingError("Stable threshold scan found no paper candidate")

    best_run: list[tuple[int, np.ndarray, float, float, np.ndarray]] = []
    run: list[tuple[int, np.ndarray, float, float, np.ndarray]] = []
    for candidate in candidates:
        _threshold, _contour, frac, rect, _binary = candidate
        ok = 0.20 <= frac <= 0.97 and rect > 0.90
        stable = not run or abs(frac - run[-1][2]) < 0.01
        if ok and stable:
            run.append(candidate)
        else:
            if len(run) > len(best_run):
                best_run = run
            run = [candidate] if ok else []
    if len(run) > len(best_run):
        best_run = run

    selected = best_run[len(best_run) // 2] if best_run else candidates[0]
    threshold, contour, frac, rect, mask_small = selected
    approx = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
    if len(approx) == 4:
        quad_small = approx.reshape(-1, 2).astype(np.float32)
    else:
        quad_small = cv2.boxPoints(cv2.minAreaRect(contour)).astype(np.float32)
    quad = order_points(quad_small / scale)
    image_height, image_width = image.shape[:2]
    open_sides: set[str] = set()
    tolerance = 0.012
    top_left, top_right, bottom_right, bottom_left = quad
    if min(top_left[1], top_right[1]) < image_height * tolerance:
        open_sides.add("top")
    if max(bottom_left[1], bottom_right[1]) > image_height * (1 - tolerance):
        open_sides.add("bottom")
    if min(top_left[0], bottom_left[0]) < image_width * tolerance:
        open_sides.add("left")
    if max(top_right[0], bottom_right[0]) > image_width * (1 - tolerance):
        open_sides.add("right")
    center = quad.mean(axis=0)
    quad = center + (quad - center) * EXPAND
    mask = cv2.resize(
        mask_small,
        (image.shape[1], image.shape[0]),
        interpolation=cv2.INTER_NEAREST,
    )
    return quad, mask, {
        "otsu_threshold": round(float(otsu_t), 2),
        "selected_threshold": int(threshold),
        "area_fraction": round(float(frac), 4),
        "rectangularity": round(float(rect), 4),
        "candidate_count": len(candidates),
        "stable_run_length": len(best_run),
        "open_sides": sorted(open_sides),
        "quad_expand": EXPAND,
    }


def warp_with_matrix(
    image: np.ndarray, quad: np.ndarray, *, upscale: float = 1.4
) -> tuple[np.ndarray, np.ndarray]:
    top_left, top_right, bottom_right, bottom_left = order_points(quad)
    out_width = int(
        max(
            np.linalg.norm(top_right - top_left),
            np.linalg.norm(bottom_right - bottom_left),
        )
        * upscale
    )
    out_height = int(
        max(
            np.linalg.norm(bottom_left - top_left),
            np.linalg.norm(bottom_right - top_right),
        )
        * upscale
    )
    if out_width < 50 or out_height < 50:
        raise PhotoPreprocessingError("Stable paper quad is too small")
    destination = np.array(
        [
            [0, 0],
            [out_width - 1, 0],
            [out_width - 1, out_height - 1],
            [0, out_height - 1],
        ],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(
        order_points(quad).astype(np.float32), destination
    )
    warped = cv2.warpPerspective(
        image,
        matrix,
        (out_width, out_height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return warped, matrix


def _runs_of(mask: np.ndarray, start: int, stop: int, min_width: int) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    index = start
    while index < stop:
        if bool(mask[index]):
            end = index
            while end + 1 < stop and bool(mask[end + 1]):
                end += 1
            if end - index + 1 >= min_width:
                runs.append((index, end))
            index = end + 1
        else:
            index += 1
    return runs


def find_gutter_cuts(warped: np.ndarray) -> tuple[int, int, int, dict]:
    gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31))
    background = cv2.GaussianBlur(
        cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel), (0, 0), 21
    )
    normalized = cv2.divide(
        gray.astype(np.float32), background.astype(np.float32) + 1e-6
    ) * 255
    height = normalized.shape[0]
    band = normalized[int(height * 0.05) : int(height * 0.95)]
    if band.size == 0:
        band = normalized
    ink = (band < 200).astype(np.float32).mean(axis=0) * 100
    width = len(ink)
    smoothed = cv2.GaussianBlur(ink.reshape(1, -1), (1, 61), 0).ravel()
    lo, hi = int(width * 0.38), int(width * 0.62)

    opening_width = max(3, int(width * 0.012)) | 1
    open_kernel = np.ones((1, opening_width), np.uint8)
    opened = cv2.dilate(
        cv2.erode(smoothed.reshape(1, -1), open_kernel), open_kernel
    ).ravel()

    safe_runs = _runs_of(
        opened < 2.5, lo, hi, max(4, int(width * 0.01))
    )
    pad = max(14, int(width * 0.008))
    if not safe_runs:
        valley = lo + int(np.argmin(smoothed[lo:hi]))
        fallback_delta = int(width * 0.015)
        return (
            min(valley + fallback_delta, width - 1),
            max(valley - fallback_delta, 0),
            pad,
            {
                "method": "valley_fallback",
                "valley": int(valley),
                "safe_run_count": 0,
                "opening_width": int(opening_width),
            },
        )

    gutter_start, gutter_end = max(safe_runs, key=lambda item: item[1] - item[0])
    cut_left = min(gutter_start + pad, width - 1)
    cut_right = max(gutter_end - pad, 0)
    method = "stable_white_gutter"
    if cut_right < cut_left:
        cut_left = cut_right = (gutter_start + gutter_end) // 2
        method = "narrow_gutter_midpoint"
    return cut_left, cut_right, pad, {
        "method": method,
        "gutter_start": int(gutter_start),
        "gutter_end": int(gutter_end),
        "cut_left": int(cut_left),
        "cut_right": int(cut_right),
        "pad": int(pad),
        "safe_run_count": len(safe_runs),
        "opening_width": int(opening_width),
    }


def clear_border_blobs(
    gray: np.ndarray, *, min_area_frac: float = 0.002, touch: int = 3
) -> np.ndarray:
    height, width = gray.shape
    dark = (gray < 150).astype(np.uint8)
    component_count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        dark, 8
    )
    out = gray.copy()
    for component_index in range(1, component_count):
        x, y, box_width, box_height, area = stats[component_index]
        touches_border = (
            x <= touch
            or y <= touch
            or x + box_width >= width - touch
            or y + box_height >= height - touch
        )
        if touches_border and area > min_area_frac * height * width:
            out[labels == component_index] = 255
    return out


def enhance_stable_page(
    bgr: np.ndarray,
    *,
    black: int = 110,
    white: int = 225,
    wipe_left: int = 0,
    wipe_right: int = 0,
) -> np.ndarray:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31))
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
    background = cv2.GaussianBlur(background, (0, 0), 21)
    normalized = np.clip(
        cv2.divide(gray.astype(np.float32), background.astype(np.float32) + 1e-6)
        * 255,
        0,
        255,
    )
    out = np.clip(
        (normalized - black) * 255.0 / max(1, white - black), 0, 255
    ).astype(np.uint8)
    out = cv2.addWeighted(out, 1.4, cv2.GaussianBlur(out, (0, 0), 2), -0.4, 0)
    out = np.clip(out, 0, 255).astype(np.uint8)
    out = clear_border_blobs(out)
    if wipe_left:
        out[:, :wipe_left] = 255
    if wipe_right:
        out[:, -wipe_right:] = 255
    return cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)


def content_protect_crop(
    image: np.ndarray,
    *,
    pad: int = 28,
    extra: int = 6,
    max_frac: float = 0.12,
    base: dict[str, int] | None = None,
) -> tuple[np.ndarray, dict[str, int], list[str]]:
    """Crop border junk while keeping a safety distance from real content.

    This ports the ``files (3)/scan_stable.py`` content-protection crop. The
    first pass expands the detected page frame to avoid irreversible over-crop;
    this pass removes the known expansion band and any continuous border junk,
    but clamps every edge so text/figures/handwriting keep at least ``pad`` px.
    """

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image.copy()
    height, width = gray.shape
    frame = int(min(height, width) * 0.03)
    dark_mask = (gray < 160).astype(np.uint8)
    component_count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        dark_mask, 8
    )
    for component_index in range(1, component_count):
        x, y, box_width, box_height, area = stats[component_index]
        inner = (
            x > frame
            and y > frame
            and x + box_width < width - frame
            and y + box_height < height - frame
        )
        if area < 15 and not inner:
            gray[labels == component_index] = 255

    dark = gray < 160
    column_density = dark.mean(axis=0)
    row_density = dark.mean(axis=1)
    column_ink = dark.sum(axis=0)
    row_ink = dark.sum(axis=1)
    content_x = np.where(column_ink > height * 0.004)[0]
    content_y = np.where(row_ink > width * 0.004)[0]
    content_left, content_right = (
        (int(content_x[0]), int(content_x[-1]))
        if len(content_x)
        else (0, width - 1)
    )
    content_top, content_bottom = (
        (int(content_y[0]), int(content_y[-1]))
        if len(content_y)
        else (0, height - 1)
    )

    def junk_width(profile: np.ndarray, limit: int) -> int:
        index = 0
        gap = 0
        max_width = int(limit * max_frac)
        while index < max_width and index < len(profile):
            if profile[index] > 0.02:
                gap = 0
            else:
                gap += 1
                if gap > 3:
                    break
            index += 1
        return max(0, index - gap)

    base = base or {}
    base_left = max(0, int(base.get("left", int(width * INSET_FRAC))) - 4)
    base_right = max(0, int(base.get("right", int(width * INSET_FRAC))) - 4)
    base_top = max(0, int(base.get("top", int(height * INSET_FRAC))) - 4)
    base_bottom = max(0, int(base.get("bottom", int(height * INSET_FRAC))) - 4)

    def clamp_cut(base_cut: int, junk_cut: int, distance_to_content: int) -> int:
        return base_cut + max(0, min(junk_cut + extra, distance_to_content - base_cut - pad))

    cuts = {
        "left": clamp_cut(
            base_left,
            junk_width(column_density[base_left:], width),
            content_left,
        ),
        "right": clamp_cut(
            base_right,
            junk_width(column_density[::-1][base_right:], width),
            width - 1 - content_right,
        ),
        "top": clamp_cut(
            base_top,
            junk_width(row_density[base_top:], height),
            content_top,
        ),
        "bottom": clamp_cut(
            base_bottom,
            junk_width(row_density[::-1][base_bottom:], height),
            height - 1 - content_bottom,
        ),
    }
    left = min(cuts["left"], max(0, width - 2))
    right = min(cuts["right"], max(0, width - left - 2))
    top = min(cuts["top"], max(0, height - 2))
    bottom = min(cuts["bottom"], max(0, height - top - 2))
    cuts = {"left": left, "right": right, "top": top, "bottom": bottom}

    cropped = gray[top : height - bottom, left : width - right]
    flags: list[str] = []
    out_height, out_width = cropped.shape
    if out_height < 1 or out_width < 1:
        raise PhotoPreprocessingError("Content-protected crop removed the whole page")

    cropped_dark = cropped < 160
    cropped_x = np.where(cropped_dark.sum(axis=0) > out_height * 0.002)[0]
    cropped_y = np.where(cropped_dark.sum(axis=1) > out_width * 0.002)[0]
    if len(cropped_x) and (cropped_x[0] < 20 or out_width - 1 - cropped_x[-1] < 20):
        flags.append("possible_overcrop_lr")
    if len(cropped_y) and (cropped_y[0] < 20 or out_height - 1 - cropped_y[-1] < 20):
        flags.append("possible_overcrop_tb")
    if len(cropped_x) and len(cropped_y):
        content_box = np.zeros_like(cropped_dark)
        content_box[cropped_y[0] : cropped_y[-1] + 1, cropped_x[0] : cropped_x[-1] + 1] = True
        residual = float((cropped_dark & ~content_box).mean())
        if residual > 0.03:
            flags.append(f"possible_undercrop_residual_{residual:.0%}")

    return cv2.cvtColor(cropped, cv2.COLOR_GRAY2BGR), cuts, flags


def map_warp_rect_to_source(inverse_matrix: np.ndarray, points: np.ndarray) -> np.ndarray:
    mapped = cv2.perspectiveTransform(
        points.astype(np.float32).reshape(1, -1, 2), inverse_matrix
    ).reshape(-1, 2)
    return order_points(mapped.astype(np.float32))


def stitch_pages_horizontally(pages: list[PreprocessedPage]) -> np.ndarray:
    if len(pages) == 1:
        return pages[0].image
    max_height = max(page.image.shape[0] for page in pages)
    resized: list[np.ndarray] = []
    for page in pages:
        height, width = page.image.shape[:2]
        if height == max_height:
            resized.append(page.image)
        else:
            resized.append(
                cv2.resize(
                    page.image,
                    (max(1, int(width * max_height / height)), max_height),
                    interpolation=cv2.INTER_AREA,
                )
            )
    return cv2.hconcat(resized)


def _page_quality(
    *,
    label: str,
    source_quad: np.ndarray,
    image: np.ndarray,
    elapsed_ms: float,
    extra: dict,
) -> dict:
    skew_angle, skew_debug = estimate_horizontal_text_skew(image)
    return {
        "detector": "scan_stable_v1",
        "label": label,
        "sharpness": round(estimate_sharpness(image), 2),
        "quad_edge_angles": quad_edge_angle_metadata(source_quad),
        "residual_horizontal_text_angle": None
        if skew_angle is None
        else round(float(skew_angle), 3),
        "text_skew": skew_debug,
        "elapsed_ms": round(elapsed_ms, 1),
        "debug": extra,
    }


def preprocess_scan_stable_bytes(contents: bytes) -> PreprocessedExamPhoto:
    total_started = time.perf_counter()
    image_buffer = np.frombuffer(contents, dtype=np.uint8)
    image = cv2.imdecode(image_buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise PhotoPreprocessingError("Could not decode scan image")

    detection_started = time.perf_counter()
    quad, mask, platform_debug = find_stable_paper_quad(image)
    detection_ms = round((time.perf_counter() - detection_started) * 1000, 1)

    warp_started = time.perf_counter()
    flat, matrix = warp_with_matrix(image, quad)
    warp_ms = round((time.perf_counter() - warp_started) * 1000, 1)

    split_started = time.perf_counter()
    height, width = flat.shape[:2]
    aspect = width / max(1, height)
    inverse_matrix = np.linalg.inv(matrix)
    pages: list[PreprocessedPage] = []
    open_sides = set(platform_debug.get("open_sides", []))
    split_debug: dict[str, object] = {
        "aspect": round(float(aspect), 4),
        "mode": "single_page" if aspect <= 1.0 else "two_page",
    }
    overlap_pixels = 0
    gutter_ratio: float | None = None
    if aspect > 1.0:
        cut_left, cut_right, pad, gutter_debug = find_gutter_cuts(flat)
        # Preserve a small overlap around the fold. The original files(3)
        # script removes the whole gutter-safe band (left page ends at
        # cut_left, right page starts at cut_right). On real exam sheets,
        # question numbers can sit very close to the inner binding edge; deleting
        # that band can remove labels such as "5.". Keeping overlap is safer for
        # recognition: a little duplicated/blank gutter is recoverable, a missing
        # question number is not.
        left_end = max(cut_left + 1, cut_right)
        right_start = min(cut_right - 1, cut_left)
        split_debug = {
            **split_debug,
            **gutter_debug,
            "content_preserving_overlap": {
                "enabled": True,
                "left_end": int(left_end),
                "right_start": int(right_start),
                "overlap_width": int(max(0, left_end - right_start)),
                "reason": "protect question numbers near inner gutter",
            },
        }
        gutter_ratio = float(((cut_left + cut_right) / 2.0) / max(1, width))
        overlap_pixels = max(0, left_end - right_start)
        page_specs = [
            ("page_1_left.jpg", "left", flat[:, :left_end], 0, left_end, 0, 0),
            (
                "page_2_right.jpg",
                "right",
                flat[:, right_start:],
                right_start,
                width,
                0,
                0,
            ),
        ]
    else:
        page_specs = [("page_1.jpg", "single", flat, 0, width, 0, 0)]

    split_ms = round((time.perf_counter() - split_started) * 1000, 1)

    enhance_started = time.perf_counter()
    for name, label, page_bgr, x_start, x_end, wipe_left, wipe_right in page_specs:
        page_started = time.perf_counter()
        full_enhanced = enhance_stable_page(
            page_bgr, wipe_left=int(wipe_left), wipe_right=int(wipe_right)
        )
        crop_base: dict[str, int] = {}
        if wipe_left:
            crop_base["left"] = 0
        if wipe_right:
            crop_base["right"] = 0
        for open_side in open_sides:
            if open_side in ("top", "bottom") or open_side == label:
                crop_base[open_side] = 0
        enhanced, crop_cuts, crop_flags = content_protect_crop(
            full_enhanced,
            base=crop_base,
        )
        crop_left = int(crop_cuts["left"])
        crop_right = int(crop_cuts["right"])
        crop_top = int(crop_cuts["top"])
        crop_bottom = int(crop_cuts["bottom"])
        source_rect = np.array(
            [
                [x_start + crop_left, crop_top],
                [x_end - 1 - crop_right, crop_top],
                [x_end - 1 - crop_right, height - 1 - crop_bottom],
                [x_start + crop_left, height - 1 - crop_bottom],
            ],
            dtype=np.float32,
        )
        source_quad = map_warp_rect_to_source(inverse_matrix, source_rect)
        pages.append(
            PreprocessedPage(
                name=name,
                image=enhanced,
                x_start=int(x_start),
                x_end=int(x_end),
                source_quad=source_quad.round(2).tolist(),
                homography=matrix.round(8).tolist(),
                quality=_page_quality(
                    label=label,
                    source_quad=source_quad,
                    image=enhanced,
                    elapsed_ms=(time.perf_counter() - page_started) * 1000,
                    extra={
                        "wipe_left": int(wipe_left),
                        "wipe_right": int(wipe_right),
                        "content_protect_crop": {
                            "base": crop_base,
                            "cuts": crop_cuts,
                            "flags": crop_flags,
                            "full_size": [
                                int(full_enhanced.shape[1]),
                                int(full_enhanced.shape[0]),
                            ],
                            "final_size": [
                                int(enhanced.shape[1]),
                                int(enhanced.shape[0]),
                            ],
                        },
                    },
                ),
            )
        )
    enhance_ms = round((time.perf_counter() - enhance_started) * 1000, 1)

    warnings = build_page_quality_warnings(pages)
    enhanced_spread = stitch_pages_horizontally(pages)
    split_strategy = (
        "scan_stable_two_page_gutter" if len(pages) == 2 else "scan_stable_single_page"
    )
    return PreprocessedExamPhoto(
        pdf_bytes=encode_pdf(pages),
        pages=pages,
        detected_quad=order_points(quad).round(2).tolist(),
        spread_size=(int(flat.shape[1]), int(flat.shape[0])),
        split=SplitMetadata(
            strategy=split_strategy,
            gutter_ratio=None if gutter_ratio is None else round(gutter_ratio, 4),
            gutter_confidence=None,
            overlap_pixels=int(overlap_pixels),
        ),
        quality_status=quality_status_from_warnings(warnings),
        quality_warnings=warnings,
        mask=mask,
        warped_spread=flat,
        enhanced_spread=enhanced_spread,
        debug={
            "engine": "scan_stable_v1",
            "source": "ported_from_downloads_files_3_scan_stable_py",
            "input_size": [int(image.shape[1]), int(image.shape[0])],
            "platform_detection": platform_debug,
            "split_debug": split_debug,
            "page_count": len(pages),
            "timings": {
                "stable_platform_detection_ms": detection_ms,
                "perspective_warp_ms": warp_ms,
                "gutter_split_ms": split_ms,
                "enhance_clean_edges_ms": enhance_ms,
                "total_ms": round((time.perf_counter() - total_started) * 1000, 1),
            },
            "faithful_core_functions": [
                "find_paper_quad threshold platform",
                "expand quad before warp",
                "warp perspective upscale 1.4",
                "find_gutter_cuts 1D opening",
                "enhance divide-by-background",
                "clear_border_blobs",
                "content_protect_crop",
            ],
        },
    )
