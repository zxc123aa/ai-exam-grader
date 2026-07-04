from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

from app.services.question_segmentation import (  # noqa: E402
    ENGINE_NAME,
    CandidateBox,
    find_layout_candidate_boxes,
)


@dataclass(frozen=True)
class SampleSpec:
    sample_id: str
    path: Path
    source: str
    expected_min: int
    expected_max: int
    notes: str


@dataclass(frozen=True)
class CandidateSummary:
    label: str
    x: int
    y: int
    width: int
    height: int
    area_ratio: float
    confidence: float


@dataclass(frozen=True)
class EvaluationResult:
    sample_id: str
    path: str
    source: str
    image_width: int
    image_height: int
    expected_range: str
    candidate_count: int
    max_area_ratio: float
    total_area_ratio: float
    status: str
    warnings: list[str]
    notes: str
    overlay_path: str
    candidates: list[CandidateSummary]


def sample_specs(root_dir: Path) -> list[SampleSpec]:
    return [
        SampleSpec(
            sample_id="english_test1_left",
            path=root_dir / "materials/English/processed/test1/page_1_left.jpg",
            source="materials/English/test1.jpg page 1",
            expected_min=4,
            expected_max=12,
            notes="English exam page with multiple sections; should not become one whole-page box.",
        ),
        SampleSpec(
            sample_id="english_test1_right",
            path=root_dir / "materials/English/processed/test1/page_2_right.jpg",
            source="materials/English/test1.jpg page 2",
            expected_min=4,
            expected_max=12,
            notes="English exam page with multiple sections and dense text.",
        ),
        SampleSpec(
            sample_id="english_writing",
            path=root_dir / "materials/English/processed/writing_service_v3/page_1.jpg",
            source="materials/English/writing.jpg",
            expected_min=1,
            expected_max=4,
            notes="Writing page can validly produce a small number of large writing regions.",
        ),
        SampleSpec(
            sample_id="physics_p1_left",
            path=root_dir / "materials/physics/processed/1/page_1_left.jpg",
            source="materials/physics/1.jpg page 1",
            expected_min=4,
            expected_max=10,
            notes="Physics page 1, choice questions and diagrams.",
        ),
        SampleSpec(
            sample_id="physics_p1_right",
            path=root_dir / "materials/physics/processed/1/page_2_right.jpg",
            source="materials/physics/1.jpg page 2",
            expected_min=4,
            expected_max=10,
            notes="Physics page 2, choice/fill-in questions.",
        ),
        SampleSpec(
            sample_id="physics_p2_left",
            path=root_dir / "materials/physics/processed/2/page_1_left.jpg",
            source="materials/physics/2.jpg page 3",
            expected_min=3,
            expected_max=6,
            notes="Physics page 3, questions 18-20.",
        ),
        SampleSpec(
            sample_id="physics_p2_right",
            path=root_dir / "materials/physics/processed/2/page_2_right.jpg",
            source="materials/physics/2.jpg page 4",
            expected_min=2,
            expected_max=5,
            notes="Physics page 4, questions 21-22.",
        ),
    ]


def summarize_candidates(
    boxes: list[CandidateBox], *, image_width: int, image_height: int
) -> list[CandidateSummary]:
    page_area = max(1, image_width * image_height)
    return [
        CandidateSummary(
            label=f"Q{index}",
            x=box.x,
            y=box.y,
            width=box.width,
            height=box.height,
            area_ratio=round((box.width * box.height) / page_area, 4),
            confidence=round(box.confidence, 4),
        )
        for index, box in enumerate(boxes, start=1)
    ]


def assess_result(
    *, spec: SampleSpec, candidate_count: int, max_area_ratio: float
) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if candidate_count == 0:
        warnings.append("no_candidates")
    if candidate_count < spec.expected_min:
        warnings.append("too_few_candidates")
    if candidate_count > spec.expected_max:
        warnings.append("too_many_candidates")
    if max_area_ratio >= 0.45:
        warnings.append("large_candidate")
    if candidate_count == 1 and max_area_ratio >= 0.55:
        warnings.append("dominant_whole_page_candidate")

    severe = {"no_candidates", "dominant_whole_page_candidate"}
    if severe.intersection(warnings):
        return "fail", warnings
    if warnings:
        return "review", warnings
    return "pass", warnings


def draw_overlay(
    image, candidates: list[CandidateSummary], *, output_path: Path
) -> str:
    overlay = image.copy()
    colors = [(0, 191, 255), (0, 128, 255), (0, 200, 80), (255, 160, 0)]
    for index, candidate in enumerate(candidates):
        color = colors[index % len(colors)]
        left = candidate.x
        top = candidate.y
        right = candidate.x + candidate.width
        bottom = candidate.y + candidate.height
        cv2.rectangle(overlay, (left, top), (right, bottom), color, 3)
        label = f"{candidate.label} {candidate.area_ratio:.2f}"
        cv2.rectangle(overlay, (left, max(0, top - 28)), (left + 120, top), color, -1)
        cv2.putText(
            overlay,
            label,
            (left + 6, max(18, top - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), overlay)
    return str(output_path.relative_to(ROOT_DIR))


def evaluate_sample(spec: SampleSpec, *, output_dir: Path) -> EvaluationResult:
    image = cv2.imread(str(spec.path))
    if image is None:
        return EvaluationResult(
            sample_id=spec.sample_id,
            path=str(spec.path.relative_to(ROOT_DIR)),
            source=spec.source,
            image_width=0,
            image_height=0,
            expected_range=f"{spec.expected_min}-{spec.expected_max}",
            candidate_count=0,
            max_area_ratio=0.0,
            total_area_ratio=0.0,
            status="missing",
            warnings=["missing_sample"],
            notes=spec.notes,
            overlay_path="",
            candidates=[],
        )

    boxes = find_layout_candidate_boxes(image)
    image_height, image_width = image.shape[:2]
    candidates = summarize_candidates(
        boxes, image_width=image_width, image_height=image_height
    )
    max_area_ratio = max((item.area_ratio for item in candidates), default=0.0)
    total_area_ratio = round(sum(item.area_ratio for item in candidates), 4)
    status, warnings = assess_result(
        spec=spec,
        candidate_count=len(candidates),
        max_area_ratio=max_area_ratio,
    )
    overlay_path = draw_overlay(
        image,
        candidates,
        output_path=output_dir / "overlays" / f"{spec.sample_id}.jpg",
    )
    return EvaluationResult(
        sample_id=spec.sample_id,
        path=str(spec.path.relative_to(ROOT_DIR)),
        source=spec.source,
        image_width=image_width,
        image_height=image_height,
        expected_range=f"{spec.expected_min}-{spec.expected_max}",
        candidate_count=len(candidates),
        max_area_ratio=round(max_area_ratio, 4),
        total_area_ratio=total_area_ratio,
        status=status,
        warnings=warnings,
        notes=spec.notes,
        overlay_path=overlay_path,
        candidates=candidates,
    )


def write_report(results: list[EvaluationResult], *, report_path: Path) -> None:
    total = len(results)
    failed = sum(1 for item in results if item.status == "fail")
    review = sum(1 for item in results if item.status == "review")
    passed = sum(1 for item in results if item.status == "pass")

    lines = [
        "# Question Segmentation Evaluation",
        "",
        "更新时间：2026-07-05",
        "",
        "## 目标",
        "",
        "评估当前 `layout_projection_v0` 题目区域候选分割在真实试卷页上的表现。该评估只针对候选框质量，不代表 OCR 或判分能力。",
        "",
        "## 执行命令",
        "",
        "```bash",
        "PYTHONPATH=backend python3 scripts/evaluate_question_segmentation.py",
        "```",
        "",
        "本地 overlay 和 JSON 生成在被 `.gitignore` 忽略的目录：",
        "",
        "```text",
        "materials/question-segmentation/evaluation/",
        "```",
        "",
        "## 结果摘要",
        "",
        f"- 样本数：`{total}`",
        f"- pass：`{passed}`",
        f"- review：`{review}`",
        f"- fail：`{failed}`",
        f"- engine：`{ENGINE_NAME}`",
        "",
        "| 样本 | 来源 | 期望数量 | 候选数量 | 最大面积占比 | 状态 | warnings |",
        "| --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for result in results:
        warnings = ", ".join(result.warnings) if result.warnings else "-"
        lines.append(
            "| "
            f"`{result.sample_id}` | `{result.source}` | {result.expected_range} | "
            f"{result.candidate_count} | {result.max_area_ratio:.3f} | "
            f"{result.status} | {warnings} |"
        )

    lines.extend(
        [
            "",
            "## 判断",
            "",
            "- 当前 `layout_projection_v0` 只能作为“候选草稿入口”的技术骨架，不能称为准确题目分割。",
            "- 英语和物理真实页多数出现 `dominant_whole_page_candidate`：算法把整页或大半页合并成一个候选框。",
            "- 写作页这类大块答题区更接近当前算法能力边界，但普通多题页面不满足自动切题要求。",
            "- 标定页保留教师确认是必要的；不能把当前候选结果自动写入正式 `ExamRegion`。",
            "",
            "## 失败模式",
            "",
            "- 版面投影和横向膨胀会把密集题干、图示、答题线连接成一个大连通块。",
            "- 没有 OCR layout、题号 anchor 或栏/题间分隔线建模，因此无法稳定判断题目边界。",
            "- 物理图示和英语长段落会进一步放大合并问题。",
            "",
            "## 下一步方案",
            "",
            "1. 保留 `layout_projection_v0` 作为 fallback，不再继续堆特例补丁。",
            "2. 新增 `layout_ocr_anchor_v1`：用 OCR 文本框和题号 anchor 生成题目边界候选。",
            "3. 若 OCR anchor 仍不稳，再进入页面区域分割模型路线，标注题区 polygon/box 样本。",
            "4. 前端继续维持“候选草稿 -> 教师确认 -> 正式题区”的闭环。",
            "",
            "## 明细",
            "",
        ]
    )
    for result in results:
        lines.extend(
            [
                f"### {result.sample_id}",
                "",
                f"- 文件：`{result.path}`",
                f"- 尺寸：`{result.image_width}x{result.image_height}`",
                f"- overlay：`{result.overlay_path}`",
                f"- 备注：{result.notes}",
                "",
                "| 候选 | x | y | w | h | area | confidence |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        if not result.candidates:
            lines.append("| - | - | - | - | - | - | - |")
        for candidate in result.candidates:
            lines.append(
                f"| {candidate.label} | {candidate.x} | {candidate.y} | "
                f"{candidate.width} | {candidate.height} | "
                f"{candidate.area_ratio:.4f} | {candidate.confidence:.4f} |"
            )
        lines.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT_DIR / "materials" / "question-segmentation" / "evaluation",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT_DIR / "docs" / "question-segmentation-evaluation.md",
    )
    parser.add_argument(
        "--fail-on-fail",
        action="store_true",
        help="Exit with status 1 when at least one sample is marked fail.",
    )
    args = parser.parse_args()

    results = [
        evaluate_sample(spec, output_dir=args.output_dir)
        for spec in sample_specs(ROOT_DIR)
    ]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(
        json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_report(results, report_path=args.report)

    failed = sum(1 for item in results if item.status == "fail")
    review = sum(1 for item in results if item.status == "review")
    passed = sum(1 for item in results if item.status == "pass")
    logger.info(
        f"Question segmentation evaluation: {passed} pass, {review} review, {failed} fail"
    )
    logger.info("Report: %s", args.report.relative_to(ROOT_DIR))
    logger.info("Artifacts: %s", args.output_dir.relative_to(ROOT_DIR))
    return 1 if args.fail_on_fail and failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
