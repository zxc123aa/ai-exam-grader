#!/usr/bin/env python3
"""Generate and seed a deterministic 50-submission physics dataset."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import random
import shutil
import sys
import textwrap
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageEnhance, ImageFilter, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_ROOT = ROOT / "参考算法" / "2_试卷分析文件"
SOURCE_DIR = REFERENCE_ROOT / "material"
OUTPUT_DIR = ROOT / "data" / "synthetic" / "physics-2021-2022"
REFERENCE_ENV = REFERENCE_ROOT / ".env"
ROOT_ENV = ROOT / ".env"
EXAM_TITLE = "2021-2022 海口市八年级物理期末检测题（B卷）· 合成数据"
SEED = 20220713

STUDENT_NAMES = [
    "陈晨", "林浩", "王悦", "李明", "张欣", "刘洋", "黄思雨", "周子涵", "吴昊",
    "徐嘉怡", "孙宇轩", "胡静", "朱文博", "高雅", "郭子豪", "何雨桐", "罗俊杰",
    "郑可欣", "梁博文", "谢语嫣", "宋嘉豪", "唐诗琪", "许明哲", "邓佳宁", "韩睿",
    "冯雨欣", "曹宇航", "彭思涵", "曾俊熙", "萧雅婷", "田浩然", "董梦琪",
    "袁嘉乐", "潘欣怡", "于子墨", "蒋依诺", "蔡承泽", "余安琪", "杜铭轩",
    "叶梓萱", "程皓", "苏语彤", "魏博", "吕佳琪", "丁泽宇", "沈心怡",
    "任天佑", "姚若曦", "卢嘉诚", "钟晓彤",
]


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def json_from_text(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if "```" in cleaned:
        parts = cleaned.split("```")
        cleaned = next((part for part in parts if "{" in part and "}" in part), cleaned)
        if cleaned.lstrip().startswith("json"):
            cleaned = cleaned.lstrip()[4:].lstrip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Fable 5 did not return a JSON object")
    return json.loads(cleaned[start : end + 1])


def image_jpeg_bytes(image: Image.Image, quality: int = 88) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def normalize_source_pages() -> list[Image.Image]:
    first = ImageOps.exif_transpose(Image.open(SOURCE_DIR / "1.jpg")).convert("RGB")
    second = ImageOps.exif_transpose(Image.open(SOURCE_DIR / "2.jpg")).convert("RGB")
    first = first.rotate(90, expand=True, fillcolor="white")
    spreads = [first, second]
    pages: list[Image.Image] = []
    for spread in spreads:
        width, height = spread.size
        center = width // 2
        overlap = max(10, int(width * 0.012))
        pages.extend(
            [
                spread.crop((0, 0, min(width, center + overlap), height)),
                spread.crop((max(0, center - overlap), 0, width, height)),
            ]
        )
    return pages


def save_pdf(pages: list[Image.Image], path: Path) -> None:
    prepared = [page.convert("RGB") for page in pages]
    prepared[0].save(
        path,
        format="PDF",
        save_all=True,
        append_images=prepared[1:],
        resolution=150,
        quality=88,
    )


def fable_standard_answers(pages: list[Image.Image]) -> dict[str, Any]:
    env = load_env(REFERENCE_ENV)
    base_url = env["PROVIDER_POMOAI_BASE_URL"].rstrip("/")
    api_key = env["PROVIDER_POMOAI_API_KEY"]
    prompt = """你是中学物理教研员。下面依次给出同一份八年级物理答卷的4个页面。
请识别印刷题目，学生手写答案只用于理解题意，不能直接当作标准答案。为每个可评分的大题生成标准答案草稿。
严格只返回JSON，不要Markdown：
{"examTitle":"", "subject":"物理", "grade":"八年级", "questions":[
 {"questionNumber":"1", "pageNumber":1, "questionText":"", "answerType":"选择题|填空题|作图题|实验题|计算题",
  "answerText":"", "maxScore":3, "rubricText":"", "scoringPoints":[{"id":"q1-p1","description":"","points":3,"required":true}],
  "region":{"x":0.0,"y":0.0,"width":1.0,"height":0.2}, "confidence":0.0, "reviewReason":""}
]}
要求：
1. 覆盖卷面可见的第1至22题，题号不能重复；小问合并到所属大题。
2. region是该题在当前单页中的归一化外接矩形，必须在0到1内。
3. maxScore和scoringPoints必须合理，scoringPoints分值之和不超过maxScore。
4. 无法确定答案时给出物理上最合理的草稿，降低confidence并写reviewReason。
5. 所有答案状态由系统统一保存为draft。"""
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for index, page in enumerate(pages, start=1):
        content.append({"type": "text", "text": f"第{index}页"})
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.b64encode(image_jpeg_bytes(page, 86)).decode("ascii"),
                },
            }
        )
    with httpx.Client(timeout=240) as client:
        response = client.post(
            f"{base_url}/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-fable-5",
                "max_tokens": 16000,
                "messages": [{"role": "user", "content": content}],
            },
        )
        response.raise_for_status()
        payload = response.json()
    text = "".join(item.get("text", "") for item in payload.get("content", []))
    result = json_from_text(text)
    result["model"] = payload.get("model", "claude-fable-5")
    result["usage"] = payload.get("usage", {})
    return validate_answer_draft(result)


def clamp(value: Any, low: float, high: float) -> float:
    try:
        return min(high, max(low, float(value)))
    except (TypeError, ValueError):
        return low


def validate_answer_draft(draft: dict[str, Any]) -> dict[str, Any]:
    questions = draft.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("Fable 5 returned no questions")
    seen: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    for index, raw in enumerate(questions, start=1):
        number = str(raw.get("questionNumber") or index).strip()
        if number in seen:
            raise ValueError(f"Duplicate question number: {number}")
        seen.add(number)
        page = max(1, min(4, int(raw.get("pageNumber") or 1)))
        region = raw.get("region") or {}
        x = clamp(region.get("x"), 0, 0.98)
        y = clamp(region.get("y"), 0, 0.98)
        width = clamp(region.get("width"), 0.02, 1 - x)
        height = clamp(region.get("height"), 0.02, 1 - y)
        max_score = max(0.5, float(raw.get("maxScore") or 1))
        points = []
        for point_index, point in enumerate(raw.get("scoringPoints") or [], start=1):
            points.append(
                {
                    "id": str(point.get("id") or f"q{number}-p{point_index}"),
                    "description": str(point.get("description") or "待人工补充评分要点"),
                    "points": max(0, float(point.get("points") or 0)),
                    "required": bool(point.get("required", False)),
                }
            )
        if not points:
            points = [{"id": f"q{number}-p1", "description": "答案正确", "points": max_score, "required": True}]
        cleaned.append(
            {
                **raw,
                "questionNumber": number,
                "pageNumber": page,
                "answerText": str(raw.get("answerText") or "[待人工确认]"),
                "maxScore": max_score,
                "rubricText": str(raw.get("rubricText") or "按答案与关键步骤给分"),
                "scoringPoints": points,
                "region": {"x": x, "y": y, "width": width, "height": height},
                "confidence": clamp(raw.get("confidence"), 0, 1),
            }
        )
    draft["questions"] = cleaned
    draft["questionCount"] = len(cleaned)
    draft["reviewRequired"] = True
    return draft


def render_answer_key(draft: dict[str, Any], path: Path) -> None:
    font_path = "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"
    title_font = ImageFont.truetype(font_path, 34)
    body_font = ImageFont.truetype(font_path, 22)
    pages: list[Image.Image] = []
    canvas = Image.new("RGB", (1240, 1754), "white")
    from PIL import ImageDraw

    draw = ImageDraw.Draw(canvas)
    y = 55
    draw.text((55, y), "物理标准答案草稿（AI生成，待教师复核）", fill="black", font=title_font)
    y += 70
    for question in draft["questions"]:
        block = f"{question['questionNumber']}. {question['answerText']}  （{question['maxScore']:g}分）"
        lines = textwrap.wrap(block, width=46) or [block]
        needed = len(lines) * 34 + 25
        if y + needed > 1680:
            pages.append(canvas)
            canvas = Image.new("RGB", (1240, 1754), "white")
            draw = ImageDraw.Draw(canvas)
            y = 55
        for line in lines:
            draw.text((55, y), line, fill="black", font=body_font)
            y += 34
        y += 18
    pages.append(canvas)
    save_pdf(pages, path)


def variant_params(index: int, rng: random.Random) -> dict[str, Any]:
    if index >= 46:
        category = "mirror_anomaly"
    elif index >= 41:
        category = "severe_readable"
    elif index >= 31:
        category = "rotated_camera"
    else:
        category = "natural_camera"
    rotations = [0, 0, 0, 90, 180, 270] if category == "rotated_camera" else [0]
    return {
        "category": category,
        "mirror": category == "mirror_anomaly",
        "quarterTurn": rng.choice(rotations),
        "fineRotation": round(rng.uniform(-2.8, 2.8), 2),
        "brightness": round(rng.uniform(0.82, 1.18), 3),
        "contrast": round(rng.uniform(0.82, 1.22), 3),
        "blurRadius": round(rng.uniform(0, 0.8 if category != "severe_readable" else 1.5), 2),
        "jpegQuality": rng.randint(68 if category == "severe_readable" else 76, 93),
        "xShear": round(rng.uniform(-0.035, 0.035), 4),
        "yShear": round(rng.uniform(-0.025, 0.025), 4),
    }


def augment_page(page: Image.Image, params: dict[str, Any], rng: random.Random) -> Image.Image:
    image = page.convert("RGB")
    if params["mirror"]:
        image = ImageOps.mirror(image)
    if params["quarterTurn"]:
        image = image.rotate(params["quarterTurn"], expand=True, fillcolor="white")
    width, height = image.size
    x_shift = int(width * params["xShear"])
    y_shift = int(height * params["yShear"])
    image = image.transform(
        image.size,
        Image.Transform.AFFINE,
        (1, params["xShear"], -x_shift, params["yShear"], 1, -y_shift),
        resample=Image.Resampling.BICUBIC,
        fillcolor="white",
    )
    image = image.rotate(params["fineRotation"], expand=False, fillcolor="white")
    image = ImageEnhance.Brightness(image).enhance(params["brightness"])
    image = ImageEnhance.Contrast(image).enhance(params["contrast"])
    if params["blurRadius"] > 0.08:
        image = image.filter(ImageFilter.GaussianBlur(params["blurRadius"]))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=params["jpegQuality"])
    return Image.open(io.BytesIO(buffer.getvalue())).convert("RGB")


class Api:
    def __init__(self, base_url: str, email: str, password: str):
        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=120)
        response = self.client.post(
            "/api/v1/login/access-token",
            data={"username": email, "password": password},
        )
        if response.is_success:
            token = response.json()["access_token"]
        else:
            token = local_admin_token(email)
        self.client.headers.update({"Authorization": f"Bearer {token}"})

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {path}: {response.status_code} {response.text[:500]}")
        return response.json()

    def upload(self, path: str, file_path: Path, data: dict[str, str]) -> dict[str, Any]:
        with file_path.open("rb") as stream:
            return self.request(
                "POST",
                path,
                data=data,
                files={"file": (file_path.name, stream, "application/pdf")},
            )


def local_admin_token(email: str) -> str:
    sys.path.insert(0, str(ROOT / "backend"))
    from sqlmodel import Session, select

    from app.core import security
    from app.core.db import engine
    from app.models import User

    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == email)).first()
        if not user:
            raise RuntimeError(f"Local admin user not found: {email}")
        return security.create_access_token(user.id)


def build_dataset(force: bool, skip_fable: bool, api_url: str) -> dict[str, Any]:
    preserved_draft: dict[str, Any] | None = None
    existing_draft_path = OUTPUT_DIR / "standard_answers_draft.json"
    if skip_fable and existing_draft_path.exists():
        preserved_draft = json.loads(existing_draft_path.read_text(encoding="utf-8"))
    if OUTPUT_DIR.exists():
        if not force:
            raise RuntimeError(f"Dataset already exists: {OUTPUT_DIR}. Use --force to replace it.")
        shutil.rmtree(OUTPUT_DIR)
    (OUTPUT_DIR / "base_pages").mkdir(parents=True)
    (OUTPUT_DIR / "submissions").mkdir()
    pages = normalize_source_pages()
    for index, page in enumerate(pages, start=1):
        page.save(OUTPUT_DIR / "base_pages" / f"page-{index}.jpg", quality=92)
    source_pdf = OUTPUT_DIR / "physics-template-reference.pdf"
    save_pdf(pages, source_pdf)

    draft_path = OUTPUT_DIR / "standard_answers_draft.json"
    if preserved_draft is not None:
        draft = preserved_draft
    else:
        draft = fable_standard_answers(pages)
    draft_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = ["# 物理标准答案草稿", "", "> AI 生成，必须由教师复核。", ""]
    for item in draft["questions"]:
        markdown.extend(
            [
                f"## 第 {item['questionNumber']} 题（{item['maxScore']:g} 分）",
                "",
                item["answerText"],
                "",
                f"评分规则：{item['rubricText']}",
                "",
                f"置信度：{item['confidence']:.0%}；复核提示：{item.get('reviewReason') or '无'}",
                "",
            ]
        )
    (OUTPUT_DIR / "standard_answers_draft.md").write_text("\n".join(markdown), encoding="utf-8")
    answer_pdf = OUTPUT_DIR / "physics-answer-key-draft.pdf"
    render_answer_key(draft, answer_pdf)

    rng = random.Random(SEED)
    students: list[dict[str, Any]] = []
    for index, name in enumerate(STUDENT_NAMES, start=1):
        params = variant_params(index, rng)
        student_rng = random.Random(SEED + index)
        augmented = [augment_page(page, params, student_rng) for page in pages]
        identifier = f"PHY2022-{index:03d}"
        pdf_path = OUTPUT_DIR / "submissions" / f"{identifier}-{name}.pdf"
        save_pdf(augmented, pdf_path)
        students.append(
            {
                "index": index,
                "name": name,
                "identifier": identifier,
                "file": str(pdf_path.relative_to(OUTPUT_DIR)),
                "sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
                "pageCount": 4,
                "augmentation": params,
            }
        )

    root_env = load_env(ROOT_ENV)
    api = Api(api_url, root_env["FIRST_SUPERUSER"], root_env["FIRST_SUPERUSER_PASSWORD"])
    existing = api.request("GET", "/api/v1/exams/?skip=0&limit=100").get("data", [])
    matches = [exam for exam in existing if exam.get("title") == EXAM_TITLE]
    if matches and not force:
        raise RuntimeError(f"Exam already exists: {matches[0]['id']}")
    for exam in matches:
        api.request("DELETE", f"/api/v1/exams/{exam['id']}")
    exam = api.request(
        "POST",
        "/api/v1/exams/",
        json={"title": EXAM_TITLE, "subject": "物理", "grade_level": "八年级"},
    )
    exam_id = exam["id"]
    documents = [
        api.upload(f"/api/v1/exams/{exam_id}/files", source_pdf, {"document_type": "blank_exam"}),
        api.upload(f"/api/v1/exams/{exam_id}/files", answer_pdf, {"document_type": "answer_key"}),
    ]
    regions: list[dict[str, Any]] = []
    answers: list[dict[str, Any]] = []
    for item in draft["questions"]:
        region_data = item["region"]
        region = api.request(
            "POST",
            f"/api/v1/exams/{exam_id}/regions",
            json={
                "label": f"第{item['questionNumber']}题",
                "region_type": "question",
                "page_number": item["pageNumber"],
                **region_data,
            },
        )
        answer = api.request(
            "POST",
            f"/api/v1/exams/{exam_id}/answers",
            json={
                "exam_region_id": region["id"],
                "answer_text": item["answerText"],
                "max_score": item["maxScore"],
                "rubric_text": item["rubricText"],
                "scoring_points": item["scoringPoints"],
                "status": "draft",
            },
        )
        regions.append(region)
        answers.append(answer)

    for student in students:
        pdf_path = OUTPUT_DIR / student["file"]
        submission = api.upload(
            f"/api/v1/exams/{exam_id}/submissions",
            pdf_path,
            {"student_name": student["name"], "student_identifier": student["identifier"]},
        )
        params = student["augmentation"]
        note = f"synthetic_seed={SEED}; category={params['category']}; mirror={str(params['mirror']).lower()}"
        api.request(
            "PATCH",
            f"/api/v1/exams/{exam_id}/submissions/{submission['id']}/registration",
            json={
                "registration_status": "pending",
                "registration_quality": None,
                "registration_notes": note,
                "registration_homography": {"source": "physics_synthetic_v1", "augmentation": params},
            },
        )
        student["submissionId"] = submission["id"]
        print(f"[{student['index']:02d}/50] seeded {student['identifier']} {student['name']}")

    normal_sample = students[0]
    mirror_sample = students[-1]
    api.request(
        "PATCH",
        f"/api/v1/exams/{exam_id}/submissions/{normal_sample['submissionId']}/registration",
        json={
            "registration_status": "manual_confirmed",
            "registration_quality": 1,
            "registration_notes": "synthetic smoke test: normal sample confirmed",
            "registration_homography": {"source": "physics_synthetic_v1", "augmentation": normal_sample["augmentation"]},
        },
    )
    processing_task = api.request(
        "POST",
        f"/api/v1/exams/{exam_id}/submissions/{normal_sample['submissionId']}/processing-tasks",
    )
    api.request(
        "PATCH",
        f"/api/v1/exams/{exam_id}/submissions/{mirror_sample['submissionId']}/registration",
        json={
            "registration_status": "failed",
            "registration_quality": 0,
            "registration_notes": "synthetic smoke test: mirrored text anomaly",
            "registration_homography": {"source": "physics_synthetic_v1", "augmentation": mirror_sample["augmentation"]},
        },
    )

    manifest = {
        "schemaVersion": 1,
        "seed": SEED,
        "sourceFiles": [str(SOURCE_DIR / "1.jpg"), str(SOURCE_DIR / "2.jpg")],
        "exam": exam,
        "documents": documents,
        "regions": [{"id": region["id"], "label": region["label"]} for region in regions],
        "standardAnswers": [{"id": answer["id"], "regionId": answer["exam_region_id"], "status": answer["status"]} for answer in answers],
        "students": students,
        "smokeTest": {
            "normalSubmissionId": normal_sample["submissionId"],
            "normalProcessingTaskId": processing_task["id"],
            "normalProcessingStatus": processing_task["status"],
            "mirrorSubmissionId": mirror_sample["submissionId"],
            "mirrorRegistrationStatus": "failed",
        },
        "counts": {"pages": 4, "questions": len(regions), "standardAnswers": len(answers), "submissions": len(students), "mirrorAnomalies": 5},
    }
    (OUTPUT_DIR / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="replace the generated dataset and same-title exam")
    parser.add_argument("--skip-fable", action="store_true", help="reuse an existing standard answer draft")
    parser.add_argument("--api-url", default="http://localhost:8000")
    args = parser.parse_args()
    manifest = build_dataset(args.force, args.skip_fable, args.api_url)
    print(json.dumps({"examId": manifest["exam"]["id"], **manifest["counts"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
