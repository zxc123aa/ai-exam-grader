from __future__ import annotations

import json
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

from app.services.question_text_normalization import (
    normalize_recognized_question_text,
    normalize_recognized_question_text_with_audit,
    normalize_reference_result_question,
    question_key_sort_key,
)


def test_question_key_sort_key_orders_numbers_and_tolerates_mixed_keys() -> None:
    # A real recognition run mixes plain numbers with region fallback keys, which
    # used to make the sort compare int against str and 500 the items endpoint.
    keys = ["10", "A1", "2", "fallback:page:2::region_1", "1", None]
    assert sorted(keys, key=question_key_sort_key) == [
        None,
        "1",
        "2",
        "10",
        "A1",
        "fallback:page:2::region_1",
    ]


def test_normalize_recognized_question_text_removes_format_noise_only() -> None:
    raw = """三、作图和实验题（18题4分，19题6分，20题10分，共20分）
18. （1）请在图甲中画出悬挂着的吊灯的重力示意图（作用点已给出）。
（2）请在图乙中组装好滑轮组，在图中画出最省力的绳子绕法。
18题 图甲
图乙"""

    assert normalize_recognized_question_text(raw, question_key="18") == (
        "（1）请在图甲中画出悬挂着的吊灯的重力示意图（作用点已给出）。 "
        "（2）请在图乙中组装好滑轮组，在图中画出最省力的绳子绕法。"
    )
    audit = normalize_recognized_question_text_with_audit(raw, question_key="18")
    assert audit["changed"] is True
    assert audit["riskLevel"] == "medium"
    assert {change["rule"] for change in audit["changes"]} >= {
        "remove_section_heading_line",
        "remove_duplicate_question_number_prefix",
        "remove_standalone_figure_label_line",
    }


def test_normalize_recognized_question_text_normalizes_formula_and_blanks() -> None:
    raw = """9. 举重题。
A. $W_1 = W_2$, $P_1 = P_2$
B. $W_1 > W_2$, $P_1 = P_2$"""

    assert normalize_recognized_question_text(raw, question_key="第9题") == (
        "举重题。 A. W1=W2, P1=P2 B. W1>W2, P1=P2"
    )
    assert (
        normalize_recognized_question_text(
            "12. 鸡蛋由于具有______并未飞出。", question_key="12"
        )
        == "鸡蛋由于具有____并未飞出。"
    )


def test_normalize_reference_result_question_preserves_raw_question_for_audit() -> None:
    result = {
        "questionNumber": "12",
        "question": "12.如图所示，用尺子快速水平击打盖在杯口的硬纸片。",
    }

    normalized = normalize_reference_result_question(result)

    assert normalized["question"] == "如图所示，用尺子快速水平击打盖在杯口的硬纸片。"
    assert normalized["rawQuestion"] == result["question"]
    assert normalized["questionNormalized"] is True
    assert (
        normalized["questionNormalization"]["version"]
        == "question_text_normalization_v1"
    )
    assert normalized["questionNormalization"]["changed"] is True
    assert normalized["questionNormalization"]["riskLevel"] == "low"
    assert any(
        change["rule"] == "remove_duplicate_question_number_prefix"
        for change in normalized["questionNormalization"]["changes"]
    )


def test_physics_reference_prediction_passes_gold_after_question_normalization(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[3]
    gold_path = root / "data/golden/physics-2021-2022-b/printed_questions_gold.json"
    prediction_path = (
        root
        / "outputs/ocr-ground-truth/physics-2021-2022-b/reference-node-run/current_prediction.json"
    )
    evaluator_path = root / "scripts/evaluate_ocr_char_accuracy.py"
    if (
        not gold_path.exists()
        or not prediction_path.exists()
        or not evaluator_path.exists()
    ):
        pytest.skip("physics OCR regression fixtures are not present in this workspace")

    prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
    normalized_prediction = {
        "questions": [
            {
                **item,
                "question_text": normalize_recognized_question_text(
                    item.get("question_text"),
                    question_key=str(item.get("question_number") or ""),
                ),
            }
            for item in prediction["questions"]
        ]
    }
    normalized_path = tmp_path / "normalized_prediction.json"
    normalized_path.write_text(
        json.dumps(normalized_prediction, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    evaluator = SourceFileLoader("ocr_eval", str(evaluator_path)).load_module()

    report = evaluator.evaluate(
        gold_path=gold_path,
        prediction_path=normalized_path,
        output_path=tmp_path / "eval.json",
        include_review_items=True,
        strict_punctuation=False,
        threshold=0.95,
    )

    assert report["passed"] is True
    assert report["overall_char_accuracy"] >= 0.99
    assert report["failed_questions"] == []
