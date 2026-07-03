import base64
from io import BytesIO

from PIL import Image

from app.core.config import settings
from app.services import scan_preprocessing


def build_png_page() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (120, 180), color=(250, 250, 245)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_preprocess_scan_photo_uses_scan_http_service(monkeypatch) -> None:
    page_bytes = build_png_page()

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "engine": "paddlex_doc_preprocessor_v1",
                "pages": [
                    {
                        "name": "page_1.jpg",
                        "image_base64": base64.b64encode(page_bytes).decode(),
                    }
                ],
                "quality": {
                    "status": "review",
                    "warnings": [
                        {
                            "code": "content_near_top_edge",
                            "severity": "warning",
                            "message": "Crop should be reviewed.",
                        }
                    ],
                },
                "split": {"strategy": "scan_service_single_page"},
            }

    def fake_post(*_args, **_kwargs):
        return FakeResponse()

    monkeypatch.setattr(settings, "SCAN_ENGINE", "scan_http")
    monkeypatch.setattr(
        settings, "SCAN_HTTP_URL", "http://ocr-service:8010/preprocess"
    )
    monkeypatch.setattr(scan_preprocessing.httpx, "post", fake_post)

    result = scan_preprocessing.preprocess_scan_photo_bytes(
        b"input-image",
        filename="phone.jpg",
        content_type="image/jpeg",
    )

    assert result.pdf_bytes.startswith(b"%PDF")
    assert len(result.pages) == 1
    assert result.pages[0].name == "page_1.jpg"
    assert result.split.strategy == "scan_service_single_page"
    assert result.quality_status == "review"
    assert result.quality_warnings[0].code == "content_near_top_edge"


def test_preprocess_scan_photo_rejects_invalid_scan_service_page(
    monkeypatch,
) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "pages": [{"name": "page_1.jpg", "image_base64": "not-base64"}],
                "quality": {"status": "fail"},
            }

    def fake_post(*_args, **_kwargs):
        return FakeResponse()

    monkeypatch.setattr(settings, "SCAN_ENGINE", "scan_http")
    monkeypatch.setattr(scan_preprocessing.httpx, "post", fake_post)

    try:
        scan_preprocessing.preprocess_scan_photo_bytes(b"input-image")
    except scan_preprocessing.PhotoPreprocessingError as exc:
        assert "invalid page image" in str(exc)
    else:
        raise AssertionError("Expected invalid scan-service page to fail")
