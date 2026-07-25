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
CHOICE_TYPES = {
    QuestionType.SINGLE_CHOICE.value,
    QuestionType.MULTIPLE_CHOICE.value,
    "选择题",
    "单选题",
    "多选题",
}
TRUE_FALSE_TYPES = {QuestionType.TRUE_FALSE.value, "判断题"}
FILL_BLANK_TYPES = {QuestionType.FILL_BLANK.value, "填空题"}


@dataclass(frozen=True)
class RuleGrade:
    score: float
    confidence: float
    comment: str
    evidence: list[dict]


def is_objective(answer: StandardAnswer) -> bool:
    question_type = answer.question_type or ""
    if question_type in FILL_BLANK_TYPES:
        return len(answer.scoring_points) == 1
    return (
        question_type in OBJECTIVE_TYPES
        or question_type in CHOICE_TYPES | TRUE_FALSE_TYPES
    )


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
    choices = set(re.findall(r"(?<![A-Z])[A-H](?![A-Z])", text.upper()))
    ordinal_choices = {
        "第一项": "A",
        "第二项": "B",
        "第三项": "C",
        "第四项": "D",
        "第五项": "E",
        "第六项": "F",
        "第七项": "G",
        "第八项": "H",
    }
    choices.update(choice for label, choice in ordinal_choices.items() if label in text)
    return choices


def _scoring_point_choices(point: dict) -> set[str]:
    choices: set[str] = set()
    for item in point.get("accepted_evidence", []):
        value = str(item).strip().upper()
        direct = re.fullmatch(r"[A-H]", value)
        labelled = re.fullmatch(r"(?:选|选择|选项)([A-H])", value)
        if direct:
            choices.add(direct.group(0))
        elif labelled:
            choices.add(labelled.group(1))
    return choices


def _grade_choice(
    *, student_answer: str, answer: StandardAnswer, extraction_confidence: float
) -> RuleGrade:
    student_choices = _choice_set(student_answer)
    point_choices = [
        (point, _scoring_point_choices(point)) for point in answer.scoring_points
    ]
    expected = set().union(*(choices for _point, choices in point_choices))
    if not expected:
        expected = _choice_set(answer.answer_text.split("。", 1)[0])

    unexpected = student_choices - expected
    evidence: list[dict] = []
    score = 0.0
    mapped_points = [(point, choices) for point, choices in point_choices if choices]
    if mapped_points:
        for point, choices in mapped_points:
            matched = not unexpected and choices.issubset(student_choices)
            points = float(point.get("points", 0)) if matched else 0.0
            score += points
            evidence.append(
                {
                    "point": str(
                        point.get("id") or point.get("description") or "客观题答案匹配"
                    ),
                    "matched": matched,
                    "points": points,
                    "reason": (
                        f"学生选择 {sorted(student_choices)}，本评分点要求 {sorted(choices)}"
                        + (
                            f"，且包含错误选项 {sorted(unexpected)}"
                            if unexpected
                            else ""
                        )
                    ),
                }
            )
    else:
        matched = bool(expected) and student_choices == expected
        score = answer.max_score if matched else 0.0
        evidence.append(
            {
                "point": "客观题答案匹配",
                "matched": matched,
                "points": score,
                "reason": f"学生选择 {sorted(student_choices)}，标准选择 {sorted(expected)}",
            }
        )
    score = min(max(score, 0), answer.max_score)
    return RuleGrade(
        score=score,
        confidence=extraction_confidence,
        comment="答案正确"
        if math.isclose(score, answer.max_score)
        else "答案与标准答案不完全一致",
        evidence=evidence,
    )


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
    if question_type in CHOICE_TYPES:
        return _grade_choice(
            student_answer=student_answer,
            answer=answer,
            extraction_confidence=extraction_confidence,
        )
    if question_type in TRUE_FALSE_TYPES:
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
