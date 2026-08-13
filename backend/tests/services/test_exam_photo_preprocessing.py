from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter

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


def build_dim_top_spread_photo() -> bytes:
    image = Image.new("RGB", (520, 320), color=(52, 80, 65))
    draw = ImageDraw.Draw(image)
    draw.polygon(
        [(28, 34), (492, 28), (500, 288), (22, 294)],
        fill=(145, 142, 132),
    )
    draw.polygon(
        [(26, 104), (494, 100), (500, 288), (22, 294)],
        fill=(248, 244, 226),
    )
    draw.line([(260, 42), (262, 286)], fill=(110, 110, 105), width=3)
    draw.rectangle((70, 66, 190, 82), fill=(20, 20, 20))
    draw.rectangle((330, 62, 450, 78), fill=(20, 20, 20))
    draw.rectangle((330, 138, 450, 160), outline=(50, 50, 50), width=2)
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def build_blurry_scan_photo() -> bytes:
    image = Image.open(BytesIO(build_scan_photo(size=(360, 220), spread=True)))
    image = image.filter(ImageFilter.GaussianBlur(radius=8))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def test_preprocess_exam_photo_splits_landscape_spread() -> None:
    result = preprocess_exam_photo_bytes(build_scan_photo(size=(360, 220), spread=True))

    assert len(result.pages) == 2
    assert result.split.strategy in {"detected_gutter", "center_fallback"}
    assert result.split.gutter_ratio is not None
    assert 0.4 <= result.split.gutter_ratio <= 0.6
    assert result.split.overlap_pixels > 0
    assert result.pages[0].x_start == 0
    assert result.pages[0].x_end > result.pages[1].x_start
    assert result.pages[1].x_end == result.spread_size[0]
    assert result.pdf_bytes.startswith(b"%PDF")
    assert result.quality_status in {"pass", "review"}
    assert isinstance(result.quality_warnings, list)


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


def test_preprocess_exam_photo_preserves_dim_top_content() -> None:
    result = preprocess_exam_photo_bytes(build_dim_top_spread_photo())

    assert len(result.pages) == 2
    top_band = result.pages[1].image[: int(result.pages[1].image.shape[0] * 0.2)]
    dark_pixel_ratio = ((top_band < 70).all(axis=2)).mean()
    assert dark_pixel_ratio > 0.02
    assert result.pdf_bytes.startswith(b"%PDF")


def test_preprocess_exam_photo_flags_blurry_upload_for_review() -> None:
    result = preprocess_exam_photo_bytes(build_blurry_scan_photo())

    assert result.quality_status == "review"
    assert any(warning.code == "low_sharpness" for warning in result.quality_warnings)
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
