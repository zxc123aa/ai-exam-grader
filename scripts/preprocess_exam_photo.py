from __future__ import annotations

import argparse
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.exam_photo_preprocessing import preprocess_exam_photo_bytes


def preprocess_photo(input_path: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    result = preprocess_exam_photo_bytes(input_path.read_bytes())

    debug = cv2.imread(str(input_path))
    if debug is not None:
        points = np.array(result.detected_quad, dtype=np.int32)
        cv2.polylines(debug, [points], True, (0, 0, 255), 4)
        cv2.imwrite(str(output_dir / "00_detected_quad.jpg"), debug)

    cv2.imwrite(str(output_dir / "00_mask.jpg"), result.mask)
    cv2.imwrite(str(output_dir / "01_warped_spread.jpg"), result.warped_spread)
    cv2.imwrite(str(output_dir / "02_enhanced_spread.jpg"), result.enhanced_spread)

    page_paths: list[Path] = []
    for page in result.pages:
        page_path = output_dir / page.name
        cv2.imwrite(str(page_path), page.image)
        page_paths.append(page_path)

    output_pdf = output_dir / f"{input_path.stem}_preprocessed.pdf"
    output_pdf.write_bytes(result.pdf_bytes)

    print(f"input={input_path}")
    print(f"output_dir={output_dir}")
    print(f"quad={result.detected_quad}")
    print(f"spread_size={result.spread_size[0]}x{result.spread_size[1]}")
    print(f"split_strategy={result.split.strategy}")
    print(f"gutter_ratio={result.split.gutter_ratio}")
    print(f"gutter_confidence={result.split.gutter_confidence}")
    for page, page_path in zip(result.pages, page_paths, strict=True):
        print(
            f"{page.name}={page.image.shape[1]}x{page.image.shape[0]} "
            f"x_range={page.x_start}:{page.x_end} path={page_path}"
        )
    print(f"pdf={output_pdf}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    output_dir = args.output_dir or args.input.parent / "processed" / args.input.stem
    preprocess_photo(args.input, output_dir)


if __name__ == "__main__":
    main()
