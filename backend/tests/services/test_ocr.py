from pathlib import Path
from types import SimpleNamespace

from app.core.config import settings
from app.services import ocr


def test_extract_ocr_draft_returns_not_configured_by_default(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "OCR_ENGINE", "disabled")

    draft = ocr.extract_ocr_draft(Path("region.png"))

    assert draft.status == "not_configured"
    assert draft.text is None
    assert draft.confidence is None
    assert draft.engine == "disabled"


def test_extract_ocr_draft_uses_tesseract_command(monkeypatch) -> None:
    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout=" Answer text \n", stderr="")

    monkeypatch.setattr(settings, "OCR_ENGINE", "tesseract")
    monkeypatch.setattr(settings, "OCR_TESSERACT_COMMAND", "fake-tesseract")
    monkeypatch.setattr(ocr.subprocess, "run", fake_run)

    draft = ocr.extract_ocr_draft(Path("region.png"))

    assert draft.status == "succeeded"
    assert draft.text == "Answer text"
    assert draft.confidence is None
    assert draft.engine == "tesseract"


def test_extract_ocr_draft_uses_paddle_http_service(
    monkeypatch, tmp_path: Path
) -> None:
    image_path = tmp_path / "region.png"
    image_path.write_bytes(b"png")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "status": "succeeded",
                "text": "Recognized answer",
                "confidence": 0.92,
                "engine": "paddleocr-gpu-cu130",
            }

    def fake_post(*_args, **_kwargs):
        return FakeResponse()

    monkeypatch.setattr(settings, "OCR_ENGINE", "paddle_http")
    monkeypatch.setattr(settings, "OCR_HTTP_URL", "http://ocr-service:8010/ocr")
    monkeypatch.setattr(ocr.httpx, "post", fake_post)

    draft = ocr.extract_ocr_draft(image_path)

    assert draft.status == "succeeded"
    assert draft.text == "Recognized answer"
    assert draft.confidence == 0.92
    assert draft.engine == "paddleocr-gpu-cu130"
