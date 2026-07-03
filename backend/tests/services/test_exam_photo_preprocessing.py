from io import BytesIO

from PIL import Image, ImageDraw

from app.services.exam_photo_preprocessing import preprocess_exam_photo_bytes


def build_scan_photo(*, size: tuple[int, int], spread: bool) -> bytes:
    image = Image.new("RGB", size, color=(72, 88, 82))
    draw = ImageDraw.Draw(image)
    width, height = size
    draw.polygon(
        [
            (int(width * 0.08), int(height * 0.10)),
            (int(width * 0.92), int(height * 0.08)),
            (int(width * 0.94), int(height * 0.90)),
            (int(width * 0.06), int(height * 0.92)),
        ],
        fill=(250, 244, 220),
    )
    if spread:
        center = int(width * 0.5)
        draw.line(
            [(center, int(height * 0.12)), (center, int(height * 0.88))],
            fill=(215, 206, 188),
            width=3,
        )
        draw.rectangle(
            (
                int(width * 0.18),
                int(height * 0.28),
                int(width * 0.38),
                int(height * 0.36),
            ),
            outline=(80, 80, 80),
            width=2,
        )
        draw.rectangle(
            (
                int(width * 0.62),
                int(height * 0.42),
                int(width * 0.84),
                int(height * 0.50),
            ),
            outline=(80, 80, 80),
            width=2,
        )
    else:
        draw.rectangle(
            (
                int(width * 0.25),
                int(height * 0.20),
                int(width * 0.75),
                int(height * 0.28),
            ),
            outline=(80, 80, 80),
            width=2,
        )

    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def build_partial_brightness_spread_photo() -> bytes:
    image = Image.new("RGB", (520, 320), color=(54, 74, 62))
    draw = ImageDraw.Draw(image)
    draw.polygon(
        [(34, 44), (265, 34), (268, 286), (22, 292)],
        fill=(250, 244, 220),
    )
    draw.polygon(
        [(264, 36), (494, 44), (504, 286), (268, 286)],
        fill=(155, 150, 138),
    )
    draw.line([(263, 42), (268, 286)], fill=(120, 114, 106), width=4)
    draw.rectangle((80, 104, 210, 132), outline=(55, 55, 55), width=2)
    draw.rectangle((320, 138, 456, 168), outline=(55, 55, 55), width=2)
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def test_preprocess_exam_photo_splits_landscape_spread() -> None:
    result = preprocess_exam_photo_bytes(
        build_scan_photo(size=(360, 220), spread=True)
    )

    assert len(result.pages) == 2
    assert result.split.strategy in {"detected_gutter", "center_fallback"}
    assert result.split.gutter_ratio is not None
    assert 0.4 <= result.split.gutter_ratio <= 0.6
    assert result.split.overlap_pixels > 0
    assert result.pages[0].x_start == 0
    assert result.pages[0].x_end > result.pages[1].x_start
    assert result.pages[1].x_end == result.spread_size[0]
    assert result.pdf_bytes.startswith(b"%PDF")


def test_preprocess_exam_photo_recovers_dim_right_page() -> None:
    result = preprocess_exam_photo_bytes(build_partial_brightness_spread_photo())

    assert len(result.pages) == 2
    assert result.split.strategy in {
        "detected_gutter",
        "center_fallback",
        "split_half_page_fallback",
    }
    assert result.spread_size[0] >= result.spread_size[1] * 1.2
    assert result.pages[0].image.shape[1] > 100
    assert result.pages[1].image.shape[1] > 100
    assert result.pdf_bytes.startswith(b"%PDF")


def test_preprocess_exam_photo_keeps_portrait_page_single() -> None:
    result = preprocess_exam_photo_bytes(
        build_scan_photo(size=(220, 360), spread=False)
    )

    assert len(result.pages) == 1
    assert result.split.strategy == "single_page"
    assert result.split.gutter_ratio is None
    assert result.split.overlap_pixels == 0
    assert result.pages[0].x_start == 0
    assert result.pages[0].x_end == result.spread_size[0]
