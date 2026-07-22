"""Layout parser: parse OCR text lines into semantic exam structure.

Two-pass approach:
1. Content-driven splitting: detect section and question boundaries by regex
2. Spatial merging: within each question, merge nearby lines into text blocks

This handles both well-separated and densely-packed pages.
"""

from __future__ import annotations

import re

from models import (
    BlockRole,
    PageLayout,
    Question,
    QuestionType,
    Section,
    SubQuestion,
    TextBlock,
    TextLine,
)

# ── Regex patterns ─────────────────────────────────────────────
_SECTION_PREFIX = r"[一二三四五六七八九十]{1,3}\s*[、,]\s*"
_SECTION_TYPES = r"(选择|填空|作图|实验探究|计算|应用|简答|综合)"
SECTION_RE = re.compile(_SECTION_PREFIX + _SECTION_TYPES)

# Loose section: just the prefix (二、) followed by at least one Chinese char
SECTION_LOOSE_RE = re.compile(r"^\s*[一二三四五六七八九十]{1,3}\s*[、,]\s*\S")

QUESTION_START_RE = re.compile(
    r"^\s*(?:"
    r"第\s*\d{1,2}\s*题|"
    r"\d{1,2}\s*[\.\u3001、\)\）](?=\s*\S)|"
    r"[一二三四五六七八九十]{1,3}\s*[\.\u3001、]"
    r")"
)

OPTION_RE = re.compile(r"^\s*[A-H]\s*[\.\u3001、\)\）]")
SUB_QUESTION_RE = re.compile(r"^\s*[\(\（]\s*\d{1,2}\s*[\)\）]")
FOOTER_RE = re.compile(r"(?:八年级|九年级|高一|高二|高三)?\s*物理.*第\d+\s*页")
HEADER_FIELD_RE = re.compile(r"(满分|考试时间|姓名|班级|学号|得分)\s*[：:]")
YEAR_SEMESTER_RE = re.compile(r"\d{4}[-~]\d{4}\s*年度|年度第[一二]\s*学期")

CHOICE_KW = re.compile(r"(选择|单选|多选)")
FILL_BLANK_KW = re.compile(r"(填空)")
DRAWING_KW = re.compile(r"(作图|画出|绘制)")
EXPERIMENT_KW = re.compile(r"(实验|探究)")
CALCULATION_KW = re.compile(r"(计算|求解|求[：:])")

# Noise patterns to filter out
NOISE_RE = re.compile(r"^[NnKkGgCcMm]$")  # Units without context


# ── Public API ─────────────────────────────────────────────────

def parse_page_structure(
    lines: list[TextLine],
    page_number: int,
    page_width: float,
    page_height: float,
) -> PageLayout:
    if not lines:
        return PageLayout(page_number=page_number, page_width=page_width, page_height=page_height)

    # 1. Filter contamination and noise
    clean = _filter_contamination_and_noise(lines, page_width)

    layout = PageLayout(
        page_number=page_number,
        page_width=page_width,
        page_height=page_height,
        raw_lines=clean,
    )

    # 2. Split into header / body / footer at the line level
    header_lines, body_lines, footer_lines = _split_zones(clean, page_height)
    layout.header_blocks = _lines_to_blocks(header_lines, BlockRole.HEADER)
    layout.footer_blocks = _lines_to_blocks(footer_lines, BlockRole.PAGE_FOOTER)

    # 3. Parse sections from body lines (content-driven split)
    layout.sections = _parse_body(body_lines, page_width)

    return layout


# ── Filtering ──────────────────────────────────────────────────

def _filter_contamination_and_noise(
    lines: list[TextLine], page_width: float
) -> list[TextLine]:
    """Remove contamination from adjacent pages and pure noise lines."""
    cutoff = page_width * 0.88
    result = []
    for l in lines:
        if l.x >= cutoff:
            continue
        if NOISE_RE.match(l.text.strip()):
            continue
        if len(l.text.strip()) <= 1 and not l.text.strip().isascii():
            continue
        result.append(l)
    return result


# ── Zone splitting ─────────────────────────────────────────────

def _split_zones(
    lines: list[TextLine], page_height: float
) -> tuple[list[TextLine], list[TextLine], list[TextLine]]:
    """Split lines into header, body, and footer zones."""
    header: list[TextLine] = []
    body: list[TextLine] = []
    footer: list[TextLine] = []

    top_zone = page_height * 0.12
    bottom_zone = page_height * 0.85

    for l in lines:
        text = l.text.strip()
        if l.y < top_zone and _is_header_text(text):
            header.append(l)
        elif l.y > bottom_zone and FOOTER_RE.search(text):
            footer.append(l)
        else:
            body.append(l)

    return header, body, footer


def _is_header_text(text: str) -> bool:
    return bool(
        YEAR_SEMESTER_RE.search(text)
        or HEADER_FIELD_RE.search(text)
    )


# ── Body parsing: section → question → blocks ─────────────────

def _parse_body(
    body_lines: list[TextLine], page_width: float
) -> list[Section]:
    """Parse body lines into sections and questions."""
    if not body_lines:
        return []

    # First pass: find section boundaries (content-driven)
    section_groups = _split_into_section_groups(body_lines)

    sections: list[Section] = []
    for title, group_lines in section_groups:
        section = _parse_section_body(title, group_lines)
        sections.append(section)

    return sections


def _split_into_section_groups(
    lines: list[TextLine],
) -> list[tuple[str, list[TextLine]]]:
    """Split lines into (section_title, lines) groups."""
    if not lines:
        return []

    # Sort by y for consistent processing
    sorted_lines = sorted(lines, key=lambda l: l.y)
    groups: list[tuple[str, list[TextLine]]] = []
    current_title = ""
    current_lines: list[TextLine] = []

    for l in sorted_lines:
        text = l.text.strip()
        if SECTION_RE.search(text):
            # Save previous group
            if current_lines:
                groups.append((current_title, current_lines))
            current_title = text
            current_lines = []
        elif SECTION_LOOSE_RE.match(text) and l.x < 60 and len(text) < 20:
            # Standalone section marker like "二、"
            if current_lines:
                groups.append((current_title, current_lines))
            current_title = text
            current_lines = []
        else:
            current_lines.append(l)

    if current_lines or (current_title and not groups):
        groups.append((current_title, current_lines))

    return groups


def _parse_section_body(
    title: str, lines: list[TextLine]
) -> Section:
    """Parse a section's body lines into questions."""
    if not lines:
        return Section(title=title)

    # Split lines into question groups (content-driven)
    question_groups = _split_into_question_groups(lines)
    qtype = _detect_question_type_from_title(title)

    questions: list[Question] = []
    for q_lines in question_groups:
        q = _build_question(q_lines, qtype)
        if q:
            questions.append(q)

    # If section title implies a type but question type is unknown, refine
    for q in questions:
        if q.question_type == QuestionType.UNKNOWN and qtype != QuestionType.UNKNOWN:
            q.question_type = qtype

    return Section(title=title, questions=questions)


def _split_into_question_groups(
    lines: list[TextLine],
) -> list[list[TextLine]]:
    """Split lines into per-question groups.

    Uses question number patterns as boundaries, with fallback to
    spatial gaps for unnumbered content.
    """
    if not lines:
        return []

    groups: list[list[TextLine]] = []
    current: list[TextLine] = []

    # Track whether we've seen options in current group
    # This helps detect when options from one question bleed into the next
    opts_in_current = 0

    for l in lines:
        text = l.text.strip()
        is_q_start = QUESTION_START_RE.match(text) and _is_question_start(text, l)

        # Also treat section-like headers as boundaries
        is_section_like = bool(SECTION_RE.search(text)) or bool(
            SECTION_LOOSE_RE.match(text) and l.x < 60 and len(text) < 25
        )

        if is_q_start or is_section_like:
            if current:
                groups.append(current)
                opts_in_current = 0
            current = [l]
        else:
            # Detect potential question boundary: new option block after non-option content
            is_option = bool(OPTION_RE.match(text))
            if is_option and opts_in_current == 0 and len(current) >= 3:
                # First option after substantial stem content — this is fine, continue
                pass
            elif is_option and not is_option and opts_in_current > 2 and len(current) > 8:
                # Many options already seen, then non-option, then option again?
                # Could be next question starting without clear number
                # Only split if there's a meaningful gap
                pass  # Conservative: don't split here
            current.append(l)
            if is_option:
                opts_in_current += 1

    if current:
        groups.append(current)

    # Post-process: split groups that have too many options (likely merged questions)
    final_groups = []
    for group in groups:
        opt_count = sum(1 for l in group if OPTION_RE.match(l.text.strip()))
        if opt_count > 6:
            # Too many options — probably multiple questions merged
            splits = _split_group_by_option_clusters(group)
            final_groups.extend(splits)
        else:
            final_groups.append(group)

    # If no question boundaries found, try spatial gap splitting
    if len(final_groups) <= 1 and len(lines) > 3:
        return _split_by_major_gaps(lines)

    return final_groups


def _split_group_by_option_clusters(
    lines: list[TextLine],
) -> list[list[TextLine]]:
    """Split a group that has too many options into separate clusters."""
    result = []
    current_cluster: list[TextLine] = []
    opts_seen = 0
    in_options = False

    for l in lines:
        text = l.text.strip()
        is_opt = bool(OPTION_RE.match(text))

        if is_opt and not in_options:
            # Starting an option sequence
            if current_cluster and opts_seen >= 2:
                # Already had options before — save previous cluster
                result.append(current_cluster)
                current_cluster = [l]
                opts_seen = 1
                in_options = True
            else:
                current_cluster.append(l)
                opts_seen += 1
                in_options = True
        elif is_opt:
            current_cluster.append(l)
            opts_seen += 1
        elif in_options and not is_opt and opts_seen >= 2:
            # Non-option text after 2+ options — likely next question's stem
            if len(current_cluster) >= 3:
                result.append(current_cluster)
            current_cluster = [l]
            opts_seen = 0
            in_options = False
        else:
            current_cluster.append(l)
            if not is_opt:
                in_options = False

    if current_cluster:
        result.append(current_cluster)

    return result if result else [lines]


def _is_question_start(text: str, line: TextLine) -> bool:
    """Validate that a line matching QUESTION_START_RE is a real question start."""
    cleaned = text.strip()
    match = QUESTION_START_RE.match(cleaned)
    if not match:
        return False
    after = cleaned[match.end():].strip()
    if len(after) < 3:
        return False
    # Filter out things like "3N", "7cm"
    if re.match(r'^[NnKkGgCcMm]', after):
        return False
    # Filter "第X题" markers (these are answer-area labels, not question starts)
    if re.match(r'第\d+\s*题', cleaned):
        return False
    # Only question starts near the left margin are real
    # (right-side numbers might be page numbers or answer area labels)
    return True


def _split_by_major_gaps(
    lines: list[TextLine],
) -> list[list[TextLine]]:
    """Fallback: split lines into groups based on large vertical gaps."""
    if not lines:
        return []

    sorted_lines = sorted(lines, key=lambda l: l.y)
    heights = [l.height for l in sorted_lines if l.height > 0]
    avg_h = sum(heights) / len(heights) if heights else 30
    gap_threshold = avg_h * 4  # Large gap = significant content break

    groups: list[list[TextLine]] = []
    current: list[TextLine] = [sorted_lines[0]]

    for l in sorted_lines[1:]:
        gap = l.y - current[-1].bottom
        if gap > gap_threshold:
            groups.append(current)
            current = [l]
        else:
            current.append(l)

    if current:
        groups.append(current)

    return groups


# ── Question building ──────────────────────────────────────────

def _build_question(
    lines: list[TextLine], default_type: QuestionType
) -> Question | None:
    """Build a Question from its lines."""
    if not lines:
        return None

    # Group lines into text blocks within this question
    blocks = _lines_to_blocks(lines)
    if not blocks:
        return None

    first_text = _block_text(blocks[0])
    q_num = _extract_question_number(first_text)

    question = Question(number=q_num, question_type=default_type)

    # Split blocks into stem and options
    stem: list[TextBlock] = []
    options: list[TextBlock] = []
    in_options = False
    prev_was_option = False

    for block in blocks:
        text = _block_text(block).strip()
        is_opt_start = bool(OPTION_RE.match(text))

        if is_opt_start:
            in_options = True
            block.role = BlockRole.OPTION
            options.append(block)
            prev_was_option = True
        elif in_options and not QUESTION_START_RE.match(text):
            # Check if this is continuation of previous option or new content
            # If text is short (< 60 chars) and previous was option, it's likely option continuation
            if len(text) < 70 and prev_was_option:
                block.role = BlockRole.OPTION
                options.append(block)
            else:
                # Longer text after options — could be next question's stem
                in_options = False
                stem.append(block)
                prev_was_option = False
        else:
            in_options = False
            stem.append(block)
            prev_was_option = False

    question.stem_blocks = stem
    question.option_blocks = options
    question.sub_questions = _extract_sub_questions(stem)
    question.has_diagram = _detect_diagram(stem)

    # Refine type: if it has options, it's a choice question
    if question.question_type == QuestionType.UNKNOWN and options:
        question.question_type = QuestionType.CHOICE

    # Sanity check: if question has NO meaningful content, return None
    stem_text = "".join(_block_text(b) for b in stem).strip()
    has_opts = len(options) > 0
    has_subs = len(question.sub_questions) > 0

    if not has_opts and not has_subs and len(stem_text) < 4:
        return None

    return question


# ── Block building (spatial, within a question) ────────────────

def _lines_to_blocks(
    lines: list[TextLine], role: BlockRole = BlockRole.OTHER
) -> list[TextBlock]:
    """Merge spatially close lines into blocks."""
    if not lines:
        return []

    sorted_lines = sorted(lines, key=lambda l: l.y)
    heights = [l.height for l in sorted_lines if l.height > 0]
    avg_h = sum(heights) / len(heights) if heights else 30
    merge_gap = avg_h * 1.2  # Conservative merging

    blocks: list[TextBlock] = []
    current: list[TextLine] = [sorted_lines[0]]

    for l in sorted_lines[1:]:
        prev = current[-1]
        gap = l.y - prev.bottom
        # Check horizontal proximity too
        h_overlap = min(prev.right, l.right) - max(prev.x, l.x)
        same_line = h_overlap > -avg_h

        if gap <= merge_gap and (same_line or abs(prev.x - l.x) < avg_h * 3):
            current.append(l)
        else:
            current.sort(key=lambda line: line.x)
            block = TextBlock(lines=current, role=role)
            blocks.append(block)
            current = [l]

    if current:
        current.sort(key=lambda line: line.x)
        blocks.append(TextBlock(lines=current, role=role))

    return blocks


# ── Question type detection ────────────────────────────────────

def _detect_question_type_from_title(section_title: str) -> QuestionType:
    if CHOICE_KW.search(section_title):
        return QuestionType.CHOICE
    if FILL_BLANK_KW.search(section_title):
        return QuestionType.FILL_BLANK
    if DRAWING_KW.search(section_title):
        return QuestionType.DRAWING
    if EXPERIMENT_KW.search(section_title):
        return QuestionType.EXPERIMENT
    if CALCULATION_KW.search(section_title):
        return QuestionType.CALCULATION
    return QuestionType.UNKNOWN


def _detect_diagram(blocks: list[TextBlock]) -> bool:
    all_text = "".join(_block_text(b) for b in blocks)
    signals = ["如图", "如图所示", "图甲", "图乙", "图丙", "图丁", "示意图", "图示", "下图", "上图"]
    return any(s in all_text for s in signals)


# ── Sub-questions extraction ───────────────────────────────────

def _extract_sub_questions(blocks: list[TextBlock]) -> list[SubQuestion]:
    subs: list[SubQuestion] = []
    current: SubQuestion | None = None
    for block in blocks:
        text = _block_text(block).strip()
        if SUB_QUESTION_RE.match(text):
            if current:
                subs.append(current)
            current = SubQuestion(label=text[:4].strip())
        if current:
            current.stem_blocks.append(block)
    if current:
        subs.append(current)
    return subs


# ── Utilities ──────────────────────────────────────────────────

def _extract_question_number(text: str) -> str:
    match = QUESTION_START_RE.match(text.strip())
    if match:
        return match.group().strip().rstrip(".、)）,").strip()
    return "?"


def _block_text(block: TextBlock) -> str:
    return "".join(l.text for l in block.lines)
