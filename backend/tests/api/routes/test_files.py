from fastapi.testclient import TestClient

from app.core.config import settings


def test_upload_file(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/files/upload",
        headers=school_owner_token_headers,
        files={"file": ("sample.txt", b"hello exam grader", "text/plain")},
    )
    assert response.status_code == 200
    content = response.json()
    assert content["original_filename"] == "sample.txt"
    assert content["content_type"] == "text/plain"
    assert content["size_bytes"] == len(b"hello exam grader")
    assert len(content["sha256"]) == 64
