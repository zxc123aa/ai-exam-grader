from __future__ import annotations

import argparse
import json
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import replace
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.core.db import engine
from app.models import (
    ExamQuestion,
    ExamQuestionRegion,
    ExamRegion,
    StandardAnswer,
    StoredFile,
    StudentSubmission,
)
from app.services.grading_workflow import (
    AdaptiveConcurrency,
    WorkPayload,
    WorkResult,
    _process_item,
    next_schedulable_payload_index,
)
from app.services.submission_crops import resolve_exam_region_paper_page
from app.services.system_config import get_grading_defaults

EXAM_ID = uuid.UUID("86c57d4b-ce38-479a-8a73-5e836b3a15d3")
QUESTION_KEYS = ("1", "9", "10")
OUTPUT_DIR = (
    Path(__file__).resolve().parents[1]
    / "outputs"
    / "grading-concurrency-benchmark-2026-07"
)


def _parse_configs(value: str) -> list[tuple[int, int]]:
    configs: list[tuple[int, int]] = []
    for item in value.split(","):
        papers, questions = item.strip().lower().split("x", 1)
        config = (int(papers), int(questions))
        if not all(1 <= part <= 8 for part in config):
            raise ValueError("并发参数必须在 1 到 8 之间")
        if config not in configs:
            configs.append(config)
    return configs


def _load_payloads(
    question_keys: tuple[str, ...] | None = None,
) -> tuple[list[WorkPayload], dict[str, Any]]:
    with Session(engine, expire_on_commit=False) as session:
        defaults = get_grading_defaults(session)
        submissions = list(
            session.exec(
                select(StudentSubmission).where(StudentSubmission.exam_id == EXAM_ID)
            ).all()
        )
        submissions.sort(key=lambda item: item.student_name)
        questions = list(
            session.exec(
                select(ExamQuestion).where(ExamQuestion.exam_id == EXAM_ID)
            ).all()
        )
        questions_by_key = {question.question_key: question for question in questions}
        regions_by_question: dict[uuid.UUID, tuple[ExamRegion, ...]] = {}
        answers: dict[uuid.UUID, StandardAnswer] = {}
        page_numbers: dict[uuid.UUID, int] = {}
        for question in questions:
            rows = list(
                session.exec(
                    select(ExamQuestionRegion, ExamRegion)
                    .join(
                        ExamRegion,
                        ExamQuestionRegion.exam_region_id == ExamRegion.id,
                    )
                    .where(ExamQuestionRegion.question_id == question.id)
                    .order_by(ExamQuestionRegion.sequence)
                ).all()
            )
            regions = tuple(region for _link, region in rows)
            regions_by_question[question.id] = regions
            for region in regions:
                page_numbers[region.id] = resolve_exam_region_paper_page(
                    session, region
                )
            answer = session.exec(
                select(StandardAnswer).where(StandardAnswer.question_id == question.id)
            ).one()
            answers[question.id] = answer

        payloads: list[WorkPayload] = []
        for submission_index, submission in enumerate(submissions):
            stored_file = session.get(StoredFile, submission.stored_file_id)
            if stored_file is None:
                continue
            keys = question_keys or (
                *QUESTION_KEYS,
                "14" if submission_index % 2 == 0 else "16",
            )
            for key in keys:
                question = questions_by_key[key]
                regions = regions_by_question[question.id]
                payloads.append(
                    WorkPayload(
                        item_id=uuid.uuid4(),
                        submission=submission,
                        stored_file=stored_file,
                        region=regions[0],
                        regions=regions,
                        answer=answers[question.id],
                        vision_provider=str(defaults["vision_provider"]),
                        vision_model=str(defaults["vision_model"]),
                        grading_provider=str(defaults["grading_provider"]),
                        grading_model=str(defaults["grading_model"]),
                        fallback_models=[
                            str(item) for item in defaults.get("fallback_models", [])
                        ],
                        attempt=1,
                        page_numbers=page_numbers,
                    )
                )
    return payloads, defaults


def _result_row(result: WorkResult) -> dict[str, Any]:
    extraction = result.extraction or {}
    grading = result.grading or {}
    return {
        "student": result.payload.submission.student_name,
        "question": result.payload.region.label,
        "attempts": result.payload.attempt,
        "objective": result.objective,
        "error": result.error,
        "transient": result.transient,
        "extraction_ms": int(extraction.get("elapsed_ms") or 0),
        "grading_ms": int(grading.get("elapsed_ms") or 0),
        "vision_route": f"{extraction.get('provider', '')}/{extraction.get('model', '')}",
        "grading_route": f"{grading.get('provider', '')}/{grading.get('model', '')}",
    }


def _run_config(
    source_payloads: list[WorkPayload], papers: int, questions: int
) -> dict[str, Any]:
    pending = [
        replace(payload, item_id=uuid.uuid4(), attempt=1) for payload in source_payloads
    ]
    active: dict[Future[WorkResult], WorkPayload] = {}
    completed: list[dict[str, Any]] = []
    maximum = min(32, papers * questions)
    adaptive = AdaptiveConcurrency(maximum)
    peak_active = 0
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=maximum) as pool:
        while pending or active:
            while len(active) < adaptive.current:
                index = next_schedulable_payload_index(
                    pending,
                    active.values(),
                    max_parallel_submissions=papers,
                    max_concurrency_per_submission=questions,
                )
                if index is None:
                    break
                payload = pending.pop(index)
                active[pool.submit(_process_item, payload)] = payload
                peak_active = max(peak_active, len(active))
            if not active:
                raise RuntimeError("调度器无法继续分配任务")
            done, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in done:
                payload = active.pop(future)
                result = future.result()
                adaptive.record(
                    transient=result.transient, failed=result.error is not None
                )
                if result.error and result.transient and payload.attempt < 3:
                    pending.append(replace(payload, attempt=payload.attempt + 1))
                else:
                    completed.append(_result_row(result))
    wall_seconds = time.perf_counter() - started
    failures = sum(bool(item["error"]) for item in completed)
    retries = sum(max(0, int(item["attempts"]) - 1) for item in completed)
    throughput = len(completed) / wall_seconds
    return {
        "parallel_submissions": papers,
        "questions_per_submission": questions,
        "configured_total": maximum,
        "peak_active": peak_active,
        "final_adaptive_concurrency": adaptive.current,
        "throttle_count": adaptive.throttle_count,
        "tasks": len(completed),
        "failures": failures,
        "retries": retries,
        "wall_seconds": round(wall_seconds, 3),
        "items_per_second": round(throughput, 4),
        "estimated_8x18_seconds": round(144 / throughput, 1),
        "objective_items": sum(bool(item["objective"]) for item in completed),
        "details": completed,
    }


def _write_report(results: list[dict[str, Any]], defaults: dict[str, Any]) -> None:
    valid = [result for result in results if result["failures"] == 0]
    winner = min(valid, key=lambda result: result["wall_seconds"]) if valid else None
    lines = [
        "# 批改并发基准测试",
        "",
        "## 测试口径",
        "",
        "- 使用演示考试的 8 份真实扫描卷。",
        "- 每份抽取 3 道客观题和 1 道主观题，共 32 个任务；比例接近整卷 13:5。",
        "- 完整执行生产链路：题区裁切 → 看图识别 → 客观题规则/主观题模型判分。",
        f"- 答题识别：`{defaults['vision_provider']} / {defaults['vision_model']}`。",
        f"- 主观题判分：`{defaults['grading_provider']} / {defaults['grading_model']}`。",
        "- 整卷预计耗时按实测吞吐量线性换算到 8×18=144 个任务，仅用于同机同服务下比较。",
        "",
        "## 结果",
        "",
        "| 同时批卷 | 每卷题目并发 | 总并发 | 实测32题 | 预计8份整卷 | 重试/失败 | 降速次数 |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        lines.append(
            "| {parallel_submissions} | {questions_per_submission} | "
            "{configured_total} | {wall_seconds:.1f}s | "
            "{estimated_8x18_seconds:.1f}s | {retries}/{failures} | "
            "{throttle_count} |".format(**result)
        )
    lines.extend(["", "## 结论", ""])
    if winner:
        lines.append(
            "本次实测最快且无失败的配置是：同时批改 "
            f"**{winner['parallel_submissions']}** 份，每份最高并发 "
            f"**{winner['questions_per_submission']}** 题。"
        )
    else:
        lines.append("所有配置均出现最终失败，暂不能确定可用的最快配置。")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--configs",
        default="2x4,4x4,8x4,1x4,4x2,8x1",
        help="逗号分隔：同时批卷数x每卷题目并发",
    )
    args = parser.parse_args()
    configs = _parse_configs(args.configs)
    payloads, defaults = _load_payloads()
    print(f"已加载 {len(payloads)} 个真实批改任务", flush=True)  # noqa: T201
    results: list[dict[str, Any]] = []
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for index, (papers, questions) in enumerate(configs, start=1):
        print(  # noqa: T201
            f"[{index}/{len(configs)}] 同时批卷={papers}，每卷并发={questions}",
            flush=True,
        )
        result = _run_config(payloads, papers, questions)
        results.append(result)
        print(  # noqa: T201
            f"  {result['wall_seconds']:.1f}s，重试={result['retries']}，失败={result['failures']}，降速={result['throttle_count']}",
            flush=True,
        )
        (OUTPUT_DIR / "raw.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _write_report(results, defaults)


if __name__ == "__main__":
    main()
