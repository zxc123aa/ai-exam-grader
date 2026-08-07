from fastapi.testclient import TestClient

from app.core.config import settings


def test_new_exam_summary_points_to_import(
    client: TestClient, school_owner_token_headers: dict[str, str]
) -> None:
    created = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"title": "工作流汇总测试"},
    )
    assert created.status_code == 200

    response = client.get(
        f"{settings.API_V1_STR}/exams/{created.json()['id']}/workflow-summary",
        headers=school_owner_token_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["next_action"] == "import_paper"
    assert payload["next_label"] == "导入模板卷"
    assert payload["steps"][0]["status"] == "active"
