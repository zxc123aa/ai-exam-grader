import httpx
import pytest

from app.services import new_api_billing


@pytest.fixture(autouse=True)
def _validated_public_relay(monkeypatch) -> None:
    # URL safety has dedicated coverage in test_provider_security. These tests
    # exercise only New API response compatibility and must not depend on DNS.
    monkeypatch.setattr(
        new_api_billing,
        "validate_provider_base_url",
        lambda value: value.rstrip("/"),
    )


def test_fetch_new_api_billing_normalizes_quota_and_consume_logs(monkeypatch) -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/api/status":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "system_name": "PomoAi",
                        "version": "test-version",
                        "quota_per_unit": 500_000,
                        "usd_exchange_rate": 7.3,
                    }
                },
            )
        if request.url.path == "/api/usage/token/":
            assert request.headers["Authorization"] == "Bearer secret"
            return httpx.Response(
                200,
                json={
                    "data": {
                        "total_granted": 10_000,
                        "total_used": 20_000,
                        "total_available": -10_000,
                        "unlimited_quota": True,
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "type": 2,
                        "request_id": "new-api-request-1",
                        "model_name": "gpt-5.6-sol",
                        "prompt_tokens": 1465,
                        "completion_tokens": 9,
                        "quota": 570,
                        "created_at": 1_785_144_713,
                        "use_time": 4,
                    },
                    {
                        "type": 5,
                        "request_id": "failed-request",
                        "quota": 0,
                        "created_at": 1_785_144_714,
                    },
                ]
            },
        )

    real_client = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        new_api_billing.httpx,
        "Client",
        lambda **_kwargs: real_client(transport=transport),
    )

    report = new_api_billing.fetch_new_api_billing(
        base_url="https://relay.example/v1",
        api_key="secret",
        timeout_seconds=30,
    )

    assert requested_paths == ["/api/status", "/api/usage/token/", "/api/log/token"]
    assert report.account.system_name == "PomoAi"
    assert report.account.total_used_quota == 20_000
    assert report.account.quota_to_micrormb(570) == 8_322
    assert len(report.logs) == 1
    assert report.logs[0].request_id == "new-api-request-1"
    assert report.logs[0].cost_micrormb == 8_322


def test_fetch_new_api_billing_uses_system_access_token_and_user_id(
    monkeypatch,
) -> None:
    requested: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append((request.url.path, request.headers.get("New-Api-User")))
        if request.url.path == "/api/status":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "system_name": "PomoAi",
                        "version": "old-version",
                        "quota_per_unit": 500_000,
                        "usd_exchange_rate": 7.3,
                    }
                },
            )
        assert request.headers["Authorization"] == "Bearer system-secret"
        assert request.headers["New-Api-User"] == "42"
        if request.url.path == "/api/user/self":
            return httpx.Response(
                200,
                json={"success": True, "data": {"quota": 800, "used_quota": 200}},
            )
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "page": 1,
                    "page_size": 100,
                    "total": 1,
                    "items": [
                        {
                            "type": 2,
                            "request_id": "account-request-1",
                            "model_name": "gpt-5.6-sol",
                            "prompt_tokens": 100,
                            "completion_tokens": 20,
                            "quota": 50,
                            "created_at": 1_785_144_713,
                        }
                    ],
                },
            },
        )

    real_client = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        new_api_billing.httpx,
        "Client",
        lambda **_kwargs: real_client(transport=transport),
    )

    report = new_api_billing.fetch_new_api_billing(
        base_url="https://relay.example/v1",
        billing_access_token="system-secret",
        billing_user_id=42,
        timeout_seconds=30,
    )

    assert requested == [
        ("/api/status", None),
        ("/api/user/self", "42"),
        ("/api/log/self", "42"),
    ]
    assert report.account.total_granted_quota == 1_000
    assert report.account.total_used_quota == 200
    assert report.logs[0].request_id == "account-request-1"
