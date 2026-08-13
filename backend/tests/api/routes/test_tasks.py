from fastapi.testclient import TestClient

from app.core.config import settings


def test_create_test_task(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/tasks/test",
        headers=superuser_token_headers,
        json={"task_type": "test"},
    )
    assert response.status_code == 200
    content = response.json()
    assert content["task_type"] == "test"
    assert content["status"] in {"queued", "running", "succeeded"}
    assert 0 <= content["progress"] <= 100


def test_read_task(client: TestClient, superuser_token_headers: dict[str, str]) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/tasks/test",
        headers=superuser_token_headers,
        json={"task_type": "test"},
    )
    task_id = create_response.json()["id"]
    response = client.get(
        f"{settings.API_V1_STR}/tasks/{task_id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    assert response.json()["id"] == task_id
