from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile

app = FastAPI(title="AI Exam Grader OCR Service")

_ocr_model: Any | None = None


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
