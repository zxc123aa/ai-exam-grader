from io import BytesIO
from pathlib import Path

import pypdfium2 as pdfium
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
