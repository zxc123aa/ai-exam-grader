from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.models import RecognitionRunCreate
from app.services import reference_algorithm


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


def test_process_stored_file_sends_evidence_verification_mode(monkeypatch) -> None:
    captured: dict = {}

    def fake_process_pages(*, pages, verification_mode):
        captured["pages"] = pages
        captured["verificationMode"] = verification_mode
        return reference_algorithm._normalize_reference_payload(
            {
                "results": [
                    {
                        "questionNumber": "21",
                        "question": "21. 伴随着低碳理念，请计算阻力。",
                    }
                ]
            }
        )

    monkeypatch.setattr(
        reference_algorithm, "get_stored_file_path", lambda _file: Path("paper.png")
    )
    monkeypatch.setattr(
        reference_algorithm, "_page_images", lambda *_args: [b"image-bytes"]
    )
    monkeypatch.setattr(reference_algorithm, "_process_pages", fake_process_pages)
    stored_file = SimpleNamespace(
        content_type="image/png", original_filename="paper.png"
    )

    payload = reference_algorithm.process_stored_file(
        stored_file=stored_file,
        verification_mode="evidence",
    )

    assert captured["verificationMode"] == "evidence"
    assert captured["pages"][0]["fileName"] == "paper.png"
    assert payload["results"][0]["question"] == "伴随着低碳理念，请计算阻力。"
    assert payload["results"][0]["rawQuestion"] == "21. 伴随着低碳理念，请计算阻力。"


def test_process_stored_files_defaults_to_fast_verification_mode(monkeypatch) -> None:
    captured: dict = {}

    def fake_process_pages(*, pages, verification_mode):
        captured["pages"] = pages
        captured["verificationMode"] = verification_mode
        return {"results": []}

    monkeypatch.setattr(
        reference_algorithm, "get_stored_file_path", lambda _file: Path("paper.png")
    )
    monkeypatch.setattr(
        reference_algorithm, "_page_images", lambda *_args: [b"image-bytes"]
    )
    monkeypatch.setattr(reference_algorithm, "_process_pages", fake_process_pages)
    document = SimpleNamespace(id="doc-1")
    stored_file = SimpleNamespace(
        content_type="image/png", original_filename="paper.png"
    )

    reference_algorithm.process_stored_files(documents=[(document, stored_file)])

    assert captured["verificationMode"] == "fast"


def test_recognition_run_create_defaults_to_selective_mode() -> None:
    payload = RecognitionRunCreate(
        exam_id="00000000-0000-0000-0000-000000000001",
        submission_id="00000000-0000-0000-0000-000000000002",
    )

    assert payload.verification_mode == "selective"


def test_verification_mode_preserves_selective() -> None:
    assert reference_algorithm._verification_mode("selective") == "selective"


def test_page_context_includes_adjacent_pages_across_image_files(monkeypatch) -> None:
    captured: dict = {}
    documents = [
        (
            SimpleNamespace(id=f"doc-{index}"),
            SimpleNamespace(
                content_type="image/png", original_filename=f"page-{index}.png"
            ),
        )
        for index in range(1, 5)
    ]

    monkeypatch.setattr(
        reference_algorithm, "get_stored_file_path", lambda _file: Path("paper.png")
    )
    monkeypatch.setattr(
        reference_algorithm,
        "_stored_file_page_image",
        lambda *, stored_file, page_number: (
            stored_file.original_filename.encode(),
            "image/png",
        ),
    )

    def fake_process_pages(*, pages, verification_mode):
        captured["page_ids"] = [page["id"] for page in pages]
        captured["verification_mode"] = verification_mode
        return {
            "blocks": [
                {"id": "left-q1", "pageId": "doc-1:page:1"},
                {"id": "current-q3", "pageId": "doc-2:page:1"},
                {"id": "next-q3", "pageId": "doc-3:page:1"},
                {"id": "next-q4", "pageId": "doc-3:page:1"},
            ],
            "results": [
                {"blockId": "left-q1", "sourceBlockIds": ["left-q1"]},
                {
                    "blockId": "current-q3",
                    "sourceBlockIds": ["current-q3", "next-q3"],
                },
                {"blockId": "next-q4", "sourceBlockIds": ["next-q4"]},
            ],
            "timing": {},
        }

    monkeypatch.setattr(reference_algorithm, "_process_pages", fake_process_pages)

    payload = reference_algorithm.process_stored_file_page_context(
        documents=documents,
        target_document_id="doc-2",
        target_page_number=1,
    )

    assert captured["page_ids"] == [
        "doc-1:page:1",
        "doc-2:page:1",
        "doc-3:page:1",
    ]
    assert captured["verification_mode"] == "fast"
    assert payload["requestedPageId"] == "doc-2:page:1"
    assert payload["contextPageIds"] == captured["page_ids"]
    assert payload["updatedPageIds"] == ["doc-2:page:1"]
    assert payload["contextResultCount"] == 3
    assert payload["returnedResultCount"] == 1
    assert payload["results"][0]["sourceBlockIds"] == [
        "current-q3",
        "next-q3",
    ]
