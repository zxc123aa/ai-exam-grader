from decimal import Decimal

from app.services import question_answer_workflow as workflow
from app.services.question_answer_workflow import (
    _leading_question_score,
    _normalize_scoring_points,
    _score_allocations_from_header_payload,
    _score_hints_from_header_payload,
)


def test_leading_question_score_reads_printed_score() -> None:
    assert _leading_question_score("(10分)如图，在水平面上……") == (
        Decimal("10.00"),
        "(10分)",
    )
    assert _leading_question_score("17.（12 分）如图1……") == (
        Decimal("12.00"),
        "17.（12 分）",
    )


def test_leading_question_score_does_not_use_numbers_inside_question() -> None:
    assert _leading_question_score("活塞质量为6.0 kg，求气体高度") is None


def test_section_score_rule_expands_each_question_score() -> None:
    scores = _score_hints_from_header_payload(
        {
            "scores": [],
            "section_rules": [
                {
                    "first_question_key": "1",
                    "question_count": 8,
                    "points_each": 3,
                    "total_score": 24,
                    "evidence_text": "本题共8小题，每小题3分，共24分",
                    "grading_rule_text": "选对得3分，错选或不选得0分",
                }
            ],
        },
        first_question_key="1",
    )

    assert scores == {str(index): Decimal("3.00") for index in range(1, 9)}


def test_section_score_rule_uses_current_page_first_question() -> None:
    scores = _score_hints_from_header_payload(
        {
            "section_rules": [
                {
                    "question_count": 4,
                    "points_each": 2.5,
                    "total_score": 10,
                    "evidence_text": "本题共4小题，每小题2.5分，共10分",
                }
            ]
        },
        first_question_key="9",
    )

    assert scores == {
        "9": Decimal("2.50"),
        "10": Decimal("2.50"),
        "11": Decimal("2.50"),
        "12": Decimal("2.50"),
    }


def test_section_score_rule_rejects_inconsistent_total() -> None:
    scores = _score_hints_from_header_payload(
        {
            "section_rules": [
                {
                    "first_question_key": "1",
                    "question_count": 8,
                    "points_each": 3,
                    "total_score": 20,
                    "evidence_text": "本题共8小题，每小题3分，共20分",
                }
            ]
        },
        first_question_key="1",
    )

    assert scores == {}


def test_score_allocation_preserves_multiselect_evidence() -> None:
    allocations = _score_allocations_from_header_payload(
        {
            "section_rules": [
                {
                    "section_type": "multiple_choice",
                    "first_question_key": "9",
                    "question_count": 4,
                    "points_each": 4,
                    "total_score": 16,
                    "evidence_text": "多项选择题共4题，每题4分，共16分",
                    "grading_rule_text": "全部选对得4分，选对但不全得2分，有选错得0分",
                }
            ]
        },
        first_question_key="9",
    )

    assert allocations["9"]["max_score"] == Decimal("4.00")
    assert "选对但不全得2分" in allocations["12"]["grading_rule_text"]
    assert allocations["9"]["evidence_text"] == "多项选择题共4题，每题4分，共16分"


def test_score_rule_without_evidence_is_not_accepted() -> None:
    allocations = _score_allocations_from_header_payload(
        {
            "section_rules": [
                {
                    "first_question_key": "1",
                    "question_count": 8,
                    "points_each": 3,
                    "total_score": 24,
                }
            ]
        },
        first_question_key="1",
    )

    assert allocations == {}


def test_scoring_points_are_rescaled_to_declared_max_score() -> None:
    points = _normalize_scoring_points(
        [
            {
                "id": "p1",
                "description": "选择正确选项",
                "points": 1,
                "required": True,
            }
        ],
        Decimal("3.00"),
    )

    assert points[0]["points"] == 3.0
    assert sum(item["points"] for item in points) == 3.0


def _fake_model_call(parsed):
    def fake_call(**_kwargs):
        return parsed, "test-sol-model", 5, {}

    return fake_call


def test_solve_question_uses_declared_score_over_model_score(monkeypatch) -> None:
    monkeypatch.setattr(
        workflow,
        "call_json_model_with_metadata",
        _fake_model_call(
            {
                "question_key": "1",
                "answer_text": "A",
                "max_score": 5,
                "rubric_text": "选对得分",
                "scoring_points": [],
                "confidence": 0.9,
            }
        ),
    )

    result = workflow._solve_question(
        {
            "id": None,
            "question_key": "1",
            "question_text": "（3分）下列说法正确的是……",
            "question_type": "single_choice",
            "declared_max_score": Decimal("3.00"),
            "score_evidence_text": "（3分）",
        },
        "provider",
        "model",
    )

    assert result["max_score"] == Decimal("3.00")
    assert result["solution_requires_review"] is False


def test_solve_question_flags_unsolvable_conclusion_for_review(monkeypatch) -> None:
    monkeypatch.setattr(
        workflow,
        "call_json_model_with_metadata",
        _fake_model_call(
            {
                "question_key": "18",
                "answer_text": "题面条件彼此矛盾，无确定解",
                "max_score": 14,
                "rubric_text": "略",
                "scoring_points": [],
                "confidence": 0.98,
            }
        ),
    )

    result = workflow._solve_question(
        {
            "id": None,
            "question_key": "18",
            "question_text": "（14分）如图，已知……",
            "question_type": "计算题",
            "declared_max_score": Decimal("14.00"),
            "score_evidence_text": "（14分）",
        },
        "provider",
        "model",
    )

    assert result["solution_requires_review"] is True
    assert result["confidence"] <= Decimal("0.4")
    assert "【需人工复核】" in result["rubric_text"]


def test_section_score_rule_propagates_to_questions_without_own_evidence() -> None:
    questions = [
        {
            "id": None,
            "question_key": "9",
            "question_text": (
                "二、多项选择题：本题共5小题，每小题4分，共20分。"
                "全部选对得4分，少选得2分，有选错得0分\n"
                "9. 下列说法正确的是……"
            ),
            "question_type": "选择题",
        },
        {
            "id": None,
            "question_key": "10",
            "question_text": "10. 关于电场线，下列说法正确的是……",
            "question_type": "选择题",
        },
    ]
    allocations = {
        "9": {
            "max_score": Decimal("4.00"),
            "evidence_text": "每小题4分",
            "grading_rule_text": "少选得2分",
            "source": "question_text",
        }
    }

    rules = workflow._propagate_section_score_rules(questions, allocations)

    assert allocations["10"]["max_score"] == Decimal("4.00")
    assert allocations["10"]["source"] == "section_shared"
    assert "少选得2分" in allocations["10"]["grading_rule_text"]
    assert any(rule["anchor_question_key"] == "9" for rule in rules)


def test_section_score_rule_conflict_keeps_fallback() -> None:
    questions = [
        {
            "id": None,
            "question_key": "9",
            "question_text": "多项选择题：本题共5小题，每小题4分，共20分\n9. ……",
            "question_type": "multiple_choice",
        },
        {
            "id": None,
            "question_key": "12",
            "question_text": "12. ……",
            "question_type": "multiple_choice",
        },
    ]
    allocations = {
        "12": {
            "max_score": Decimal("5.00"),
            "evidence_text": "12题5分",
            "grading_rule_text": "12题5分",
            "source": "question_text",
        }
    }

    workflow._propagate_section_score_rules(questions, allocations)

    # Existing per-question evidence always wins over section propagation.
    assert allocations["12"]["max_score"] == Decimal("5.00")
    assert allocations["12"]["source"] == "question_text"


def test_exam_score_rules_summary_lists_ranges() -> None:
    summary = workflow._exam_score_rules_summary(
        [
            {
                "section_type": "multiple_choice",
                "points_each": Decimal("4.00"),
                "grading_rule_text": "本题共5小题，每小题4分，共20分，少选得2分",
                "evidence_text": "本题共5小题，每小题4分，共20分，少选得2分",
                "anchor_question_key": "9",
                "question_count": 5,
                "source": "question_text_section_rule",
            }
        ]
    )

    assert "第9-13题" in summary
    assert "每小题4分" in summary
    assert "少选得2分" in summary


def test_solve_question_prompt_contains_shared_section_rules(monkeypatch) -> None:
    captured = {}

    def fake_call(**kwargs):
        captured["prompt"] = kwargs["messages"][0]["content"][0]["text"]
        return (
            {
                "question_key": "10",
                "answer_text": "AC",
                "max_score": 4,
                "rubric_text": "全部选对得4分，少选得2分，有选错得0分",
                "scoring_points": [],
                "confidence": 0.9,
            },
            "test-sol-model",
            5,
            {},
        )

    monkeypatch.setattr(workflow, "call_json_model_with_metadata", fake_call)

    result = workflow._solve_question(
        {
            "id": None,
            "question_key": "10",
            "question_text": "10. 关于电场线，下列说法正确的是……",
            "question_type": "multiple_choice",
            "declared_max_score": Decimal("4.00"),
            "score_evidence_text": "本题共5小题，每小题4分，共20分，少选得2分",
            "declared_grading_rule": "本题共5小题，每小题4分，共20分，少选得2分",
            "score_evidence_source": "section_shared",
            "exam_score_rules_text": "- 第9-13题：每小题4分；计分规则原文：少选得2分",
        },
        "provider",
        "model",
    )

    assert "全卷大题赋分规则汇总" in captured["prompt"]
    assert "少选得2分" in captured["prompt"]
    assert "跨题共享" in captured["prompt"]
    assert result["max_score"] == Decimal("4.00")
    assert result["score_evidence_source"] == "section_shared"


def test_harvest_collects_quoted_section_rule_and_rejects_fallback() -> None:
    results = [
        {
            "question_key": "9",
            "rubric_text": (
                "评分依据卷面印刷规则：二、多项选择题：本题共5小题，"
                "每小题4分，共20分，全部选对的得4分，选对但不全的得2分"
            ),
            "answer_text": "AC",
            "raw_result": {},
        },
        {
            "question_key": "10",
            "rubric_text": "卷面未标注分值，按5分设定（待教师确认）",
            "answer_text": "B",
            "raw_result": {},
        },
    ]

    rules = workflow._harvest_section_rules_from_results(results)

    assert len(rules) == 1
    rule = rules[0]
    assert rule["points_each"] == Decimal("4.00")
    assert rule["anchor_question_key"] == "9"
    assert rule["question_count"] == 5
    assert rule["section_type"] == "multiple_choice"
    assert rule["source"] == "batch_harvest"


def test_harvested_rule_propagates_by_range_as_batch_source() -> None:
    questions = [
        {"id": None, "question_key": "9", "question_text": "9. ……", "question_type": "选择题"},
        {"id": None, "question_key": "10", "question_text": "10. ……", "question_type": "选择题"},
        {"id": None, "question_key": "13", "question_text": "13. ……", "question_type": "选择题"},
    ]
    allocations = {}
    harvested = workflow._harvest_section_rules_from_results(
        [
            {
                "question_key": "9",
                "rubric_text": "本题共5小题，每小题4分，共20分，选对但不全的得2分",
                "answer_text": "AC",
                "raw_result": {},
            }
        ]
    )

    workflow._propagate_section_score_rules(questions, allocations, rules=harvested)

    for key in ("9", "10", "13"):
        assert allocations[key]["max_score"] == Decimal("4.00")
        assert allocations[key]["source"] == "batch_harvest"
        assert allocations[key]["anchor_question_key"] == "9"


def test_answer_item_fields_marks_batch_harvest_evidence() -> None:
    fields = workflow._answer_item_fields(
        {
            "question_key": "10",
            "answer_text": "BD",
            "max_score": Decimal("4.00"),
            "rubric_text": "全部选对得4分，选对但不全得2分",
            "scoring_points": [],
            "confidence": Decimal("0.9"),
            "raw_result": {},
            "score_evidence_text": "本题共5小题，每小题4分，共20分",
            "score_evidence_source": "batch_harvest",
            "score_evidence_anchor": "9",
            "declared_grading_rule": "本题共5小题，每小题4分，共20分",
            "score_requires_review": False,
            "solution_requires_review": False,
        }
    )

    assert "赋分证据来自第9题裁图（批次内共享）" in fields["match_reason"]
    assert fields["raw_result"]["scoreEvidenceSource"] == "batch_harvest"
    assert fields["raw_result"]["scoreEvidenceAnchor"] == "9"


def test_solve_question_prompt_marks_batch_harvest_origin(monkeypatch) -> None:
    captured = {}

    def fake_call(**kwargs):
        captured["prompt"] = kwargs["messages"][0]["content"][0]["text"]
        return (
            {
                "question_key": "10",
                "answer_text": "BD",
                "max_score": 4,
                "rubric_text": "全部选对得4分，选对但不全得2分",
                "scoring_points": [],
                "confidence": 0.9,
            },
            "test-sol-model",
            5,
            {},
        )

    monkeypatch.setattr(workflow, "call_json_model_with_metadata", fake_call)

    result = workflow._solve_question(
        {
            "id": None,
            "question_key": "10",
            "question_text": "10. 关于磁场……",
            "question_type": "选择题",
            "declared_max_score": Decimal("4.00"),
            "score_evidence_text": "本题共5小题，每小题4分，共20分",
            "declared_grading_rule": "本题共5小题，每小题4分，共20分，选对但不全的得2分",
            "score_evidence_source": "batch_harvest",
            "score_evidence_anchor": "9",
        },
        "provider",
        "model",
    )

    assert "第9题裁图" in captured["prompt"]
    assert "批次内共享" in captured["prompt"]
    assert result["max_score"] == Decimal("4.00")
    assert result["score_evidence_anchor"] == "9"


def test_harvest_trims_answer_specific_content_from_evidence() -> None:
    rubric = (
        "题面印刷赋分规则为：'二、多项选择题：本题共5小题，每小题4分，共20分。"
        "全部选对的得4分，选对但不全的得2分，有选错的得0分。'本题正确选项为B、C。"
        "仅选择B或仅选择C得2分……"
    )

    rules = workflow._harvest_section_rules_from_results(
        [{"question_key": "9", "rubric_text": rubric, "answer_text": "BC", "raw_result": {}}]
    )

    assert len(rules) == 1
    evidence = rules[0]["grading_rule_text"]
    assert "每小题4分" in evidence
    assert "选对但不全的得2分" in evidence
    assert "得0分" in evidence
    assert rules[0]["question_count"] == 5
    assert rules[0]["section_type"] == "multiple_choice"
    for leaked in ("正确选项", "B、C", "本题选", "仅选择"):
        assert leaked not in evidence


def test_trim_keeps_following_grading_sentences_without_zero_points() -> None:
    evidence = workflow._trim_score_rule_evidence(
        "本题共5小题，每小题4分，共20分。全部选对得4分，少选得2分。本题考查电场概念。"
    )

    assert evidence == "本题共5小题，每小题4分，共20分。全部选对得4分，少选得2分。"


def test_trim_returns_empty_without_printed_points() -> None:
    assert workflow._trim_score_rule_evidence("本题正确选项为B、C") == ""
