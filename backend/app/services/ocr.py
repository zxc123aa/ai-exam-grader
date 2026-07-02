from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.core.config import settings


@dataclass(frozen=True)
class OcrDraft:
    status: str
    text: str | None
    confidence: float | None
    engine: str
    error: str | None = None


def extract_ocr_draft(image_path: Path) -> OcrDraft:
    if settings.OCR_ENGINE == "disabled":
        return OcrDraft(
            status="not_configured",
            text=None,
            confidence=None,
            engine="disabled",
        )

    if settings.OCR_ENGINE == "paddle_http":
        return extract_http_ocr_draft(image_path)

    return extract_tesseract_ocr_draft(image_path)


def extract_http_ocr_draft(image_path: Path) -> OcrDraft:
    try:
        with image_path.open("rb") as image_file:
            response = httpx.post(
                settings.OCR_HTTP_URL,
                files={
                    "file": (
                        image_path.name,
                        image_file,
                        "image/png",
                    )
                },
                timeout=settings.OCR_HTTP_TIMEOUT_SECONDS,
            )
        response.raise_for_status()
        payload = response.json()
    except (OSError, ValueError, httpx.HTTPError) as exc:
        return OcrDraft(
            status="failed",
            text=None,
            confidence=None,
            engine="paddle_http",
            error=str(exc),
        )

    return OcrDraft(
        status=str(payload.get("status") or "succeeded"),
        text=payload.get("text"),
        confidence=payload.get("confidence"),
        engine=str(payload.get("engine") or "paddle_http"),
        error=payload.get("error"),
    )


def extract_tesseract_ocr_draft(image_path: Path) -> OcrDraft:
    try:
        result = subprocess.run(
            [
                settings.OCR_TESSERACT_COMMAND,
                str(image_path),
                "stdout",
                "--psm",
                "6",
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return OcrDraft(
            status="failed",
            text=None,
            confidence=None,
            engine="tesseract",
            error=str(exc),
        )

    if result.returncode != 0:
        return OcrDraft(
            status="failed",
            text=None,
            confidence=None,
            engine="tesseract",
            error=result.stderr.strip() or "Tesseract OCR failed",
        )

    text = result.stdout.strip() or None
    return OcrDraft(
        status="succeeded",
        text=text,
        confidence=None,
        engine="tesseract",
    )
