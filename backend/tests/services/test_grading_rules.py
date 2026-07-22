from app.models import StandardAnswer
from app.services.grading_rules import grade_objective, validate_rubric
from app.services.grading_workflow import AdaptiveConcurrency


def answer(**updates: object) -> StandardAnswer:
    values = {
        "exam_id": "00000000-0000-0000-0000-000000000001",
        "exam_region_id": "00000000-0000-0000-0000-000000000002",
        "answer_text": "B",
        "max_score": 3,
        "question_text": "下列说法正确的是（ ） A.甲 B.乙",
        "question_type": "single_choice",
        "scoring_points": [
            {"id": "p1", "description": "选B", "points": 3, "required": True}
        ],
        "rubric_config": {"accepted_answers": ["选项B"]},
        "validation_report": {"valid": True},
    }
    values.update(updates)
    return StandardAnswer(**values)


def test_single_choice_is_scored_deterministically() -> None:
    result = grade_objective(
        student_answer="B", answer=answer(), extraction_confidence=0.96
    )
    assert result.score == 3
    assert result.confidence == 0.96
    assert result.evidence[0]["matched"] is True


def test_single_choice_does_not_accept_neighbor_answer() -> None:
    result = grade_objective(
        student_answer="第1题 A", answer=answer(), extraction_confidence=0.9
    )
    assert result.score == 0


def test_numeric_fill_blank_uses_absolute_tolerance() -> None:
    item = answer(
        answer_text="9.8 m/s²",
        question_type="fill_blank",
        rubric_config={"tolerance": {"absolute": 0.05, "relative": 0}},
    )
    result = grade_objective(
        student_answer="9.81 m/s²", answer=item, extraction_confidence=0.93
    )
    assert result.score == 3


def test_rubric_rejects_score_sum_mismatch() -> None:
    errors = validate_rubric(
        answer(
            scoring_points=[
                {"id": "p1", "description": "选B", "points": 2, "required": True}
            ]
        )
    )
    assert any("评分点合计" in error for error in errors)


def test_adaptive_concurrency_throttles_and_recovers() -> None:
    controller = AdaptiveConcurrency(8)
    controller.record(transient=True, failed=True)
    assert controller.current == 4
    assert controller.throttle_count == 1
    for _ in range(20):
        controller.record(transient=False, failed=False)
    assert controller.current == 5


def test_adaptive_concurrency_never_exceeds_eight_or_drops_below_one() -> None:
    controller = AdaptiveConcurrency(20)
    assert controller.current == 8
    for _ in range(5):
        controller.record(transient=True, failed=True)
    assert controller.current == 1
