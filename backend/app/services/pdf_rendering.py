from io import BytesIO
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image
from pypdfium2 import PdfiumError


class InvalidPdfError(ValueError):
    pass


def get_pdf_page_count(path: Path) -> int:
    try:
        pdf = pdfium.PdfDocument(path)
    except PdfiumError as exc:
        raise InvalidPdfError("Invalid PDF file") from exc
    try:
        return len(pdf)
    finally:
        pdf.close()


def render_pdf_page_png(path: Path, page_number: int, scale: float = 2.0) -> bytes:
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
