"""Semantic reconstruction pipeline: OCR + layout -> clean exam PDF.

Main entry point that orchestrates:
1. OCR text line extraction (from cached JSON or live OCR service)
2. Reading-order correction
3. Layout parsing (sections, questions, options)
4. Clean PDF generation
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from layout_parser import parse_page_structure
from models import (
    ExamDocument,
    TextLine,
)
from pdf_generator import generate_exam_pdf
from reading_order import sort_lines_by_reading_order


def load_ocr_lines_from_json(json_path: str | Path) -> list[dict]:
    """Load cached OCR line data from a JSON file."""
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("lines", [])


def fetch_ocr_lines_from_service(
    image_path: str | Path,
    ocr_url: str = "http://localhost:8010/ocr",
    timeout: int = 60,
) -> list[dict]:
    """Fetch OCR line data from the OCR HTTP service."""
    with open(image_path, "rb") as f:
        response = httpx.post(
            ocr_url,
            files={"file": (Path(image_path).name, f, "image/jpeg")},
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
    return data.get("raw", {}).get("lines", [])


def raw_lines_to_text_lines(raw_lines: list[dict]) -> list[TextLine]:
    """Convert raw OCR line dicts to TextLine objects."""
    result: list[TextLine] = []
    for item in raw_lines:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        box = item.get("box")
        if not isinstance(box, (list, tuple)) or len(box) < 4:
            continue
        try:
            x1, y1, x2, y2 = [int(v) for v in box[:4]]
        except (ValueError, TypeError):
            continue
        if x1 == x2 or y1 == y2:
            continue
        conf = item.get("confidence")
        try:
            conf = float(conf) if conf is not None else None
        except (ValueError, TypeError):
            conf = None
        result.append(
            TextLine(
                text=text,
                x=min(x1, x2),
                y=min(y1, y2),
                width=abs(x2 - x1),
                height=abs(y2 - y1),
                confidence=conf,
            )
        )
    return result


def get_page_dimensions(image_path: str | Path) -> tuple[float, float]:
    """Get page width and height from an image file."""
    from PIL import Image
    with Image.open(image_path) as img:
        return img.width, img.height


def reconstruct_exam(
    *,
    page_image_paths: list[str | Path],
    ocr_lines_cache: dict[str, list[dict]] | None = None,
    ocr_url: str = "http://localhost:8010/ocr",
    exam_title: str = "",
) -> ExamDocument:
    """Run the full semantic reconstruction pipeline.

    Args:
        page_image_paths: List of page image file paths in order.
        ocr_lines_cache: Optional dict mapping image path -> pre-fetched OCR lines.
        ocr_url: URL of the OCR HTTP service.
        exam_title: Title for the reconstructed exam.

    Returns:
        ExamDocument with full semantic structure.
    """
    doc = ExamDocument(title=exam_title)
    cache = ocr_lines_cache or {}

    for i, img_path in enumerate(page_image_paths):
        img_path_str = str(img_path)
        page_number = i + 1

        # Get OCR lines
        if img_path_str in cache:
            raw_lines = cache[img_path_str]
        else:
            raw_lines = fetch_ocr_lines_from_service(img_path, ocr_url=ocr_url)

        # Get page dimensions
        page_width, page_height = get_page_dimensions(img_path)

        # Convert to TextLine objects
        text_lines = raw_lines_to_text_lines(raw_lines)

        # Sort by reading order
        sorted_lines = sort_lines_by_reading_order(
            text_lines, page_width=page_width
        )

        # Parse page structure
        page_layout = parse_page_structure(
            sorted_lines,
            page_number=page_number,
            page_width=page_width,
            page_height=page_height,
        )

        doc.pages.append(page_layout)

    return doc


def run_physics_reconstruction() -> Path:
    """Run the reconstruction on the physics exam material and generate a PDF."""
    base = Path("D:/Songtan/ai-exam-grader/materials/physics/evaluation")

    page_images = [
        base / "pages" / "p1_left_auto.jpg",
        base / "pages" / "p1_right_auto.jpg",
        base / "pages" / "p2_left_auto.jpg",
        base / "pages" / "p2_right_auto.jpg",
    ]

    # Try to load cached OCR data first
    ocr_cache: dict[str, list[dict]] = {}
    cache_names = ["p1_left", "p1_right", "p2_left", "p2_right"]
    for name, img_path in zip(cache_names, page_images):
        cache_file = base / f"ocr_lines_{name}.json"
        if cache_file.exists():
            with open(cache_file, encoding="utf-8") as f:
                data = json.load(f)
            ocr_cache[str(img_path)] = data.get("lines", [])
            print(f"  Loaded cached OCR: {name} ({len(ocr_cache[str(img_path)])} lines)")
        else:
            # Fetch fresh
            print(f"  Fetching OCR for: {name}...")
            lines = fetch_ocr_lines_from_service(str(img_path))
            ocr_cache[str(img_path)] = lines
            # Save cache
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump({"lines": lines}, f, ensure_ascii=False)

    # Reconstruct
    print("\nReconstructing exam structure...")
    doc = reconstruct_exam(
        page_image_paths=[str(p) for p in page_images],
        ocr_lines_cache=ocr_cache,
        exam_title="2024-2025 年度第二学期八年级物理（重建版）",
    )

    # Print debug info
    for page in doc.pages:
        print(f"\n--- Page {page.page_number} ---")
        print(f"  Raw lines: {len(page.raw_lines)}")
        print(f"  Header blocks: {len(page.header_blocks)}")
        print(f"  Sections: {len(page.sections)}")
        for section in page.sections:
            print(f"    Section: {section.title}")
            print(f"      Questions: {len(section.questions)}")
            for q in section.questions[:3]:
                types = [q.question_type.value]
                print(f"      Q{q.number}: type={types}, options={len(q.option_blocks)}, subs={len(q.sub_questions)}, diagram={q.has_diagram}")

    # Generate PDF
    output_dir = Path("D:/Songtan/ai-exam-grader/outputs")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "physics_exam_reconstructed.pdf"

    print(f"\nGenerating PDF: {output_path}")
    pdf_path = generate_exam_pdf(doc, output_path)
    print(f"PDF generated: {pdf_path} ({pdf_path.stat().st_size} bytes)")

    return pdf_path


if __name__ == "__main__":
    run_physics_reconstruction()
