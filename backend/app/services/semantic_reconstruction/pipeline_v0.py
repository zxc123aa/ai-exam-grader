"""Semantic reconstruction V0.1: Complete pipeline with region-crop supplementation.

Features:
- Page-level OCR with contamination filtering
- Region-crop OCR for missing questions (Q1-Q4 on page 1)
- Reading order correction
- Layout parsing (sections, questions, options, sub-questions)
- High-quality PDF generation with proper formatting
- Reconstruction report
"""

from __future__ import annotations

import json
import re

# Import local modules
import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).parent))

from layout_parser import parse_page_structure
from models import (
    BlockRole,
    ExamDocument,
    PageLayout,
    Question,
    QuestionType,
    Section,
    TextBlock,
    TextLine,
)
from pdf_generator import generate_exam_pdf
from reading_order import sort_lines_by_reading_order

# ── Configuration ────────────────────────────────────────────────

BASE_DIR = Path("D:/Songtan/ai-exam-grader/materials/physics")
OUT_DIR = Path("D:/Songtan/ai-exam-grader/outputs")
OUT_DIR.mkdir(parents=True, exist_ok=True)

OCR_URL = "http://localhost:8010/ocr"


# ── OCR helpers ──────────────────────────────────────────────────

def fetch_ocr(path: str | Path) -> dict[str, Any]:
    """Fetch OCR data from the HTTP service."""
    with open(path, "rb") as f:
        r = httpx.post(
            OCR_URL,
            files={"file": (Path(path).name, f, "image/jpeg")},
            timeout=60,
        )
        r.raise_for_status()
    return r.json()


def load_or_fetch_ocr(json_path: Path, image_path: Path) -> list[dict]:
    """Load from cache or fetch fresh OCR."""
    if json_path.exists():
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("lines", [])
    data = fetch_ocr(image_path)
    lines = data.get("raw", {}).get("lines", [])
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"status": data.get("status"), "confidence": data.get("confidence"), "lines": lines}, f, ensure_ascii=False)
    return lines


def raw_to_text_lines(raw: list[dict]) -> list[TextLine]:
    """Convert raw OCR dicts to TextLine objects."""
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        box = item.get("box", [])
        if not isinstance(box, (list, tuple)) or len(box) < 4:
            continue
        try:
            x1, y1, x2, y2 = [int(v) for v in box[:4]]
        except (TypeError, ValueError):
            continue
        if x1 == x2 or y1 == y2:
            continue
        conf = item.get("confidence")
        try:
            conf = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            conf = None
        result.append(TextLine(
            text=text,
            x=min(x1, x2),
            y=min(y1, y2),
            width=abs(x2 - x1),
            height=abs(y2 - y1),
            confidence=conf,
        ))
    return result


# ── Page-level reconstruction ──────────────────────────────────

def reconstruct_page(
    image_path: Path, page_number: int, cached_lines: list[dict] | None = None
) -> PageLayout:
    """Reconstruct a single page from its OCR data."""
    from PIL import Image
    with Image.open(image_path) as img:
        pw, ph = img.width, img.height

    raw = cached_lines if cached_lines is not None else []
    text_lines = raw_to_text_lines(raw)
    sorted_lines = sort_lines_by_reading_order(text_lines, page_width=pw)

    return parse_page_structure(sorted_lines, page_number, pw, ph)


# ── Supplementary question builder ───────────────────────────────

def build_question_from_ocr_text(text: str, q_number: str, q_type: QuestionType) -> Question:
    """Build a Question object from plain OCR text."""
    q = Question(number=q_number, question_type=q_type)

    lines = text.split("\n")
    stem_blocks: list[TextBlock] = []
    option_blocks: list[TextBlock] = []

    in_options = False
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Skip noise
        if re.match(r"^[NnKkGgCcMm]\s*$", line):
            continue
        if line in ("9", "车", "0"):  # OCR artifacts from diagrams
            continue
        if line in ("房", "密"):
            continue

        # Check for option
        if re.match(r"^[A-H]\s*[\.\u3001、\)\）]", line):
            in_options = True
            option_blocks.append(TextBlock(lines=[TextLine(
                text=line, x=0, y=0, width=100, height=20
            )], role=BlockRole.OPTION))
        else:
            in_options = False
            stem_blocks.append(TextBlock(lines=[TextLine(
                text=line, x=0, y=0, width=100, height=20
            )], role=BlockRole.QUESTION_STEM))

    q.stem_blocks = stem_blocks
    q.option_blocks = option_blocks
    q.has_diagram = bool(
        "如图" in text or "图" in text
    )

    return q


def supplement_page1_questions(sections: list[Section]) -> list[Section]:
    """Supplement page 1 with Q1-Q4 from region crop OCR data."""
    # Fetch region crop OCRs
    regions = {
        "Q1-Q2": BASE_DIR / "evaluation" / "crops" / "p1_q1_q2.jpg",
        "Q3-Q4": BASE_DIR / "evaluation" / "crops" / "p1_q3_q4_diagrams.jpg",
        "Q5-Q6": BASE_DIR / "evaluation" / "crops" / "p1_q5_q6_figures.jpg",
    }

    region_text: dict[str, str] = {}
    for name, path in regions.items():
        cache = path.parent / f"ocr_{path.stem}.json"
        if cache.exists():
            with open(cache, encoding="utf-8") as f:
                data = json.load(f)
                lines = data.get("lines", [])
        else:
            data = fetch_ocr(path)
            lines = data.get("raw", {}).get("lines", [])
            with open(cache, "w", encoding="utf-8") as f:
                json.dump({"status": data.get("status"), "confidence": data.get("confidence"), "lines": lines}, f, ensure_ascii=False)
        # Concatenate text from lines
        region_text[name] = "\n".join(
            l.get("text", "") for l in lines
            if l.get("text", "").strip()
        )

    # Build Q1-Q4
    q1_q2_text = region_text.get("Q1-Q2", "")
    q3_q4_text = region_text.get("Q3-Q4", "")
    q5_q6_text = region_text.get("Q5-Q6", "")

    questions = []

    # Q1: from p1_q1_q2
    if "1." in q1_q2_text:
        q1 = build_question_from_ocr_text(q1_q2_text, "1", QuestionType.CHOICE)
        questions.append(q1)

    # Q2: from p1_q1_q2 (split by "2.")
    if "2." in q1_q2_text:
        # Extract Q2 part
        parts = q1_q2_text.split("2.")
        if len(parts) > 1:
            q2_text = "2." + parts[1].split("3.")[0] if "3." in parts[1] else "2." + parts[1]
            q2 = build_question_from_ocr_text(q2_text, "2", QuestionType.CHOICE)
            questions.append(q2)

    # Q3: from p1_q3_q4
    if "3." in q3_q4_text or "3N" in q3_q4_text:  # "3N" is diagram label, question stem is before it
        # Try to find Q3 stem
        q3 = build_question_from_ocr_text(q3_q4_text, "3", QuestionType.CHOICE)
        questions.append(q3)

    # Q4: from p1_q3_q4
    if "4." in q3_q4_text:
        parts = q3_q4_text.split("4.")
        if len(parts) > 1:
            q4_text = "4." + parts[-1]
            q4 = build_question_from_ocr_text(q4_text, "4", QuestionType.CHOICE)
            questions.append(q4)

    # Q5: from p1_q5_q6
    if "5." in q5_q6_text:
        q5 = build_question_from_ocr_text(q5_q6_text, "5", QuestionType.CHOICE)
        questions.append(q5)

    # Q6: from p1_q5_q6
    if "6." in q5_q6_text:
        parts = q5_q6_text.split("6.")
        if len(parts) > 1:
            q6_text = "6." + parts[-1]
            q6 = build_question_from_ocr_text(q6_text, "6", QuestionType.CHOICE)
            questions.append(q6)

    # Insert Q1-Q4 into the first section (choice section)
    if not sections:
        sections = [Section(title="")]

    # Prepend Q1-Q4 to first section
    existing = sections[0].questions if sections[0].questions else []
    # Filter out false positive questions from page-level
    existing = [q for q in existing if q.number not in ("0", "?", "")
                or (q.number == "?" and len(q.stem_blocks) > 0)]

    # Find Q5-Q6 in existing and remove them (they'll be from region crops too)
    existing_numbers = {q.number for q in existing}
    existing = [q for q in existing if q.number not in ("5", "6")]

    # Merge: Q1-Q6 from regions + rest from page-level
    merged = questions + existing
    sections[0].questions = merged

    # Set title if empty
    if not sections[0].title:
        sections[0].title = "一、选择题（本大题有10小题，每小题3分，共30分）"

    return sections


def supplement_page3_questions(sections: list[Section]) -> list[Section]:
    """Fix Q19 missing number on page 3."""
    if not sections or not sections[0].questions:
        return sections

    q_list = sections[0].questions
    # Find the question that has Q18 content but lacks Q19
    # Q18 is at index 0, Q19 should be between Q18 and Q20

    # Q19 was probably detected as a "?" question with Q19 content
    for i, q in enumerate(q_list):
        if q.number == "?":
            # Check if its stem mentions "探究实验" or "超载"
            stem_text = "".join(
                b.lines[0].text if b.lines else "" for b in q.stem_blocks
            )
            if "探究实验" in stem_text or "超载" in stem_text or "安全隐患" in stem_text:
                q.number = "19"
                q.question_type = QuestionType.EXPERIMENT
            # Could also be Q20 split
            elif "杠杆" in stem_text or "平衡条件" in stem_text:
                q.number = "20"
                q.question_type = QuestionType.EXPERIMENT

    # Fix Q20 (already has number 20 from OCR)
    for q in q_list:
        if q.number == "20" or (q.number == "?" and q.stem_blocks):
            # Q20 is the lever experiment question
            stem_text = "".join(b.lines[0].text if b.lines else "" for b in q.stem_blocks)
            if "杠杆" in stem_text or "平衡条件" in stem_text:
                q.number = "20"
                q.question_type = QuestionType.EXPERIMENT

    return sections


def remove_false_positives(sections: list[Section]) -> list[Section]:
    """Remove obviously false-positive questions."""
    for section in sections:
        section.questions = [
            q for q in section.questions
            if not (q.number == "0" and len(q.stem_blocks) <= 1)
            and not (q.number == "?" and not q.stem_blocks)
        ]
    return sections


# ── Main pipeline ──────────────────────────────────────────────

def run_reconstruction() -> tuple[ExamDocument, Path]:
    """Run the full reconstruction pipeline."""
    print("=" * 60)
    print("语义重建 V0.1: 八年级物理期末试卷")
    print("=" * 60)

    # Page images
    page_images = [
        BASE_DIR / "evaluation" / "pages" / "p1_left_auto.jpg",
        BASE_DIR / "evaluation" / "pages" / "p1_right_auto.jpg",
        BASE_DIR / "evaluation" / "pages" / "p2_left_auto.jpg",
        BASE_DIR / "evaluation" / "pages" / "p2_right_auto.jpg",
    ]

    # Load cached OCR
    ocr_cache = {}
    cache_names = ["p1_left", "p1_right", "p2_left", "p2_right"]
    for name, img_path in zip(cache_names, page_images):
        cache_file = BASE_DIR / "evaluation" / f"ocr_lines_{name}.json"
        lines = load_or_fetch_ocr(cache_file, img_path)
        ocr_cache[str(img_path)] = lines
        print(f"  {name}: {len(lines)} OCR lines")

    # Build document
    doc = ExamDocument(title="2024-2025 年度第二学期八年级物理期末检测题（重建版）")

    for i, img_path in enumerate(page_images):
        page = reconstruct_page(img_path, page_number=i+1, cached_lines=ocr_cache[str(img_path)])
        doc.pages.append(page)

    # Apply supplements
    doc.pages[0].sections = supplement_page1_questions(doc.pages[0].sections)
    doc.pages[2].sections = supplement_page3_questions(doc.pages[2].sections)

    # Remove false positives across all pages
    for page in doc.pages:
        page.sections = remove_false_positives(page.sections)

    # Print summary
    print("\n" + "=" * 60)
    print("重建结构摘要")
    print("=" * 60)
    total_q = 0
    for page in doc.pages:
        print(f"\n第 {page.page_number} 页:")
        print(f"  Header: {len(page.header_blocks)} blocks")
        print(f"  Sections: {len(page.sections)}")
        for section in page.sections:
            print(f"    Section: {section.title}")
            print(f"      Questions: {len(section.questions)}")
            for q in section.questions:
                total_q += 1
                stem_preview = ""
                if q.stem_blocks and q.stem_blocks[0].lines:
                    stem_preview = q.stem_blocks[0].lines[0].text[:40]
                print(f"      Q{q.number}: type={q.question_type.value}, options={len(q.option_blocks)}, subs={len(q.sub_questions)}, diagram={q.has_diagram}")
                if stem_preview:
                    print(f"        Stem: {stem_preview}")
    print(f"\n总计: {total_q} 题")

    # Generate PDF
    print("\n生成 PDF...")
    pdf_path = OUT_DIR / "physics_exam_reconstructed_v0.pdf"
    generate_exam_pdf(doc, pdf_path)
    print(f"PDF: {pdf_path} ({pdf_path.stat().st_size:,} bytes)")

    return doc, pdf_path


if __name__ == "__main__":
    run_reconstruction()
