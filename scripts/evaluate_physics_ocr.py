from __future__ import annotations

import argparse
import base64
import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import httpx
import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImageSample:
    sample_id: str
    kind: str
    path: Path
    source: str
    notes: str


@dataclass(frozen=True)
class OcrResult:
    sample_id: str
    engine: str
    status: str
    elapsed_seconds: float
    text: str | None
    confidence: float | None = None
    usage: dict[str, Any] | None = None
    error: str | None = None


def read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    config: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        config[key.strip()] = value.strip()
    return config


def four_point_transform(image: np.ndarray, points: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    summed = points.sum(axis=1)
    diff = np.diff(points, axis=1)
    rect[0] = points[np.argmin(summed)]
    rect[2] = points[np.argmax(summed)]
    rect[1] = points[np.argmin(diff)]
    rect[3] = points[np.argmax(diff)]

    top_left, top_right, bottom_right, bottom_left = rect
    width_a = np.linalg.norm(bottom_right - bottom_left)
    width_b = np.linalg.norm(top_right - top_left)
    height_a = np.linalg.norm(top_right - bottom_right)
    height_b = np.linalg.norm(top_left - bottom_left)
    max_width = int(max(width_a, width_b))
    max_height = int(max(height_a, height_b))
    destination = np.array(
        [
            [0, 0],
            [max_width - 1, 0],
            [max_width - 1, max_height - 1],
            [0, max_height - 1],
        ],
        dtype="float32",
    )
    matrix = cv2.getPerspectiveTransform(rect, destination)
    return cv2.warpPerspective(image, matrix, (max_width, max_height))


def write_image(path: Path, image: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), image)
    return path


def crop_fraction(image: np.ndarray, box: tuple[float, float, float, float]) -> np.ndarray:
    height, width = image.shape[:2]
    x, y, w, h = box
    left = max(0, min(width - 1, int(width * x)))
    top = max(0, min(height - 1, int(height * y)))
    right = max(left + 1, min(width, int(width * (x + w))))
    bottom = max(top + 1, min(height, int(height * (y + h))))
    return image[top:bottom, left:right]


def build_samples(materials_dir: Path, output_dir: Path) -> list[ImageSample]:
    pages_dir = output_dir / "pages"
    crops_dir = output_dir / "crops"
    samples: list[ImageSample] = []

    raw_1 = cv2.imread(str(materials_dir / "1.jpg"))
    raw_2 = cv2.imread(str(materials_dir / "2.jpg"))
    if raw_1 is None or raw_2 is None:
        raise RuntimeError("Could not read materials/physics/1.jpg or 2.jpg")

    processed_1_dir = materials_dir / "processed" / "1"
    processed_1_left = cv2.imread(str(processed_1_dir / "page_1_left.jpg"))
    processed_1_right = cv2.imread(str(processed_1_dir / "page_2_right.jpg"))
    p1_right_sample_id = "p1_right_auto"
    if processed_1_left is not None and processed_1_right is not None:
        p1_left = write_image(pages_dir / "p1_left_auto.jpg", processed_1_left)
        samples.append(
            ImageSample(
                sample_id="p1_left_auto",
                kind="page",
                path=p1_left,
                source="materials/physics/1.jpg",
                notes="current scan preprocessing output; expected page 1",
            )
        )
        p1_right = write_image(pages_dir / "p1_right_auto.jpg", processed_1_right)
        samples.append(
            ImageSample(
                sample_id="p1_right_auto",
                kind="page",
                path=p1_right,
                source="materials/physics/1.jpg",
                notes="current scan preprocessing output; expected page 2",
            )
        )
    else:
        auto_page_1 = cv2.imread(str(processed_1_dir / "page_1.jpg"))
        if auto_page_1 is None:
            auto_page_1 = four_point_transform(
                raw_1,
                np.array(
                    [[40, 1216], [918, 1256], [967, 167], [90, 127]],
                    dtype="float32",
                ),
            )
        p1_left = write_image(pages_dir / "p1_left_auto.jpg", auto_page_1)
        samples.append(
            ImageSample(
                sample_id="p1_left_auto",
                kind="page",
                path=p1_left,
                source="materials/physics/1.jpg",
                notes="legacy scan preprocessing output; expected page 1",
            )
        )

        p1_right_image = four_point_transform(
            raw_1,
            np.array(
                [[945, 128], [1584, 174], [1588, 1214], [922, 1198]],
                dtype="float32",
            ),
        )
        p1_right = write_image(pages_dir / "p1_right_manual.jpg", p1_right_image)
        p1_right_sample_id = "p1_right_manual"
        samples.append(
            ImageSample(
                sample_id="p1_right_manual",
                kind="page",
                path=p1_right,
                source="materials/physics/1.jpg",
                notes="manual right-page crop because legacy preprocessing misses this page",
            )
        )

    for sample_id, name, source_page in [
        ("p2_left_auto", "page_1_left.jpg", "materials/physics/2.jpg"),
        ("p2_right_auto", "page_2_right.jpg", "materials/physics/2.jpg"),
    ]:
        page_image = cv2.imread(str(materials_dir / "processed" / "2" / name))
        if page_image is None:
            continue
        page_path = write_image(pages_dir / f"{sample_id}.jpg", page_image)
        samples.append(
            ImageSample(
                sample_id=sample_id,
                kind="page",
                path=page_path,
                source=source_page,
                notes="current scan preprocessing output",
            )
        )

    page_images = {sample.sample_id: cv2.imread(str(sample.path)) for sample in samples}
    crop_specs = [
        ("p1_header", "p1_left_auto", (0.18, 0.02, 0.64, 0.16), "title/header"),
        ("p1_q1_q2", "p1_left_auto", (0.05, 0.17, 0.9, 0.18), "choice questions 1-2"),
        ("p1_q3_q4_diagrams", "p1_left_auto", (0.04, 0.28, 0.9, 0.24), "force diagrams and choice text"),
        ("p1_q5_q6_figures", "p1_left_auto", (0.04, 0.55, 0.9, 0.36), "photo/cartoon figure options"),
        (
            "p2_q7_q10",
            p1_right_sample_id,
            (0.04, 0.02, 0.92, 0.45),
            "right-page choice questions with diagrams",
        ),
        ("p2_q11_q16", p1_right_sample_id, (0.04, 0.42, 0.92, 0.5), "fill-in-the-blank questions"),
        ("p3_q18", "p2_left_auto", (0.06, 0.00, 0.88, 0.23), "drawing question"),
        ("p3_q19", "p2_left_auto", (0.05, 0.21, 0.9, 0.42), "experiment question with diagrams"),
        ("p3_q20", "p2_left_auto", (0.04, 0.62, 0.9, 0.34), "lever experiment question"),
        ("p4_q21", "p2_right_auto", (0.04, 0.00, 0.9, 0.35), "calculation question"),
        ("p4_q22", "p2_right_auto", (0.04, 0.36, 0.9, 0.45), "application question"),
    ]
    for sample_id, page_id, box, notes in crop_specs:
        page_image = page_images.get(page_id)
        if page_image is None:
            continue
        crop = crop_fraction(page_image, box)
        crop_path = write_image(crops_dir / f"{sample_id}.jpg", crop)
        samples.append(
            ImageSample(
                sample_id=sample_id,
                kind="region",
                path=crop_path,
                source=page_id,
                notes=notes,
            )
        )
    return samples


def call_paddle(sample: ImageSample, paddle_url: str, timeout: float) -> OcrResult:
    start = time.time()
    try:
        with httpx.Client(timeout=timeout) as client:
            with sample.path.open("rb") as image_file:
                response = client.post(
                    paddle_url,
                    files={"file": (sample.path.name, image_file, "image/jpeg")},
                )
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return OcrResult(
            sample_id=sample.sample_id,
            engine="paddleocr-gpu-cu130",
            status="failed",
            elapsed_seconds=round(time.time() - start, 2),
            text=None,
            error=str(exc),
        )
    return OcrResult(
        sample_id=sample.sample_id,
        engine=str(payload.get("engine") or "paddleocr-gpu-cu130"),
        status=str(payload.get("status") or "succeeded"),
        elapsed_seconds=round(time.time() - start, 2),
        text=payload.get("text"),
        confidence=payload.get("confidence"),
        usage=payload.get("raw"),
    )


def call_kimi(
    sample: ImageSample,
    config: dict[str, str],
    timeout: float,
    max_tokens: int,
) -> OcrResult:
    start = time.time()
    api_key = config.get("KIMI_API_KEY")
    if not api_key or api_key == "replace_me":
        return OcrResult(
            sample_id=sample.sample_id,
            engine="kimi",
            status="not_configured",
            elapsed_seconds=0.0,
            text=None,
            error="KIMI_API_KEY is not configured",
        )
    base_url = config.get("KIMI_BASE_URL", "https://api.moonshot.cn/v1").rstrip("/")
    model = config.get("KIMI_MODEL", "kimi-k2.7-code")
    image_b64 = base64.b64encode(sample.path.read_bytes()).decode("ascii")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "请尽可能准确地识别这张物理试卷图片中的文字。"
                            "保留题号、选项、公式、单位和图示标签。"
                            "只输出识别文本，不要解释。"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_b64}",
                        },
                    },
                ],
            }
        ],
        "temperature": 1,
        "max_tokens": max_tokens,
    }
    try:
        # trust_env=False avoids the local WSL proxy that breaks TLS CONNECT.
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            response = client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        return OcrResult(
            sample_id=sample.sample_id,
            engine=model,
            status="failed",
            elapsed_seconds=round(time.time() - start, 2),
            text=None,
            error=str(exc),
        )
    return OcrResult(
        sample_id=sample.sample_id,
        engine=model,
        status="succeeded",
        elapsed_seconds=round(time.time() - start, 2),
        text=data.get("choices", [{}])[0].get("message", {}).get("content"),
        usage=data.get("usage"),
    )


def text_preview(text: str | None, limit: int = 220) -> str:
    if not text:
        return ""
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[:limit] + "..."


def write_report(
    output_path: Path,
    samples: list[ImageSample],
    results: list[OcrResult],
    preprocess_notes: list[str],
) -> None:
    by_sample: dict[str, list[OcrResult]] = {}
    for result in results:
        by_sample.setdefault(result.sample_id, []).append(result)

    lines = [
        "# Physics OCR Evaluation Report",
        "",
        "## Scan Preprocessing",
        "",
        *[f"- {note}" for note in preprocess_notes],
        "",
        "## OCR Result Summary",
        "",
        "| Sample | Kind | Engine | Status | Confidence / Usage | Time | Preview |",
        "|---|---|---|---|---|---:|---|",
    ]
    sample_by_id = {sample.sample_id: sample for sample in samples}
    for sample in samples:
        for result in by_sample.get(sample.sample_id, []):
            confidence = (
                f"{result.confidence:.3f}"
                if isinstance(result.confidence, int | float)
                else ""
            )
            if result.usage:
                confidence = confidence or json.dumps(result.usage, ensure_ascii=False)
            preview = text_preview(result.text).replace("|", "\\|")
            lines.append(
                "| "
                + " | ".join(
                    [
                        result.sample_id,
                        sample_by_id[result.sample_id].kind,
                        result.engine,
                        result.status,
                        confidence,
                        f"{result.elapsed_seconds:.2f}s",
                        preview,
                    ]
                )
                + " |"
            )

    lines.extend(
        [
            "",
            "## Findings",
            "",
            "- `materials/physics/1.jpg` exposes a scan preprocessing failure: the current contour detector captures only the left page and misses the right page.",
            "- `materials/physics/2.jpg` is split into two usable pages, but the right page remains low contrast and shadowed.",
            "- PaddleOCR should be treated as the fast baseline for printed text; Kimi should be treated as the slower fallback for layout restoration and difficult physics regions.",
            "",
            "## Sample Files",
            "",
        ]
    )
    for sample in samples:
        rel_path = sample.path.relative_to(ROOT_DIR)
        lines.append(f"- `{sample.sample_id}`: `{rel_path}` ({sample.notes})")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--materials-dir", type=Path, default=ROOT_DIR / "materials" / "physics")
    parser.add_argument("--output-dir", type=Path, default=ROOT_DIR / "materials" / "physics" / "evaluation")
    parser.add_argument("--paddle-url", default="http://localhost:8010/ocr")
    parser.add_argument("--kimi-env", type=Path, default=ROOT_DIR / ".secrets" / "kimi.env")
    parser.add_argument("--skip-kimi", action="store_true")
    parser.add_argument(
        "--kimi-samples",
        default=None,
        help="Comma-separated sample ids to send to Kimi. Defaults to all samples.",
    )
    parser.add_argument("--kimi-max-tokens", type=int, default=1200)
    args = parser.parse_args()

    samples = build_samples(args.materials_dir, args.output_dir)
    config = read_env_file(args.kimi_env)
    results: list[OcrResult] = []
    kimi_sample_ids = (
        {sample_id.strip() for sample_id in args.kimi_samples.split(",") if sample_id.strip()}
        if args.kimi_samples
        else None
    )
    for sample in samples:
        logger.info("paddle %s", sample.sample_id)
        results.append(call_paddle(sample, args.paddle_url, timeout=180))
        should_call_kimi = not args.skip_kimi and (
            kimi_sample_ids is None or sample.sample_id in kimi_sample_ids
        )
        if should_call_kimi:
            logger.info("kimi %s", sample.sample_id)
            results.append(
                call_kimi(
                    sample,
                    config=config,
                    timeout=180,
                    max_tokens=args.kimi_max_tokens,
                )
            )

    preprocess_notes = [
        "1.jpg current preprocessing output: single_page, captures only left page; right page requires fallback/manual crop.",
        "2.jpg current preprocessing output: detected_gutter, splits into left/right pages.",
    ]
    payload = {
        "samples": [
            {**asdict(sample), "path": str(sample.path.relative_to(ROOT_DIR))}
            for sample in samples
        ],
        "results": [asdict(result) for result in results],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_report(args.output_dir / "report.md", samples, results, preprocess_notes)
    logger.info("wrote %s", args.output_dir / "results.json")
    logger.info("wrote %s", args.output_dir / "report.md")


if __name__ == "__main__":
    main()
