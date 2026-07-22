"""PDF generator: produce a clean, re-typeset exam paper PDF.

Uses fpdf2 with Microsoft YaHei for Chinese text support.
Professional exam paper formatting:
- Clean header with title and score
- Section headers with horizontal rules
- 2-column options for short choices
- Answer blanks for fill-in-blank questions
- Calculation space with ruled lines
- Drawing areas with frame boxes
"""

from __future__ import annotations

import re
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import Align
from models import (
    BlockRole,
    ExamDocument,
    PageLayout,
    Question,
    QuestionType,
    Section,
    TextBlock,
)

# ── Font setup ───────────────────────────────────────────────
_FONT_PATH = "C:/Windows/Fonts/msyh.ttc"


def _block_text(block: TextBlock) -> str:
    return "".join(l.text for l in block.lines)


class ExamPaperPDF(FPDF):
    """Professional exam paper PDF generator."""

    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=22)
        self._register_fonts()
        self._init_colors()

    def _register_fonts(self) -> None:
        if not Path(_FONT_PATH).exists():
            raise RuntimeError(f"No Chinese font found at {_FONT_PATH}")
        self.add_font("YaHei", "", _FONT_PATH, uni=True)
        self.set_font("YaHei", "", 10)

    def _init_colors(self) -> None:
        self._black = (0, 0, 0)
        self._gray_dark = (50, 50, 50)
        self._gray = (120, 120, 120)
        self._gray_light = (200, 200, 200)
        self._section_bar = (70, 70, 90)
        self._blue_accent = (30, 60, 114)

    # ── Public API ─────────────────────────────────────────────

    def build_exam(self, doc: ExamDocument) -> None:
        self._render_title(doc)
        for page in doc.pages:
            self._render_page(page)
        # Footer: add page numbers on last page if needed
        self._render_footer()

    # ── Page layout ────────────────────────────────────────────

    def _render_title(self, doc: ExamDocument) -> None:
        self.add_page()
        self.set_y(20)

        # Top title
        self.set_font("YaHei", "", 20)
        self.set_text_color(*self._black)
        self.cell(0, 10, "2024-2025 年度第二学期", align=Align.C, new_x="LMARGIN", new_y="NEXT")

        self.set_font("YaHei", "", 24)
        self.set_text_color(*self._blue_accent)
        self.cell(0, 12, "八年级物理期末检测题", align=Align.C, new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(*self._black)

        # Score/time bar
        self.set_font("YaHei", "", 10)
        self.set_draw_color(*self._gray_light)
        self.line(20, self.get_y() + 2, 190, self.get_y() + 2)
        self.ln(4)
        self.cell(0, 6, "得分：______    满分：100分    考试时间：60分钟", align=Align.C, new_x="LMARGIN", new_y="NEXT")
        self.line(20, self.get_y(), 190, self.get_y())
        self.ln(8)

    def _render_page(self, page: PageLayout) -> None:
        for section in page.sections:
            self._render_section(section)

    def _render_section(self, section: Section) -> None:
        if section.title:
            self.ln(5)
            self.set_font("YaHei", "", 13)
            self.set_text_color(*self._black)
            self.cell(0, 8, section.title, align=Align.L, new_x="LMARGIN", new_y="NEXT")
            self.set_draw_color(*self._section_bar)
            self.line(20, self.get_y(), 20 + self.get_string_width(section.title), self.get_y())
            self.set_draw_color(0, 0, 0)
            self.ln(2)

        self.set_font("YaHei", "", 10)
        self.set_text_color(*self._black)
        for q in section.questions:
            display_num = q.number if q.number != "?" else "?"
            try:
                int(display_num)
            except ValueError:
                display_num = "?"
            self._render_question(q, display_num)

    def _render_question(self, question: Question, display_num: str | int) -> None:
        q_type = question.question_type
        if q_type == QuestionType.CHOICE:
            self._render_choice(question, display_num)
        elif q_type == QuestionType.FILL_BLANK:
            self._render_fill_blank(question, display_num)
        elif q_type == QuestionType.CALCULATION:
            self._render_calculation(question, display_num)
        elif q_type == QuestionType.DRAWING:
            self._render_drawing(question, display_num)
        elif q_type == QuestionType.EXPERIMENT:
            self._render_experiment(question, display_num)
        else:
            self._render_generic(question, display_num)

    # ── Question type renderers ────────────────────────────────

    def _render_choice(self, q: Question, display_num: str | int) -> None:
        self._write_q_stem(q, display_num)
        opts = self._collect_options(q)
        if not opts:
            self.ln(2)
            return

        # 2-column layout for short options
        self.set_font("YaHei", "", 9)
        self.set_x(26)
        for i, opt in enumerate(opts):
            if i % 2 == 0 and i > 0:
                self.ln(5)
                self.set_x(26)
            # Write option, try to fit two per line
            if i % 2 == 0 and i + 1 < len(opts):
                next_opt = opts[i + 1]
                if len(opt) + len(next_opt) < 50:
                    self._write_option_pair(opt, next_opt)
                    continue
            self._write_wrapped(opt, x=26, width=164)
        self.ln(3)

    def _render_fill_blank(self, q: Question, display_num: str | int) -> None:
        self._write_q_stem(q, display_num)
        # Draw blank answer lines
        self._draw_blank_lines(count=2, x=26, y_start=self.get_y() + 2)
        self.ln(4)

    def _render_calculation(self, q: Question, display_num: str | int) -> None:
        self._write_q_stem(q, display_num)
        # Sub-questions
        for sub in q.sub_questions:
            sub_text = "".join(_block_text(b) for b in sub.stem_blocks)
            self._write_wrapped(sub_text, x=26, width=164)
        # Calculation space
        self._draw_ruled_area(lines=8, x=26, y=self.get_y() + 4)
        self.ln(4)

    def _render_drawing(self, q: Question, display_num: str | int) -> None:
        self._write_q_stem(q, display_num)
        # Sub-questions
        for sub in q.sub_questions:
            sub_text = "".join(_block_text(b) for b in sub.stem_blocks)
            self._write_wrapped(sub_text, x=26, width=164)
        # Drawing frame
        self._draw_frame_box(x=26, width=164, height=50)
        self.ln(6)

    def _render_experiment(self, q: Question, display_num: str | int) -> None:
        self._write_q_stem(q, display_num)
        for sub in q.sub_questions:
            sub_text = "".join(_block_text(b) for b in sub.stem_blocks)
            self._write_wrapped(sub_text, x=26, width=164)
            self.ln(2)
        self.ln(4)

    def _render_generic(self, q: Question, display_num: str | int) -> None:
        self._write_q_stem(q, display_num)
        self.ln(4)

    # ── Text helpers ───────────────────────────────────────────

    def _write_q_stem(self, q: Question, display_num: str | int) -> None:
        """Write the question stem text."""
        self.set_font("YaHei", "", 10)
        self.set_text_color(*self._black)
        stem = self._get_stem_text(q)
        if not stem:
            stem = "[题干内容缺失]"
        self._write_wrapped(f"{display_num}. {stem}", x=20, width=170)
        if q.has_diagram:
            self.set_font("YaHei", "", 7)
            self.set_text_color(*self._gray)
            self._write_wrapped("[图示]", x=20, width=170)
            self.set_text_color(*self._black)

    def _write_wrapped(self, text: str, x: float = 20, width: float = 170) -> None:
        if not text:
            return
        self.set_x(x)
        self.multi_cell(width, 5.2, text, align=Align.L)

    def _write_option_pair(self, a: str, b: str) -> None:
        """Write two options on the same line."""
        w_total = 164
        half = w_total / 2
        self.set_x(26)
        self.cell(half, 5.2, a)
        self.cell(half, 5.2, b)

    # ── Option extraction ──────────────────────────────────────

    def _collect_options(self, q: Question) -> list[str]:
        opts = []
        for block in q.option_blocks:
            text = _block_text(block).strip()
            if not text:
                continue
            # Skip noise: single letters, diagram labels, very short garbage
            if len(text) < 4:
                continue
            if re.match(r"^[A-H]$", text):
                continue
            # Options should start with A-H prefix
            if not re.match(r"^[A-H][\.\u3001、\)\）]", text):
                continue
            opts.append(text)
        # Deduplicate
        seen = set()
        result = []
        for o in opts:
            key = o[:30]
            if key not in seen:
                seen.add(key)
                result.append(o)
        return result

    def _get_stem_text(self, q: Question) -> str:
        parts = []
        for block in q.stem_blocks:
            if block.role == BlockRole.OPTION:
                break
            if block.role == BlockRole.SUB_QUESTION:
                continue
            parts.append(_block_text(block))
        return "".join(parts).strip()

    # ── Drawing helpers ────────────────────────────────────────

    def _draw_blank_lines(self, count: int, x: float, y_start: float) -> None:
        self.set_draw_color(*self._gray_light)
        for i in range(count):
            y = y_start + i * 6
            self.line(x, y, x + 160, y)
            self.ln(6)
        self.set_draw_color(0, 0, 0)

    def _draw_ruled_area(self, lines: int, x: float, y: float) -> None:
        self.set_draw_color(*self._gray_light)
        for i in range(lines):
            self.line(x, y + i * 6, x + 160, y + i * 6)
        self.set_draw_color(0, 0, 0)
        self.set_y(y + lines * 6)

    def _draw_frame_box(self, x: float, width: float, height: float) -> None:
        self.set_draw_color(*self._gray_light)
        self.set_line_width(0.2)
        self.rect(x, self.get_y(), width, height, style="D")
        self.set_draw_color(0, 0, 0)
        self.set_line_width(0.3)
        self.set_y(self.get_y() + height + 2)

    def _render_footer(self) -> None:
        """Add a final reconstruction note."""
        # Temporarily disable auto page break to avoid infinite recursion
        # when set_y(-20) falls inside the auto-break margin (22mm).
        self.set_auto_page_break(auto=False)
        self.set_y(-20)
        self.set_font("YaHei", "", 7)
        self.set_text_color(*self._gray)
        self.cell(0, 6, "由 AI 语义重建系统生成 | 部分内容可能因 OCR 质量而缺失或错误，需教师人工复核", align=Align.C)
        self.set_auto_page_break(auto=True, margin=22)


# ── Entry point ───────────────────────────────────────────────

def generate_exam_pdf(doc: ExamDocument, output_path: str | Path) -> Path:
    pdf = ExamPaperPDF()
    pdf.build_exam(doc)
    pdf.output(str(output_path))
    return Path(output_path)
