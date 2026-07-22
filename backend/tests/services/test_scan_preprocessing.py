import base64
from io import BytesIO

from PIL import Image

from app.core.config import settings
from app.services import scan_preprocessing
from app.services.exam_photo_preprocessing import (
    PreprocessedExamPhoto,
    PreprocessedPage,
    SplitMetadata,
)


def build_png_page() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (120, 180), color=(250, 250, 245)).save(buffer, format="PNG")
    return buffer.getvalue()


def build_jpeg_spread() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (400, 240), color=(245, 245, 238)).save(
        buffer, format="JPEG"
    )
    return buffer.getvalue()


def build_baseline(*, strategy: str = "center_fallback") -> PreprocessedExamPhoto:
    import cv2
    import numpy as np

    image = np.full((240, 400, 3), 245, dtype=np.uint8)
    pages = [
        PreprocessedPage(
            "left.jpg",
            image[:, :210],
            0,
            210,
            source_quad=[[0, 0], [205, 0], [205, 239], [0, 239]],
        ),
        PreprocessedPage(
            "right.jpg",
            image[:, 190:],
            190,
            400,
            source_quad=[[195, 0], [399, 0], [399, 239], [195, 239]],
        ),
    ]
    return PreprocessedExamPhoto(
        pdf_bytes=b"%PDF",
        pages=pages,
        detected_quad=[],
        spread_size=(400, 240),
        split=SplitMetadata(strategy, 0.5, 0.0, 20),
        quality_status="review",
        quality_warnings=[],
        mask=np.zeros((240, 400), dtype=np.uint8),
        warped_spread=image,
        enhanced_spread=cv2.hconcat([pages[0].image, pages[1].image]),
        debug={},
    )


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

    class FakeClient:
        def __init__(self, *, trust_env: bool):
            assert trust_env is False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(settings, "SCAN_ENGINE", "scan_http")
    monkeypatch.setattr(
        settings, "SCAN_HTTP_URL", "http://ocr-service:8010/preprocess"
    )
    monkeypatch.setattr(scan_preprocessing.httpx, "Client", FakeClient)

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

    class FakeClient:
        def __init__(self, *, trust_env: bool):
            assert trust_env is False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(settings, "SCAN_ENGINE", "scan_http")
    monkeypatch.setattr(scan_preprocessing.httpx, "Client", FakeClient)

    try:
        scan_preprocessing.preprocess_scan_photo_bytes(b"input-image")
    except scan_preprocessing.PhotoPreprocessingError as exc:
        assert "invalid page image" in str(exc)
    else:
        raise AssertionError("Expected invalid scan-service page to fail")


def test_gemini_page_polygons_are_accepted_for_two_page_spread(monkeypatch) -> None:
    monkeypatch.setattr(settings, "PROVIDER_FLUXNODE_GEMINI_API_KEY", "configured")
    monkeypatch.setattr(
        scan_preprocessing,
        "call_json_model",
        lambda **_kwargs: (
            {
                "pages": [
                    {
                        "label": "left",
                        "confidence": 0.96,
                        "points": [[40, 70], [500, 70], [500, 940], [30, 950]],
                    },
                    {
                        "label": "right",
                        "confidence": 0.95,
                        "points": [[500, 70], [960, 60], [970, 950], [500, 940]],
                    },
                ]
            },
            "gemini-3.5-flash",
            420,
        ),
    )

    result = scan_preprocessing.refine_page_polygons_with_gemini(
        build_baseline(),
        contents=build_jpeg_spread(),
        content_type="image/jpeg",
    )

    assert len(result.pages) == 2
    assert result.split.strategy == "vision_page_polygons"
    assert result.debug["vision_polygon_fallback"] == "accepted"
    assert result.debug["vision_polygon_margin_mode"] == "minimal"


def test_gemini_page_polygons_reject_excessive_overlap(monkeypatch) -> None:
    monkeypatch.setattr(settings, "PROVIDER_FLUXNODE_GEMINI_API_KEY", "configured")
    monkeypatch.setattr(
        scan_preprocessing,
        "call_json_model",
        lambda **_kwargs: (
            {
                "pages": [
                    {
                        "label": "left",
                        "confidence": 0.96,
                        "points": [[40, 60], [700, 60], [700, 950], [40, 950]],
                    },
                    {
                        "label": "right",
                        "confidence": 0.95,
                        "points": [[300, 60], [960, 60], [960, 950], [300, 950]],
                    },
                ]
            },
            "gemini-3.5-flash",
            420,
        ),
    )

    baseline = build_baseline()
    result = scan_preprocessing.refine_page_polygons_with_gemini(
        baseline,
        contents=build_jpeg_spread(),
        content_type="image/jpeg",
    )

    assert result.pages is baseline.pages
    assert result.debug["vision_polygon_fallback"] == "rejected"
    assert "overlap" in result.debug["vision_polygon_rejection_reason"]


def test_gemini_page_polygons_reject_wrong_page_count_for_landscape(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "PROVIDER_FLUXNODE_GEMINI_API_KEY", "configured")
    monkeypatch.setattr(
        scan_preprocessing,
        "call_json_model",
        lambda **_kwargs: (
            {
                "pages": [
                    {
                        "label": "single",
                        "confidence": 0.97,
                        "points": [[40, 50], [960, 50], [960, 950], [40, 950]],
                    }
                ]
            },
            "gemini-3.5-flash",
            300,
        ),
    )

    baseline = build_baseline()
    result = scan_preprocessing.refine_page_polygons_with_gemini(
        baseline,
        contents=build_jpeg_spread(),
        content_type="image/jpeg",
    )

    assert result.pages is baseline.pages
    assert result.debug["vision_polygon_fallback"] == "rejected"
    assert "expected 2" in result.debug["vision_polygon_rejection_reason"]


def test_doc_preprocessor_rejects_geometry_regression(monkeypatch) -> None:
    import numpy as np

    baseline = build_baseline(strategy="vision_page_polygons")
    bad_page = PreprocessedPage(
        name="page_1.jpg",
        image=np.full((80, 400, 3), 245, dtype=np.uint8),
        x_start=0,
        x_end=400,
    )
    bad_result = PreprocessedExamPhoto(
        pdf_bytes=b"%PDF",
        pages=[bad_page],
        detected_quad=[],
        spread_size=(400, 80),
        split=SplitMetadata("scan_service_single_page", None, None, 0),
        quality_status="pass",
        quality_warnings=[],
        mask=np.zeros((80, 400), dtype=np.uint8),
        warped_spread=bad_page.image,
        enhanced_spread=bad_page.image,
        debug={},
    )
    monkeypatch.setattr(
        scan_preprocessing,
        "preprocess_scan_photo_http",
        lambda *_args, **_kwargs: bad_result,
    )

    result = scan_preprocessing.refine_pages_with_doc_preprocessor(
        baseline, filename="spread.jpg"
    )

    assert result.debug["doc_unwarping_applied"] == 0
    assert all(
        page.quality["doc_unwarping_applied"] is False for page in result.pages
    )
    assert any(
        warning.code == "doc_unwarping_quality_rejected"
        for warning in result.quality_warnings
    )


def test_doc_preprocessor_does_not_accept_service_warning(monkeypatch) -> None:
    import numpy as np

    baseline = build_baseline(strategy="vision_page_polygons")
    candidate_page = PreprocessedPage(
        name="page_1.jpg",
        image=baseline.pages[0].image.copy(),
        x_start=0,
        x_end=baseline.pages[0].image.shape[1],
    )
    warning = scan_preprocessing.QualityWarning(
        code="doc_preprocessor_unavailable",
        severity="warning",
        message="model unavailable",
    )
    warned_result = PreprocessedExamPhoto(
        pdf_bytes=b"%PDF",
        pages=[candidate_page],
        detected_quad=[],
        spread_size=(candidate_page.image.shape[1], candidate_page.image.shape[0]),
        split=SplitMetadata("scan_service_single_page", None, None, 0),
        quality_status="review",
        quality_warnings=[warning],
        mask=np.zeros(candidate_page.image.shape[:2], dtype=np.uint8),
        warped_spread=candidate_page.image,
        enhanced_spread=candidate_page.image,
        debug={"doc_preprocessor_available": False},
    )
    monkeypatch.setattr(
        scan_preprocessing,
        "preprocess_scan_photo_http",
        lambda *_args, **_kwargs: warned_result,
    )

    result = scan_preprocessing.refine_pages_with_doc_preprocessor(
        baseline, filename="spread.jpg"
    )

    assert result.debug["doc_unwarping_applied"] == 0
    assert all(
        attempt["reason"] == "uvdoc_service_warning"
        for attempt in result.debug["doc_unwarping_pages"]
    )
