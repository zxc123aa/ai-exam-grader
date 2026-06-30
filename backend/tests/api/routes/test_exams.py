import asyncio
from io import BytesIO
import uuid

import pytest
from fastapi import HTTPException, UploadFile, status
from sqlmodel import Session
from starlette.datastructures import Headers
from fastapi.testclient import TestClient

from app import crud
from app.core.config import settings
from app.models import UserCreate
from app.services.file_storage import store_upload_file
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


PNG_BYTES = b"\x89PNG\r\n\x1a\nexam image bytes"
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
