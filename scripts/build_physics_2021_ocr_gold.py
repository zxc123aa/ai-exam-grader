from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/synthetic/physics-2021-2022/standard_answers_draft.json"
OUT_DIR = ROOT / "data/golden/physics-2021-2022-b"


def normalize_text(text: str) -> str:
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def build_gold(data: dict[str, Any]) -> dict[str, Any]:
    questions = []
    for item in data["questions"]:
        confidence = float(item.get("confidence") or 0)
        review_reason = (item.get("reviewReason") or "").strip()
        question_text = normalize_text(item["questionText"])
        questions.append(
            {
                "question_number": str(item["questionNumber"]),
                "page_number": int(item["pageNumber"]),
                "answer_type": item.get("answerType"),
                "max_score": float(item.get("maxScore") or 0),
                "printed_question_text": question_text,
                "printed_question_text_char_count": len(question_text),
                "printed_text_status": (
                    "needs_human_review"
                    if confidence < 0.9 or review_reason
                    else "gold_candidate"
                ),
                "review_reason": review_reason,
                "source_confidence": confidence,
                "student_handwriting_text": None,
                "student_handwriting_status": "not_transcribed",
            }
        )
    return {
        "dataset_id": "physics-2021-2022-b",
        "exam_title": data["examTitle"],
        "scope": {
            "printed_question_text": "用于 OCR 字符准确率评测的印刷题干金标准候选。",
            "student_handwriting_text": "学生手写答案必须单独人工转写；未转写前不得计入 95% 字符准确率。",
        },
        "source_files": [
            "参考算法/2_试卷分析文件/material/1.jpg",
            "参考算法/2_试卷分析文件/material/2.jpg",
            "data/synthetic/physics-2021-2022/standard_answers_draft.json",
        ],
        "acceptance_rule": {
            "printed_text_char_accuracy_min": 0.95,
            "handwriting_char_accuracy_min": None,
            "note": "95% 只对已人工确认的 gold text 生效；needs_human_review 项应先复核再计入最终验收。",
        },
        "questions": questions,
    }


def write_markdown(gold: dict[str, Any]) -> None:
    lines = [
        f"# {gold['exam_title']} OCR Gold Text",
        "",
        "本文件是 `printed_questions_gold.json` 的人工复核用视图。",
        "状态为 `needs_human_review` 的题目不得直接作为最终 95% 验收依据。",
        "",
    ]
    for item in gold["questions"]:
        lines.extend(
            [
                f"## {item['question_number']}",
                "",
                f"- page: {item['page_number']}",
                f"- status: {item['printed_text_status']}",
                f"- char_count: {item['printed_question_text_char_count']}",
            ]
        )
        if item["review_reason"]:
            lines.append(f"- review_reason: {item['review_reason']}")
        lines.extend(["", item["printed_question_text"], ""])
    (OUT_DIR / "printed_questions_gold.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def main() -> None:
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    gold = build_gold(data)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "printed_questions_gold.json").write_text(
        json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_markdown(gold)
    summary = {
        "dataset_id": gold["dataset_id"],
        "question_count": len(gold["questions"]),
        "gold_candidate_count": sum(
            1
            for item in gold["questions"]
            if item["printed_text_status"] == "gold_candidate"
        ),
        "needs_human_review_count": sum(
            1
            for item in gold["questions"]
            if item["printed_text_status"] == "needs_human_review"
        ),
        "printed_question_text_total_chars": sum(
            item["printed_question_text_char_count"] for item in gold["questions"]
        ),
    }
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
