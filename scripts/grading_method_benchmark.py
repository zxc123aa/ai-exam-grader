from __future__ import annotations

import base64
import json
import math
import statistics
import time
import uuid
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from sqlmodel import Session, select

from app.core.db import engine
from app.models import (
    ExamQuestion,
    ExamQuestionRegion,
    ExamRegion,
    StandardAnswer,
    StoredFile,
    StudentSubmission,
    SubmissionAnnotation,
)
from app.services.grading_rules import enforce_scoring_points
from app.services.submission_crops import (
    crop_region_png,
    resolve_exam_region_paper_page,
)
from app.services.vision_grading import (
    call_json_model_with_route,
    extract_answer_images,
    grade_answer_text,
)

EXAM_ID = uuid.UUID("86c57d4b-ce38-479a-8a73-5e836b3a15d3")
OUTPUT_DIR = (
    Path(__file__).resolve().parents[1] / "outputs" / "grading-method-benchmark-2026-07"
)
FONT_PATH = "/mnt/c/Windows/Fonts/msyh.ttc"
PROVIDER = "pomoai"
MODEL = "gpt-5.6-sol"
FALLBACKS = ["pomoai/gpt-5.5"]


@dataclass
class BenchmarkCase:
    case_id: str
    source: str
    question_key: str
    gold_score: float
    image_bytes_list: list[bytes]
    answer: StandardAnswer
    reference_ocr: str | None = None


def _wrap(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int
) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        current = ""
        for char in paragraph:
            candidate = current + char
            if current and draw.textlength(candidate, font=font) > width:
                lines.append(current)
                current = char
            else:
                current = candidate
        lines.append(current)
    return lines


def _render_answer_image(question: ExamQuestion, student_answer: str) -> bytes:
    title_font = ImageFont.truetype(FONT_PATH, 32)
    body_font = ImageFont.truetype(FONT_PATH, 25)
    answer_font = ImageFont.truetype(FONT_PATH, 31)
    scratch = Image.new("RGB", (1280, 200), "white")
    draw = ImageDraw.Draw(scratch)
    question_lines = _wrap(draw, question.question_text[:700], body_font, 1130)
    answer_lines = _wrap(draw, student_answer or "[空白]", answer_font, 1080)
    height = max(520, 260 + len(question_lines) * 39 + len(answer_lines) * 48)
    image = Image.new("RGB", (1280, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 25, 1250, height - 25), outline=(195, 195, 195), width=2)
    draw.text(
        (65, 55), f"第 {question.question_key} 题", fill=(20, 20, 20), font=title_font
    )
    y = 110
    for line in question_lines:
        draw.text((65, y), line, fill=(70, 70, 70), font=body_font)
        y += 39
    y += 20
    draw.line((65, y, 1215, y), fill=(215, 215, 215), width=2)
    y += 28
    draw.text((65, y), "学生作答：", fill=(40, 40, 40), font=body_font)
    y += 48
    for line in answer_lines:
        draw.text((105, y), line, fill=(22, 70, 155), font=answer_font)
        y += 48
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()


def _load_question_answer(
    session: Session, key: str
) -> tuple[ExamQuestion, StandardAnswer]:
    question = session.exec(
        select(ExamQuestion).where(
            ExamQuestion.exam_id == EXAM_ID,
            ExamQuestion.question_key == key,
        )
    ).one()
    answer = session.exec(
        select(StandardAnswer).where(StandardAnswer.question_id == question.id)
    ).one()
    return question, answer


def _synthetic_cases(session: Session) -> list[BenchmarkCase]:
    definitions = [
        ("q1-correct", "1", "选择第二项", 3),
        ("q1-wrong", "1", "选择第一项", 0),
        ("q10-full", "10", "选择第一项、第四项", 4),
        ("q10-partial", "10", "只选择第一项", 2),
        ("q10-wrong-extra", "10", "选择第一项、第二项", 0),
        (
            "q14-full",
            "14",
            "（1）①选择第一项；②向左。（2）①选择第二项；②能，因为体积等于横截面积乘气柱长度，横截面积不变。③压缩过快，气体未充分散热，温度升高，测得压强偏大。",
            10,
        ),
        (
            "q14-missing-last",
            "14",
            "（1）①选择第一项；②向左。（2）①选择第二项；②能，因为体积等于横截面积乘气柱长度，横截面积不变。③未作答。",
            8,
        ),
        (
            "q16-full",
            "16",
            "初态由活塞受力平衡得气体压强为1.1×10^5帕。第一问为等压变化，由高度与热力学温度成正比，得高度32.0厘米。第二问末态体积等于初态，状态方程得压强1.1733×10^5帕；再由活塞受力平衡，解得沙子质量4.4千克。",
            10,
        ),
        (
            "q16-first-part",
            "16",
            "初态由活塞受力平衡得气体压强为1.1×10^5帕。第一问为等压变化，由高度与热力学温度成正比，得高度32.0厘米。第二问未作答。",
            4,
        ),
    ]
    result: list[BenchmarkCase] = []
    for case_id, key, response, score in definitions:
        question, answer = _load_question_answer(session, key)
        result.append(
            BenchmarkCase(
                case_id=case_id,
                source="controlled",
                question_key=key,
                gold_score=float(score),
                image_bytes_list=[_render_answer_image(question, response)],
                answer=answer,
                reference_ocr=response,
            )
        )
    return result


def _real_cases(session: Session) -> list[BenchmarkCase]:
    rows = session.exec(
        select(SubmissionAnnotation, StudentSubmission, ExamRegion, StoredFile)
        .join(
            StudentSubmission,
            SubmissionAnnotation.submission_id == StudentSubmission.id,
        )
        .join(ExamRegion, SubmissionAnnotation.exam_region_id == ExamRegion.id)
        .join(StoredFile, StudentSubmission.stored_file_id == StoredFile.id)
        .where(
            StudentSubmission.exam_id == EXAM_ID,
            SubmissionAnnotation.score_source == "human",
            SubmissionAnnotation.label == "第14题",
        )
    ).all()
    result: list[BenchmarkCase] = []
    for annotation, submission, region, stored_file in rows:
        link = session.exec(
            select(ExamQuestionRegion).where(
                ExamQuestionRegion.exam_region_id == region.id
            )
        ).first()
        if not link:
            continue
        question = session.get(ExamQuestion, link.question_id)
        answer = session.exec(
            select(StandardAnswer).where(StandardAnswer.question_id == link.question_id)
        ).first()
        if not question or not answer or annotation.score is None:
            continue
        question_regions = list(
            session.exec(
                select(ExamRegion)
                .join(
                    ExamQuestionRegion,
                    ExamQuestionRegion.exam_region_id == ExamRegion.id,
                )
                .where(ExamQuestionRegion.question_id == question.id)
                .order_by(ExamQuestionRegion.sequence)
            ).all()
        )
        result.append(
            BenchmarkCase(
                case_id=f"real-q14-{submission.student_name}",
                source="real_scan",
                question_key=question.question_key,
                gold_score=float(annotation.score),
                image_bytes_list=[
                    crop_region_png(
                        stored_file=stored_file,
                        region=question_region,
                        page_number=resolve_exam_region_paper_page(
                            session, question_region
                        ),
                    )
                    for question_region in question_regions
                ],
                answer=answer,
                reference_ocr=annotation.ocr_text,
            )
        )
    return result


def _multimodal_grade(case: BenchmarkCase, *, ocr_text: str | None) -> dict[str, Any]:
    evidence_note = (
        f"识别文本仅作为辅助证据，必须对照图片核验：\n{ocr_text}"
        if ocr_text is not None
        else "没有提供识别文本，必须直接从图片读取学生作答。"
    )
    prompt = f"""你是严谨的中文试卷阅卷教师。图片包含印刷题目和学生作答，请区分二者，只评价学生作答。
{evidence_note}
标准答案：{case.answer.answer_text}
满分：{case.answer.max_score}
评分细则：{case.answer.rubric_text or "按评分点给分"}
评分点：{json.dumps(case.answer.scoring_points, ensure_ascii=False)}
逐个评分点核对后，只返回 JSON：{{"student_answer":"核验后的学生答案","score":0,"confidence":0.0,"comment":"中文理由","evidence":[{{"point":"评分点","matched":true,"points":0,"reason":"图片依据"}}]}}。
score 必须在0到满分之间；不得因为答案字迹工整或解析详细额外加分。"""
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for image_bytes in case.image_bytes_list:
        image = base64.b64encode(image_bytes).decode("ascii")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image}"},
            }
        )
    started = time.perf_counter()
    parsed, provider, model, elapsed_ms, usage = call_json_model_with_route(
        provider=PROVIDER,
        model=MODEL,
        fallback_models=FALLBACKS,
        messages=[
            {
                "role": "user",
                "content": content,
            }
        ],
    )
    evidence = (
        parsed.get("evidence") if isinstance(parsed.get("evidence"), list) else []
    )
    score = enforce_scoring_points(
        float(parsed.get("score") or 0), evidence, case.answer.max_score
    )
    return {
        "score": score,
        "confidence": float(parsed.get("confidence") or 0),
        "student_answer": str(parsed.get("student_answer") or ""),
        "comment": str(parsed.get("comment") or ""),
        "evidence": evidence,
        "provider": provider,
        "model": model,
        "elapsed_ms": elapsed_ms,
        "wall_ms": round((time.perf_counter() - started) * 1000),
        "usage": usage,
    }


def _text_grade(case: BenchmarkCase, ocr_text: str) -> dict[str, Any]:
    grade = grade_answer_text(
        student_answer=ocr_text,
        standard_answer=case.answer,
        provider=PROVIDER,
        model=MODEL,
        fallback_models=FALLBACKS,
    )
    return {
        "score": enforce_scoring_points(
            grade.score, grade.evidence, case.answer.max_score
        ),
        "confidence": grade.confidence,
        "student_answer": ocr_text,
        "comment": grade.comment,
        "evidence": grade.evidence,
        "provider": grade.provider,
        "model": grade.model,
        "elapsed_ms": grade.elapsed_ms,
    }


def _ocr(case: BenchmarkCase) -> tuple[str, dict[str, Any]]:
    if case.source == "real_scan" and case.reference_ocr is not None:
        return case.reference_ocr, {
            "source": "stored_confirmed_extraction",
            "elapsed_ms": 0,
        }
    extraction = extract_answer_images(
        image_bytes_list=case.image_bytes_list,
        provider="pomoai",
        model="gemini-3.5-flash",
        fallback_models=FALLBACKS,
        question_label=f"第{case.question_key}题",
    )
    return extraction.student_answer, {
        "source": "live_visual_extraction",
        "provider": extraction.provider,
        "model": extraction.model,
        "confidence": extraction.confidence,
        "elapsed_ms": extraction.elapsed_ms,
    }


def _metrics(rows: list[dict[str, Any]], method: str) -> dict[str, Any]:
    selected = [row for row in rows if row["method"] == method and row.get("ok")]
    errors = [abs(row["score"] - row["gold_score"]) for row in selected]
    return {
        "samples": len(selected),
        "exact": sum(math.isclose(error, 0, abs_tol=0.01) for error in errors),
        "within_one": sum(error <= 1.0 for error in errors),
        "mae": round(statistics.mean(errors), 3) if errors else None,
        "mean_elapsed_ms": round(statistics.mean(row["elapsed_ms"] for row in selected))
        if selected
        else None,
    }


def _with_retry(label: str, operation: Any) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                delay = 1.5 * attempt
                print(  # noqa: T201
                    f"  {label}: 第{attempt}次请求失败，{delay:g}s 后重试",
                    flush=True,
                )
                time.sleep(delay)
    assert last_error is not None
    raise last_error


def _write_report(rows: list[dict[str, Any]], cases: list[BenchmarkCase]) -> None:
    labels = {
        "ocr_then_text": "看图识别 → 文本判分（当前）",
        "image_only": "判题模型直接看图",
        "dual_evidence": "图片 + 识别文本联合判分",
    }
    metrics = {method: _metrics(rows, method) for method in labels}
    ranking = sorted(
        metrics, key=lambda method: (metrics[method]["mae"], -metrics[method]["exact"])
    )
    lines = [
        "# 批改证据方式基准测试",
        "",
        "## 测试口径",
        "",
        f"- 样本：{len(cases)} 个（9 个受控金标准 + 2 个真实扫描人工分）",
        "- 判题模型统一为 `pomoai / gpt-5.6-sol`，只改变模型看到的证据形式",
        "- 指标：精确命中数、误差不超过 1 分、平均绝对误差（MAE，越低越好）",
        "- 说明：这是小样本方法对比，不代表所有学科的绝对准确率",
        "",
        "## 总结果",
        "",
        "| 方法 | 精确命中 | ±1分内 | MAE | 平均判分耗时 |",
        "|---|---:|---:|---:|---:|",
    ]
    for method, label in labels.items():
        item = metrics[method]
        lines.append(
            f"| {label} | {item['exact']}/{item['samples']} | {item['within_one']}/{item['samples']} | {item['mae']:.3f} | {item['mean_elapsed_ms'] / 1000:.1f}s |"
        )
    lines.extend(
        [
            "",
            "## 逐样本",
            "",
            "| 样本 | 金标准 | 当前 | 直接看图 | 联合判分 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    by_case: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        by_case.setdefault(row["case_id"], {})[row["method"]] = row
    for case in cases:
        values = by_case.get(case.case_id, {})
        rendered = []
        for method in labels:
            row = values.get(method, {})
            rendered.append(str(row.get("score", "失败")))
        lines.append(
            f"| {case.case_id} ({case.source}) | {case.gold_score:g} | {rendered[0]} | {rendered[1]} | {rendered[2]} |"
        )
    winner = ranking[0]
    lines.extend(
        [
            "",
            "## 结论",
            "",
            f"本次小样本中，**{labels[winner]}** 的平均绝对误差最低。生产建议以该方法为主，仍保留低置信度和模型分歧进入人工复核。",
        ]
    )
    (OUTPUT_DIR / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with Session(engine) as session:
        cases = [*_synthetic_cases(session), *_real_cases(session)]
    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case.case_id}", flush=True)  # noqa: T201
        try:
            ocr_text, ocr_meta = _with_retry("ocr", lambda case=case: _ocr(case))
        except Exception as exc:
            ocr_text, ocr_meta = "", {"error": str(exc)}
        for method in ("ocr_then_text", "image_only", "dual_evidence"):
            try:
                if method == "ocr_then_text":
                    result = _with_retry(
                        method,
                        lambda case=case, ocr_text=ocr_text: _text_grade(
                            case, ocr_text
                        ),
                    )
                elif method == "image_only":
                    result = _with_retry(
                        method,
                        lambda case=case: _multimodal_grade(case, ocr_text=None),
                    )
                else:
                    result = _with_retry(
                        method,
                        lambda case=case, ocr_text=ocr_text: _multimodal_grade(
                            case, ocr_text=ocr_text
                        ),
                    )
                row = {
                    "case_id": case.case_id,
                    "source": case.source,
                    "question_key": case.question_key,
                    "gold_score": case.gold_score,
                    "method": method,
                    "ocr_text": ocr_text,
                    "ocr_meta": ocr_meta,
                    "ok": True,
                    **result,
                }
            except Exception as exc:
                row = {
                    "case_id": case.case_id,
                    "source": case.source,
                    "question_key": case.question_key,
                    "gold_score": case.gold_score,
                    "method": method,
                    "ocr_text": ocr_text,
                    "ocr_meta": ocr_meta,
                    "ok": False,
                    "error": str(exc),
                }
            rows.append(row)
            print(  # noqa: T201
                f"  {method}: {row.get('score', row.get('error'))}", flush=True
            )
        (OUTPUT_DIR / "raw.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    _write_report(rows, cases)
    print(OUTPUT_DIR / "report.md")  # noqa: T201


if __name__ == "__main__":
    main()
