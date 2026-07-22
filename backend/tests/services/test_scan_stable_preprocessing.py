from io import BytesIO

from PIL import Image, ImageDraw

from app.core.config import settings
from app.services import scan_preprocessing
from app.services.scan_stable_preprocessing import preprocess_scan_stable_bytes


def _jpeg_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def build_stable_spread_photo() -> bytes:
    image = Image.new("RGB", (640, 420), color=(35, 42, 38))
    draw = ImageDraw.Draw(image)
    draw.polygon(
        [(46, 50), (594, 38), (610, 368), (34, 382)],
        fill=(235, 232, 218),
    )
    draw.line([(320, 48), (323, 370)], fill=(205, 202, 190), width=5)
    for y in range(88, 320, 38):
        draw.rectangle((90, y, 250, y + 8), fill=(30, 30, 30))
        draw.rectangle((390, y + 8, 550, y + 16), fill=(30, 30, 30))
    draw.rectangle((0, 310, 58, 420), fill=(10, 10, 10))
    return _jpeg_bytes(image)


def build_stable_single_photo() -> bytes:
    image = Image.new("RGB", (360, 560), color=(45, 52, 48))
    draw = ImageDraw.Draw(image)
    draw.polygon(
        [(50, 42), (320, 56), (305, 520), (38, 506)],
        fill=(238, 235, 222),
    )
    for y in range(110, 450, 42):
        draw.rectangle((86, y, 270, y + 9), fill=(35, 35, 35))
    return _jpeg_bytes(image)


def test_scan_stable_splits_landscape_spread() -> None:
    result = preprocess_scan_stable_bytes(build_stable_spread_photo())

    assert len(result.pages) == 2
    assert result.split.strategy == "scan_stable_two_page_gutter"
    assert result.split.gutter_ratio is not None
    assert 0.38 <= result.split.gutter_ratio <= 0.62
    assert result.pdf_bytes.startswith(b"%PDF")
    assert result.debug["engine"] == "scan_stable_v1"
    assert result.debug["platform_detection"]["stable_run_length"] >= 1
    assert result.debug["timings"]["total_ms"] > 0


def test_scan_stable_keeps_portrait_single_page() -> None:
    result = preprocess_scan_stable_bytes(build_stable_single_photo())

    assert len(result.pages) == 1
    assert result.split.strategy == "scan_stable_single_page"
    assert result.split.gutter_ratio is None
    assert result.pdf_bytes.startswith(b"%PDF")
    assert result.pages[0].quality["detector"] == "scan_stable_v1"


def test_scan_preprocessing_can_select_scan_stable_engine(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SCAN_ENGINE", "scan_stable_v1")

    result = scan_preprocessing.preprocess_scan_photo_bytes(
        build_stable_single_photo(),
        filename="single.jpg",
        content_type="image/jpeg",
    )

    assert len(result.pages) == 1
    assert result.debug["engine"] == "scan_stable_v1"
