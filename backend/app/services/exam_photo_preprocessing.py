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


@dataclass(frozen=True)
class PreprocessedExamPhoto:
    pdf_bytes: bytes
    pages: list[PreprocessedPage]
    detected_quad: list[list[float]]
    spread_size: tuple[int, int]


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


def find_document_quad(image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    resized, scale = resize_for_detection(image)
    lab = cv2.cvtColor(resized, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    mask = np.zeros(l_channel.shape, dtype=np.uint8)
    mask[(l_channel > 165) & (a_channel > 124) & (b_channel > 126)] = 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise PhotoPreprocessingError("No document-like bright region found")

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
    if cv2.contourArea(largest) < image_area * 0.15:
        raise PhotoPreprocessingError("Detected document region is too small")
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


def split_spread(image: np.ndarray, gutter_ratio: float = 0.5) -> list[PreprocessedPage]:
    height, width = image.shape[:2]
    if width < height * 1.2:
        return [PreprocessedPage(name="page_1.jpg", image=image)]

    center = int(width * gutter_ratio)
    overlap = max(16, int(width * 0.025))
    left = image[:, : min(width, center + overlap)]
    right = image[:, max(0, center - overlap) :]
    return [
        PreprocessedPage(name="page_1_left.jpg", image=left),
        PreprocessedPage(name="page_2_right.jpg", image=right),
    ]


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

    quad, _mask = find_document_quad(image)
    warped = four_point_transform(image, quad)
    enhanced_spread = enhance_page(warped)
    pages = split_spread(enhanced_spread)
    pdf_bytes = encode_pdf(pages)
    return PreprocessedExamPhoto(
        pdf_bytes=pdf_bytes,
        pages=pages,
        detected_quad=quad.round(1).tolist(),
        spread_size=(warped.shape[1], warped.shape[0]),
    )
