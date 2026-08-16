import threading
from io import BytesIO
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image
from pypdfium2 import PdfiumError

# pypdfium2 非线程安全：并发渲染会损坏库内部状态，之后所有 PDF
# 操作持续报错（"Stored PDF could not be opened"）。进程内串行化。
PDFIUM_LOCK = threading.Lock()


class InvalidPdfError(ValueError):
    pass


def get_pdf_page_count(path: Path) -> int:
    with PDFIUM_LOCK:
        try:
            pdf = pdfium.PdfDocument(path)
        except PdfiumError as exc:
            raise InvalidPdfError("Invalid PDF file") from exc
        try:
            return len(pdf)
        finally:
            pdf.close()


def render_pdf_page_png(path: Path, page_number: int, scale: float = 2.0) -> bytes:
    with PDFIUM_LOCK:
        try:
            pdf = pdfium.PdfDocument(path)
        except PdfiumError as exc:
            raise InvalidPdfError("Invalid PDF file") from exc
        try:
            if page_number < 1 or page_number > len(pdf):
                raise IndexError("PDF page out of range")
            page = pdf[page_number - 1]
            try:
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil()
                buffer = BytesIO()
                image.save(buffer, format="PNG")
                return buffer.getvalue()
            finally:
                page.close()
        finally:
            pdf.close()


def render_pdf_page_jpeg(
    path: Path, page_number: int, scale: float = 2.0, quality: int = 82
) -> bytes:
    """页面预览用 JPEG：同尺寸下体积约为 PNG 的 1/15，跨区域加载明显更快。

    批卷/框选等页面预览接口专用；裁切、识别等需要无损图的流程仍用 PNG。
    """
    with PDFIUM_LOCK:
        try:
            pdf = pdfium.PdfDocument(path)
        except PdfiumError as exc:
            raise InvalidPdfError("Invalid PDF file") from exc
        try:
            if page_number < 1 or page_number > len(pdf):
                raise IndexError("PDF page out of range")
            page = pdf[page_number - 1]
            try:
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil().convert("RGB")
                buffer = BytesIO()
                image.save(buffer, format="JPEG", quality=quality, optimize=True)
                return buffer.getvalue()
            finally:
                page.close()
        finally:
            pdf.close()


def image_bytes_to_pdf(contents: bytes) -> bytes:
    """Encode a single image (JPEG/PNG) as a one-page PDF."""
    try:
        with Image.open(BytesIO(contents)) as image:
            buffer = BytesIO()
            image.convert("RGB").save(buffer, format="PDF")
            return buffer.getvalue()
    except (OSError, ValueError) as exc:
        raise InvalidPdfError("Image could not be converted to PDF") from exc


def merge_pdf_bytes(*pdf_blobs: bytes) -> bytes:
    """Concatenate the pages of the given PDFs into a single PDF."""
    with PDFIUM_LOCK:
        merged = pdfium.PdfDocument.new()
        sources: list[pdfium.PdfDocument] = []
        try:
            for blob in pdf_blobs:
                try:
                    source = pdfium.PdfDocument(blob)
                except PdfiumError as exc:
                    raise InvalidPdfError("Invalid PDF file") from exc
                sources.append(source)
                merged.import_pages(source)
            buffer = BytesIO()
            merged.save(buffer)
            return buffer.getvalue()
        finally:
            merged.close()
            for source in sources:
                source.close()
