"""Markdown generator: render the reconstructed exam document to clean Markdown.

This is a pragmatic, human-reviewable alternative to the PDF generator.
The Markdown output:
- Reads cleanly and is easy to eyeball / hand-edit
- Preserves the full semantic structure (title, sections, questions, options)
- Marks missing/low-confidence content so a teacher knows what to patch
- Uses real global question numbers
"""

from __future__ import annotations

import re
from pathlib import Path

from models import (
    BlockRole,
    ExamDocument,
    Question,
    QuestionType,
    Section,
    TextBlock,
)

# ── Text helpers ──────────────────────────────────────────────

def _block_text(block: TextBlock) -> str:
    return "".join(l.text for l in block.lines)


def _strip_leading_number(text: str) -> str:
    """Remove a leading question number like '1.' / '3、' / '12）' from stem."""
    return re.sub(r"^\s*\d{1,3}\s*[\.\u3001、）)]\s*", "", text).strip()


def _clean_stem_garbage(stem: str) -> str:
    """Remove residual OCR noise inside stems (e.g. '（mx=mg<mc.h=h>hg）')."""
    # Drop parenthetical junk that contains angle brackets or 'mx='
    stem = re.sub(r"[（(][^（）()]*[<>][^（）()]*[)）]", "", stem)
    stem = re.sub(r"[（(][^（）()]*mx=[^（）()]*[)）]", "", stem)
    # Collapse multiple spaces left behind
    stem = re.sub(r"\s{2,}", " ", stem).strip()
    return stem


def _stem_text(q: Question) -> str:
    """Concatenate stem blocks (excluding options and sub-question markers)."""
    parts: list[str] = []
    for block in q.stem_blocks:
        if block.role == BlockRole.OPTION:
            break  # options come after the stem
        if block.role == BlockRole.SUB_QUESTION:
            continue
        parts.append(_block_text(block))
    return _clean_stem_garbage(_strip_leading_number("".join(parts)).strip())


def _collect_options(q: Question) -> list[str]:
    """Re-assemble per-option text, handling continuation lines.

    option_blocks is a flat list where each option may span several blocks
    (the option-start block plus any continuation blocks). We re-group by
    the option-start regex so each option becomes one clean string.
    """
    groups: list[list[str]] = []
    cur: list[str] | None = None
    for block in q.option_blocks:
        text = _block_text(block).strip()
        if not text:
            continue
        # A new option begins when its block starts with an A-H prefix
        if re.match(r"^[A-H][\.\u3001、）)]", text):
            if cur is not None:
                groups.append(cur)
            cur = [text]
        else:
            if cur is None:
                cur = [text]
            else:
                cur.append(text)
    if cur is not None:
        groups.append(cur)

    opts: list[str] = []
    for g in groups:
        s = "".join(g).strip()
        # Drop single stray letters / tiny noise
        if len(s) < 4 or re.match(r"^[A-H]$", s):
            continue
        opts.append(s)

    # De-duplicate by prefix
    seen: set[str] = set()
    result: list[str] = []
    for o in opts:
        key = o[:25]
        if key not in seen:
            seen.add(key)
            result.append(o)
    return result


def _sub_text(sub) -> str:
    return "".join(_block_text(b) for b in sub.stem_blocks).strip()


# ── Per-question renderers ────────────────────────────────────

def _render_choice(q: Question, num: str) -> str:
    out: list[str] = []
    stem = _stem_text(q)
    if not stem:
        stem = "［题干内容缺失（OCR 未识别）］"
    out.append(f"**{num}.** {stem}")
    opts = _collect_options(q)
    if opts:
        # Pair short options two-per-line for a paper-like look
        avg_len = sum(len(o) for o in opts) / max(len(opts), 1)
        if avg_len < 22 and len(opts) % 2 == 0:
            for i in range(0, len(opts), 2):
                left = opts[i]
                right = opts[i + 1] if i + 1 < len(opts) else ""
                out.append(f"{left}　　{right}".rstrip())
        else:
            for o in opts:
                out.append(o)
    else:
        out.append("　　*（选项缺失）*")
    out.append("")
    return "\n".join(out)


def _render_fill_blank(q: Question, num: str) -> str:
    out: list[str] = []
    stem = _stem_text(q)
    if not stem:
        stem = "［题干内容缺失（OCR 未识别）］"
    out.append(f"**{num}.** {stem}")
    out.append("")
    return "\n".join(out)


def _render_calculation(q: Question, num: str) -> str:
    out: list[str] = []
    stem = _stem_text(q)
    if not stem:
        stem = "［题干内容缺失（OCR 未识别）］"
    out.append(f"**{num}.** {stem}")
    for sub in q.sub_questions:
        st = _sub_text(sub)
        if st:
            out.append(f"　　{st}")
    out.append("")
    out.append("> **解答区：**")
    out.append(">")
    out.append(">")
    out.append("")
    return "\n".join(out)


def _render_drawing(q: Question, num: str) -> str:
    out: list[str] = []
    stem = _stem_text(q)
    if not stem:
        stem = "［题干内容缺失（OCR 未识别）］"
    out.append(f"**{num}.** {stem}")
    for sub in q.sub_questions:
        st = _sub_text(sub)
        if st:
            out.append(f"　　{st}")
    out.append("")
    out.append("> **作图区：**")
    out.append(">")
    out.append(">")
    out.append("")
    return "\n".join(out)


def _render_experiment(q: Question, num: str) -> str:
    out: list[str] = []
    stem = _stem_text(q)
    if not stem:
        stem = "［题干内容缺失（OCR 未识别）］"
    out.append(f"**{num}.** {stem}")
    if q.sub_questions:
        for sub in q.sub_questions:
            st = _sub_text(sub)
            if st:
                out.append(f"　　{st}")
    out.append("")
    return "\n".join(out)


def _render_generic(q: Question, num: str) -> str:
    out: list[str] = []
    stem = _stem_text(q)
    if not stem:
        stem = "［题干内容缺失（OCR 未识别）］"
    out.append(f"**{num}.** {stem}")
    for sub in q.sub_questions:
        st = _sub_text(sub)
        if st:
            out.append(f"　　{st}")
    out.append("")
    return "\n".join(out)


def _render_question(q: Question, num: str) -> str:
    t = q.question_type
    if t == QuestionType.CHOICE:
        return _render_choice(q, num)
    if t == QuestionType.FILL_BLANK:
        return _render_fill_blank(q, num)
    if t == QuestionType.CALCULATION:
        return _render_calculation(q, num)
    if t == QuestionType.DRAWING:
        return _render_drawing(q, num)
    if t == QuestionType.EXPERIMENT:
        return _render_experiment(q, num)
    return _render_generic(q, num)


# ── Section / document renderers ──────────────────────────────

def _default_section_title(section: Section) -> str:
    """Infer a section title when OCR failed to detect one."""
    types = [q.question_type for q in section.questions]
    if not types:
        return "（未识别题型）"
    if all(t == QuestionType.CHOICE for t in types):
        return "一、选择题"
    if all(t == QuestionType.FILL_BLANK for t in types):
        return "二、填空题"
    if all(t == QuestionType.DRAWING for t in types):
        return "三、作图题"
    if all(t == QuestionType.EXPERIMENT for t in types):
        return "实验题"
    if all(t == QuestionType.CALCULATION for t in types):
        return "计算题"
    # Mixed (typically 作图 + 实验 + 计算 lumped on later pages)
    if QuestionType.CHOICE in types:
        return "一、选择题"
    if QuestionType.FILL_BLANK in types:
        return "二、填空题"
    if {QuestionType.DRAWING, QuestionType.EXPERIMENT, QuestionType.CALCULATION, QuestionType.UNKNOWN} & set(types):
        return "三、作图·实验与计算题"
    return "（未识别题型）"


def _render_section(section: Section) -> str:
    lines: list[str] = []
    title = section.title.strip() if section.title else ""
    if not title:
        title = _default_section_title(section)
    lines.append(f"## {title}")
    lines.append("")
    for q in section.questions:
        num = q.number if q.number and q.number != "?" else "?"
        lines.append(_render_question(q, num))
    return "\n".join(lines)


def generate_exam_markdown(doc: ExamDocument) -> str:
    """Render the full ExamDocument to a Markdown string."""
    parts: list[str] = []

    # Title block
    title = doc.title.strip() if doc.title else "期末检测题"
    # Normalize the title: split year/semester line from subject line if present
    parts.append(f"# {title}")
    parts.append("")
    parts.append("**得分：________　　满分：100分　　考试时间：60分钟**")
    parts.append("")
    parts.append(
        "> ⚠️ 本文档由 AI 语义重建系统生成，部分内容可能因 OCR 质量而缺失或错误，"
        "需教师人工复核后再用于考试。"
    )
    parts.append("")

    for page in doc.pages:
        parts.append("---")
        parts.append("")
        parts.append(f"<!-- 逻辑第 {page.page_number} 页 -->")
        parts.append("")
        for section in page.sections:
            parts.append(_render_section(section))
            parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def generate_exam_markdown_file(doc: ExamDocument, output_path: str | Path) -> Path:
    output_path = Path(output_path)
    text = generate_exam_markdown(doc)
    output_path.write_text(text, encoding="utf-8")
    return output_path
