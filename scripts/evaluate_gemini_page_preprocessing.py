from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import cv2

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.scan_preprocessing import detect_page_polygons_with_gemini  # noqa: E402
from app.services.exam_photo_preprocessing import (  # noqa: E402
    PhotoPreprocessingError,
    preprocess_exam_photo_with_page_quads,
    stitch_debug_spread,
)


DEFAULT_INPUTS = [
    ROOT / "参考算法" / "2_试卷分析文件" / "material" / "样本2" / "0_0.jpg",
    ROOT / "参考算法" / "2_试卷分析文件" / "material" / "样本2" / "0_1.jpg",
    ROOT / "参考算法" / "2_试卷分析文件" / "material" / "样本2" / "0_2.jpg",
    ROOT / "参考算法" / "2_试卷分析文件" / "material" / "样本2" / "0_3.jpg",
    ROOT / "参考算法" / "2_试卷分析文件" / "material" / "样本2" / "0_4.jpg",
    ROOT / "参考算法" / "2_试卷分析文件" / "material" / "1.jpg",
    ROOT / "参考算法" / "2_试卷分析文件" / "material" / "2.jpg",
]


def image_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    return "image/jpeg"


def warning_codes(result: Any) -> list[str]:
    return [warning.code for warning in result.quality_warnings]


def evaluate_one(path: Path, *, output_dir: Path, margin_mode: str) -> dict[str, Any]:
    started = time.perf_counter()
    contents = path.read_bytes()
    image = cv2.imread(str(path))
    if image is None:
        return {
            "file": str(path),
            "status": "decode_failed",
            "wall_ms": round((time.perf_counter() - started) * 1000),
        }
    height, width = image.shape[:2]
    expected_page_count = 2 if width >= height * 1.2 else 1
    detection = detect_page_polygons_with_gemini(
        contents=contents,
        content_type=image_content_type(path),
        expected_page_count=expected_page_count,
    )
    item: dict[str, Any] = {
        "file": str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path),
        "image_size": [width, height],
        "expected_page_count": expected_page_count,
        "detection_status": detection.status,
        "model": detection.model,
        "model_elapsed_ms": detection.elapsed_ms,
        "returned_page_count": len(detection.quads),
        "confidences": [round(value, 4) for value in detection.confidences],
        "labels": detection.labels,
        "rejection_reason": detection.rejection_reason,
        "attempts": detection.attempts,
    }
    if detection.status != "accepted":
        item["wall_ms"] = round((time.perf_counter() - started) * 1000)
        return item

    try:
        processed = preprocess_exam_photo_with_page_quads(
            contents,
            detection.quads,
            detector=f"gemini:{detection.model}",
            margin_mode=margin_mode,
        )
    except PhotoPreprocessingError as exc:
        item.update(
            {
                "preprocess_status": "failed",
                "preprocess_error": str(exc),
                "wall_ms": round((time.perf_counter() - started) * 1000),
            }
        )
        return item

    stem_dir = output_dir / path.stem
    stem_dir.mkdir(parents=True, exist_ok=True)
    overlay = image.copy()
    colors = [(0, 180, 255), (0, 255, 0)]
    for index, quad in enumerate(detection.quads):
        points = quad.astype("int32").reshape((-1, 1, 2))
        color = colors[index % len(colors)]
        cv2.polylines(overlay, [points], isClosed=True, color=color, thickness=6)
        label = (
            detection.labels[index]
            if index < len(detection.labels)
            else f"p{index + 1}"
        )
        cv2.putText(
            overlay,
            f"{label} {detection.confidences[index]:.2f}",
            tuple(points[0, 0]),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            color,
            3,
            cv2.LINE_AA,
        )
    overlay_path = stem_dir / "detected_overlay.jpg"
    cv2.imwrite(str(overlay_path), overlay)
    spread_path = stem_dir / "spread.jpg"
    cv2.imwrite(str(spread_path), stitch_debug_spread(processed.pages))
    page_paths: list[str] = []
    for index, page in enumerate(processed.pages, start=1):
        page_path = stem_dir / f"page_{index}.jpg"
        cv2.imwrite(str(page_path), page.image)
        page_paths.append(str(page_path.relative_to(ROOT)))

    page_aspects = [
        round(page.image.shape[1] / max(1, page.image.shape[0]), 4)
        for page in processed.pages
    ]
    item.update(
        {
            "preprocess_status": "ok",
            "output_page_count": len(processed.pages),
            "quality_status": processed.quality_status,
            "warning_codes": warning_codes(processed),
            "page_aspects": page_aspects,
            "split_axis": processed.debug.get("split_axis"),
            "preprocess_timings": processed.debug.get("timings", {}),
            "orientation_attempts": processed.debug.get("orientation_attempts", []),
            "detected_overlay": str(overlay_path.relative_to(ROOT)),
            "output_spread": str(spread_path.relative_to(ROOT)),
            "output_pages": page_paths,
            "wall_ms": round((time.perf_counter() - started) * 1000),
        }
    )
    return item


def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [item for item in items if item.get("detection_status") == "accepted"]
    transformed = [item for item in items if item.get("preprocess_status") == "ok"]
    expected_ok = [
        item
        for item in accepted
        if item.get("returned_page_count") == item.get("expected_page_count")
    ]
    confidences = [
        confidence
        for item in accepted
        for confidence in item.get("confidences", [])
        if isinstance(confidence, int | float)
    ]
    return {
        "image_count": len(items),
        "gemini_detection_accepted": len(accepted),
        "page_count_correct": len(expected_ok),
        "preprocess_ok": len(transformed),
        "avg_confidence": round(sum(confidences) / len(confidences), 4)
        if confidences
        else None,
        "avg_model_elapsed_ms": round(
            sum(item.get("model_elapsed_ms") or 0 for item in items) / len(items)
        )
        if items
        else None,
        "avg_wall_ms": round(
            sum(item.get("wall_ms") or 0 for item in items) / len(items)
        )
        if items
        else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate Gemini page polygon detection for exam scan preprocessing."
    )
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "outputs" / "gemini_page_preprocessing",
    )
    parser.add_argument(
        "--margin-mode",
        choices=["minimal", "conservative", "safe"],
        default="safe",
    )
    args = parser.parse_args()

    files = args.files or [path for path in DEFAULT_INPUTS if path.exists()]
    args.output_dir = args.output_dir.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    items = [
        evaluate_one(
            path.resolve(), output_dir=args.output_dir, margin_mode=args.margin_mode
        )
        for path in files
    ]
    report = {"summary": summarize(items), "items": items}
    report_path = args.output_dir / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"report={report_path}")


if __name__ == "__main__":
    main()
