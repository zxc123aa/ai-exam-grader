import asyncio
import base64
import uuid
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile, status
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlmodel import Session
from starlette.datastructures import Headers

from app import crud
from app.core.config import settings
from app.models import UserCreate
from app.services import ocr, scan_preprocessing
from app.services.file_storage import store_upload_file
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def build_test_png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (4, 4), color=(255, 255, 255)).save(buffer, format="PNG")
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
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    data = {"title": "Midterm Exam", "subject": "Math", "grade_level": "Grade 8"}
    response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
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
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Read Exam"},
    )
    exam_id = create_response.json()["id"]
    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Read Exam"


def test_read_exam_not_found(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/exams/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Exam not found"


def test_read_exams(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "List Exam"},
    )
    response = client.get(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    assert response.json()["count"] >= 1


def test_upload_exam_file(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Upload Exam"},
    )
    exam_id = create_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=superuser_token_headers,
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


def test_read_exam_files(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "File List Exam"},
    )
    exam_id = create_response.json()["id"]
    client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=superuser_token_headers,
        files={"file": ("blank.jpg", b"\xff\xd8\xff image bytes", "image/jpeg")},
    )

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    content = response.json()
    assert content["count"] == 1
    assert content["data"][0]["exam_id"] == exam_id
    assert content["data"][0]["stored_file"]["original_filename"] == "blank.jpg"


def test_read_exam_file_content(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Preview Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=superuser_token_headers,
        files={"file": ("blank.png", PNG_BYTES, "image/png")},
    )
    document_id = upload_response.json()["id"]

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/files/{document_id}/content",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.content == PNG_BYTES
    assert response.headers["content-type"] == "image/png"


def test_read_exam_file_content_requires_authorization_header(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Protected Preview Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=superuser_token_headers,
        files={"file": ("blank.png", PNG_BYTES, "image/png")},
    )
    document_id = upload_response.json()["id"]

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/files/{document_id}/content"
    )

    assert response.status_code == 401


def test_read_exam_file_content_rejects_query_token_only(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Query Token Preview Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=superuser_token_headers,
        files={"file": ("blank.png", PNG_BYTES, "image/png")},
    )
    document_id = upload_response.json()["id"]
    token = superuser_token_headers["Authorization"].replace("Bearer ", "")

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/files/{document_id}/content",
        params={"access_token": token},
    )

    assert response.status_code == 401


def test_read_pdf_exam_file_page_image(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "PDF Page Preview Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=superuser_token_headers,
        files={"file": ("blank.pdf", PDF_BYTES, "application/pdf")},
    )
    document_id = upload_response.json()["id"]

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/files/{document_id}/pages/1/image",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_read_exam_region_candidates(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Candidate Regions Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=superuser_token_headers,
        files={"file": ("layout.png", QUESTION_LAYOUT_BYTES, "image/png")},
    )
    document_id = upload_response.json()["id"]

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/files/{document_id}/region-candidates",
        headers=superuser_token_headers,
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
        headers=superuser_token_headers,
    )
    assert regions_response.json()["count"] == 0


def test_read_pdf_exam_file_page_image_not_found(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "PDF Page Missing Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=superuser_token_headers,
        files={"file": ("blank.pdf", PDF_BYTES, "application/pdf")},
    )
    document_id = upload_response.json()["id"]

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/files/{document_id}/pages/2/image",
        headers=superuser_token_headers,
    )

    assert response.status_code == 404


def test_upload_exam_file_rejects_unsupported_type(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Reject Upload Exam"},
    )
    exam_id = create_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=superuser_token_headers,
        files={"file": ("notes.txt", b"plain text", "text/plain")},
    )

    assert response.status_code == 415


def test_upload_exam_file_rejects_invalid_pdf(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Invalid PDF Upload Exam"},
    )
    exam_id = create_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=superuser_token_headers,
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
    superuser_token_headers: dict[str, str],
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Private Exam"},
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

    assert response.status_code == 403


def test_superuser_exam_upload_is_owned_by_exam_owner(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    password = random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(email=random_email(), password=password),
    )
    headers = user_authentication_headers(
        client=client, email=user.email, password=password
    )
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=headers,
        json={"title": "Owned Upload Exam"},
    )
    exam_id = create_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=superuser_token_headers,
        files={"file": ("blank.png", PNG_BYTES, "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["stored_file"]["uploaded_by_id"] == str(user.id)


def test_create_read_update_delete_exam_region(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Region Exam"},
    )
    exam_id = create_response.json()["id"]

    region_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions",
        headers=superuser_token_headers,
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
        headers=superuser_token_headers,
    )
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 1

    update_response = client.patch(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions/{region['id']}",
        headers=superuser_token_headers,
        json={"label": "Q1 revised", "width": 0.25},
    )
    assert update_response.status_code == 200
    assert update_response.json()["label"] == "Q1 revised"
    assert update_response.json()["width"] == 0.25

    delete_response = client.delete(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions/{region['id']}",
        headers=superuser_token_headers,
    )
    assert delete_response.status_code == 200


def test_create_exam_region_rejects_out_of_bounds(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Bounds Exam"},
    )
    exam_id = create_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions",
        headers=superuser_token_headers,
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


def test_update_exam_region_rejects_out_of_bounds(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Update Bounds Exam"},
    )
    exam_id = create_response.json()["id"]
    region_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions",
        headers=superuser_token_headers,
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
        headers=superuser_token_headers,
        json={"width": 0.3},
    )

    assert response.status_code == 422


def test_upload_student_submission(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Submission Upload Exam"},
    )
    exam_id = create_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=superuser_token_headers,
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


def test_read_student_submissions(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Submission List Exam"},
    )
    exam_id = create_response.json()["id"]
    client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=superuser_token_headers,
        files={"file": ("student-a.png", PNG_BYTES, "image/png")},
        data={"student_name": "Student A"},
    )

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    content = response.json()
    assert content["count"] == 1
    assert content["data"][0]["exam_id"] == exam_id
    assert content["data"][0]["student_name"] == "Student A"
    assert content["data"][0]["stored_file"]["original_filename"] == "student-a.png"


def test_preprocess_student_submission_photo_creates_pdf_submission(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Scan Photo Exam"},
    )
    exam_id = create_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/preprocess-photo",
        headers=superuser_token_headers,
        files={"file": ("phone.jpg", SCAN_PHOTO_BYTES, "image/jpeg")},
        data={"student_name": "Student Scan", "student_identifier": "SCAN001"},
    )

    assert response.status_code == 200
    content = response.json()
    assert content["student_name"] == "Student Scan"
    assert content["student_identifier"] == "SCAN001"
    assert content["status"] == "registration_pending"
    assert content["registration_status"] == "pending"
    assert content["registration_notes"].startswith("Preprocessed from mobile photo")
    assert "scan_quality=" in content["registration_notes"]
    assert content["registration_homography"]["source"] == (
        "mobile_photo_preprocessing_v1"
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
    assert len(content["registration_homography"]["split"]["pages"]) == 2
    assert content["stored_file"]["original_filename"] == "phone-preprocessed.pdf"
    assert content["stored_file"]["content_type"] == "application/pdf"
    assert content["page_count"] == 2

    page_response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{content['id']}/pages/1/image",
        headers=superuser_token_headers,
    )
    assert page_response.status_code == 200
    assert page_response.headers["content-type"] == "image/png"
    assert page_response.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_preprocess_student_submission_photo_uses_scan_http_engine(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Scan HTTP Exam"},
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

    def fake_post(*_args, **_kwargs):
        return FakeResponse()

    monkeypatch.setattr(settings, "SCAN_ENGINE", "scan_http")
    monkeypatch.setattr(scan_preprocessing.httpx, "post", fake_post)

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/preprocess-photo",
        headers=superuser_token_headers,
        files={"file": ("phone.jpg", SCAN_PHOTO_BYTES, "image/jpeg")},
        data={"student_name": "Student Scan HTTP"},
    )

    assert response.status_code == 200
    content = response.json()
    assert content["student_name"] == "Student Scan HTTP"
    assert content["page_count"] == 1
    assert "scan_quality=review" in content["registration_notes"]
    assert content["registration_homography"]["scan_engine"] == "scan_http"
    assert content["registration_homography"]["quality"]["status"] == "review"
    assert content["registration_homography"]["quality"]["warnings"][0]["code"] == (
        "content_near_top_edge"
    )
    assert content["registration_homography"]["split"]["strategy"] == (
        "scan_service_single_page"
    )


def test_read_student_submission_page_image(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Submission Preview Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=superuser_token_headers,
        files={"file": ("student-a.png", PNG_BYTES, "image/png")},
    )
    submission_id = upload_response.json()["id"]

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/pages/1/image",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.content == PNG_BYTES
    assert response.headers["content-type"] == "image/png"


def test_update_student_submission_registration_manual_confirmed(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Submission Registration Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=superuser_token_headers,
        files={"file": ("student-a.png", PNG_BYTES, "image/png")},
    )
    submission_id = upload_response.json()["id"]

    response = client.patch(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/registration",
        headers=superuser_token_headers,
        json={
            "registration_status": "manual_confirmed",
            "registration_quality": 1,
            "registration_notes": "Teacher confirmed same-layout scan",
            "registration_homography": {
                "matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
            },
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
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Submission Registration Failed Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=superuser_token_headers,
        files={"file": ("student-a.png", PNG_BYTES, "image/png")},
    )
    submission_id = upload_response.json()["id"]

    response = client.patch(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/registration",
        headers=superuser_token_headers,
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
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Submission Protected Preview Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=superuser_token_headers,
        files={"file": ("student-a.png", PNG_BYTES, "image/png")},
    )
    submission_id = upload_response.json()["id"]

    response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/pages/1/image"
    )

    assert response.status_code == 401


def test_read_student_submission_template_regions(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Submission Regions Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=superuser_token_headers,
        files={"file": ("student-a.png", VALID_PNG_BYTES, "image/png")},
    )
    submission_id = upload_response.json()["id"]
    region_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions",
        headers=superuser_token_headers,
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
        headers=superuser_token_headers,
        params={"page_number": 1},
    )

    assert region_response.status_code == 200
    assert response.status_code == 200
    content = response.json()
    assert content["count"] == 1
    assert content["data"][0]["label"] == "Q1"
    assert content["data"][0]["page_number"] == 1


def test_read_student_submission_region_crop(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Submission Crop Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=superuser_token_headers,
        files={"file": ("student-a.png", VALID_PNG_BYTES, "image/png")},
    )
    submission_id = upload_response.json()["id"]
    region_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions",
        headers=superuser_token_headers,
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
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_create_update_and_delete_submission_annotation(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Submission Annotation Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=superuser_token_headers,
        files={"file": ("student-a.png", VALID_PNG_BYTES, "image/png")},
    )
    submission_id = upload_response.json()["id"]
    region_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions",
        headers=superuser_token_headers,
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
        headers=superuser_token_headers,
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
        headers=superuser_token_headers,
    )
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 1

    update_response = client.patch(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/annotations/{annotation_id}",
        headers=superuser_token_headers,
        json={"status": "accepted", "score": 4, "comment": "Looks correct"},
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["status"] == "accepted"
    assert updated["score"] == 4
    assert updated["comment"] == "Looks correct"

    delete_response = client.delete(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/annotations/{annotation_id}",
        headers=superuser_token_headers,
    )
    assert delete_response.status_code == 200

    empty_response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/annotations",
        headers=superuser_token_headers,
    )
    assert empty_response.json()["count"] == 0


def test_create_student_submission_processing_task_generates_annotation_placeholders(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Submission Processing Task Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=superuser_token_headers,
        files={"file": ("student-a.png", VALID_PNG_BYTES, "image/png")},
    )
    submission_id = upload_response.json()["id"]
    client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions",
        headers=superuser_token_headers,
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
        headers=superuser_token_headers,
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
    assert len(task["output_ref"]["region_crops"]) == 1
    assert task["output_ref"]["region_crops"][0]["label"] == "Q1"
    assert task["output_ref"]["region_crops"][0]["storage_key"].endswith(".png")
    assert len(task["output_ref"]["ocr_results"]) == 1
    assert task["output_ref"]["ocr_results"][0]["status"] == "not_configured"
    assert task["output_ref"]["created_annotation_count"] == 1

    annotations_response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/annotations",
        headers=superuser_token_headers,
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
    annotation_id = annotations["data"][0]["id"]

    crop_response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/annotations/{annotation_id}/crop",
        headers=superuser_token_headers,
    )
    assert crop_response.status_code == 200
    assert crop_response.headers["content-type"] == "image/png"
    assert crop_response.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_student_submission_processing_task_writes_paddle_http_ocr_result(
    client: TestClient,
    superuser_token_headers: dict[str, str],
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
        headers=superuser_token_headers,
        json={"title": "Paddle OCR Processing Exam"},
    )
    exam_id = create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=superuser_token_headers,
        files={"file": ("student-a.png", VALID_PNG_BYTES, "image/png")},
    )
    submission_id = upload_response.json()["id"]
    client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/regions",
        headers=superuser_token_headers,
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
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    task = response.json()
    assert task["status"] == "succeeded"
    assert task["output_ref"]["stages"]["ocr"] == "succeeded"
    assert task["output_ref"]["ocr_results"][0]["status"] == "succeeded"
    assert task["output_ref"]["ocr_results"][0]["engine"] == "paddleocr-gpu-cu130"
    assert task["output_ref"]["ocr_results"][0]["confidence"] == 0.94

    annotations_response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions/{submission_id}/annotations",
        headers=superuser_token_headers,
    )
    annotation = annotations_response.json()["data"][0]
    assert annotation["ocr_status"] == "succeeded"
    assert annotation["ocr_engine"] == "paddleocr-gpu-cu130"
    assert annotation["ocr_confidence"] == 0.94
    assert annotation["ocr_text"] == "Recognized answer"


def test_submission_annotation_rejects_region_from_other_exam(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Annotation Exam A"},
    )
    exam_id = create_response.json()["id"]
    other_create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Annotation Exam B"},
    )
    other_exam_id = other_create_response.json()["id"]
    upload_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=superuser_token_headers,
        files={"file": ("student-a.png", VALID_PNG_BYTES, "image/png")},
    )
    submission_id = upload_response.json()["id"]
    other_region_response = client.post(
        f"{settings.API_V1_STR}/exams/{other_exam_id}/regions",
        headers=superuser_token_headers,
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
        headers=superuser_token_headers,
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
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Invalid Submission PDF Exam"},
    )
    exam_id = create_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=superuser_token_headers,
        files={"file": ("student-a.pdf", b"%PDF-1.4 exam", "application/pdf")},
    )

    assert response.status_code == 415


def test_normal_user_cannot_upload_submission_to_other_users_exam(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"title": "Private Submission Exam"},
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

    assert response.status_code == 403


def test_superuser_submission_upload_is_owned_by_exam_owner(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    password = random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(email=random_email(), password=password),
    )
    headers = user_authentication_headers(
        client=client, email=user.email, password=password
    )
    create_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=headers,
        json={"title": "Owned Submission Upload Exam"},
    )
    exam_id = create_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=superuser_token_headers,
        files={"file": ("student-a.png", PNG_BYTES, "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["stored_file"]["uploaded_by_id"] == str(user.id)
