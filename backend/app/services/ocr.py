from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

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
