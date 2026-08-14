"""ZIP 答卷包解包：一包照片等价于一次传多张照片。

收卷时一个学生的答卷常打成一个 zip（内装 JPG/PNG 照片）。这里负责：
- 解包并挑出图片（非图片文件跳过），按文件名 numeric 自然排序；
- 逐张走现有照片预处理（auto/force/none 语义与单张照片一致），合并为多页 PDF。
"""

import re
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Literal

from fastapi import HTTPException

from app.services.exam_photo_preprocessing import PhotoPreprocessingError
from app.services.pdf_rendering import image_bytes_to_pdf, merge_pdf_bytes
from app.services.scan_preprocessing import preprocess_scan_photo_bytes

MAX_ZIP_IMAGES = 50
ZIP_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}

_DIGIT_RUN = re.compile(r"\d+")
# macOS/Windows 打包工具产生的元数据目录，一律跳过
_SKIP_PREFIXES = ("__MACOSX/",)


def natural_sort_key(name: str) -> tuple:
    """文件名 numeric 自然排序键：1 < 2 < ... < 10，而不是字符串序。"""
    stem = Path(name).name.lower()
    key: list[tuple[int, object]] = []
    cursor = 0
    for match in _DIGIT_RUN.finditer(stem):
        key.append((0, stem[cursor : match.start()]))
        key.append((1, int(match.group())))
        cursor = match.end()
    key.append((0, stem[cursor:]))
    return tuple(key)


def extract_zip_images(contents: bytes) -> list[tuple[str, bytes]]:
    """解包 zip，返回按文件名自然排序的 (文件名, 图片字节) 列表。

    非图片文件跳过；空 zip / 无图片 / 损坏 zip / 图片数超限 → 422。
    """
    try:
        archive = zipfile.ZipFile(BytesIO(contents))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=422, detail="ZIP 文件损坏，无法解包") from exc
    images: list[tuple[str, bytes]] = []
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            if name.startswith(_SKIP_PREFIXES) or Path(name).name.startswith("."):
                continue
            if Path(name).suffix.lower() not in ZIP_IMAGE_EXTENSIONS:
                continue
            images.append((name, archive.read(info)))
    if not images:
        raise HTTPException(status_code=422, detail="ZIP 包里没有可用的照片（JPG/PNG）")
    if len(images) > MAX_ZIP_IMAGES:
        raise HTTPException(
            status_code=422,
            detail=f"ZIP 包内照片超过 {MAX_ZIP_IMAGES} 张，请分包后上传",
        )
    images.sort(key=lambda item: natural_sort_key(item[0]))
    return images


def build_pdf_bytes_from_zip(
    contents: bytes,
    *,
    preprocess_mode: Literal["auto", "force", "none"],
) -> tuple[bytes, int, int]:
    """把 zip 内照片转成多页 PDF，返回 (pdf_bytes, 图片数, 预处理成功数)。

    auto：逐张尝试照片预处理，失败的照片退化为原图直接转一页；
    force：任一照片预处理失败即 422；
    none：全部原图直接转 PDF 页。
    """
    images = extract_zip_images(contents)
    page_blobs: list[bytes] = []
    preprocessed_count = 0
    for name, image_contents in images:
        if preprocess_mode == "none":
            page_blobs.append(image_bytes_to_pdf(image_contents))
            continue
        try:
            preprocessed = preprocess_scan_photo_bytes(
                image_contents,
                filename=Path(name).name,
                content_type="image/jpeg",
            )
            page_blobs.append(preprocessed.pdf_bytes)
            preprocessed_count += 1
        except PhotoPreprocessingError as exc:
            if preprocess_mode == "force":
                raise HTTPException(
                    status_code=422,
                    detail=f"Could not preprocess exam photo: {exc}",
                ) from exc
            page_blobs.append(image_bytes_to_pdf(image_contents))
    return merge_pdf_bytes(*page_blobs), len(images), preprocessed_count
