from __future__ import annotations

import base64
import json
import re
import threading
import time
from dataclasses import dataclass
from io import BytesIO

import httpx
from PIL import Image

from app.core.config import settings
from app.models import StandardAnswer


class VisionGradingError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelTarget:
    provider: str
    model: str


_PROVIDER_PREFERENCE = ("pomoai", "kimi", "fluxnode_gemini", "fluxnode_grok")
_PROVIDER_COOLDOWNS: dict[str, tuple[float, str]] = {}
_PROVIDER_COOLDOWNS_LOCK = threading.Lock()


@dataclass
class VisionGrade:
    student_answer: str
    score: float
    confidence: float
    comment: str
    evidence: list[dict]
    provider: str
    model: str
    elapsed_ms: int


@dataclass
class VisionExtraction:
    question_text: str
    student_answer: str
    final_answer: str
    answer_type: str
    confidence: float
    notes: list[str]
    provider: str
    model: str
    elapsed_ms: int


def segment_page_with_gemini(
    *, image_bytes: bytes, provider: str = "fluxnode_gemini", model: str = "gemini-3.5-flash"
) -> tuple[list[dict], str, int, int]:
    """Use the reference layout prompt to locate complete question blocks."""
    source = Image.open(BytesIO(image_bytes)).convert("RGB")
    orientation_prompt = '下面依次给出同一张中文试卷实际旋转后的四个候选图。请选择文字可以正常从左到右、从上到下阅读且不倒置的候选图。标签就是程序实际采用的顺时针旋转角度，不需要换算。只返回 JSON：{"rotation":0|90|180|270}'
    orientation_content = [{"type": "text", "text": orientation_prompt}]
    for rotation in (0, 90, 180, 270):
        rotated = source.rotate(-rotation, expand=True)
        rotated.thumbnail((900, 900))
        buffer = BytesIO()
        rotated.save(buffer, format="JPEG", quality=82)
        orientation_content.extend(
            [
                {"type": "text", "text": f"候选 {rotation}°"},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")}},
            ]
        )
    orientation, _orientation_model, orientation_ms = _call_model(
        provider=provider,
        model=model,
        fallback_models=[],
        messages=[{"role": "user", "content": orientation_content}],
    )
    rotation = int(orientation.get("rotation", 0)) if str(orientation.get("rotation", 0)).isdigit() else 0
    rotation = rotation if rotation in {0, 90, 180, 270} else 0
    upright = source.rotate(-rotation, expand=True)
    upright_buffer = BytesIO()
    upright.save(upright_buffer, format="PNG")
    image = base64.b64encode(upright_buffer.getvalue()).decode("ascii")
    prompt = """你是考试试卷版面分析器。输入图片已经转正，可能同时拍到左右两页或一张跨页展开的中文试卷。请只返回 JSON，不要 Markdown。
任务：按印刷题号找出每一个需要 OCR 的完整题目块。一个块必须从题号和题干开始，包含该题全部选项、插图、填空及考生手写答案，结束于下一道印刷题号之前。严禁把同一道题的题干、选项或作答拆成多个块，也不要把试卷标题、姓名栏、密封线单独当题目块。questionNumber 必须读取图片中真实印刷题号，不能根据块次序猜测。
若照片边界确实截断一道题，保留可见部分并在 kind 使用 continuation、continuationOf 写同一真实题号。左右两页分别按从上到下阅读，整张图按正常页序排列。每个矩形左右应覆盖所在纸页的完整文字列，并在不包含相邻题目的前提下保留约 2% 边缘。
同时读取姓名、座号、班级，用 studentLabel 返回可读标识，用 studentKey 返回稳定短键（优先“姓名+座号”，看不清或不存在时为空）。不要把不同考生页面配在一起。
坐标基于当前已转正图片，归一化到 0-1000，字段顺序为 ymin,xmin,ymax,xmax。
JSON格式：{"pageLabel":"...","studentLabel":"姓名/座号/班级的可读组合","studentKey":"跨页配对键或空字符串","paperPart":"前半/后半/第几页等","pageNumber":null,"regions":[{"id":"p1_q1","questionNumber":"1","label":"第1题","kind":"question_answer|continuation","readingOrder":1,"continuationOf":null,"ymin":0,"xmin":0,"ymax":1000,"xmax":500}]}。最多返回40个块，按阅读顺序排列。"""
    parsed, used_model, elapsed_ms = _call_model(
        provider=provider,
        model=model,
        fallback_models=[],
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image}"}},
                ],
            }
        ],
    )
    regions = parsed.get("regions")
    if not isinstance(regions, list):
        raise VisionGradingError("Gemini 版面分析未返回 regions")
    return [item for item in regions if isinstance(item, dict)], used_model, elapsed_ms, orientation_ms


def provider_config(provider: str) -> tuple[str, str]:
    configs = {
        "pomoai": (settings.PROVIDER_POMOAI_BASE_URL, settings.PROVIDER_POMOAI_API_KEY),
        "fluxnode_gemini": (
            settings.PROVIDER_FLUXNODE_GEMINI_BASE_URL,
            settings.PROVIDER_FLUXNODE_GEMINI_API_KEY,
        ),
        "fluxnode_grok": (
            settings.PROVIDER_FLUXNODE_GROK_BASE_URL,
            settings.PROVIDER_FLUXNODE_GROK_API_KEY,
        ),
        "kimi": (settings.PROVIDER_KIMI_BASE_URL, settings.PROVIDER_KIMI_API_KEY),
    }
    if provider not in configs:
        raise VisionGradingError(f"不支持的模型提供者：{provider}")
    base_url, api_key = configs[provider]
    if not api_key:
        raise VisionGradingError(f"提供者 {provider} 未配置 API Key")
    return base_url.rstrip("/"), api_key




def _temperature_for(provider: str) -> float:
    """Kimi 系列模型只接受 temperature=1（其余值 400），其他 provider 用低温求稳。"""
    return 1.0 if provider == "kimi" else 0.1


def _configured(provider: str) -> bool:
    try:
        provider_config(provider)
    except VisionGradingError:
        return False
    return True


def _resolve_target(primary_provider: str, value: str) -> ModelTarget:
    """Resolve legacy model names and explicit ``provider/model`` targets."""
    raw = value.strip()
    for separator in ("/", ":"):
        if separator in raw:
            provider, model = raw.split(separator, 1)
            if provider and model:
                return ModelTarget(provider.strip(), model.strip())

    # Import lazily so the low-level model client stays usable in isolation.
    from app.services.system_config import PROVIDER_MODELS

    if raw in PROVIDER_MODELS.get(primary_provider, []):
        return ModelTarget(primary_provider, raw)
    providers = [
        provider
        for provider in _PROVIDER_PREFERENCE
        if raw in PROVIDER_MODELS.get(provider, []) and _configured(provider)
    ]
    return ModelTarget(providers[0] if providers else primary_provider, raw)


def _candidate_targets(
    provider: str, model: str, fallback_models: list[str]
) -> list[ModelTarget]:
    targets = [ModelTarget(provider, model)]
    targets.extend(_resolve_target(provider, item) for item in fallback_models if item.strip())
    return list(dict.fromkeys(targets))


def _provider_cooldown_reason(provider: str) -> str | None:
    now = time.monotonic()
    with _PROVIDER_COOLDOWNS_LOCK:
        blocked = _PROVIDER_COOLDOWNS.get(provider)
        if not blocked:
            return None
        expires_at, reason = blocked
        if expires_at <= now:
            _PROVIDER_COOLDOWNS.pop(provider, None)
            return None
        return reason


def _cool_down_provider(provider: str, seconds: int, reason: str) -> None:
    with _PROVIDER_COOLDOWNS_LOCK:
        _PROVIDER_COOLDOWNS[provider] = (time.monotonic() + seconds, reason)


def reset_provider_cooldowns() -> None:
    """Clear process-local provider health state (primarily for tests/admin probes)."""
    with _PROVIDER_COOLDOWNS_LOCK:
        _PROVIDER_COOLDOWNS.clear()


def _response_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return response.text[:500]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("type") or "")[:500]
    return str(error or payload)[:500]


def _raise_for_model_response(response: httpx.Response, provider: str) -> None:
    if response.status_code < 400:
        return
    detail = _response_message(response)
    normalized = detail.lower()
    if response.status_code == 403 and any(
        token in normalized
        for token in ("usage limit", "quota", "billing cycle", "purchase extra")
    ):
        reason = "当前模型额度已用完，系统将尝试备用通道"
        _cool_down_provider(provider, 15 * 60, reason)
        raise VisionGradingError(reason)
    if response.status_code in {401, 403}:
        reason = "当前模型服务暂不可用，系统将尝试备用通道"
        _cool_down_provider(provider, 5 * 60, reason)
        raise VisionGradingError(reason)
    if response.status_code == 429:
        reason = "当前模型请求较多，系统将尝试备用通道"
        _cool_down_provider(provider, 60, reason)
        raise VisionGradingError(reason)
    if response.status_code >= 500:
        reason = "模型服务暂时异常，系统将尝试备用通道"
        _cool_down_provider(provider, 30, reason)
        raise VisionGradingError(reason)
    raise VisionGradingError(f"模型请求未被接受（HTTP {response.status_code}）")

def _parse_json(text: str) -> dict:
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.I)
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, flags=re.I)
    raw = (
        fenced.group(1)
        if fenced
        else cleaned[cleaned.find("{") : cleaned.rfind("}") + 1]
    )
    try:
        value = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise VisionGradingError("模型未返回有效 JSON") from exc
    if not isinstance(value, dict):
        raise VisionGradingError("模型 JSON 不是对象")
    return value


def _endpoint(base_url: str) -> str:
    return (
        f"{base_url}/chat/completions"
        if base_url.endswith("/v1")
        else f"{base_url}/v1/chat/completions"
    )


def _call_model(
    *, provider: str, model: str, messages: list[dict], fallback_models: list[str]
) -> tuple[dict, str, int]:
    parsed, _used_provider, used_model, elapsed_ms, _usage = _call_model_with_route(
        provider=provider,
        model=model,
        messages=messages,
        fallback_models=fallback_models,
    )
    return parsed, used_model, elapsed_ms


def _call_model_with_metadata(
    *, provider: str, model: str, messages: list[dict], fallback_models: list[str]
) -> tuple[dict, str, int, dict]:
    parsed, used_provider, used_model, elapsed_ms, usage = _call_model_with_route(
        provider=provider,
        model=model,
        messages=messages,
        fallback_models=fallback_models,
    )
    if used_provider != provider:
        usage = {**usage, "_used_provider": used_provider}
    return parsed, used_model, elapsed_ms, usage


def _call_model_with_route(
    *, provider: str, model: str, messages: list[dict], fallback_models: list[str]
) -> tuple[dict, str, str, int, dict]:
    candidates = _candidate_targets(provider, model, fallback_models)
    last_error: Exception | None = None
    for candidate in candidates:
        started = time.perf_counter()
        try:
            cooldown_reason = _provider_cooldown_reason(candidate.provider)
            if cooldown_reason:
                raise VisionGradingError(cooldown_reason)
            base_url, api_key = provider_config(candidate.provider)
            response = httpx.post(
                _endpoint(base_url),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": candidate.model,
                    "temperature": _temperature_for(candidate.provider),
                    "messages": messages,
                },
                timeout=settings.VISION_TIMEOUT_SECONDS,
            )
            _raise_for_model_response(response, candidate.provider)
            payload = response.json()
            parsed = _parse_json(
                payload.get("choices", [{}])[0].get("message", {}).get("content", "")
            )
            usage = payload.get("usage")
            return (
                parsed,
                candidate.provider,
                candidate.model,
                round((time.perf_counter() - started) * 1000),
                usage if isinstance(usage, dict) else {},
            )
        except (
            httpx.TimeoutException,
            httpx.HTTPError,
            KeyError,
            TypeError,
            ValueError,
            VisionGradingError,
        ) as exc:
            last_error = exc
    raise VisionGradingError(f"可用模型均未完成请求：{last_error}")


def call_json_model(
    *,
    provider: str,
    model: str,
    messages: list[dict],
    fallback_models: list[str] | None = None,
) -> tuple[dict, str, int]:
    return _call_model(
        provider=provider,
        model=model,
        messages=messages,
        fallback_models=fallback_models or [],
    )


def call_json_model_with_metadata(
    *,
    provider: str,
    model: str,
    messages: list[dict],
    fallback_models: list[str] | None = None,
) -> tuple[dict, str, int, dict]:
    return _call_model_with_metadata(
        provider=provider,
        model=model,
        messages=messages,
        fallback_models=fallback_models or [],
    )


def call_json_model_with_route(
    *,
    provider: str,
    model: str,
    messages: list[dict],
    fallback_models: list[str] | None = None,
) -> tuple[dict, str, str, int, dict]:
    """Return payload plus the provider/model that actually completed the call."""
    return _call_model_with_route(
        provider=provider,
        model=model,
        messages=messages,
        fallback_models=fallback_models or [],
    )


def extract_answer_image(
    *,
    image_bytes: bytes,
    provider: str,
    model: str,
    question_label: str,
    fallback_models: list[str] | None = None,
) -> VisionExtraction:
    return extract_answer_images(
        image_bytes_list=[image_bytes],
        provider=provider,
        model=model,
        question_label=question_label,
        fallback_models=fallback_models,
    )


def extract_answer_images(
    *,
    image_bytes_list: list[bytes],
    provider: str,
    model: str,
    question_label: str,
    fallback_models: list[str] | None = None,
) -> VisionExtraction:
    if not image_bytes_list:
        raise VisionGradingError("题目没有可识别的区域图片")
    prompt = f"""你是中文考试阅卷 OCR。请识别图片中的一块试卷，区分印刷题目和考生手写内容。不要补写图片中不存在的内容；看不清的位置写“[无法辨认]”。只返回 JSON：
{{"questionNumber":"题号","question":"完整题干和选项（含公式尽量用纯文本）","studentAnswer":"考生回答原文；没有则为空","answerType":"选择题|填空题|计算题|实验题|未知","confidence":0到1,"notes":"图示、跨页或辨认风险"}}
题号优先读取图片中的印刷题号，候选题号仅供校验。同一道题可能有多张按顺序给出的连续区域，必须合并理解，保留完整手写计算过程，不把它混入题干。逐项检查题干、A/B/C/D 等选项和作答是否完整；只要所有区域合并后仍截断文字、缺少可见选项或存在“[无法辨认]”，confidence 不得高于 0.6，并在 notes 明确说明。候选题号：{question_label}。"""
    content: list[dict] = [{"type": "text", "text": prompt}]
    for index, image_bytes in enumerate(image_bytes_list, start=1):
        image = base64.b64encode(image_bytes).decode("ascii")
        content.extend(
            [
                {
                    "type": "text",
                    "text": f"同一道题的区域 {index}/{len(image_bytes_list)}",
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image}"},
                },
            ]
        )
    parsed, used_provider, used_model, elapsed_ms, _usage = _call_model_with_route(
        provider=provider,
        model=model,
        fallback_models=fallback_models or [],
        messages=[
            {
                "role": "user",
                "content": content,
            }
        ],
    )
    confidence = min(max(float(parsed["confidence"]), 0), 1)
    raw_notes = parsed.get("notes", "")
    notes = [str(item) for item in raw_notes] if isinstance(raw_notes, list) else ([str(raw_notes)] if raw_notes else [])
    return VisionExtraction(
        question_text=str(parsed.get("question", ""))[:12000],
        student_answer=str(parsed.get("studentAnswer", ""))[:8000],
        final_answer=str(parsed.get("studentAnswer", ""))[:2000],
        answer_type=str(parsed.get("answerType", "未知")),
        confidence=confidence,
        notes=notes,
        provider=used_provider,
        model=used_model,
        elapsed_ms=elapsed_ms,
    )


def grade_answer_text(
    *,
    student_answer: str,
    standard_answer: StandardAnswer,
    provider: str,
    model: str,
    fallback_models: list[str],
) -> VisionGrade:
    prompt = f"""你是严谨的中文试卷阅卷教师。以下学生作答已经由独立视觉模型忠实转录。你只能依据转录文本、标准答案和评分点判题，不要假设图片中还有其他内容。
学生作答：{student_answer or "[空白]"}
标准答案：{standard_answer.answer_text}
满分：{standard_answer.max_score}
评分细则：{standard_answer.rubric_text or "按答案正确程度给分"}
评分点：{json.dumps(standard_answer.scoring_points, ensure_ascii=False)}
只返回 JSON：{{"score":0,"confidence":0.0,"comment":"中文评语","evidence":[{{"point":"评分点","matched":true,"points":0,"reason":"依据"}}]}}。score 必须在 0 到满分之间；confidence 为 0 到 1。"""
    parsed, used_provider, used_model, elapsed_ms, _usage = _call_model_with_route(
        provider=provider,
        model=model,
        fallback_models=fallback_models,
        messages=[{"role": "user", "content": prompt}],
    )
    score = min(max(float(parsed["score"]), 0), standard_answer.max_score)
    confidence = min(max(float(parsed["confidence"]), 0), 1)
    evidence = parsed.get("evidence", [])
    return VisionGrade(
        student_answer=student_answer,
        score=score,
        confidence=confidence,
        comment=str(parsed.get("comment", ""))[:2000],
        evidence=evidence if isinstance(evidence, list) else [],
        provider=used_provider,
        model=used_model,
        elapsed_ms=elapsed_ms,
    )


def grade_answer_image(
    *,
    image_bytes: bytes,
    standard_answer: StandardAnswer,
    provider: str,
    model: str,
    fallback_models: list[str],
) -> VisionGrade:
    image = base64.b64encode(image_bytes).decode("ascii")
    prompt = f"""你是严谨的中文试卷阅卷教师。读取图片中的学生作答，根据标准答案和评分点给分。
标准答案：{standard_answer.answer_text}
满分：{standard_answer.max_score}
评分细则：{standard_answer.rubric_text or "按答案正确程度给分"}
评分点：{json.dumps(standard_answer.scoring_points, ensure_ascii=False)}
只返回 JSON：{{"student_answer":"识别出的作答","score":0,"confidence":0.0,"comment":"中文评语","evidence":[{{"point":"评分点","matched":true,"points":0,"reason":"依据"}}]}}
score 必须在 0 到满分之间；confidence 为 0 到 1。看不清时降低 confidence，不能臆测。"""
    parsed, used_provider, used_model, elapsed_ms, _usage = _call_model_with_route(
        provider=provider,
        model=model,
        fallback_models=fallback_models,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image}"},
                    },
                ],
            }
        ],
    )
    score = min(max(float(parsed["score"]), 0), standard_answer.max_score)
    confidence = min(max(float(parsed["confidence"]), 0), 1)
    evidence = parsed.get("evidence", [])
    return VisionGrade(
        student_answer=str(parsed.get("student_answer", ""))[:8000],
        score=score,
        confidence=confidence,
        comment=str(parsed.get("comment", ""))[:2000],
        evidence=evidence if isinstance(evidence, list) else [],
        provider=used_provider,
        model=used_model,
        elapsed_ms=elapsed_ms,
    )
