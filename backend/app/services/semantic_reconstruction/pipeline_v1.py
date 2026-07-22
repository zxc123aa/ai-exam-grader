"""Semantic reconstruction V1.0: Clean pipeline without region-crop noise.

Key changes from V0:
- NO region-crop supplementation (diagram-area OCR is too noisy)
- Parse each half-page separately, then merge results logically
- Aggressive noise filtering: diagram labels (single letters, N/7N/SN etc.)
- Spatially-aware option assignment
- Global question numbering across all pages
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
from md_generator import generate_exam_markdown_file
from models import (
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

# Half-pages: each photo of a book spread half
HALF_PAGES = [
    {"name": "p1_left", "image": BASE_DIR / "evaluation" / "pages" / "p1_left_auto.jpg"},
    {"name": "p1_right", "image": BASE_DIR / "evaluation" / "pages" / "p1_right_auto.jpg"},
    {"name": "p2_left", "image": BASE_DIR / "evaluation" / "pages" / "p2_left_auto.jpg"},
    {"name": "p2_right", "image": BASE_DIR / "evaluation" / "pages" / "p2_right_auto.jpg"},
]

# Logical grouping: which half-pages form each logical exam page
LOGICAL_PAGE_GROUPS = [
    # Logical page 1: pages 1-2 of the exam (choice + fill-blank start)
    {"page_num": 1, "halves": [0, 1]},
    # Logical page 2: pages 3-4 of the exam (fill-blank cont + calc/exp)
    {"page_num": 2, "halves": [2, 3]},
]


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
        json.dump(
            {"status": data.get("status"), "confidence": data.get("confidence"), "lines": lines},
            f,
            ensure_ascii=False,
        )
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


# ── Enhanced noise filtering ─────────────────────────────────────

def filter_noise(lines: list[TextLine], page_width: float) -> list[TextLine]:
    """Aggressive multi-pass noise filtering."""
    DIAGRAM_LABEL_RE = re.compile(
        "^("
        "[A-H]$|"                    # Single option letter alone
        "[NnKkGgCcMm]$|"             # Single unit letter
        "\\d{1,2}[Nn]$|"             # Force labels like "3N", "7N"
        "\\d{1,2}[Ss][Nn]$|"         # Like "SN"
        "[甲乙丙丁戊己庚辛壬癸]$|"     # Chinese figure labels
        "^房$|^密$|^车$|^证$|^医$|"  # Known OCR artifacts
        "^型$|^线$|^名$|^现$|"
        "\\d{5,}$"                   # Long number strings
        ")$"
    )

    cutoff = page_width * 0.88
    result = []

    for l in lines:
        text = l.text.strip()

        # Pass 1: contamination from adjacent page (right-edge bleed)
        if l.x >= cutoff:
            continue

        # Pass 2: known diagram label patterns
        if DIAGRAM_LABEL_RE.match(text):
            continue

        # Pass 3: very short non-ASCII lines
        if len(text) <= 1 and not text.isascii():
            continue

        # Pass 4: short numeric-looking force/unit labels
        if re.match(r"^\\d{1,3}[NnSs]?[Nn]?$", text) and len(text) <= 4:
            continue

        result.append(l)

    return result


# ── Per-half-page reconstruction ─────────────────────────────────

def reconstruct_half_page(
    image_path: Path, name: str, cached_lines: list[dict] | None = None,
) -> PageLayout:
    """Reconstruct a single half-page from its OCR data."""
    from PIL import Image
    with Image.open(image_path) as img:
        pw, ph = img.width, img.height

    raw = cached_lines if cached_lines is not None else []
    text_lines = raw_to_text_lines(raw)

    # Filter noise before sorting
    clean = filter_noise(text_lines, pw)
    print(f"    {name}: {len(raw)}→{len(clean)} 行")

    # Sort by reading order
    sorted_lines = sort_lines_by_reading_order(clean, page_width=pw)

    return parse_page_structure(sorted_lines, 0, pw, ph)


# ── Post-parsing cleanup ─────────────────────────────────────────

def assign_global_numbers(pages: list[PageLayout]) -> None:
    """Assign sequential global question numbers across all pages."""
    counter = 0
    for page in pages:
        for section in page.sections:
            for q in section.questions:
                counter += 1
                q.number = str(counter)


def clean_option_assignment(section: Section) -> None:
    """Ensure options belong to the correct question based on vertical position."""
    questions = section.questions
    if not questions:
        return

    # Collect all options with positions
    all_options: list[tuple[float, TextBlock]] = []  # (y, block)
    for q in questions:
        for ob in q.option_blocks:
            if ob.lines:
                all_options.append((ob.lines[0].y, ob))

    # Clear and reassign
    for q in questions:
        q.option_blocks = []

    if not all_options:
        return

    all_options.sort(key=lambda t: t[0])

    for opt_y, opt_block in all_options:
        # Find the last question whose stem ends above this option
        best_qi = 0
        best_gap = float("inf")
        for qi, q in enumerate(questions):
            stem_bottom = 0
            if q.stem_blocks:
                for sb in q.stem_blocks:
                    for sl in sb.lines:
                        stem_bottom = max(stem_bottom, sl.bottom)
            if opt_y >= stem_bottom - 30:
                gap = opt_y - stem_bottom
                if gap < best_gap:
                    best_gap = gap
                    best_qi = qi
        questions[best_qi].option_blocks.append(opt_block)


def _is_garbage_stem(stem_text: str) -> bool:
    """Detect clearly corrupted stems produced by bad OCR / diagram leakage."""
    if not stem_text:
        return False
    # Leading broken punctuation (e.g. ")", "(", "）")
    if stem_text[0] in "）（)]":
        return True
    # Starts with a bare option letter (e.g. "D动能增大") — misparse
    if re.match(r"^[A-H][^.\u3001、）)]", stem_text):
        return True
    # Multiple "第X题" diagram labels leaked into the stem
    if len(re.findall(r"第\d+题", stem_text)) >= 2:
        return True
    # Explicit OCR noise tokens
    if any(tok in stem_text for tok in ["000", "电型", ">hg", "mx=mg"]):
        return True
    return False


def merge_leading_fragment(sections: list[Section]) -> None:
    """Merge a dangling first-question fragment forward into the next question.

    Sometimes the head of a question is lost (e.g. its number/stem fell in a
    filtered zone) and only a mid-sentence tail is parsed as the first question
    of a section. If that first question has no number prefix and the next
    question does, append the fragment to the next question's stem.
    """
    NUM_PREFIX_RE = re.compile(r"^\s*\d{1,3}\s*[\.\u3001、）)]\s*(?!\d)")
    SENTENCE_START_RE = re.compile(r"^(\d|[（(]|第|求|如图|为减少|根据|实验|探究)")
    for section in sections:
        if len(section.questions) < 2:
            continue
        first = section.questions[0]
        first_text = "".join(l.text for b in first.stem_blocks for l in b.lines).strip()
        next_q = section.questions[1]
        next_text = "".join(l.text for b in next_q.stem_blocks for l in b.lines).strip()
        is_fragment = (
            len(first.option_blocks) == 0
            and len(first.sub_questions) == 0
            and 3 < len(first_text) < 120
            and not NUM_PREFIX_RE.match(first_text[:12])
            and not SENTENCE_START_RE.match(first_text)
            and NUM_PREFIX_RE.match(next_text[:12])  # next has a real number
        )
        if is_fragment:
            # Prepend fragment to the next question's stem blocks
            next_q.stem_blocks = first.stem_blocks + next_q.stem_blocks
            next_q.has_diagram = next_q.has_diagram or first.has_diagram
            section.questions = section.questions[1:]


def merge_continuation_fragments(sections: list[Section]) -> None:
    """Merge a question into the previous one when it is clearly a mid-sentence
    continuation (the previous question did not end with terminal punctuation
    and the current one does not start a new question).

    This recovers questions that OCR split across two fragments, e.g.
    '...阻力为总重的' + '03倍(ρ=...)，求:(1)...'.
    """
    NEW_Q_START_RE = re.compile(
        r"^\s*(\d{1,3}\s*[\.\u3001、）)]\s*(?!\d)|[（(]|第|如图|为减少|根据|实验|探究|求)"
    )
    TERMINAL = "。！？?！"

    def _stem(q: Question) -> str:
        return "".join(l.text for b in q.stem_blocks for l in b.lines).strip()

    for section in sections:
        if len(section.questions) < 2:
            continue
        merged: list[Question] = [section.questions[0]]
        for q in section.questions[1:]:
            prev = merged[-1]
            prev_text = _stem(prev)
            cur_text = _stem(q)
            prev_ends_term = bool(prev_text) and prev_text[-1] in TERMINAL
            cur_starts_new = bool(NEW_Q_START_RE.match(cur_text[:15]))
            if (not prev_ends_term) and (not cur_starts_new) and len(cur_text) < 160:
                prev.stem_blocks.extend(q.stem_blocks)
                prev.has_diagram = prev.has_diagram or q.has_diagram
                continue
            merged.append(q)
        section.questions = merged


def merge_untitled_sections(pages: list[PageLayout]) -> None:
    """Merge consecutive sections that have no title into the previous section.

    The reading-order / zone parser sometimes fails to detect a section title
    (e.g. the choice section header lands in the header zone), producing
    several untitled fragments. Merge them so the document reads cleanly.
    """
    for page in pages:
        merged: list[Section] = []
        for sec in page.sections:
            if not sec.title and merged:
                merged[-1].questions.extend(sec.questions)
            else:
                merged.append(sec)
        page.sections = merged


def remove_bad_questions(sections: list[Section]) -> list[Section]:
    """Remove false-positive, empty, or very low-quality questions.

    Quality thresholds:
    - Choice questions: must have a stem with >= 10 chars OR at least 2 proper options
    - Other questions: must have a stem with >= 15 chars
    - Always drop: pure noise, markers, single-char content
    """
    cleaned_sections = []
    for section in sections:
        good_qs = []
        for q in section.questions:
            stem_text = ""
            if q.stem_blocks:
                for b in q.stem_blocks:
                    for l in b.lines:
                        stem_text += l.text
            stem_text = stem_text.strip()

            # Basic content checks
            has_stem = len(stem_text) >= 4
            has_opts = len(q.option_blocks) > 0
            has_subs = len(q.sub_questions) > 0

            if not (has_stem or has_opts or has_subs):
                continue

            # Drop clearly corrupted stems (bad OCR / diagram leakage)
            if _is_garbage_stem(stem_text):
                continue

            # Drop pure noise stems (single numbers/units)
            if not has_opts and not has_subs and re.match(r"^\d{1,2}[NnSs\.\、\)]?$", stem_text):
                continue

            # Drop "第X题" markers
            if re.match(r"^第\d+\s*题$", stem_text) and not has_opts:
                continue

            # Drop questions with garbage stems (contain noise patterns)
            noise_patterns = ["000SN", "000", "[NnKkGg]$", "电型"]
            is_garbage = False
            for np_ in noise_patterns:
                if re.search(np_, stem_text):
                    is_garbage = True
                    break
            if is_garbage and len(stem_text) < 20:
                continue

            # For choice questions: need either meaningful stem OR multiple options
            if q.question_type == QuestionType.CHOICE:
                proper_opts = [o for o in q.option_blocks
                               if o.lines and len(o.lines[0].text) > 5]
                if len(stem_text) < 10 and len(proper_opts) < 2:
                    continue  # Not enough content for a real choice question
                # Drop choice questions with NO stem at all (question text lost)
                if len(stem_text) == 0:
                    continue

            # For non-choice: need substantial stem content
            if q.question_type != QuestionType.CHOICE:
                if len(stem_text) < 15 and not has_subs:
                    continue

            good_qs.append(q)

        if good_qs or section.title:
            section.questions = good_qs
            cleaned_sections.append(section)

    return cleaned_sections


def merge_split_questions(sections: list[Section]) -> list[Section]:
    """Merge consecutive short fragments that are likely parts of one split question.

    When OCR or parsing splits a multi-part question into several fragments,
    each fragment has a short stem (< 40 chars) and no options.
    Merge consecutive such fragments within the same section.
    """
    # Pattern for text that looks like a continuation (not a new question start)
    CONTINUATION_RE = re.compile(
        r"^("
        r"\d{1,3}\.|"
        r"[（(]\d{1,2}[）)]|"
        r"求|计算|解|答|证明|说明|解释|分析|比较|判断|选择|填"
        r")"
    )

    for section in sections:
        if len(section.questions) < 2:
            continue

        merged = []
        i = 0
        while i < len(section.questions):
            q = section.questions[i]

            # Check if this looks like a fragment (short stem, no opts/subs)
            stem_text = "".join(l.text for b in q.stem_blocks for l in b.lines).strip()
            is_fragment = (
                len(q.option_blocks) == 0
                and len(q.sub_questions) == 0
                and 1 <= len(stem_text) < 150
                and not CONTINUATION_RE.match(stem_text)  # Not starting with (1), 求, etc.
                and not re.match(r"^\d{1,2}\s*[\.\u3001、\)\（]", stem_text[:10])  # No question number prefix
            )

            if is_fragment and merged:
                prev = merged[-1]
                # Always merge fragments with previous question
                prev.stem_blocks.extend(q.stem_blocks)
                prev.has_diagram = prev.has_diagram or q.has_diagram
                i += 1
                continue

            merged.append(q)
            i += 1

        section.questions = merged

    return sections


# ── Main pipeline ──────────────────────────────────────────────

def run_reconstruction() -> tuple[ExamDocument, Path]:
    """Run the full V1 reconstruction pipeline."""
    print("=" * 60)
    print("语义重建 V1.0: 八年级物理期末试卷")
    print("=" * 60)

    # Load all OCR data
    ocr_data: dict[str, list[dict]] = {}
    for hp in HALF_PAGES:
        cache_file = BASE_DIR / "evaluation" / f"ocr_lines_{hp['name']}.json"
        lines = load_or_fetch_ocr(cache_file, hp["image"])
        ocr_data[hp["name"]] = lines

    doc = ExamDocument(title="2024-2025 年度第二学期八年级物理期末检测题（重建版）")

    # Reconstruct each half-page
    half_page_results: list[PageLayout] = []
    print("\n--- 半页解析 ---")
    for hp in HALF_PAGES:
        layout = reconstruct_half_page(hp["image"], hp["name"], ocr_data[hp["name"]])
        half_page_results.append(layout)

    # Group into logical pages
    print("\n--- 合并逻辑页 ---")
    for group in LOGICAL_PAGE_GROUPS:
        logical_page = PageLayout(
            page_number=group["page_num"],
            page_width=half_page_results[group["halves"][0]].page_width,
            page_height=half_page_results[group["halves"][0]].page_height,
        )

        for hi in group["halves"]:
            hp_layout = half_page_results[hi]
            logical_page.header_blocks.extend(hp_layout.header_blocks)
            logical_page.sections.extend(hp_layout.sections)
            logical_page.footer_blocks.extend(hp_layout.footer_blocks)

        doc.pages.append(logical_page)
        total_secs = len(logical_page.sections)
        total_qs = sum(len(s.questions) for s in logical_page.sections)
        print(f"  逻辑第 {group['page_num']} 页: {total_secs} 节, {total_qs} 题 (原始)")

    # Post-processing
    print("\n--- 后处理 ---")
    for page in doc.pages:
        page.sections = remove_bad_questions(page.sections)
        page.sections = merge_split_questions(page.sections)
        merge_leading_fragment(page.sections)
        merge_continuation_fragments(page.sections)
        for section in page.sections:
            clean_option_assignment(section)

    # Merge untitled consecutive sections (e.g. choice header missed)
    merge_untitled_sections(doc.pages)

    # Re-run continuation merge across the now-merged sections
    # (a question may have been split across the two half-page sections)
    for page in doc.pages:
        merge_continuation_fragments(page.sections)

    # Assign global question numbers
    assign_global_numbers(doc.pages)

    # Print summary
    print("\n" + "=" * 60)
    print("重建结构摘要")
    print("=" * 60)
    total_q = 0
    for page in doc.pages:
        print(f"\n逻辑第 {page.page_number} 页:")
        print(f"  Sections: {len(page.sections)}")
        for section in page.sections:
            title_preview = section.title[:45] if section.title else "(无标题)"
            print(f"    节: {title_preview}")
            print(f"      题目数: {len(section.questions)}")
            for q in section.questions:
                total_q += 1
                stem_preview = ""
                if q.stem_blocks and q.stem_blocks[0].lines:
                    stem_preview = q.stem_blocks[0].lines[0].text[:55]
                opts_count = len(q.option_blocks)
                print(f"      Q{q.number}: [{q.question_type.value}] "
                      f"选项={opts_count} | {stem_preview}")

    print(f"\n总计: {total_q} 题")

    # Generate PDF
    print("\n生成 PDF...")
    pdf_path = OUT_DIR / "physics_exam_reconstructed_v1.pdf"
    generate_exam_pdf(doc, pdf_path)
    print(f"PDF: {pdf_path} ({pdf_path.stat().st_size:,} bytes)")

    # Generate Markdown (primary, human-reviewable output)
    print("\n生成 Markdown...")
    md_path = OUT_DIR / "physics_exam_reconstructed_v1.md"
    generate_exam_markdown_file(doc, md_path)
    md_size = md_path.stat().st_size
    print(f"MD: {md_path} ({md_size:,} bytes)")

    return doc, md_path


if __name__ == "__main__":
    run_reconstruction()
