import uuid
from types import SimpleNamespace

from app.models import StandardAnswer
from app.services.grading_rules import grade_objective, is_objective, validate_rubric
from app.services.grading_workflow import (
    AdaptiveConcurrency,
    next_schedulable_payload_index,
)


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


def test_localized_choice_type_uses_rules_and_ignores_answer_explanation() -> None:
    item = answer(
        answer_text="B。A、C、D错误。",
        question_type="选择题",
        scoring_points=[
            {
                "id": "p1",
                "description": "唯一选择B",
                "points": 3,
                "accepted_evidence": ["B", "选择B"],
            }
        ],
    )

    assert is_objective(item) is True
    assert (
        grade_objective(
            student_answer="选择第二项", answer=item, extraction_confidence=0.95
        ).score
        == 3
    )


def test_localized_multiple_choice_awards_partial_points_without_wrong_options() -> (
    None
):
    item = answer(
        answer_text="正确选项为A、D。",
        max_score=4,
        question_type="选择题",
        scoring_points=[
            {"id": "p1", "points": 2, "accepted_evidence": ["A", "选项A"]},
            {"id": "p2", "points": 2, "accepted_evidence": ["D", "选项D"]},
        ],
    )

    assert (
        grade_objective(
            student_answer="只选择第一项", answer=item, extraction_confidence=0.9
        ).score
        == 2
    )
    assert (
        grade_objective(
            student_answer="选择第一项、第二项", answer=item, extraction_confidence=0.9
        ).score
        == 0
    )


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


def test_adaptive_concurrency_never_exceeds_thirty_two_or_drops_below_one() -> None:
    controller = AdaptiveConcurrency(50)
    assert controller.current == 32
    for _ in range(5):
        controller.record(transient=True, failed=True)
    assert controller.current == 1


def _payload(submission_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(submission=SimpleNamespace(id=submission_id))


def test_two_level_scheduler_limits_parallel_submissions() -> None:
    first, second, third = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    active = [_payload(first), _payload(second)]
    pending = [_payload(third), _payload(first)]

    index = next_schedulable_payload_index(
        pending,
        active,
        max_parallel_submissions=2,
        max_concurrency_per_submission=2,
    )

    assert index == 1


def test_two_level_scheduler_limits_questions_within_one_submission() -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    active = [_payload(first), _payload(first)]
    pending = [_payload(first), _payload(second)]

    index = next_schedulable_payload_index(
        pending,
        active,
        max_parallel_submissions=2,
        max_concurrency_per_submission=2,
    )

    assert index == 1
