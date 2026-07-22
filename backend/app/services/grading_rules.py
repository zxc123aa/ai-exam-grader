from __future__ import annotations

import math
import re
from dataclasses import dataclass

from app.models import QuestionType, StandardAnswer

OBJECTIVE_TYPES = {
    QuestionType.SINGLE_CHOICE.value,
    QuestionType.MULTIPLE_CHOICE.value,
    QuestionType.TRUE_FALSE.value,
    QuestionType.FILL_BLANK.value,
}


@dataclass(frozen=True)
class RuleGrade:
    score: float
    confidence: float
    comment: str
    evidence: list[dict]


def is_objective(answer: StandardAnswer) -> bool:
    question_type = answer.question_type or ""
    if question_type == QuestionType.FILL_BLANK.value:
        return len(answer.scoring_points) == 1
    return question_type in OBJECTIVE_TYPES


def validate_rubric(answer: StandardAnswer) -> list[str]:
    errors: list[str] = []
    points = answer.scoring_points
    if not answer.question_text:
        errors.append("缺少完整题干")
    if not answer.question_type:
        errors.append("缺少题型")
    if not points:
        errors.append("缺少评分点")
    ids = [str(item.get("id", "")).strip() for item in points]
    if len(ids) != len(set(ids)):
        errors.append("评分点 ID 重复")
    point_total = sum(float(item.get("points", 0)) for item in points)
    if not math.isclose(point_total, answer.max_score, abs_tol=0.001):
        errors.append(f"评分点合计 {point_total:g} 与满分 {answer.max_score:g} 不一致")
    report = answer.validation_report or {}
    if report.get("valid") is not True:
        errors.append("AI 独立校验未通过")
    return errors


def _choice_set(text: str) -> set[str]:
    return set(re.findall(r"(?<![A-Z])[A-H](?![A-Z])", text.upper()))


def _truth_value(text: str) -> bool | None:
    value = text.strip().lower()
    if any(token in value for token in ("正确", "对", "true", "√")):
        return True
    if any(token in value for token in ("错误", "错", "false", "×", "x")):
        return False
    return None


def _numbers(text: str) -> list[float]:
    return [float(item) for item in re.findall(r"[-+]?\d+(?:\.\d+)?", text)]


def grade_objective(
    *, student_answer: str, answer: StandardAnswer, extraction_confidence: float
) -> RuleGrade:
    question_type = answer.question_type
    rubric = answer.rubric_config or {}
    accepted = [answer.answer_text, *rubric.get("accepted_answers", [])]
    matched = False
    reason = "学生答案与标准答案不一致"
    if question_type in {
        QuestionType.SINGLE_CHOICE.value,
        QuestionType.MULTIPLE_CHOICE.value,
    }:
        student_choices = _choice_set(student_answer)
        matched = any(student_choices == _choice_set(str(item)) for item in accepted)
        reason = f"学生选择 {sorted(student_choices)}，标准选择 {sorted(_choice_set(answer.answer_text))}"
    elif question_type == QuestionType.TRUE_FALSE.value:
        student_value = _truth_value(student_answer)
        matched = any(
            student_value is not None and student_value == _truth_value(str(item))
            for item in accepted
        )
        reason = f"学生判断为 {student_value}"
    else:
        tolerance = rubric.get("tolerance", {})
        absolute = float(tolerance.get("absolute", 0))
        relative = float(tolerance.get("relative", 0))
        student_numbers = _numbers(student_answer)
        expected_numbers = _numbers(answer.answer_text)
        if student_numbers and expected_numbers:
            actual, expected = student_numbers[0], expected_numbers[0]
            matched = math.isclose(actual, expected, abs_tol=absolute, rel_tol=relative)
            reason = f"学生数值 {actual:g}，标准数值 {expected:g}"
        else:
            normalized = re.sub(r"\s+", "", student_answer).lower()
            matched = any(
                normalized == re.sub(r"\s+", "", str(item)).lower() for item in accepted
            )
    score = answer.max_score if matched else 0.0
    return RuleGrade(
        score=score,
        confidence=extraction_confidence,
        comment="答案正确" if matched else "答案与标准答案不一致",
        evidence=[
            {
                "point": "客观题答案匹配",
                "matched": matched,
                "points": score,
                "reason": reason,
            }
        ],
    )


def enforce_scoring_points(
    raw_score: float, evidence: list[dict], max_score: float
) -> float:
    awarded = [
        float(item.get("points", 0)) for item in evidence if item.get("matched") is True
    ]
    if awarded:
        return min(max(sum(awarded), 0), max_score)
    return min(max(raw_score, 0), max_score)
