from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import cv2
import httpx
import numpy as np

from app.core.config import settings
from app.services.file_storage import get_stored_file_path
from app.services.pdf_rendering import get_pdf_page_count, render_pdf_page_png
from app.services.question_text_normalization import normalize_reference_result_question


def _page_images(path: Path, content_type: str) -> list[bytes]:
    if content_type == "application/pdf":
        return [
            render_pdf_page_png(path, page)
            for page in range(1, get_pdf_page_count(path) + 1)
        ]
    return [path.read_bytes()]


def _image_data_url(contents: bytes, *, content_type: str = "image/png") -> str:
    return f"data:{content_type};base64," + base64.b64encode(contents).decode("ascii")


def _decode_image(contents: bytes) -> np.ndarray:
    image_buffer = np.frombuffer(contents, dtype=np.uint8)
    image = cv2.imdecode(image_buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("参考算法无法读取页面图片")
    return image


def _rotate_upright(image: np.ndarray, rotation: int) -> np.ndarray:
    rotation = int(rotation or 0) % 360
    if rotation == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    if rotation == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    if rotation == 270:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return image


def _jpeg_data_url(image: np.ndarray) -> str:
    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok:
        raise RuntimeError("参考算法题块裁剪失败")
    return "data:image/jpeg;base64," + base64.b64encode(buffer).decode("ascii")


def _crop_region_image(page_image: np.ndarray, layout: dict, region: dict) -> str:
    working = page_image
    if layout.get("coordinateSpace") == "upright":
        working = _rotate_upright(page_image, int(layout.get("rotation") or 0))
        xmin = max(0.0, float(region.get("xmin", 0)) - 12)
        ymin = max(0.0, float(region.get("ymin", 0)) - 8)
        xmax = min(1000.0, float(region.get("xmax", 1000)) + 12)
        ymax = min(1000.0, float(region.get("ymax", 1000)) + 8)
    else:
        xmin = max(0.0, float(region.get("xmin", 0)))
        ymin = max(0.0, float(region.get("ymin", 0)))
        xmax = min(1000.0, float(region.get("xmax", 1000)))
        ymax = min(1000.0, float(region.get("ymax", 1000)))
    if xmax <= xmin or ymax <= ymin:
        raise RuntimeError("参考算法返回了无效题块坐标")
    height, width = working.shape[:2]
    x0 = max(0, min(width - 1, round(width * xmin / 1000)))
    y0 = max(0, min(height - 1, round(height * ymin / 1000)))
    x1 = max(x0 + 1, min(width, round(width * xmax / 1000)))
    y1 = max(y0 + 1, min(height, round(height * ymax / 1000)))
    return _jpeg_data_url(working[y0:y1, x0:x1])


def _normalize_reference_payload(payload: dict) -> dict:
    results = payload.get("results")
    if not isinstance(results, list):
        return payload
    return {
        **payload,
        "results": [
            normalize_reference_result_question(item)
            if isinstance(item, dict)
            else item
            for item in results
        ],
    }


def _verification_mode(value: str | None) -> str:
    return value if value in {"evidence", "selective"} else "fast"


def _merge_token_usage(*usages: Any) -> dict[str, int]:
    merged = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for usage in usages:
        if not isinstance(usage, dict):
            continue
        input_tokens = int(
            usage.get("inputTokens")
            or usage.get("input_tokens")
            or usage.get("prompt_tokens")
            or 0
        )
        output_tokens = int(
            usage.get("outputTokens")
            or usage.get("output_tokens")
            or usage.get("completion_tokens")
            or 0
        )
        merged["input_tokens"] += max(0, input_tokens)
        merged["output_tokens"] += max(0, output_tokens)
        merged["total_tokens"] += max(
            0,
            int(
                usage.get("totalTokens")
                or usage.get("total_tokens")
                or input_tokens + output_tokens
            ),
        )
    return merged


def _process_pages(
    *,
    pages: list[dict],
    verification_mode: str = "fast",
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    # 未显式传入时回落 env 默认（系统设置未接入的调用方保持原行为）
    provider = provider or settings.VISION_DEFAULT_PROVIDER
    model = model or settings.VISION_DEFAULT_MODEL
    client_payload = {
        "provider": provider,
        "model": model,
        "pages": [
            {
                "id": page["id"],
                "fileName": page["fileName"],
                "image": page["image"],
                "assumeUpright": bool(page.get("assumeUpright")),
            }
            for page in pages
        ],
        "verificationMode": _verification_mode(verification_mode),
    }
    with httpx.Client(timeout=settings.VISION_TIMEOUT_SECONDS) as client:
        layout_response = client.post(
            f"{settings.REFERENCE_ALGORITHM_URL.rstrip('/')}/api/layout",
            json=client_payload,
        )
        layout_response.raise_for_status()
        layout_payload = layout_response.json()
        layout_usage = layout_payload.get("tokenUsage") or {}

        page_images = {page["id"]: _decode_image(page["contents"]) for page in pages}
        blocks: list[dict] = []
        for layout in layout_payload.get("layouts", []):
            if not isinstance(layout, dict) or not isinstance(
                layout.get("regions"), list
            ):
                continue
            page_image = page_images.get(str(layout.get("pageId")))
            if page_image is None:
                continue
            paper_key = (
                str(
                    layout.get("studentKey")
                    or layout.get("studentLabel")
                    or "未分组试卷"
                ).strip()
                or "未分组试卷"
            )
            for index, region in enumerate(layout["regions"], start=1):
                if not isinstance(region, dict):
                    continue
                region_id = str(region.get("id") or f"block_{index}")
                page_id = str(layout.get("pageId") or "")
                block = {
                    **region,
                    "id": f"{page_id}::{region_id}",
                    "layoutRegionId": region_id,
                    "provider": provider,
                    "model": model,
                    "pageId": page_id,
                    "paperKey": paper_key,
                    "studentKey": layout.get("studentKey") or "",
                    "studentLabel": layout.get("studentLabel") or "",
                    "layoutReviewRequired": bool(
                        layout.get("layoutReviewRequired", False)
                    ),
                    "layoutReviewReason": layout.get("layoutReviewReason"),
                    "image": _crop_region_image(page_image, layout, region),
                }
                blocks.append(block)

        if not blocks:
            return _normalize_reference_payload(
                {
                    "provider": layout_payload.get("provider"),
                    "providerLabel": layout_payload.get("providerLabel"),
                    "model": layout_payload.get("model"),
                    "layouts": layout_payload.get("layouts", []),
                    "blocks": [],
                    "results": [],
                    "usage": _merge_token_usage(layout_usage),
                    "layoutTokenUsage": layout_usage,
                    "ocrTokenUsage": {},
                    "timing": {
                        "layoutMs": layout_payload.get("elapsedMs", 0),
                        "orientationModelMs": layout_payload.get(
                            "orientationModelMs", 0
                        ),
                        "regionModelMs": layout_payload.get("regionModelMs", 0),
                        "cropMs": 0,
                        "ocrMs": 0,
                        "totalElapsedMs": layout_payload.get("elapsedMs", 0),
                    },
                }
            )

        recognize_response = client.post(
            f"{settings.REFERENCE_ALGORITHM_URL.rstrip('/')}/api/recognize",
            json={
                "provider": provider,
                "model": model,
                "blocks": blocks,
            },
        )
        recognize_response.raise_for_status()
        recognize_payload = recognize_response.json()
        ocr_usage = recognize_payload.get("tokenUsage") or {}

    timing = {
        "layoutMs": layout_payload.get("elapsedMs", 0),
        "orientationModelMs": layout_payload.get("orientationModelMs", 0),
        "regionModelMs": layout_payload.get("regionModelMs", 0),
        "ocrMs": recognize_payload.get("elapsedMs", 0),
        "blockCount": len(blocks),
        "ocrBatchCount": recognize_payload.get("batchCount", 0),
        "modelRequestCount": recognize_payload.get("modelRequestCount", 0),
        "fallbackBatchCount": recognize_payload.get("fallbackBatchCount", 0),
        "mergedContinuationCount": recognize_payload.get("mergedContinuationCount", 0),
    }
    timing["totalElapsedMs"] = int(timing["layoutMs"] or 0) + int(timing["ocrMs"] or 0)
    return _normalize_reference_payload(
        {
            "provider": recognize_payload.get("provider")
            or layout_payload.get("provider"),
            "providerLabel": recognize_payload.get("providerLabel")
            or layout_payload.get("providerLabel"),
            "model": recognize_payload.get("model") or layout_payload.get("model"),
            "layouts": layout_payload.get("layouts", []),
            "blocks": blocks,
            "results": recognize_payload.get("results", []),
            "timing": timing,
            "usage": _merge_token_usage(layout_usage, ocr_usage),
            "layoutTokenUsage": layout_usage,
            "ocrTokenUsage": ocr_usage,
        }
    )


def process_stored_file(
    *,
    stored_file,
    verification_mode: str = "fast",
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    pages = []
    for index, contents in enumerate(
        _page_images(get_stored_file_path(stored_file), stored_file.content_type),
        start=1,
    ):
        pages.append(
            {
                "id": f"page-{index}",
                "fileName": stored_file.original_filename,
                "image": _image_data_url(contents),
                "contents": contents,
            }
        )
    return _process_pages(
        pages=pages,
        verification_mode=verification_mode,
        provider=provider,
        model=model,
    )


def _stored_file_page_image(*, stored_file: Any, page_number: int) -> tuple[bytes, str]:
    path = get_stored_file_path(stored_file)
    if page_number < 1:
        raise RuntimeError("页码必须大于等于 1")
    if stored_file.content_type == "application/pdf":
        if page_number > get_pdf_page_count(path):
            raise RuntimeError("PDF 页码超出范围")
        return render_pdf_page_png(path, page_number), "image/png"
    if page_number != 1:
        raise RuntimeError("图片文件只有 1 页")
    return path.read_bytes(), stored_file.content_type or "image/png"


def process_stored_file_pages(
    *,
    document: Any,
    stored_file: Any,
    page_numbers: list[int],
    verification_mode: str = "fast",
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """Run the unchanged Node reference pipeline on selected pages only."""
    pages = []
    for page_number in page_numbers:
        contents, content_type = _stored_file_page_image(
            stored_file=stored_file,
            page_number=page_number,
        )
        pages.append(
            {
                "id": f"{document.id}:page:{page_number}",
                "fileName": f"{stored_file.original_filename}#page-{page_number}",
                "image": _image_data_url(contents, content_type=content_type),
                "contents": contents,
            }
        )
    return _process_pages(
        pages=pages,
        verification_mode=verification_mode,
        provider=provider,
        model=model,
    )


def process_stored_file_page_context(
    *,
    documents: list[tuple[Any, Any]],
    target_document_id: Any,
    target_page_number: int,
    context_radius: int = 1,
    verification_mode: str = "fast",
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """Recognize a page together with adjacent paper pages across file boundaries."""
    ordered_pages: list[tuple[Any, Any, int]] = []
    for document, stored_file in documents:
        path = get_stored_file_path(stored_file)
        page_count = (
            get_pdf_page_count(path)
            if stored_file.content_type == "application/pdf"
            else 1
        )
        ordered_pages.extend(
            (document, stored_file, page_number)
            for page_number in range(1, page_count + 1)
        )

    target_index = next(
        (
            index
            for index, (document, _stored_file, page_number) in enumerate(ordered_pages)
            if str(document.id) == str(target_document_id)
            and page_number == target_page_number
        ),
        None,
    )
    if target_index is None:
        raise RuntimeError("当前页不在试卷页面序列中")

    radius = max(0, int(context_radius))
    selected_pages = ordered_pages[
        max(0, target_index - radius) : min(
            len(ordered_pages), target_index + radius + 1
        )
    ]
    pages = []
    context_page_ids = []
    for document, stored_file, page_number in selected_pages:
        contents, content_type = _stored_file_page_image(
            stored_file=stored_file,
            page_number=page_number,
        )
        page_id = f"{document.id}:page:{page_number}"
        context_page_ids.append(page_id)
        pages.append(
            {
                "id": page_id,
                "fileName": f"{stored_file.original_filename}#page-{page_number}",
                "image": _image_data_url(contents, content_type=content_type),
                "contents": contents,
            }
        )

    payload = _process_pages(
        pages=pages,
        verification_mode=verification_mode,
        provider=provider,
        model=model,
    )
    requested_page_id = f"{target_document_id}:page:{target_page_number}"
    block_page_by_id = {
        str(block.get("id")): str(block.get("pageId"))
        for block in payload.get("blocks", [])
        if isinstance(block, dict) and block.get("id") and block.get("pageId")
    }

    def touches_requested_page(result: Any) -> bool:
        if not isinstance(result, dict):
            return False
        if str(result.get("pageId") or "") == requested_page_id:
            return True
        source_ids = result.get("sourceBlockIds")
        if not isinstance(source_ids, list) or not source_ids:
            source_ids = [result.get("blockId"), result.get("id")]
        return any(
            block_page_by_id.get(str(source_id)) == requested_page_id
            for source_id in source_ids
            if source_id
        )

    all_results = payload.get("results", [])
    visible_results = [
        result for result in all_results if touches_requested_page(result)
    ]
    return {
        **payload,
        "results": visible_results,
        "requestedPageId": requested_page_id,
        "contextPageIds": context_page_ids,
        "updatedPageIds": [requested_page_id],
        "contextResultCount": len(all_results),
        "returnedResultCount": len(visible_results),
    }


def process_stored_files(
    *,
    documents: list[tuple[Any, Any]],
    verification_mode: str = "fast",
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """Send multiple exam documents to the unchanged Node reference pipeline."""
    pages = []
    for document, stored_file in documents:
        for index, contents in enumerate(
            _page_images(get_stored_file_path(stored_file), stored_file.content_type),
            start=1,
        ):
            pages.append(
                {
                    "id": f"{document.id}:page:{index}",
                    "fileName": stored_file.original_filename,
                    "image": _image_data_url(contents),
                    "contents": contents,
                    # 预处理管线确认转正后，参考服务可跳过方向判断模型调用
                    "assumeUpright": bool(
                        getattr(document, "preprocessing_status", None) == "completed"
                    ),
                }
            )
    return _process_pages(
        pages=pages,
        verification_mode=verification_mode,
        provider=provider,
        model=model,
    )


def stored_file_page_data_urls(*, stored_file) -> list[str]:
    return [
        "data:image/png;base64," + base64.b64encode(contents).decode("ascii")
        for contents in _page_images(
            get_stored_file_path(stored_file), stored_file.content_type
        )
    ]


def layout_stored_file(
    *,
    stored_file,
    page_numbers: list[int] | None = None,
    assume_upright: bool = False,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    pages = []
    path = get_stored_file_path(stored_file)
    if page_numbers is None:
        selected_pages = list(
            enumerate(_page_images(path, stored_file.content_type), start=1)
        )
    else:
        selected_pages = []
        for page_number in page_numbers:
            contents, _content_type = _stored_file_page_image(
                stored_file=stored_file, page_number=page_number
            )
            selected_pages.append((page_number, contents))
    for page_number, contents in selected_pages:
        pages.append(
            {
                "id": f"page-{page_number}",
                "fileName": f"{stored_file.original_filename}#page-{page_number}",
                "image": "data:image/png;base64,"
                + base64.b64encode(contents).decode("ascii"),
                "assumeUpright": assume_upright,
            }
        )
    response = httpx.post(
        f"{settings.REFERENCE_ALGORITHM_URL.rstrip('/')}/api/layout",
        json={
            "provider": provider or settings.VISION_DEFAULT_PROVIDER,
            "model": model or settings.VISION_DEFAULT_MODEL,
            "pages": pages,
        },
        timeout=settings.VISION_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()
