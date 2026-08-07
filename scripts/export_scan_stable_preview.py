from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.exam_photo_preprocessing import stitch_debug_spread
from app.services.scan_stable_preprocessing import preprocess_scan_stable_bytes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    original_bytes = args.input.read_bytes()
    result = preprocess_scan_stable_bytes(original_bytes)

    original = cv2.imdecode(np.frombuffer(original_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if original is None:
        raise RuntimeError("无法读取原始图片")
    overlay = original.copy()
    cv2.polylines(
        overlay,
        [np.array(result.detected_quad, dtype=np.int32)],
        True,
        (0, 0, 255),
        4,
    )

    outputs = {
        "00_原图.jpg": original,
        "01_检测边界.jpg": overlay,
        "02_整卷摆正_未增强.jpg": result.warped_spread,
        "03_整卷摆正_清晰版.jpg": stitch_debug_spread(result.pages),
    }
    for name, image in outputs.items():
        cv2.imwrite(str(args.output_dir / name), image, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    for index, page in enumerate(result.pages, start=1):
        cv2.imwrite(
            str(args.output_dir / f"{index + 3:02d}_第{index}页.jpg"),
            page.image,
            [int(cv2.IMWRITE_JPEG_QUALITY), 95],
        )
    (args.output_dir / "06_摆正双页.pdf").write_bytes(result.pdf_bytes)

    metadata = {
        "input": str(args.input),
        "spread_size": result.spread_size,
        "detected_quad": result.detected_quad,
        "split_strategy": result.split.strategy,
        "gutter_ratio": result.split.gutter_ratio,
        "overlap_pixels": result.split.overlap_pixels,
        "quality_status": result.quality_status,
        "warnings": [warning.__dict__ for warning in result.quality_warnings],
        "pages": [
            {
                "name": page.name,
                "width": int(page.image.shape[1]),
                "height": int(page.image.shape[0]),
                "quality": page.quality,
            }
            for page in result.pages
        ],
        "debug": result.debug,
    }
    (args.output_dir / "处理信息.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
