#!/usr/bin/env python3
"""Fast deterministic gate for reconstructed exam text.

The gate compares a candidate reconstruction round against a trusted Markdown
reference and emits a small anomaly queue for agent or human review. It keeps
slow agent work focused on the few places that need judgment.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


CONTRACT_FILES = (
    "reconstructed_exam.md",
    "ocr_raw_blocks.json",
    "question_index.json",
    "qc_report.md",
    "uncertainties.md",
    "diff_against_previous.md",
)


@dataclass(frozen=True)
class Rule:
    question: int
    code: str
    severity: str
    expected: str
    bad: str
    detail: str


DEFAULT_RULES = (
    Rule(
        question=7,
        code="Q7_ROCKET_MODEL",
        severity="warning",
        expected="遥十八运载火箭",
        bad="遥火箭",
        detail="Q7 rocket model should be checked against the trusted reconstruction.",
    ),
    Rule(
        question=7,
        code="Q7_SUBJECT",
        severity="warning",
        expected="航天员动能和势能变化",
        bad="火箭动能和势能变化",
        detail="Q7 kinetic/potential energy subject differs from the trusted reconstruction.",
    ),
    Rule(
        question=12,
        code="Q12_DRINK_PHRASE",
        severity="minor",
        expected="夏日里用吸管",
        bad="我们用吸管",
        detail="Q12 drink sentence differs from the trusted reconstruction.",
    ),
    Rule(
        question=21,
        code="Q21_RHO_WATER",
        severity="minor",
        expected="ρ水",
        bad="ρ=",
        detail="Q21 density symbol lacks water subscript in candidate output.",
    ),
    Rule(
        question=22,
        code="Q22_AIRBAG_VOLUME",
        severity="critical",
        expected="3.5×10⁻²",
        bad="3.5×10²",
        detail="Q22 airbag volume exponent/unit must not regress.",
    ),
)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalize(text: str) -> str:
    text = re.sub(r"\s+", "", text)
    return (
        text.replace("（", "(")
        .replace("）", ")")
        .replace("，", ",")
        .replace("。", ".")
        .replace("；", ";")
    )


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def extract_candidate_questions(md: str) -> dict[int, str]:
    pattern = re.compile(r"^## 第\s*(\d+)\s*题.*?$", re.M)
    matches = list(pattern.finditer(md))
    questions: dict[int, str] = {}
    for idx, match in enumerate(matches):
        number = int(match.group(1))
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(md)
        body = md[start:end].strip()
        body = body.split("## 不确定项占位")[0].strip()
        questions[number] = body
    return questions


def extract_trusted_questions(md: str) -> dict[int, str]:
    pattern = re.compile(r"^###\s*(\d+)\..*$", re.M)
    matches = list(pattern.finditer(md))
    questions: dict[int, str] = {}
    for idx, match in enumerate(matches):
        number = int(match.group(1))
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(md)
        body = md[start:end].strip()
        body = body.split("## 本版仍需人工核对的位置")[0].strip()
        questions[number] = body
    return questions


def add_anomaly(
    anomalies: list[dict[str, Any]],
    question: int | None,
    code: str,
    severity: str,
    detail: str,
    evidence: dict[str, Any],
) -> None:
    anomalies.append(
        {
            "question": question,
            "code": code,
            "severity": severity,
            "detail": detail,
            "evidence": evidence,
        }
    )


def load_question_index(path: Path) -> list[dict[str, Any]]:
    data = json.loads(read_text(path))
    questions = data.get("questions", [])
    if not isinstance(questions, list):
        raise ValueError("question_index.json must contain a list field named 'questions'")
    return questions


def run_gate(
    candidate_round: Path,
    trusted_md: Path,
    output_dir: Path,
    *,
    expected_score: int = 100,
    expected_questions: range = range(1, 23),
    rules: tuple[Rule, ...] = DEFAULT_RULES,
    similarity_questions: set[int] | None = None,
    similarity_threshold: float = 0.70,
) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)

    candidate_md = read_text(candidate_round / "reconstructed_exam.md")
    trusted_text = read_text(trusted_md)
    question_index = load_question_index(candidate_round / "question_index.json")
    qc_report = read_text(candidate_round / "qc_report.md")
    uncertainties = read_text(candidate_round / "uncertainties.md")

    candidate_questions = extract_candidate_questions(candidate_md)
    trusted_questions = extract_trusted_questions(trusted_text)
    expected_numbers = list(expected_questions)
    candidate_numbers = sorted(candidate_questions)
    trusted_numbers = sorted(trusted_questions)
    anomalies: list[dict[str, Any]] = []

    contract_presence = {
        name: (candidate_round / name).exists()
        and (candidate_round / name).stat().st_size > 0
        for name in CONTRACT_FILES
    }
    missing_contract = [name for name, present in contract_presence.items() if not present]
    if missing_contract:
        add_anomaly(
            anomalies,
            None,
            "CONTRACT_FILES",
            "critical",
            "Candidate round is missing required contract files.",
            {"missing": missing_contract},
        )

    if candidate_numbers != expected_numbers:
        add_anomaly(
            anomalies,
            None,
            "QSEQ_CANDIDATE",
            "critical",
            "Candidate question sequence is not the expected contiguous range.",
            {"candidate_numbers": candidate_numbers, "expected_numbers": expected_numbers},
        )

    if trusted_numbers != expected_numbers:
        add_anomaly(
            anomalies,
            None,
            "QSEQ_TRUSTED",
            "critical",
            "Trusted question sequence is not the expected contiguous range.",
            {"trusted_numbers": trusted_numbers, "expected_numbers": expected_numbers},
        )

    score_total = sum((question.get("score") or 0) for question in question_index)
    if score_total != expected_score:
        add_anomaly(
            anomalies,
            None,
            "SCORE_TOTAL",
            "critical",
            "Question index score total does not match expected total.",
            {"score_total": score_total, "expected_score": expected_score},
        )

    for rule in rules:
        candidate_body = candidate_questions.get(rule.question, "")
        trusted_body = trusted_questions.get(rule.question, "")
        bad_present = rule.bad in candidate_body
        expected_missing = rule.expected not in candidate_body
        if bad_present or expected_missing:
            add_anomaly(
                anomalies,
                rule.question,
                rule.code,
                rule.severity,
                rule.detail,
                {
                    "expected": rule.expected,
                    "bad_pattern": rule.bad,
                    "bad_present": bad_present,
                    "expected_missing": expected_missing,
                    "candidate_excerpt": candidate_body[:600],
                    "trusted_excerpt": trusted_body[:600],
                    "similarity_to_trusted": round(
                        similarity(candidate_body, trusted_body), 4
                    ),
                },
            )

    if similarity_questions is None:
        similarity_questions = {1, 3, 7, 11, 12, 16, 21, 22}
    for question in similarity_questions:
        if question in candidate_questions and question in trusted_questions:
            score = similarity(candidate_questions[question], trusted_questions[question])
            if score < similarity_threshold:
                add_anomaly(
                    anomalies,
                    question,
                    "LOW_TEXT_SIMILARITY",
                    "info",
                    "Candidate question text differs substantially from trusted text.",
                    {"similarity_to_trusted": round(score, 4)},
                )

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    severity_counts: dict[str, int] = {}
    for anomaly in anomalies:
        severity = anomaly["severity"]
        severity_counts[severity] = severity_counts.get(severity, 0) + 1

    result = {
        "metadata": {
            "elapsed_ms": elapsed_ms,
            "candidate_round": str(candidate_round),
            "trusted": str(trusted_md),
        },
        "checks": {
            "contract_files_present": all(contract_presence.values()),
            "contract_presence": contract_presence,
            "candidate_questions": candidate_numbers,
            "trusted_questions": trusted_numbers,
            "expected_questions": expected_numbers,
            "score_total": score_total,
            "expected_score": expected_score,
            "candidate_qc_status_partial": "状态：PARTIAL" in qc_report,
            "uncertainties_count": uncertainties.count("\n## U"),
        },
        "severity_counts": severity_counts,
        "anomalies": anomalies,
    }
    write_outputs(result, output_dir, candidate_round, trusted_md)
    return result


def write_outputs(
    result: dict[str, Any],
    output_dir: Path,
    candidate_round: Path,
    trusted_md: Path,
) -> None:
    (output_dir / "deterministic_checks.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    checks = result["checks"]
    lines = [
        "# Fast Reconstruction Gate Summary",
        "",
        f"- Runtime: {result['metadata']['elapsed_ms']} ms",
        f"- Contract files present: {checks['contract_files_present']}",
        f"- Candidate question sequence: {checks['candidate_questions']}",
        f"- Trusted question sequence: {checks['trusted_questions']}",
        f"- Score total: {checks['score_total']}",
        f"- Candidate QC status is PARTIAL: {checks['candidate_qc_status_partial']}",
        f"- Uncertainty items: {checks['uncertainties_count']}",
        f"- Anomalies: {len(result['anomalies'])}",
        f"- By severity: {result['severity_counts']}",
        "",
        "## Key Finding",
        "",
        "The deterministic gate reduces agent review to a bounded anomaly queue. "
        "Agents should review only `anomaly_queue.md`, not the full exam.",
        "",
    ]
    (output_dir / "gate_summary.md").write_text("\n".join(lines), encoding="utf-8")

    queue = ["# Anomaly Queue", ""]
    for idx, anomaly in enumerate(result["anomalies"], 1):
        queue.extend(
            [
                f"## A{idx:03d} — {anomaly['code']}",
                "",
                f"- Question: {anomaly['question']}",
                f"- Severity: {anomaly['severity']}",
                f"- Detail: {anomaly['detail']}",
                "",
                "```json",
                json.dumps(anomaly["evidence"], ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    (output_dir / "anomaly_queue.md").write_text("\n".join(queue), encoding="utf-8")

    prompt = [
        "# Agent Review Prompt",
        "",
        "You are only reviewing anomalies, not the full exam.",
        "",
        "Inputs:",
        f"- Candidate round: `{candidate_round}/reconstructed_exam.md`",
        f"- Trusted reference: `{trusted_md}`",
        f"- Anomaly queue: `{output_dir / 'anomaly_queue.md'}`",
        "",
        "Task:",
        "1. Review only the listed anomalies.",
        "2. For each anomaly, decide: accept candidate, accept trusted reference, or require human image review.",
        "3. Do not rewrite the full exam.",
        "4. Output a patch plan for the next round.",
        "",
        "Priority anomalies:",
    ]
    for anomaly in result["anomalies"]:
        if anomaly["severity"] in {"critical", "warning"}:
            prompt.append(
                f"- {anomaly['code']} on Q{anomaly['question']}: {anomaly['detail']}"
            )
    (output_dir / "agent_review_prompt.md").write_text(
        "\n".join(prompt), encoding="utf-8"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a fast deterministic gate on an exam reconstruction round."
    )
    parser.add_argument(
        "--candidate-round",
        required=True,
        type=Path,
        help="Directory containing reconstructed_exam.md and contract JSON/Markdown files.",
    )
    parser.add_argument(
        "--trusted-md",
        required=True,
        type=Path,
        help="Trusted Markdown reconstruction used as a reference.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Directory for deterministic_checks.json, anomaly_queue.md, and agent prompt.",
    )
    parser.add_argument(
        "--expected-score",
        default=100,
        type=int,
        help="Expected total score in question_index.json.",
    )
    parser.add_argument(
        "--fail-on-critical",
        action="store_true",
        help="Exit with code 1 if any critical anomaly is emitted.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_gate(
        args.candidate_round,
        args.trusted_md,
        args.output_dir,
        expected_score=args.expected_score,
    )
    anomaly_count = len(result["anomalies"])
    elapsed_ms = result["metadata"]["elapsed_ms"]
    print(
        f"fast reconstruction gate complete: {elapsed_ms} ms, "
        f"anomalies={anomaly_count}, output={args.output_dir}"
    )
    if args.fail_on_critical and result["severity_counts"].get("critical", 0) > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
