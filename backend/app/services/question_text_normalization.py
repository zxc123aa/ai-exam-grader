from __future__ import annotations

import re


NORMALIZATION_VERSION = "question_text_normalization_v1"
_SECTION_HEADING_RE = re.compile(
    r"^[一二三四五六七八九十]+[、.．]\s*.*(?:题|选择|填空|作图|实验|综合应用|计算).*"
)
_FIGURE_TOKEN = r"图[甲乙丙丁戊己庚辛壬癸A-Za-z0-9]+"
_STANDALONE_FIGURE_LABEL_RE = re.compile(
    rf"^(?:第?\s*\d+\s*题\s*)?(?:{_FIGURE_TOKEN})(?:\s*[、,，/]\s*{_FIGURE_TOKEN}|\s+{_FIGURE_TOKEN})*$"
)


def _canonical_question_key(question_key: str | None) -> str:
    key = str(question_key or "").strip()
    if key.isdigit():
        return key
    match = re.search(r"\d{1,3}", key)
    return match.group(0) if match else key


def _strip_question_prefix(text: str, question_key: str | None) -> str:
    key = _canonical_question_key(question_key)
    if key:
        escaped = re.escape(key)
        return re.sub(
            rf"^\s*(?:第\s*)?{escaped}\s*(?:题|[.．、:：])\s*",
            "",
            text,
            count=1,
        )
    return re.sub(r"^\s*\d{1,3}\s*[.．、:：]\s*", "", text, count=1)


def _record_change(
    changes: list[dict[str, str]],
    *,
    rule: str,
    before: str,
    after: str = "",
) -> None:
    if before == after:
        return
    changes.append(
        {
            "rule": rule,
            "before": before[:500],
            "after": after[:500],
        }
    )


def normalize_recognized_question_text_with_audit(
    text: str | None, *, question_key: str | None = None
) -> dict:
    """Clean model OCR formatting noise without changing question semantics.

    This is intentionally conservative: it removes duplicated question numbers,
    section-heading lines, standalone figure labels, Markdown/LaTeX wrappers,
    and normalizes blank lines. It must not rewrite physics wording or infer
    missing content.
    """
    original = str(text or "")
    changes: list[dict[str, str]] = []
    value = original.replace("\u3000", " ").strip()
    _record_change(
        changes,
        rule="trim_and_normalize_full_width_spaces",
        before=original,
        after=value,
    )
    if not value:
        return {
            "version": NORMALIZATION_VERSION,
            "text": "",
            "changed": bool(changes),
            "changes": changes,
            "riskLevel": "low",
        }

    before = value
    value = re.sub(r"\$([^$]+)\$", r"\1", value)
    _record_change(changes, rule="unwrap_markdown_math", before=before, after=value)

    before = value
    value = re.sub(r"([A-Za-z])_\{?(\d+)\}?", r"\1\2", value)
    _record_change(changes, rule="normalize_simple_latex_subscript", before=before, after=value)

    before = value
    value = re.sub(r"_{2,}", "____", value)
    _record_change(changes, rule="normalize_blank_underscores", before=before, after=value)

    lines: list[str] = []
    removed_section_lines: list[str] = []
    removed_figure_lines: list[str] = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _SECTION_HEADING_RE.match(line):
            removed_section_lines.append(line)
            continue
        if _STANDALONE_FIGURE_LABEL_RE.match(line):
            removed_figure_lines.append(line)
            continue
        lines.append(line)
    for line in removed_section_lines:
        _record_change(
            changes,
            rule="remove_section_heading_line",
            before=line,
            after="",
        )
    for line in removed_figure_lines:
        _record_change(
            changes,
            rule="remove_standalone_figure_label_line",
            before=line,
            after="",
        )

    if not lines:
        return {
            "version": NORMALIZATION_VERSION,
            "text": "",
            "changed": value.strip() != original.strip(),
            "changes": changes,
            "riskLevel": "medium" if changes else "low",
        }

    before = lines[0]
    lines[0] = _strip_question_prefix(lines[0], question_key).strip()
    _record_change(
        changes,
        rule="remove_duplicate_question_number_prefix",
        before=before,
        after=lines[0],
    )
    lines = [line for line in lines if line]
    value = "\n".join(lines)
    before = value
    value = re.sub(
        r"(?<=[A-Za-z0-9])\s*([=<>+\-×*/])\s*(?=[A-Za-z0-9])",
        r"\1",
        value,
    )
    _record_change(changes, rule="normalize_formula_operator_spacing", before=before, after=value)
    before = value
    value = re.sub(r"\s+", " ", value)
    _record_change(changes, rule="collapse_whitespace", before=before, after=value)
    normalized = value.strip()
    changed = normalized != original.strip()
    risky_rules = {
        "remove_section_heading_line",
        "remove_standalone_figure_label_line",
    }
    return {
        "version": NORMALIZATION_VERSION,
        "text": normalized,
        "changed": changed,
        "changes": changes,
        "riskLevel": (
            "medium"
            if any(change["rule"] in risky_rules for change in changes)
            else "low"
        ),
    }


def normalize_recognized_question_text(
    text: str | None, *, question_key: str | None = None
) -> str:
    return str(
        normalize_recognized_question_text_with_audit(
            text,
            question_key=question_key,
        )["text"]
    )


def normalize_reference_result_question(result: dict) -> dict:
    """Return a copy of a reference-algorithm result with normalized question."""
    raw_question = str(result.get("question") or "")
    audit = normalize_recognized_question_text_with_audit(
        raw_question,
        question_key=str(result.get("questionNumber") or "").strip() or None,
    )
    normalized = str(audit["text"])
    if normalized == raw_question.strip():
        return result
    updated = {
        **result,
        "question": normalized,
        "questionNormalized": True,
        "questionNormalization": {
            key: value
            for key, value in audit.items()
            if key not in {"text"}
        },
    }
    if raw_question.strip():
        updated.setdefault("rawQuestion", raw_question)
    return updated
