"""Data models for semantic reconstruction."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class QuestionType(str, Enum):
    CHOICE = "choice"
    FILL_BLANK = "fill_blank"
    DRAWING = "drawing"
    EXPERIMENT = "experiment"
    CALCULATION = "calculation"
    UNKNOWN = "unknown"


class BlockRole(str, Enum):
    HEADER = "header"
    SECTION_TITLE = "section_title"
    QUESTION_STEM = "question_stem"
    OPTION = "option"
    SUB_QUESTION = "sub_question"
    PAGE_FOOTER = "page_footer"
    FIGURE_LABEL = "figure_label"
    DIAGRAM_MARKER = "diagram_marker"
    OTHER = "other"


@dataclass
class TextLine:
    """A single OCR-detected text line with bounding box."""
    text: str
    x: float       # pixel coordinate (left)
    y: float       # pixel coordinate (top)
    width: float   # pixel
    height: float  # pixel
    confidence: float | None = None

    @property
    def cx(self) -> float:
        """Center x."""
        return self.x + self.width / 2

    @property
    def cy(self) -> float:
        """Center y."""
        return self.y + self.height / 2

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def right(self) -> float:
        return self.x + self.width

    def to_normalized(self, page_width: float, page_height: float) -> TextLine:
        return TextLine(
            text=self.text,
            x=self.x / page_width,
            y=self.y / page_height,
            width=self.width / page_width,
            height=self.height / page_height,
            confidence=self.confidence,
        )


@dataclass
class TextBlock:
    """A group of text lines forming a logical unit."""
    lines: list[TextLine]
    role: BlockRole = BlockRole.OTHER
    extra: dict = field(default_factory=dict)


@dataclass
class Question:
    """A single question with its structure."""
    number: str
    stem_blocks: list[TextBlock] = field(default_factory=list)
    option_blocks: list[TextBlock] = field(default_factory=list)
    sub_questions: list[SubQuestion] = field(default_factory=list)
    question_type: QuestionType = QuestionType.UNKNOWN
    max_score: float | None = None
    has_diagram: bool = False


@dataclass
class SubQuestion:
    """A sub-question within a parent question."""
    label: str          # e.g. "(1)", "(2)"
    stem_blocks: list[TextBlock] = field(default_factory=list)
    answer_lines_count: int = 0


@dataclass
class Section:
    """A section of the exam (e.g. 一、选择题)."""
    title: str
    questions: list[Question] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


@dataclass
class PageLayout:
    """The full semantic structure of one exam page."""
    page_number: int
    page_width: float
    page_height: float
    header_blocks: list[TextBlock] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    footer_blocks: list[TextBlock] = field(default_factory=list)
    raw_lines: list[TextLine] = field(default_factory=list)


@dataclass
class ExamDocument:
    """The full reconstructed exam document."""
    title: str = ""
    pages: list[PageLayout] = field(default_factory=list)
