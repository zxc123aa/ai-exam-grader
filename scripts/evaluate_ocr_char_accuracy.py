from __future__ import annotations

import argparse
import json
import re
import string
from pathlib import Path
from typing import Any


PUNCTUATION_TO_IGNORE = (
    string.punctuation
    + "，。、“”‘’：；？！（）【】《》〈〉「」『』〔〕｛｝［］（）·…—"
)


def normalize_text(text: str, *, strict_punctuation: bool) -> str:
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", "", text)
    if not strict_punctuation:
        text = text.translate(str.maketrans("", "", PUNCTUATION_TO_IGNORE))
    return text


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            curr.append(
                min(
                    prev[j] + 1,
                    curr[j - 1] + 1,
                    prev[j - 1] + (0 if ca == cb else 1),
                )
            )
        prev = curr
    return prev[-1]


def load_prediction_items(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        if "questions" in data:
            rows = data["questions"]
        elif "results" in data:
            rows = data["results"]
        elif "data" in data:
            rows = data["data"]
        else:
            rows = [
                {"question_number": key, "text": value}
                for key, value in data.items()
                if isinstance(value, str)
            ]
    elif isinstance(data, list):
        rows = data
    else:
        raise ValueError("Prediction JSON must be an object or a list")

    predictions: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        number = (
            row.get("question_number")
            or row.get("questionNumber")
            or row.get("number")
            or row.get("id")
        )
        text = (
            row.get("printed_question_text")
            or row.get("question_text")
            or row.get("questionText")
            or row.get("question")
            or row.get("text")
        )
        if number is None or text is None:
            continue
        predictions[str(number)] = str(text)
    return predictions


def evaluate(
    *,
    gold_path: Path,
    prediction_path: Path,
    output_path: Path,
    include_review_items: bool,
    strict_punctuation: bool,
    threshold: float,
) -> dict[str, Any]:
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    predictions = load_prediction_items(prediction_path)
    rows = []
    total_distance = 0
    total_chars = 0
    included_count = 0
    for item in gold["questions"]:
        status = item.get("printed_text_status")
        if status == "needs_human_review" and not include_review_items:
            continue
        number = str(item["question_number"])
        expected = normalize_text(
            item["printed_question_text"], strict_punctuation=strict_punctuation
        )
        predicted_raw = predictions.get(number, "")
        predicted = normalize_text(
            predicted_raw, strict_punctuation=strict_punctuation
        )
        distance = levenshtein(expected, predicted)
        denominator = max(len(expected), 1)
        accuracy = max(0.0, 1.0 - distance / denominator)
        total_distance += distance
        total_chars += denominator
        included_count += 1
        rows.append(
            {
                "question_number": number,
                "gold_status": status,
                "expected_chars": len(expected),
                "predicted_chars": len(predicted),
                "edit_distance": distance,
                "char_accuracy": round(accuracy, 6),
                "passed": accuracy >= threshold,
            }
        )

    overall = max(0.0, 1.0 - total_distance / max(total_chars, 1))
    report = {
        "gold_path": str(gold_path),
        "prediction_path": str(prediction_path),
        "include_review_items": include_review_items,
        "strict_punctuation": strict_punctuation,
        "threshold": threshold,
        "question_count": included_count,
        "overall_char_accuracy": round(overall, 6),
        "passed": overall >= threshold and all(row["passed"] for row in rows),
        "failed_questions": [
            row["question_number"] for row in rows if not row["passed"]
        ],
        "items": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--pred", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--include-review-items", action="store_true")
    parser.add_argument("--strict-punctuation", action="store_true")
    parser.add_argument("--threshold", type=float, default=0.95)
    args = parser.parse_args()
    report = evaluate(
        gold_path=args.gold,
        prediction_path=args.pred,
        output_path=args.out,
        include_review_items=args.include_review_items,
        strict_punctuation=args.strict_punctuation,
        threshold=args.threshold,
    )
    print(json.dumps({k: report[k] for k in ("overall_char_accuracy", "passed", "failed_questions")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
