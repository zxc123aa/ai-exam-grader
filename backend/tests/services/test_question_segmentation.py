from __future__ import annotations

import cv2
import numpy as np

from app.core.config import settings
from app.services import question_segmentation


def test_ocr_anchor_candidate_boxes_use_question_numbers(monkeypatch) -> None:
    image = np.full((420, 300, 3), 255, dtype=np.uint8)

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "status": "succeeded",
                "raw": {
                    "lines": [
                        {
                            "text": "1. Question one",
                            "confidence": 0.95,
                            "box": [35, 50, 180, 70],
                        },
                        {
                            "text": "answer line",
                            "confidence": 0.9,
                            "box": [45, 95, 260, 110],
                        },
                        {
                            "text": "2. Question two",
                            "confidence": 0.96,
                            "box": [35, 160, 180, 180],
                        },
                        {
                            "text": "3. Question three",
                            "confidence": 0.97,
                            "box": [35, 275, 200, 295],
                        },
                    ]
                },
            }

    def fake_post(*_args, **_kwargs):
        return FakeResponse()

    monkeypatch.setattr(settings, "OCR_HTTP_URL", "http://ocr-service:8010/ocr")
    monkeypatch.setattr(question_segmentation.httpx, "post", fake_post)

    candidates = question_segmentation.find_question_region_candidates(
        image,
        page_number=1,
        engine=question_segmentation.OCR_ANCHOR_ENGINE_NAME,
    )

    assert len(candidates) == 3
    assert candidates[0].source == "layout_ocr_anchor_v1"
    assert candidates[0].reasons == ["ocr-question-anchor", "ocr-layout-lines"]
    assert candidates[0].y < candidates[1].y < candidates[2].y


def test_ocr_anchor_candidate_boxes_return_empty_without_anchors(monkeypatch) -> None:
    image = np.full((420, 300, 3), 255, dtype=np.uint8)

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "status": "succeeded",
                "raw": {
                    "lines": [
                        {
                            "text": "Essay writing area",
                            "confidence": 0.95,
                            "box": [35, 50, 220, 70],
                        }
                    ]
                },
            }

    def fake_post(*_args, **_kwargs):
        return FakeResponse()

    monkeypatch.setattr(question_segmentation.httpx, "post", fake_post)

    candidates = question_segmentation.find_question_region_candidates(
        image,
        page_number=1,
        engine=question_segmentation.OCR_ANCHOR_ENGINE_NAME,
    )

    assert candidates == []


def test_ocr_anchor_candidate_boxes_skip_malformed_ocr_lines(monkeypatch) -> None:
    image = np.full((420, 300, 3), 255, dtype=np.uint8)

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "status": "succeeded",
                "raw": {
                    "lines": [
                        {
                            "text": "1. Broken box",
                            "confidence": "nan",
                            "box": [None, "bad", 180, 70],
                        },
                        {
                            "text": "2. Polygon fallback",
                            "confidence": 1.2,
                            "polygon": [[35, 160], ["180", 160], [180, 190], [35, 190]],
                        },
                        {
                            "text": "3. Question three",
                            "confidence": 0.97,
                            "box": [35, 275, 200, 295],
                        },
                    ]
                },
            }

    def fake_post(*_args, **_kwargs):
        return FakeResponse()

    monkeypatch.setattr(question_segmentation.httpx, "post", fake_post)

    candidates = question_segmentation.find_question_region_candidates(
        image,
        page_number=1,
        engine=question_segmentation.OCR_ANCHOR_ENGINE_NAME,
    )

    assert len(candidates) == 2
    assert candidates[0].confidence == 1.0
    assert candidates[0].y < candidates[1].y


def test_projection_candidate_boxes_still_work() -> None:
    image = np.full((420, 300, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (35, 50), (260, 110), (20, 20, 20), 2)

    candidates = question_segmentation.find_question_region_candidates(
        image,
        page_number=1,
    )

    assert candidates
    assert candidates[0].source == "layout_projection_v0"
