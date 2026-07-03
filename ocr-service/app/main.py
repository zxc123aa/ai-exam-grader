from __future__ import annotations

import tempfile
import base64
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from fastapi import FastAPI, Form, HTTPException, UploadFile

app = FastAPI(title="AI Exam Grader Vision Service")

_ocr_model: Any | None = None
_doc_preprocessor: Any | None = None


def get_ocr_model() -> Any:
    global _ocr_model
    if _ocr_model is None:
        from paddleocr import PaddleOCR

        _ocr_model = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
    return _ocr_model


def get_doc_preprocessor() -> Any | None:
    global _doc_preprocessor
    if _doc_preprocessor is not None:
        return _doc_preprocessor
    try:
        from paddleocr import DocPreprocessor

        _doc_preprocessor = DocPreprocessor(
            use_doc_orientation_classify=True,
            use_doc_unwarping=True,
        )
    except Exception:
        _doc_preprocessor = False
    return _doc_preprocessor or None


def to_plain_result(value: Any) -> Any:
    if hasattr(value, "json") and callable(value.json):
        try:
            return value.json
        except Exception:
            pass
    if isinstance(value, dict):
        return {key: to_plain_result(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [to_plain_result(item) for item in value]
    return value


def collect_texts_and_scores(value: Any) -> tuple[list[str], list[float]]:
    texts: list[str] = []
    scores: list[float] = []

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            rec_texts = item.get("rec_texts")
            if isinstance(rec_texts, list):
                texts.extend(str(text).strip() for text in rec_texts if str(text).strip())
            rec_scores = item.get("rec_scores")
            if isinstance(rec_scores, list):
                scores.extend(
                    float(score)
                    for score in rec_scores
                    if isinstance(score, int | float)
                )
            for nested in item.values():
                walk(nested)
            return
        if isinstance(item, list | tuple):
            for nested in item:
                walk(nested)

    walk(value)
    return texts, scores


def collect_output_images(value: Any) -> list[np.ndarray]:
    images: list[np.ndarray] = []

    def walk(item: Any) -> None:
        if isinstance(item, np.ndarray):
            images.append(item)
            return
        if isinstance(item, dict):
            for key in ("output_img", "doc_preprocessor_res", "image", "img"):
                nested = item.get(key)
                if isinstance(nested, np.ndarray):
                    images.append(nested)
            for nested in item.values():
                walk(nested)
            return
        if isinstance(item, list | tuple):
            for nested in item:
                walk(nested)

    walk(value)
    return images


def encode_jpeg_base64(image: np.ndarray) -> str:
    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 94])
    if not ok:
        raise HTTPException(status_code=500, detail="Could not encode page image")
    return base64.b64encode(buffer.tobytes()).decode("ascii")


def decode_upload_image(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=422, detail="Could not decode uploaded image")
    return image


def run_doc_preprocessor(
    path: Path,
) -> tuple[list[np.ndarray], list[dict[str, str]], dict[str, Any]]:
    model = get_doc_preprocessor()
    if model is None:
        return [], [
            {
                "code": "doc_preprocessor_unavailable",
                "severity": "warning",
                "message": "Paddle document preprocessor is unavailable; returned conservative page image.",
            }
        ], {"doc_preprocessor_available": False}

    try:
        result = model.predict(input=str(path))
    except Exception as exc:
        return [], [
            {
                "code": "doc_preprocessor_failed",
                "severity": "warning",
                "message": f"Paddle document preprocessor failed: {exc}",
            }
        ], {"doc_preprocessor_available": True}

    plain = to_plain_result(result)
    images = collect_output_images(result)
    if images:
        images = [images[-1]]
    return images, [], {
        "doc_preprocessor_available": True,
        "raw_type": type(plain).__name__,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "engine": "paddleocr-gpu-cu130"}


@app.post("/ocr")
async def run_ocr(file: UploadFile) -> dict[str, Any]:
    if file.content_type not in {"image/png", "image/jpeg"}:
        raise HTTPException(status_code=415, detail="Only PNG and JPG images are supported")

    suffix = Path(file.filename or "region.png").suffix.lower() or ".png"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
        temp_path = Path(temp_file.name)
        temp_file.write(await file.read())

    try:
        result = get_ocr_model().predict(input=str(temp_path))
        plain_result = to_plain_result(result)
        texts, scores = collect_texts_and_scores(plain_result)
        confidence = sum(scores) / len(scores) if scores else None
        return {
            "status": "succeeded",
            "text": "\n".join(texts) or None,
            "confidence": confidence,
            "engine": "paddleocr-gpu-cu130",
            "raw": {
                "text_count": len(texts),
                "score_count": len(scores),
            },
        }
    finally:
        temp_path.unlink(missing_ok=True)


@app.post("/preprocess")
async def preprocess_scan(
    file: UploadFile,
    mode: str = Form(default="exam_scan"),
    engine: str = Form(default="paddlex_doc_preprocessor_v1"),
) -> dict[str, Any]:
    if file.content_type not in {"image/png", "image/jpeg"}:
        raise HTTPException(status_code=415, detail="Only PNG and JPG images are supported")
    if mode != "exam_scan":
        raise HTTPException(status_code=400, detail="Only exam_scan mode is supported")
    if engine != "paddlex_doc_preprocessor_v1":
        raise HTTPException(status_code=400, detail=f"Unsupported scan engine: {engine}")

    suffix = Path(file.filename or "scan-photo.jpg").suffix.lower() or ".jpg"
    started = time.perf_counter()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
        temp_path = Path(temp_file.name)
        temp_file.write(await file.read())

    try:
        original = decode_upload_image(temp_path)
        output_images, warnings, debug = run_doc_preprocessor(temp_path)
        if not output_images:
            output_images = [original]
        pages = [
            {
                "name": f"page_{index}.jpg",
                "image_base64": encode_jpeg_base64(image),
                "width": int(image.shape[1]),
                "height": int(image.shape[0]),
            }
            for index, image in enumerate(output_images, start=1)
        ]
        return {
            "engine": "paddlex_doc_preprocessor_v1",
            "version": "0.1.0",
            "pages": pages,
            "quality": {
                "status": "review" if warnings else "pass",
                "warnings": warnings,
            },
            "split": {
                "strategy": "scan_service_single_page"
                if len(pages) == 1
                else "scan_service_pages",
                "gutter_ratio": None,
                "gutter_confidence": None,
                "overlap_pixels": 0,
            },
            "debug": {
                **debug,
                "page_count": len(pages),
                "processing_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        }
    finally:
        temp_path.unlink(missing_ok=True)
