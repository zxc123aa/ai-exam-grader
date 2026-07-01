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
