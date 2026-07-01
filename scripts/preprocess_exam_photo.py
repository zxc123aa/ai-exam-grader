from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


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


def resize_for_detection(image: np.ndarray, max_width: int = 1200) -> tuple[np.ndarray, float]:
    height, width = image.shape[:2]
    if width <= max_width:
        return image.copy(), 1.0
    scale = max_width / width
    resized = cv2.resize(image, (max_width, int(height * scale)))
    return resized, scale


def find_document_quad(image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    resized, scale = resize_for_detection(image)
    lab = cv2.cvtColor(resized, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    # The photographed paper is bright and warm; the fabric background is darker
    # and gray-green. Lab thresholds are more stable here than HSV saturation.
    mask = np.zeros(l_channel.shape, dtype=np.uint8)
    mask[
        (l_channel > 165)
        & (a_channel > 128)
        & (b_channel > 134)
    ] = 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise RuntimeError("No document-like bright region found")

    contours = sorted(contours, key=cv2.contourArea, reverse=True)
    image_area = resized.shape[0] * resized.shape[1]
    for contour in contours[:5]:
        area = cv2.contourArea(contour)
        if area < image_area * 0.15:
            continue
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.025 * perimeter, True)
        if len(approx) == 4:
            return (approx.reshape(4, 2) / scale).astype("float32"), mask

    largest = contours[0]
    box = cv2.boxPoints(cv2.minAreaRect(largest))
    return (box / scale).astype("float32"), mask


def enhance_page(image: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced_l = clahe.apply(l_channel)
    enhanced = cv2.merge((enhanced_l, a_channel, b_channel))
    enhanced = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
    return cv2.fastNlMeansDenoisingColored(enhanced, None, 3, 3, 7, 21)


def split_spread(image: np.ndarray, gutter_ratio: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
    height, width = image.shape[:2]
    center = int(width * gutter_ratio)
    # Keep a small overlap around the fold. It is better to duplicate a narrow
    # gutter strip than to cut off questions that sit close to the center.
    overlap = max(16, int(width * 0.025))
    left = image[:, : min(width, center + overlap)]
    right = image[:, max(0, center - overlap) :]
    return left, right


def save_pdf(page_paths: list[Path], output_pdf: Path) -> None:
    pil_pages = []
    for path in page_paths:
        pil_pages.append(Image.open(path).convert("RGB"))
    try:
        first, rest = pil_pages[0], pil_pages[1:]
        first.save(output_pdf, save_all=True, append_images=rest)
    finally:
        for page in pil_pages:
            page.close()


def preprocess_photo(input_path: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    image = cv2.imread(str(input_path))
    if image is None:
        raise RuntimeError(f"Could not read image: {input_path}")

    quad, mask = find_document_quad(image)
    debug = image.copy()
    cv2.polylines(debug, [quad.astype(int)], True, (0, 0, 255), 4)
    cv2.imwrite(str(output_dir / "00_detected_quad.jpg"), debug)
    cv2.imwrite(str(output_dir / "00_mask.jpg"), mask)

    warped = four_point_transform(image, quad)
    cv2.imwrite(str(output_dir / "01_warped_spread.jpg"), warped)

    enhanced_spread = enhance_page(warped)
    cv2.imwrite(str(output_dir / "02_enhanced_spread.jpg"), enhanced_spread)

    left, right = split_spread(enhanced_spread)
    left_path = output_dir / "page_1_left.jpg"
    right_path = output_dir / "page_2_right.jpg"
    cv2.imwrite(str(left_path), left)
    cv2.imwrite(str(right_path), right)
    save_pdf([left_path, right_path], output_dir / "test1_preprocessed.pdf")

    print(f"input={input_path}")
    print(f"output_dir={output_dir}")
    print(f"quad={quad.round(1).tolist()}")
    print(f"spread_size={warped.shape[1]}x{warped.shape[0]}")
    print(f"left_size={left.shape[1]}x{left.shape[0]}")
    print(f"right_size={right.shape[1]}x{right.shape[0]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    output_dir = args.output_dir or args.input.parent / "processed" / args.input.stem
    preprocess_photo(args.input, output_dir)


if __name__ == "__main__":
    main()
