import asyncio
import base64
import uuid
import zipfile
from io import BytesIO
from unittest.mock import Mock

import pytest
from fastapi import HTTPException, UploadFile, status
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlmodel import Session
from starlette.datastructures import Headers

from app import crud
from app.api.routes import exams as exams_route
from app.core.config import settings
from app.models import UserCreate
from app.services import ocr, question_segmentation, scan_preprocessing
from app.services.file_storage import store_upload_file
from app.services.pdf_rendering import merge_pdf_bytes
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def build_test_png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (4, 4), color=(255, 255, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def build_test_zip(entries: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def build_test_scan_photo() -> bytes:
    image = Image.new("RGB", (360, 220), color=(72, 88, 82))
    draw = ImageDraw.Draw(image)
    draw.polygon(
        [(28, 24), (334, 18), (342, 196), (20, 202)],
        fill=(250, 244, 220),
    )
    draw.line([(180, 26), (180, 195)], fill=(218, 210, 190), width=2)
    draw.rectangle((60, 60, 150, 78), outline=(80, 80, 80), width=2)
    draw.rectangle((210, 80, 310, 98), outline=(80, 80, 80), width=2)
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def build_question_layout_page() -> bytes:
    image = Image.new("RGB", (800, 1100), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)
    y_positions = [110, 330, 560]
    for index, y in enumerate(y_positions, start=1):
        draw.text((70, y), f"{index}. Question {index}", fill=(20, 20, 20))
        draw.rectangle((70, y + 38, 720, y + 92), outline=(30, 30, 30), width=3)
        draw.line((90, y + 130, 700, y + 130), fill=(30, 30, 30), width=3)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001"

PNG_BYTES = b"\x89PNG\r\n\x1a\nexam image bytes"
VALID_PNG_BYTES = build_test_png()
SCAN_PHOTO_BYTES = build_test_scan_photo()
QUESTION_LAYOUT_BYTES = build_question_layout_page()
PDF_BYTES = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 44 >>
stream
BT /F1 18 Tf 50 120 Td (Hello PDF) Tj ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000241 00000 n
0000000335 00000 n
trailer
<< /Root 1 0 R /Size 6 >>
startxref
405
%%EOF
"""


def test_create_exam(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    data = {
        "org_id": DEFAULT_ORG_ID,
        "title": "Midterm Exam",
        "subject": "Math",
        "grade_level": "Grade 8",
    }
    response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json=data,
    )
    assert response.status_code == 200
    content = response.json()
    assert content["title"] == data["title"]
    assert content["subject"] == data["subject"]
    assert content["grade_level"] == data["grade_level"]
    assert content["status"] == "draft"
    assert "id" in content
    assert "owner_id" in content


def test_read_exam(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Read Exam"},
    )
    exam_id = create_response.json()["id"]
    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}",
        headers=school_owner_token_headers,
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Read Exam"


def test_read_exam_not_found(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/exams/{uuid.uuid4()}",
        headers=school_owner_token_headers,
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Exam not found"


def test_read_exams(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "List Exam"},
    )
    response = client.get(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
    )
    assert response.status_code == 200
    assert response.json()["count"] >= 1


def test_upload_exam_file(
    client: TestClient,
    school_owner_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enqueue = Mock()
    monkeypatch.setattr(
        exams_route.process_exam_document_preprocessing, "send", enqueue
    )
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Upload Exam"},
    )
    exam_id = create_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=school_owner_token_headers,
        files={"file": ("blank.pdf", PDF_BYTES, "application/pdf")},
        data={"document_type": "blank_exam"},
    )

    assert response.status_code == 200
    content = response.json()
    assert content["exam_id"] == exam_id
    assert content["document_type"] == "blank_exam"
    assert content["stored_file"]["original_filename"] == "blank.pdf"
    assert content["stored_file"]["content_type"] == "application/pdf"
    assert content["page_count"] == 1
    assert content["preprocessing_status"] == "not_required"
    enqueue.assert_not_called()


def test_read_exam_files(
    client: TestClient,
    school_owner_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enqueue = Mock()
    monkeypatch.setattr(
        exams_route.process_exam_document_preprocessing, "send", enqueue
    )
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "File List Exam"},
    )
    exam_id = create_response.json()["id"]
    client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=school_owner_token_headers,
        files={"file": ("blank.jpg", b"\xff\xd8\xff image bytes", "image/jpeg")},
    )

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=school_owner_token_headers,
    )

    assert response.status_code == 200
    content = response.json()
    assert content["count"] == 1
    assert content["data"][0]["exam_id"] == exam_id
    assert content["data"][0]["stored_file"]["original_filename"] == "blank.jpg"
    assert content["data"][0]["preprocessing_status"] == "queued"
    assert (
        content["data"][0]["original_stored_file_id"]
        == content["data"][0]["stored_file_id"]
    )
    enqueue.assert_called_once_with(content["data"][0]["id"])


def test_upload_multiple_exam_files_and_reorder_pages(
    client: TestClient,
    school_owner_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enqueue = Mock()
    monkeypatch.setattr(
        exams_route.process_exam_document_preprocessing, "send", enqueue
    )
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Multi-page Exam"},
    )
    exam_id = create_response.json()["id"]

    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files/batch",
        headers=school_owner_token_headers,
        files=[
            ("files", ("1.jpg", b"\xff\xd8\xff first page", "image/jpeg")),
            ("files", ("2.jpg", b"\xff\xd8\xff second page", "image/jpeg")),
            ("files", ("appendix.pdf", PDF_BYTES, "application/pdf")),
        ],
        data={"document_type": "blank_exam"},
    )

    assert upload_response.status_code == 200
    uploaded = upload_response.json()["data"]
    assert [item["stored_file"]["original_filename"] for item in uploaded] == [
        "1.jpg",
        "2.jpg",
        "appendix.pdf",
    ]
    assert [item["sort_order"] for item in uploaded] == [1, 2, 3]
    assert sum(item["page_count"] for item in uploaded) == 3
    assert [item["preprocessing_status"] for item in uploaded] == [
        "queued",
        "queued",
        "not_required",
    ]
    assert [call.args[0] for call in enqueue.call_args_list] == [
        uploaded[0]["id"],
        uploaded[1]["id"],
    ]

    reversed_ids = [item["id"] for item in reversed(uploaded)]
    reorder_response = client.patch(
        f"{settings.API_V1_STR}/exams/{exam_id}/files/order",
        headers=school_owner_token_headers,
        json={"document_ids": reversed_ids},
    )

    assert reorder_response.status_code == 200
    reordered = reorder_response.json()["data"]
    assert [item["id"] for item in reordered] == reversed_ids
    assert [item["sort_order"] for item in reordered] == [1, 2, 3]

    list_response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=school_owner_token_headers,
    )
    assert [item["id"] for item in list_response.json()["data"]] == reversed_ids


def test_read_exam_file_content(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Preview Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=school_owner_token_headers,
        files={"file": ("blank.png", PNG_BYTES, "image/png")},
    )
    document_id = upload_response.json()["id"]

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/files/{document_id}/content",
        headers=school_owner_token_headers,
    )

    assert response.status_code == 200
    assert response.content == PNG_BYTES
    assert response.headers["content-type"] == "image/png"


def test_read_exam_file_content_requires_authorization_header(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Protected Preview Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=school_owner_token_headers,
        files={"file": ("blank.png", PNG_BYTES, "image/png")},
    )
    document_id = upload_response.json()["id"]

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/files/{document_id}/content"
    )

    assert response.status_code == 401


def test_read_exam_file_content_rejects_query_token_only(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Query Token Preview Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=school_owner_token_headers,
        files={"file": ("blank.png", PNG_BYTES, "image/png")},
    )
    document_id = upload_response.json()["id"]
    token = school_owner_token_headers["Authorization"].replace("Bearer ", "")

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/files/{document_id}/content",
        params={"access_token": token},
    )

    assert response.status_code == 401


def test_read_pdf_exam_file_page_image(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "PDF Page Preview Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=school_owner_token_headers,
        files={"file": ("blank.pdf", PDF_BYTES, "application/pdf")},
    )
    document_id = upload_response.json()["id"]

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/files/{document_id}/pages/1/image",
        headers=school_owner_token_headers,
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content.startswith(b"\xff\xd8\xff")


def test_read_exam_region_candidates(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Candidate Regions Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=school_owner_token_headers,
        files={"file": ("layout.png", QUESTION_LAYOUT_BYTES, "image/png")},
        data={"preprocess": "none"},
    )
    document_id = upload_response.json()["id"]

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/files/{document_id}/region-candidates",
        headers=school_owner_token_headers,
    )

    assert response.status_code == 200
    content = response.json()
    assert content["engine"] == "layout_projection_v0"
    assert content["page_number"] == 1
    assert content["count"] >= 3
    first = content["data"][0]
    assert first["label"] == "Q1"
    assert first["region_type"] == "question"
    assert 0 <= first["x"] < 1
    assert 0 <= first["y"] < 1
    assert first["width"] > 0
    assert first["height"] > 0
    assert first["confidence"] > 0

    regions_response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions",
        headers=school_owner_token_headers,
    )
    assert regions_response.json()["count"] == 0


def test_read_exam_region_candidates_with_ocr_anchor_engine(
    client: TestClient, school_owner_token_headers: dict[str, str], monkeypatch
) -> None:
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
                            "box": [70, 110, 220, 135],
                        },
                        {
                            "text": "2. Question two",
                            "confidence": 0.96,
                            "box": [70, 330, 220, 355],
                        },
                        {
                            "text": "3. Question three",
                            "confidence": 0.97,
                            "box": [70, 560, 240, 585],
                        },
                    ]
                },
            }

    def fake_post(*_args, **_kwargs):
        return FakeResponse()

    monkeypatch.setattr(question_segmentation.httpx, "post", fake_post)
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "OCR Anchor Candidate Regions Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=school_owner_token_headers,
        files={"file": ("layout.png", QUESTION_LAYOUT_BYTES, "image/png")},
        data={"preprocess": "none"},
    )
    document_id = upload_response.json()["id"]

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/files/{document_id}/region-candidates"
        "?engine=layout_ocr_anchor_v1",
        headers=school_owner_token_headers,
    )

    assert response.status_code == 200
    content = response.json()
    assert content["engine"] == "layout_ocr_anchor_v1"
    assert content["count"] == 3
    assert content["data"][0]["source"] == "layout_ocr_anchor_v1"


def test_gemini_region_candidates_expose_projection_refinement(
    client: TestClient,
    school_owner_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Gemini refined layout exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=school_owner_token_headers,
        files={"file": ("layout.png", VALID_PNG_BYTES, "image/png")},
    )
    document_id = upload_response.json()["id"]
    upright_image = (
        "data:image/png;base64," + base64.b64encode(VALID_PNG_BYTES).decode()
    )

    monkeypatch.setattr(
        exams_route,
        "layout_stored_file",
        lambda **_kwargs: {
            "layouts": [
                {
                    "rotation": 0,
                    "uprightImage": upright_image,
                    "orientationElapsedMs": 80,
                    "regionModelElapsedMs": 120,
                    "refinementElapsedMs": 7,
                    "regions": [
                        {
                            "questionNumber": "1",
                            "label": "第1题",
                            "ymin": 100,
                            "xmin": 50,
                            "ymax": 300,
                            "xmax": 480,
                            "refinement": {
                                "applied": True,
                                "confidence": 0.87,
                            },
                        }
                    ],
                }
            ]
        },
    )

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/files/{document_id}/region-candidates"
        "?engine=gemini_layout_v1",
        headers=school_owner_token_headers,
    )

    assert response.status_code == 200
    content = response.json()
    assert content["layout_ms"] == 120
    assert content["refinement_ms"] == 7
    assert content["data"][0]["confidence"] == 0.87
    assert "horizontal-projection-snap" in content["data"][0]["reasons"]


def test_read_pdf_exam_file_page_image_not_found(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "PDF Page Missing Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=school_owner_token_headers,
        files={"file": ("blank.pdf", PDF_BYTES, "application/pdf")},
    )
    document_id = upload_response.json()["id"]

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/files/{document_id}/pages/2/image",
        headers=school_owner_token_headers,
    )

    assert response.status_code == 404


def test_upload_exam_file_rejects_unsupported_type(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Reject Upload Exam"},
    )
    exam_id = create_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=school_owner_token_headers,
        files={"file": ("notes.txt", b"plain text", "text/plain")},
    )

    assert response.status_code == 415


def test_upload_exam_file_rejects_invalid_pdf(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Invalid PDF Upload Exam"},
    )
    exam_id = create_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=school_owner_token_headers,
        files={"file": ("blank.pdf", b"%PDF-1.4 exam", "application/pdf")},
    )

    assert response.status_code == 415


def test_store_exam_upload_rejects_oversized_file_and_cleans_disk(
    db: Session, tmp_path, monkeypatch
) -> None:
    user = crud.create_user(
        session=db,
        user_create=UserCreate(email=random_email(), password=random_lower_string()),
    )
    monkeypatch.setattr(settings, "LOCAL_UPLOAD_DIR", tmp_path)
    upload = UploadFile(
        filename="blank.png",
        file=BytesIO(PNG_BYTES),
        headers=Headers({"content-type": "image/png"}),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            store_upload_file(
                session=db,
                current_user=user,
                file=upload,
                validate_exam_file=True,
                max_bytes=4,
            )
        )

    assert exc_info.value.status_code == status.HTTP_413_CONTENT_TOO_LARGE
    assert list(tmp_path.rglob("*")) == []


def test_normal_user_cannot_upload_to_other_users_exam(
    client: TestClient,
    db: Session,
    school_owner_token_headers: dict[str, str],
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Private Exam"},
    )
    exam_id = create_response.json()["id"]
    password = random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(email=random_email(), password=password),
    )
    headers = user_authentication_headers(
        client=client, email=user.email, password=password
    )

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=headers,
        files={"file": ("blank.png", PNG_BYTES, "image/png")},
    )

    assert response.status_code == 404


def test_school_owner_exam_upload_is_owned_by_exam_owner(
    client: TestClient,
    db: Session,
    school_owner_token_headers: dict[str, str],
) -> None:
    password = random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(), password=password, org_id=DEFAULT_ORG_ID
        ),
    )
    headers = user_authentication_headers(
        client=client, email=user.email, password=password
    )
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Owned Upload Exam"},
    )
    exam_id = create_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=school_owner_token_headers,
        files={"file": ("blank.png", PNG_BYTES, "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["stored_file"]["uploaded_by_id"] == str(user.id)


def test_create_read_update_delete_exam_region(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Region Exam"},
    )
    exam_id = create_response.json()["id"]

    region_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions",
        headers=school_owner_token_headers,
        json={
            "label": "Q1",
            "region_type": "question",
            "page_number": 1,
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.4,
        },
    )
    assert region_response.status_code == 200
    region = region_response.json()
    assert region["label"] == "Q1"
    assert region["exam_id"] == exam_id

    list_response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions",
        headers=school_owner_token_headers,
    )
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 1

    update_response = client.patch(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions/{region['id']}",
        headers=school_owner_token_headers,
        json={"label": "Q1 revised", "width": 0.25},
    )
    assert update_response.status_code == 200
    assert update_response.json()["label"] == "Q1 revised"
    assert update_response.json()["width"] == 0.25

    delete_response = client.delete(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions/{region['id']}",
        headers=school_owner_token_headers,
    )
    assert delete_response.status_code == 200


def test_create_exam_region_rejects_out_of_bounds(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Bounds Exam"},
    )
    exam_id = create_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions",
        headers=school_owner_token_headers,
        json={
            "label": "Q outside",
            "region_type": "question",
            "page_number": 1,
            "x": 0.8,
            "y": 0.2,
            "width": 0.3,
            "height": 0.4,
        },
    )

    assert response.status_code == 422


def test_create_read_update_delete_standard_answer(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Standard Answer Exam"},
    )
    exam_id = create_response.json()["id"]
    region_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions",
        headers=school_owner_token_headers,
        json={
            "label": "Q1",
            "region_type": "question",
            "page_number": 1,
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.4,
        },
    )
    region_id = region_response.json()["id"]

    create_answer_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/answers",
        headers=school_owner_token_headers,
        json={
            "exam_region_id": region_id,
            "answer_text": "Use conservation of energy.",
            "max_score": 6,
            "rubric_text": "Award method and final value.",
            "scoring_points": [
                {
                    "id": "formula",
                    "description": "Writes the correct formula",
                    "points": 2,
                    "required": True,
                }
            ],
            "status": "draft",
        },
    )
    assert create_answer_response.status_code == 200
    answer = create_answer_response.json()
    assert answer["exam_id"] == exam_id
    assert answer["exam_region_id"] == region_id
    assert answer["max_score"] == 6
    assert answer["scoring_points"][0]["id"] == "formula"

    list_response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/answers",
        headers=school_owner_token_headers,
    )
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 1

    read_response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/answers/{answer['id']}",
        headers=school_owner_token_headers,
    )
    assert read_response.status_code == 200
    assert read_response.json()["answer_text"] == "Use conservation of energy."

    update_response = client.patch(
        f"{settings.API_V1_STR}/exams/{exam_id}/answers/{answer['id']}",
        headers=school_owner_token_headers,
        json={"status": "ready", "max_score": 8},
    )
    assert update_response.status_code == 200
    assert update_response.json()["status"] == "ready"
    assert update_response.json()["max_score"] == 8

    delete_response = client.delete(
        f"{settings.API_V1_STR}/exams/{exam_id}/answers/{answer['id']}",
        headers=school_owner_token_headers,
    )
    assert delete_response.status_code == 200

    empty_list_response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/answers",
        headers=school_owner_token_headers,
    )
    assert empty_list_response.json()["count"] == 0


def test_create_standard_answer_rejects_duplicate_region(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Duplicate Answer Exam"},
    )
    exam_id = create_response.json()["id"]
    region_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions",
        headers=school_owner_token_headers,
        json={
            "label": "Q1",
            "region_type": "question",
            "page_number": 1,
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.4,
        },
    )
    region_id = region_response.json()["id"]
    payload = {
        "exam_region_id": region_id,
        "answer_text": "Answer",
        "max_score": 1,
        "scoring_points": [],
        "status": "draft",
    }

    first_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/answers",
        headers=school_owner_token_headers,
        json=payload,
    )
    second_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/answers",
        headers=school_owner_token_headers,
        json=payload,
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 409


def test_create_standard_answer_rejects_non_question_region(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Non Question Answer Exam"},
    )
    exam_id = create_response.json()["id"]
    region_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions",
        headers=school_owner_token_headers,
        json={
            "label": "Header",
            "region_type": "header",
            "page_number": 1,
            "x": 0.1,
            "y": 0.1,
            "width": 0.3,
            "height": 0.1,
        },
    )
    region_id = region_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/answers",
        headers=school_owner_token_headers,
        json={
            "exam_region_id": region_id,
            "answer_text": "Should fail",
            "max_score": 1,
            "scoring_points": [],
        },
    )

    assert response.status_code == 422
    assert "question regions" in response.json()["detail"]


def test_normal_user_cannot_read_other_users_standard_answers(
    client: TestClient,
    db: Session,
    school_owner_token_headers: dict[str, str],
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Private Answer Exam"},
    )
    exam_id = create_response.json()["id"]
    password = random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(email=random_email(), password=password),
    )
    headers = user_authentication_headers(
        client=client, email=user.email, password=password
    )

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/answers",
        headers=headers,
    )

    assert response.status_code == 404


def test_update_exam_region_rejects_out_of_bounds(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Update Bounds Exam"},
    )
    exam_id = create_response.json()["id"]
    region_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions",
        headers=school_owner_token_headers,
        json={
            "label": "Q1",
            "region_type": "question",
            "page_number": 1,
            "x": 0.8,
            "y": 0.2,
            "width": 0.1,
            "height": 0.3,
        },
    )
    region_id = region_response.json()["id"]

    response = client.patch(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions/{region_id}",
        headers=school_owner_token_headers,
        json={"width": 0.3},
    )

    assert response.status_code == 422


def test_upload_student_submission(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Submission Upload Exam"},
    )
    exam_id = create_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("student-a.pdf", PDF_BYTES, "application/pdf")},
        data={"student_name": "Student A", "student_identifier": "A001"},
    )

    assert response.status_code == 200
    content = response.json()
    assert content["exam_id"] == exam_id
    assert content["student_name"] == "Student A"
    assert content["student_identifier"] == "A001"
    assert content["status"] == "registration_pending"
    assert content["registration_status"] == "pending"
    assert content["stored_file"]["original_filename"] == "student-a.pdf"
    assert content["stored_file"]["content_type"] == "application/pdf"
    assert content["page_count"] == 1


def test_upload_student_submission_with_client_original_and_quality(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Client Preprocess Exam"},
    )
    exam_id = create_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={
            "file": ("student-a-p1.jpg", SCAN_PHOTO_BYTES, "image/jpeg"),
            "original_file": (
                "student-a-original.jpg",
                SCAN_PHOTO_BYTES,
                "image/jpeg",
            ),
        },
        data={
            "student_name": "Student A",
            "preprocess": "none",
            "client_quality": "0.87",
        },
    )

    assert response.status_code == 200
    content = response.json()
    assert content["original_stored_file_id"] is not None
    assert content["original_stored_file_id"] != content["stored_file"]["id"]
    assert content["registration_quality"] == 0.87
    assert content["registration_notes"] == "客户端本地预处理；检测置信度 87%"


def test_upload_student_submission_without_client_metadata_unchanged(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Plain Photo Upload Exam"},
    )
    exam_id = create_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("student-a.jpg", SCAN_PHOTO_BYTES, "image/jpeg")},
        data={"student_name": "Student A", "preprocess": "none"},
    )

    assert response.status_code == 200
    content = response.json()
    assert content["original_stored_file_id"] is None
    assert content["registration_quality"] is None
    assert content["registration_notes"] is None


def test_read_student_submissions(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Submission List Exam"},
    )
    exam_id = create_response.json()["id"]
    client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("student-a.png", PNG_BYTES, "image/png")},
        data={"student_name": "Student A"},
    )

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
    )

    assert response.status_code == 200
    content = response.json()
    assert content["count"] == 1
    assert content["data"][0]["exam_id"] == exam_id
    assert content["data"][0]["student_name"] == "Student A"
    assert content["data"][0]["stored_file"]["original_filename"] == "student-a.png"


def test_preprocess_student_submission_photo_creates_pdf_submission(
    client: TestClient,
    school_owner_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "SCAN_ENGINE", "opencv_v1")
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Scan Photo Exam"},
    )
    exam_id = create_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/preprocess-photo",
        headers=school_owner_token_headers,
        files={"file": ("phone.jpg", SCAN_PHOTO_BYTES, "image/jpeg")},
        data={"student_name": "Student Scan", "student_identifier": "SCAN001"},
    )

    assert response.status_code == 200
    content = response.json()
    assert content["student_name"] == "Student Scan"
    assert content["student_identifier"] == "SCAN001"
    assert content["status"] == "registration_pending"
    assert content["registration_status"] == "pending"
    assert content["registration_notes"].startswith("手机照片已预处理")
    assert "扫描质量：" in content["registration_notes"]
    assert content["registration_homography"]["source"] == (
        "mobile_document_preprocessing_v2"
    )
    assert content["registration_homography"]["scan_engine"] == "opencv_v1"
    assert content["registration_homography"]["quality"]["status"] in {
        "pass",
        "review",
    }
    assert isinstance(content["registration_homography"]["quality"]["warnings"], list)
    assert content["registration_homography"]["split"]["strategy"] in {
        "detected_gutter",
        "center_fallback",
    }
    assert content["registration_homography"]["split"]["gutter_ratio"] is not None
    assert len(content["registration_homography"]["pages"]) == 2
    assert content["original_stored_file_id"] is not None
    assert content["stored_file"]["original_filename"] == "phone-preprocessed.pdf"
    assert content["stored_file"]["content_type"] == "application/pdf"
    assert content["page_count"] == 2

    page_response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{content['id']}/pages/1/image",
        headers=school_owner_token_headers,
    )
    assert page_response.status_code == 200
    assert page_response.headers["content-type"] == "image/jpeg"
    assert page_response.content.startswith(b"\xff\xd8\xff")


def test_preprocess_student_submission_photo_uses_scan_http_engine(
    client: TestClient,
    school_owner_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Scan HTTP Exam"},
    )
    exam_id = create_response.json()["id"]
    page_b64 = base64.b64encode(build_test_png()).decode()

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "engine": "paddlex_doc_preprocessor_v1",
                "pages": [
                    {
                        "name": "page_1.jpg",
                        "image_base64": page_b64,
                    }
                ],
                "quality": {
                    "status": "review",
                    "warnings": [
                        {
                            "code": "content_near_top_edge",
                            "severity": "warning",
                            "message": "Crop should be reviewed.",
                        }
                    ],
                },
                "split": {"strategy": "scan_service_single_page"},
            }

    class FakeClient:
        def __init__(self, *, trust_env: bool):
            assert trust_env is False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(settings, "SCAN_ENGINE", "scan_http")
    monkeypatch.setattr(scan_preprocessing.httpx, "Client", FakeClient)

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/preprocess-photo",
        headers=school_owner_token_headers,
        files={"file": ("phone.jpg", SCAN_PHOTO_BYTES, "image/jpeg")},
        data={"student_name": "Student Scan HTTP"},
    )

    assert response.status_code == 200
    content = response.json()
    assert content["student_name"] == "Student Scan HTTP"
    assert content["page_count"] == 1
    assert "扫描质量：review" in content["registration_notes"]
    assert content["registration_homography"]["scan_engine"] == "scan_http"
    assert content["registration_homography"]["quality"]["status"] == "review"
    assert content["registration_homography"]["quality"]["warnings"][0]["code"] == (
        "content_near_top_edge"
    )
    assert content["registration_homography"]["split"]["strategy"] == (
        "scan_service_single_page"
    )


def test_append_student_submission_pages_pdf(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Submission Append PDF Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("student-a.pdf", PDF_BYTES, "application/pdf")},
        data={"student_name": "Student A"},
    )
    submission_id = upload_response.json()["id"]
    assert upload_response.json()["page_count"] == 1

    append_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/pages",
        headers=school_owner_token_headers,
        files={"file": ("student-a-page2.pdf", PDF_BYTES, "application/pdf")},
    )

    assert append_response.status_code == 200
    content = append_response.json()
    assert content["id"] == submission_id
    assert content["student_name"] == "Student A"
    assert content["page_count"] == 2
    assert content["stored_file"]["content_type"] == "application/pdf"

    for page_number in (1, 2):
        page_response = client.get(
            f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}"
            f"/pages/{page_number}/image",
            headers=school_owner_token_headers,
        )
        assert page_response.status_code == 200
        assert page_response.headers["content-type"] == "image/jpeg"


def test_append_student_submission_pages_photo_runs_split(
    client: TestClient,
    school_owner_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "SCAN_ENGINE", "opencv_v1")
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Submission Append Photo Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("student-a.pdf", PDF_BYTES, "application/pdf")},
        data={"student_name": "Student Photo"},
    )
    submission_id = upload_response.json()["id"]
    assert upload_response.json()["page_count"] == 1

    append_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/pages",
        headers=school_owner_token_headers,
        files={"file": ("phone.jpg", SCAN_PHOTO_BYTES, "image/jpeg")},
    )

    assert append_response.status_code == 200
    content = append_response.json()
    assert content["id"] == submission_id
    assert content["stored_file"]["content_type"] == "application/pdf"
    # 1 original PDF page + 2 pages split from the double-page photo
    assert content["page_count"] == 3

    page_response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}"
        "/pages/3/image",
        headers=school_owner_token_headers,
    )
    assert page_response.status_code == 200
    assert page_response.content.startswith(b"\xff\xd8\xff")


def test_upload_student_submission_zip(
    client: TestClient,
    school_owner_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "SCAN_ENGINE", "opencv_v1")
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Submission Zip Exam"},
    )
    exam_id = create_response.json()["id"]
    zip_bytes = build_test_zip(
        {
            "10.jpg": SCAN_PHOTO_BYTES,
            "2.jpg": SCAN_PHOTO_BYTES,
        }
    )

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("student-a.zip", zip_bytes, "application/zip")},
        data={"student_name": "Student Zip", "class_name": "001班"},
    )

    assert response.status_code == 200
    content = response.json()
    assert content["student_name"] == "Student Zip"
    assert content["class_name"] == "001班"
    assert content["status"] == "registration_pending"
    # 原始 zip 留存在 original，答卷文件为解包合并后的 PDF
    assert content["original_stored_file_id"] is not None
    assert content["stored_file"]["original_filename"] == "student-a-scanned.pdf"
    assert content["stored_file"]["content_type"] == "application/pdf"
    assert "ZIP 解包" in content["registration_notes"]
    # 两张双页照片各拆 2 页
    assert content["page_count"] == 4


def test_append_student_submission_pages_zip(
    client: TestClient,
    school_owner_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "SCAN_ENGINE", "opencv_v1")
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Submission Append Zip Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("student-a.pdf", PDF_BYTES, "application/pdf")},
        data={"student_name": "Student Zip Append"},
    )
    submission_id = upload_response.json()["id"]
    assert upload_response.json()["page_count"] == 1

    zip_bytes = build_test_zip({"0_0.jpg": SCAN_PHOTO_BYTES})
    append_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/pages",
        headers=school_owner_token_headers,
        files={"file": ("student-a-pages.zip", zip_bytes, "application/zip")},
    )

    assert append_response.status_code == 200
    content = append_response.json()
    assert content["id"] == submission_id
    assert content["stored_file"]["content_type"] == "application/pdf"
    # 1 页原 PDF + zip 内双页照片拆出的 2 页
    assert content["page_count"] == 3


def test_upload_student_submission_zip_empty_rejected(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Submission Empty Zip Exam"},
    )
    exam_id = create_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("empty.zip", build_test_zip({}), "application/zip")},
        data={"student_name": "Student Empty Zip"},
    )

    assert response.status_code == 422


def test_upload_student_submission_zip_skips_non_images(
    client: TestClient,
    school_owner_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "SCAN_ENGINE", "opencv_v1")
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Submission Mixed Zip Exam"},
    )
    exam_id = create_response.json()["id"]
    zip_bytes = build_test_zip(
        {
            "说明.txt": b"not an image",
            "readme.pdf": PDF_BYTES,
            "1.jpg": SCAN_PHOTO_BYTES,
        }
    )

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("mixed.zip", zip_bytes, "application/zip")},
        data={"student_name": "Student Mixed Zip"},
    )

    assert response.status_code == 200
    content = response.json()
    # 非图片文件被跳过，仅 1 张双页照片拆 2 页
    assert content["page_count"] == 2
    assert "1 张照片" in content["registration_notes"]


def test_append_student_submission_pages_confirmed_registration_conflict(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Submission Append Conflict Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("student-a.pdf", PDF_BYTES, "application/pdf")},
    )
    submission_id = upload_response.json()["id"]
    client.patch(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/registration",
        headers=school_owner_token_headers,
        json={
            "registration_status": "manual_confirmed",
            "registration_quality": 1,
            "registration_notes": "Teacher confirmed",
            "registration_homography": {"matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]},
        },
    )

    append_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/pages",
        headers=school_owner_token_headers,
        files={"file": ("student-a-page2.pdf", PDF_BYTES, "application/pdf")},
    )

    assert append_response.status_code == 409


def test_read_student_submission_page_image(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Submission Preview Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("student-a.png", PNG_BYTES, "image/png")},
    )
    submission_id = upload_response.json()["id"]

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/pages/1/image",
        headers=school_owner_token_headers,
    )

    assert response.status_code == 200
    assert response.content == PNG_BYTES
    assert response.headers["content-type"] == "image/png"


def test_update_student_submission_registration_manual_confirmed(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Submission Registration Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("student-a.png", PNG_BYTES, "image/png")},
    )
    submission_id = upload_response.json()["id"]

    response = client.patch(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/registration",
        headers=school_owner_token_headers,
        json={
            "registration_status": "manual_confirmed",
            "registration_quality": 1,
            "registration_notes": "Teacher confirmed same-layout scan",
            "registration_homography": {"matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]},
        },
    )

    assert response.status_code == 200
    content = response.json()
    assert content["status"] == "ready_for_review"
    assert content["registration_status"] == "manual_confirmed"
    assert content["registration_quality"] == 1
    assert content["registration_homography"]["matrix"][0] == [1, 0, 0]
    assert content["registered_at"] is not None


def test_update_student_submission_registration_failed(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Submission Registration Failed Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("student-a.png", PNG_BYTES, "image/png")},
    )
    submission_id = upload_response.json()["id"]

    response = client.patch(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/registration",
        headers=school_owner_token_headers,
        json={
            "registration_status": "failed",
            "registration_quality": 0,
            "registration_notes": "Wrong exam template",
        },
    )

    assert response.status_code == 200
    content = response.json()
    assert content["status"] == "registration_failed"
    assert content["registration_status"] == "failed"
    assert content["registration_quality"] == 0
    assert content["registration_notes"] == "Wrong exam template"


def test_student_submission_page_image_requires_authorization_header(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Submission Protected Preview Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("student-a.png", PNG_BYTES, "image/png")},
    )
    submission_id = upload_response.json()["id"]

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/pages/1/image"
    )

    assert response.status_code == 401


def test_read_student_submission_template_regions(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Submission Regions Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("student-a.png", VALID_PNG_BYTES, "image/png")},
    )
    submission_id = upload_response.json()["id"]
    region_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions",
        headers=school_owner_token_headers,
        json={
            "label": "Q1",
            "region_type": "question",
            "page_number": 1,
            "x": 0.0,
            "y": 0.0,
            "width": 0.5,
            "height": 0.5,
        },
    )

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/regions",
        headers=school_owner_token_headers,
        params={"page_number": 1},
    )

    assert region_response.status_code == 200
    assert response.status_code == 200
    content = response.json()
    assert content["count"] == 1
    assert content["data"][0]["label"] == "Q1"
    assert content["data"][0]["page_number"] == 1


def test_read_student_submission_region_crop(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Submission Crop Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("student-a.png", VALID_PNG_BYTES, "image/png")},
    )
    submission_id = upload_response.json()["id"]
    region_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions",
        headers=school_owner_token_headers,
        json={
            "label": "Q1",
            "region_type": "question",
            "page_number": 1,
            "x": 0.0,
            "y": 0.0,
            "width": 0.5,
            "height": 0.5,
        },
    )
    region_id = region_response.json()["id"]

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/regions/{region_id}/crop",
        headers=school_owner_token_headers,
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")


def build_single_page_pdf(color: tuple[int, int, int]) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (200, 200), color=color).save(buffer, format="PDF")
    return buffer.getvalue()


def test_read_student_submission_template_regions_global_page_number(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Global Page Regions Exam"},
    )
    exam_id = create_response.json()["id"]
    two_page_pdf = merge_pdf_bytes(
        build_single_page_pdf((255, 255, 255)),
        build_single_page_pdf((255, 255, 255)),
    )
    document_ids = []
    for name in ("doc-a.pdf", "doc-b.pdf"):
        upload_doc_response = client.post(
            f"{settings.API_V1_STR}/exams/{exam_id}/files",
            headers=school_owner_token_headers,
            files={"file": (name, two_page_pdf, "application/pdf")},
            data={"document_type": "blank_exam"},
        )
        assert upload_doc_response.status_code == 200
        assert upload_doc_response.json()["page_count"] == 2
        document_ids.append(upload_doc_response.json()["id"])
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("student-a.png", VALID_PNG_BYTES, "image/png")},
    )
    submission_id = upload_response.json()["id"]
    region_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions",
        headers=school_owner_token_headers,
        json={
            "label": "Q1",
            "region_type": "question",
            "page_number": 1,
            "exam_document_id": document_ids[1],
            "x": 0.0,
            "y": 0.0,
            "width": 0.5,
            "height": 0.5,
        },
    )
    assert region_response.status_code == 200

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/regions",
        headers=school_owner_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert content["count"] == 1
    # Second 2-page document, document-local page 1 -> global paper page 3.
    assert content["data"][0]["page_number"] == 3

    filtered = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/regions",
        headers=school_owner_token_headers,
        params={"page_number": 3},
    )
    assert filtered.status_code == 200
    assert filtered.json()["count"] == 1

    unfiltered = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/regions",
        headers=school_owner_token_headers,
        params={"page_number": 1},
    )
    assert unfiltered.status_code == 200
    assert unfiltered.json()["count"] == 0


def test_read_student_submission_region_crop_uses_global_page_number(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Global Page Crop Exam"},
    )
    exam_id = create_response.json()["id"]
    two_page_pdf = merge_pdf_bytes(
        build_single_page_pdf((255, 255, 255)),
        build_single_page_pdf((255, 255, 255)),
    )
    document_ids = []
    for name in ("doc-a.pdf", "doc-b.pdf"):
        upload_doc_response = client.post(
            f"{settings.API_V1_STR}/exams/{exam_id}/files",
            headers=school_owner_token_headers,
            files={"file": (name, two_page_pdf, "application/pdf")},
            data={"document_type": "blank_exam"},
        )
        assert upload_doc_response.status_code == 200
        document_ids.append(upload_doc_response.json()["id"])
    # Submission pages: 1 = red, 2 = green, 3 = blue.
    submission_pdf = merge_pdf_bytes(
        build_single_page_pdf((220, 30, 30)),
        build_single_page_pdf((30, 220, 30)),
        build_single_page_pdf((30, 30, 220)),
    )
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("student-a.pdf", submission_pdf, "application/pdf")},
    )
    submission_id = upload_response.json()["id"]
    region_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions",
        headers=school_owner_token_headers,
        json={
            "label": "Q1",
            "region_type": "question",
            "page_number": 1,
            "exam_document_id": document_ids[1],
            "x": 0.0,
            "y": 0.0,
            "width": 0.5,
            "height": 0.5,
        },
    )
    region_id = region_response.json()["id"]

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/regions/{region_id}/crop",
        headers=school_owner_token_headers,
    )

    assert response.status_code == 200
    crop = Image.open(BytesIO(response.content)).convert("RGB")
    pixels = list(crop.getdata())
    avg_r = sum(pixel[0] for pixel in pixels) / len(pixels)
    avg_g = sum(pixel[1] for pixel in pixels) / len(pixels)
    avg_b = sum(pixel[2] for pixel in pixels) / len(pixels)
    # The crop must come from submission page 3 (blue), not document-local
    # page 1 (red).
    assert avg_b > avg_r + 80
    assert avg_b > avg_g + 80


def test_create_update_and_delete_submission_annotation(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Submission Annotation Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("student-a.png", VALID_PNG_BYTES, "image/png")},
    )
    submission_id = upload_response.json()["id"]
    region_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions",
        headers=school_owner_token_headers,
        json={
            "label": "Q1",
            "region_type": "question",
            "page_number": 1,
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.2,
        },
    )
    region_id = region_response.json()["id"]

    create_annotation_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/annotations",
        headers=school_owner_token_headers,
        json={
            "exam_region_id": region_id,
            "label": "Q1",
            "status": "needs_review",
            "page_number": 1,
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.2,
            "score": 3,
            "max_score": 5,
            "comment": "Check method step",
        },
    )

    assert create_annotation_response.status_code == 200
    annotation = create_annotation_response.json()
    annotation_id = annotation["id"]
    assert annotation["exam_region_id"] == region_id
    assert annotation["label"] == "Q1"
    assert annotation["status"] == "needs_review"
    assert annotation["score"] == 3
    assert annotation["max_score"] == 5

    list_response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/annotations",
        headers=school_owner_token_headers,
    )
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 1

    update_response = client.patch(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/annotations/{annotation_id}",
        headers=school_owner_token_headers,
        json={"status": "accepted", "score": 4, "comment": "Looks correct"},
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["status"] == "accepted"
    assert updated["score"] == 4
    assert updated["comment"] == "Looks correct"

    delete_response = client.delete(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/annotations/{annotation_id}",
        headers=school_owner_token_headers,
    )
    assert delete_response.status_code == 200

    empty_response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/annotations",
        headers=school_owner_token_headers,
    )
    assert empty_response.json()["count"] == 0


def test_create_student_submission_processing_task_generates_annotation_placeholders(
    client: TestClient,
    school_owner_token_headers: dict[str, str],
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Submission Processing Task Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("student-a.png", VALID_PNG_BYTES, "image/png")},
    )
    submission_id = upload_response.json()["id"]
    client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions",
        headers=school_owner_token_headers,
        json={
            "label": "Q1",
            "region_type": "question",
            "page_number": 1,
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.2,
        },
    )

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/processing-tasks",
        headers=school_owner_token_headers,
    )

    assert response.status_code == 200
    task = response.json()
    assert task["task_type"] == "student_submission_processing"
    assert task["status"] == "succeeded"
    assert task["progress"] == 100
    assert task["input_ref"]["exam_id"] == exam_id
    assert task["input_ref"]["submission_id"] == submission_id
    assert task["output_ref"]["pipeline"] == "submission_processing_v1"
    assert task["output_ref"]["region_count"] == 1
    assert task["output_ref"]["stages"]["region_crops"] == "succeeded"
    assert task["output_ref"]["stages"]["registration"]["source"] == "identity_v1"
    assert task["output_ref"]["stages"]["ocr"]["status"] == "needs_configuration"
    assert task["output_ref"]["stages"]["grading"]["status"] == "skipped_missing_answer"
    assert len(task["output_ref"]["region_crops"]) == 1
    assert task["output_ref"]["region_crops"][0]["label"] == "Q1"
    assert task["output_ref"]["region_crops"][0]["storage_key"].endswith(".png")
    assert len(task["output_ref"]["ocr_results"]) == 1
    assert task["output_ref"]["ocr_results"][0]["status"] == "not_configured"
    assert len(task["output_ref"]["grading_results"]) == 1
    assert (
        task["output_ref"]["grading_results"][0]["status"] == "skipped_missing_answer"
    )
    assert task["output_ref"]["created_annotation_count"] == 1

    annotations_response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/annotations",
        headers=school_owner_token_headers,
    )
    assert annotations_response.status_code == 200
    annotations = annotations_response.json()
    assert annotations["count"] == 1
    assert annotations["data"][0]["label"] == "Q1"
    assert annotations["data"][0]["status"] == "needs_review"
    assert annotations["data"][0]["comment"] == "Awaiting OCR and AI grading result."
    assert annotations["data"][0]["ocr_status"] == "not_configured"
    assert annotations["data"][0]["ocr_engine"] == "disabled"
    assert annotations["data"][0]["ocr_text"] is None
    assert annotations["data"][0]["grading_status"] == "skipped_missing_answer"
    assert annotations["data"][0]["suggested_score"] is None
    assert (
        annotations["data"][0]["grading_reasons"][0]["type"]
        == "missing_standard_answer"
    )
    annotation_id = annotations["data"][0]["id"]

    crop_response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/annotations/{annotation_id}/crop",
        headers=school_owner_token_headers,
    )
    assert crop_response.status_code == 200
    assert crop_response.headers["content-type"] == "image/png"
    assert crop_response.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_student_submission_processing_task_writes_paddle_http_ocr_result(
    client: TestClient,
    school_owner_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "status": "succeeded",
                "text": "Recognized answer",
                "confidence": 0.94,
                "engine": "paddleocr-gpu-cu130",
            }

    def fake_post(*_args, **_kwargs):
        return FakeResponse()

    monkeypatch.setattr(settings, "OCR_ENGINE", "paddle_http")
    monkeypatch.setattr(settings, "OCR_HTTP_URL", "http://ocr-service:8010/ocr")
    monkeypatch.setattr(ocr.httpx, "post", fake_post)

    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Paddle OCR Processing Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("student-a.png", VALID_PNG_BYTES, "image/png")},
    )
    submission_id = upload_response.json()["id"]
    region_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions",
        headers=school_owner_token_headers,
        json={
            "label": "Q1",
            "region_type": "question",
            "page_number": 1,
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.2,
        },
    )
    region_id = region_response.json()["id"]
    answer_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/answers",
        headers=school_owner_token_headers,
        json={
            "exam_region_id": region_id,
            "answer_text": "Recognized answer",
            "max_score": 5,
            "rubric_text": "Match the expected answer.",
            "scoring_points": [
                {
                    "id": "content",
                    "description": "Recognized answer content",
                    "points": 5,
                    "required": True,
                }
            ],
            "status": "ready",
        },
    )
    assert answer_response.status_code == 200

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/processing-tasks",
        headers=school_owner_token_headers,
    )

    assert response.status_code == 200
    task = response.json()
    assert task["status"] == "succeeded"
    assert task["output_ref"]["stages"]["ocr"] == "succeeded"
    assert task["output_ref"]["stages"]["grading"] == "succeeded"
    assert task["output_ref"]["ocr_results"][0]["status"] == "succeeded"
    assert task["output_ref"]["ocr_results"][0]["engine"] == "paddleocr-gpu-cu130"
    assert task["output_ref"]["ocr_results"][0]["confidence"] == 0.94
    assert task["output_ref"]["grading_results"][0]["status"] == "succeeded"
    assert task["output_ref"]["grading_results"][0]["suggested_score"] == 5

    annotations_response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/annotations",
        headers=school_owner_token_headers,
    )
    annotation = annotations_response.json()["data"][0]
    assert annotation["ocr_status"] == "succeeded"
    assert annotation["ocr_engine"] == "paddleocr-gpu-cu130"
    assert annotation["ocr_confidence"] == 0.94
    assert annotation["ocr_text"] == "Recognized answer"
    assert annotation["max_score"] == 5
    assert annotation["grading_status"] == "succeeded"
    assert annotation["suggested_score"] == 5
    assert annotation["suggested_comment"]
    assert annotation["grading_confidence"] == 0.94
    assert annotation["grading_reasons"][0]["type"] == "text_overlap_heuristic_v0"
    assert annotation["answer_key_updated_at"] is not None

    stale_response = client.patch(
        f"{settings.API_V1_STR}/exams/{exam_id}/answers/{answer_response.json()['id']}",
        headers=school_owner_token_headers,
        json={"answer_text": "Updated recognized answer"},
    )
    assert stale_response.status_code == 200
    stale_annotations_response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/annotations",
        headers=school_owner_token_headers,
    )
    stale_annotation = stale_annotations_response.json()["data"][0]
    assert stale_annotation["grading_status"] == "stale"
    assert stale_annotation["score"] is None


def test_submission_annotation_rejects_region_from_other_exam(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Annotation Exam A"},
    )
    exam_id = create_response.json()["id"]
    other_create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Annotation Exam B"},
    )
    other_exam_id = other_create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("student-a.png", VALID_PNG_BYTES, "image/png")},
    )
    submission_id = upload_response.json()["id"]
    other_region_response = client.post(
        f"{settings.API_V1_STR}/exams/{other_exam_id}/regions",
        headers=school_owner_token_headers,
        json={
            "label": "Q1",
            "region_type": "question",
            "page_number": 1,
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.2,
        },
    )
    other_region_id = other_region_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/annotations",
        headers=school_owner_token_headers,
        json={
            "exam_region_id": other_region_id,
            "label": "Q1",
            "status": "needs_review",
            "page_number": 1,
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.2,
        },
    )

    assert response.status_code == 404


def test_upload_student_submission_rejects_invalid_pdf(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Invalid Submission PDF Exam"},
    )
    exam_id = create_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("student-a.pdf", b"%PDF-1.4 exam", "application/pdf")},
    )

    assert response.status_code == 415


def test_normal_user_cannot_upload_submission_to_other_users_exam(
    client: TestClient,
    db: Session,
    school_owner_token_headers: dict[str, str],
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Private Submission Exam"},
    )
    exam_id = create_response.json()["id"]
    password = random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(email=random_email(), password=password),
    )
    headers = user_authentication_headers(
        client=client, email=user.email, password=password
    )

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=headers,
        files={"file": ("student-a.png", PNG_BYTES, "image/png")},
    )

    assert response.status_code == 404


def test_school_owner_submission_upload_is_owned_by_exam_owner(
    client: TestClient,
    db: Session,
    school_owner_token_headers: dict[str, str],
) -> None:
    password = random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(), password=password, org_id=DEFAULT_ORG_ID
        ),
    )
    headers = user_authentication_headers(
        client=client, email=user.email, password=password
    )
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Owned Submission Upload Exam"},
    )
    exam_id = create_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("student-a.png", PNG_BYTES, "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["stored_file"]["uploaded_by_id"] == str(user.id)


def test_create_exam_analysis_report(
    client: TestClient,
    school_owner_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Analysis Report Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=school_owner_token_headers,
        files={"file": ("student-a.png", VALID_PNG_BYTES, "image/png")},
        data={"student_name": "Student A", "class_name": "Class 1"},
    )
    submission_id = upload_response.json()["id"]
    client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/annotations",
        headers=school_owner_token_headers,
        json={
            "label": "Q1",
            "status": "accepted",
            "page_number": 1,
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.2,
            "score": 4,
            "max_score": 5,
        },
    )

    def fake_call_json_model(**_kwargs: object) -> tuple[dict, str, int]:
        return (
            {
                "overall": "班级整体表现良好，平均分处于中上水平。",
                "weak": "第 Q1 题得分率偏低，是主要薄弱点。",
                "polar": "前后 25% 学生均分差距较小，分化不明显。",
                "advice": "建议针对薄弱题目安排专题讲评并布置分层练习。",
            },
            "mock-model",
            1,
        )

    monkeypatch.setattr(exams_route, "call_json_model", fake_call_json_model)

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/analysis-report",
        headers=school_owner_token_headers,
    )

    assert response.status_code == 200
    content = response.json()
    assert content["overall"] == "班级整体表现良好，平均分处于中上水平。"
    assert content["weak"]
    assert content["polar"]
    assert content["advice"]
    assert content["generated_at"]


def test_create_exam_analysis_report_requires_scores(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Analysis Report Empty Exam"},
    )
    exam_id = create_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/analysis-report",
        headers=school_owner_token_headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "该考试还没有批改成绩，无法生成学情报告"
