"""Reading-order correction: sort OCR lines into natural reading order.

PaddleOCR returns lines in detection order, which does NOT match
human reading order for multi-column exam papers.

Strategy:
1. Filter contamination from adjacent pages
2. Detect column layout (single vs dual column)
3. For single column: simple y→x sort
4. For dual column: separate into columns, sort each by y, interleave
"""

from __future__ import annotations

from models import TextLine


def sort_lines_by_reading_order(
    lines: list[TextLine],
    page_width: float | None = None,
) -> list[TextLine]:
    """Sort lines into natural top-to-bottom, left-to-right reading order."""
    if not lines:
        return []

    if page_width is None:
        page_width = max(line.right for line in lines)

    # Detect columns
    columns = _detect_columns(lines, page_width)

    if len(columns) == 1:
        # Single column: simple y-then-x sort
        return sorted(lines, key=lambda l: (round(l.y / _y_tolerance(lines)), l.x))

    # Multi-column: sort within each column, then interleave by y-band
    return _interleave_by_columns(lines, columns)


def _y_tolerance(lines: list[TextLine]) -> float:
    """Estimate the y-tolerance for considering lines on the same row."""
    heights = [l.height for l in lines if l.height > 0]
    return sum(heights) / len(heights) if heights else 30


def _detect_columns(
    lines: list[TextLine], page_width: float
) -> list[tuple[float, float]]:
    """Detect column boundaries based on x-center distribution.

    Returns list of (x_min, x_max) for each detected column.
    """
    if len(lines) < 6:
        return [(0, page_width)]

    mid = page_width / 2
    left_lines = [l for l in lines if l.cx < mid]
    right_lines = [l for l in lines if l.cx >= mid]

    # Need enough lines on each side to consider it a real column
    threshold = max(3, len(lines) * 0.08)

    if len(left_lines) < threshold or len(right_lines) < threshold:
        return [(0, page_width)]

    # Check there's a clear gap between columns
    if left_lines and right_lines:
        left_max = max(l.cx for l in left_lines)
        right_min = min(l.cx for l in right_lines)
        gap = right_min - left_max
        if gap > page_width * 0.06:
            # Significant gap found
            divider = (left_max + right_min) / 2
            margin = page_width * 0.03
            return [
                (0, divider - margin),
                (divider + margin, page_width),
            ]

    return [(0, page_width)]


def _interleave_by_columns(
    lines: list[TextLine],
    columns: list[tuple[float, float]],
) -> list[TextLine]:
    """Sort lines within each column, then interleave columns by row.

    All lines in the same y-band (row) from different columns are
    ordered left-to-right within that band.
    """
    # Assign lines to columns
    col_lines: dict[int, list[TextLine]] = {i: [] for i in range(len(columns))}
    for line in lines:
        for i, (cmin, cmax) in enumerate(columns):
            if cmin <= line.cx <= cmax:
                col_lines[i].append(line)
                break
        else:
            # Assign to nearest column
            best = min(
                range(len(columns)),
                key=lambda i: abs(line.cx - (columns[i][0] + columns[i][1]) / 2),
            )
            col_lines[best].append(line)

    # Sort within each column
    for i in col_lines:
        col_lines[i].sort(key=lambda l: l.y)

    # Interleave: process one row at a time across columns
    result: list[TextLine] = []
    pointers = dict.fromkeys(col_lines, 0)
    y_tol = _y_tolerance(lines) * 1.8

    while True:
        # Find the smallest y among all columns' current lines
        candidates: list[tuple[int, TextLine]] = []
        for i in col_lines:
            if pointers[i] < len(col_lines[i]):
                line = col_lines[i][pointers[i]]
                candidates.append((i, line))

        if not candidates:
            break

        # Take all lines in the same y-band across columns
        min_y = min(l.y for _, l in candidates)
        band: list[TextLine] = []

        for i in list(col_lines.keys()):
            while pointers[i] < len(col_lines[i]):
                line = col_lines[i][pointers[i]]
                if line.y <= min_y + y_tol:
                    band.append(line)
                    pointers[i] += 1
                else:
                    break

        # Sort band left-to-right
        band.sort(key=lambda l: l.x)
        result.extend(band)

    return result


# ── Row-based helpers (used by layout_parser) ──────────────────

def group_lines_into_rows(
    lines: list[TextLine],
    y_tolerance: float | None = None,
) -> list[list[TextLine]]:
    """Group sorted lines into rows by y-proximity."""
    if not lines:
        return []

    if y_tolerance is None:
        y_tolerance = _y_tolerance(lines) * 1.5

    sorted_lines = sorted(lines, key=lambda l: l.y)
    rows: list[list[TextLine]] = []
    current_row = [sorted_lines[0]]
    current_bottom = sorted_lines[0].bottom

    for line in sorted_lines[1:]:
        if line.y - current_bottom > y_tolerance:
            current_row.sort(key=lambda l: l.x)
            rows.append(current_row)
            current_row = [line]
            current_bottom = line.bottom
        else:
            current_row.append(line)
            current_bottom = max(current_bottom, line.bottom)

    if current_row:
        current_row.sort(key=lambda l: l.x)
        rows.append(current_row)

    return rows
