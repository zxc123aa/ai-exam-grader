import base64
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.api.routes import provider_channels
from app.core.config import settings
from app.models import (
    ModelUsageEvent,
    ModelUsageStatus,
    Organization,
    ProviderAuditLog,
    ProviderChannel,
    ProviderChannelKind,
    ProviderChannelStatus,
    ProviderCredential,
    ProviderInternalRateVersion,
    ProviderModelMapping,
    ProviderProtocol,
    UsageReconciliationStatus,
    UserCreate,
    UserRole,
)
from app.services import new_api_billing, provider_security
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string

URL = f"{settings.API_V1_STR}/platform/provider-channels"


def _master_key() -> str:
    return base64.urlsafe_b64encode(b"p" * 32).decode("ascii")


def _public_dns(*_args, **_kwargs):
    return [(2, 1, 6, "", ("93.184.216.34", 443))]


def _support_headers(client: TestClient, db: Session) -> dict[str, str]:
    password = random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(),
            password=password,
            role=UserRole.PLATFORM_SUPPORT,
        ),
    )
    return user_authentication_headers(
        client=client, email=user.email, password=password
    )


def _route_channel(
    db: Session, *, model: str, upstream_model: str | None = None
) -> tuple[ProviderChannel, ProviderModelMapping]:
    channel = ProviderChannel(
        code=f"route-{random_lower_string()[:10]}",
        display_name=f"路由测试 {model}",
        kind=ProviderChannelKind.AUTHORIZED_RELAY,
        protocol=ProviderProtocol.OPENAI_CHAT,
        base_url="https://relay.example/v1",
        status=ProviderChannelStatus.ACTIVE,
    )
    db.add(channel)
    db.flush()
    mapping = ProviderModelMapping(
        channel_id=channel.id,
        canonical_model=model,
        upstream_model=upstream_model or f"upstream-{model}",
        usage_metering_verified=True,
    )
    db.add(mapping)
    db.commit()
    db.refresh(channel)
    db.refresh(mapping)
    return channel, mapping


def _save_and_publish_route(
    client: TestClient,
    headers: dict[str, str],
    *,
    purpose: str,
    model: str,
    mapping_ids: list[str],
    routing_mode: str = "balanced",
) -> dict:
    saved = client.put(
        f"{URL}/routes/{purpose}",
        headers=headers,
        json={
            "canonical_model": model,
            "routing_mode": routing_mode,
            "targets": [
                {"mapping_id": mapping_id, "priority": 1, "weight": 100}
                for mapping_id in mapping_ids
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    versions = client.get(
        f"{URL}/routes/{purpose}/versions",
        headers=headers,
        params={"canonical_model": model},
    )
    assert versions.status_code == 200, versions.text
    draft = next(item for item in versions.json() if item["status"] == "draft")
    published = client.post(
        f"{URL}/routes/{purpose}/versions/{draft['id']}/publish",
        headers=headers,
    )
    assert published.status_code == 200, published.text
    return published.json()


def test_only_superuser_can_manage_channels(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    assert client.get(URL, headers=superuser_token_headers).status_code == 200
    assert client.get(URL, headers=_support_headers(client, db)).status_code == 403


def test_channel_crud_masks_secret_and_audits(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "PROVIDER_CREDENTIAL_MASTER_KEY", _master_key())
    monkeypatch.setattr(provider_security.socket, "getaddrinfo", _public_dns)
    code = f"relay-{random_lower_string()[:8]}"
    secret = "sk-never-return-this"
    response = client.post(
        URL,
        headers=superuser_token_headers,
        json={
            "code": code,
            "display_name": "授权中转",
            "kind": "authorized_relay",
            "protocol": "openai_chat",
            "base_url": "https://relay.example/v1",
            "api_key": secret,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["credential_configured"] is True
    assert body["credential_last_four"] == "this"
    assert secret not in response.text
    assert "ciphertext" not in response.text

    listed = client.get(URL, headers=superuser_token_headers)
    assert listed.status_code == 200
    assert secret not in listed.text
    channel_id = body["id"]
    mapping = client.post(
        f"{URL}/{channel_id}/models",
        headers=superuser_token_headers,
        json={
            "canonical_model": "gpt-5.6-sol-test-main",
            "upstream_model": "gpt-upstream",
        },
    )
    assert mapping.status_code == 200, mapping.text
    mapping_id = mapping.json()["id"]
    auto_route = client.get(
        f"{URL}/routes/subjective_grading",
        headers=superuser_token_headers,
        params={"canonical_model": "gpt-5.6-sol-test-main"},
    )
    assert auto_route.status_code == 404, auto_route.text
    duplicate = client.post(
        f"{URL}/{channel_id}/models",
        headers=superuser_token_headers,
        json={"canonical_model": "gpt-5.6-sol-test-main", "upstream_model": "other"},
    )
    assert duplicate.status_code == 409
    enabled = client.patch(
        f"{URL}/{channel_id}",
        headers=superuser_token_headers,
        json={"enabled": True},
    )
    assert enabled.status_code == 200, enabled.text
    route = client.put(
        f"{URL}/routes/subjective_grading",
        headers=superuser_token_headers,
        json={
            "canonical_model": "gpt-5.6-sol-test-main",
            "max_attempts": 2,
            "targets": [{"mapping_id": mapping_id, "priority": 10, "weight": 100}],
        },
    )
    assert route.status_code == 200, route.text
    assert route.json()["targets"][0]["channel_code"] == code
    second_channel = client.post(
        URL,
        headers=superuser_token_headers,
        json={
            "code": f"backup-{random_lower_string()[:8]}",
            "display_name": "备用中转",
            "kind": "authorized_relay",
            "protocol": "openai_chat",
            "base_url": "https://backup.example/v1",
            "api_key": "backup-secret",
        },
    )
    assert second_channel.status_code == 200
    backup_mapping = client.post(
        f"{URL}/{second_channel.json()['id']}/models",
        headers=superuser_token_headers,
        json={
            "canonical_model": "gpt-5.6-sol-test-main",
            "upstream_model": "backup-model",
        },
    )
    assert backup_mapping.status_code == 200
    added = client.post(
        f"{URL}/routes/subjective_grading/targets",
        headers=superuser_token_headers,
        params={"canonical_model": "gpt-5.6-sol-test-main"},
        json={
            "mapping_id": backup_mapping.json()["id"],
            "priority": 20,
            "weight": 100,
        },
    )
    assert added.status_code == 200, added.text
    assert len(added.json()["targets"]) == 2
    read_route = client.get(
        f"{URL}/routes/subjective_grading",
        headers=superuser_token_headers,
        params={"canonical_model": "gpt-5.6-sol-test-main"},
    )
    assert read_route.status_code == 200
    assert read_route.json()["max_attempts"] == 2
    next_mapping = client.post(
        f"{URL}/{channel_id}/models",
        headers=superuser_token_headers,
        json={
            "canonical_model": "gpt-5.6-terra-test-next",
            "upstream_model": "next-model",
        },
    )
    assert next_mapping.status_code == 200, next_mapping.text
    stored_next_mapping = db.get(ProviderModelMapping, next_mapping.json()["id"])
    assert stored_next_mapping is not None
    stored_next_mapping.usage_metering_verified = True
    db.add(stored_next_mapping)
    db.commit()
    switched = client.put(
        f"{URL}/routes/subjective_grading",
        headers=superuser_token_headers,
        json={
            "canonical_model": "gpt-5.6-terra-test-next",
            "targets": [{"mapping_id": next_mapping.json()["id"]}],
        },
    )
    assert switched.status_code == 200, switched.text
    switch_versions = client.get(
        f"{URL}/routes/subjective_grading/versions",
        headers=superuser_token_headers,
        params={"canonical_model": "gpt-5.6-terra-test-next"},
    )
    switch_draft = next(
        item for item in switch_versions.json() if item["status"] == "draft"
    )
    published_switch = client.post(
        f"{URL}/routes/subjective_grading/versions/{switch_draft['id']}/publish",
        headers=superuser_token_headers,
    )
    assert published_switch.status_code == 200, published_switch.text
    reused = client.put(
        f"{URL}/routes/rubric_generation",
        headers=superuser_token_headers,
        json={
            "canonical_model": "gpt-5.6-terra-test-next",
            "targets": [{"mapping_id": next_mapping.json()["id"]}],
        },
    )
    assert reused.status_code == 200, reused.text
    reuse_versions = client.get(
        f"{URL}/routes/rubric_generation/versions",
        headers=superuser_token_headers,
        params={"canonical_model": "gpt-5.6-terra-test-next"},
    )
    reuse_draft = next(
        item for item in reuse_versions.json() if item["status"] == "draft"
    )
    published_reuse = client.post(
        f"{URL}/routes/rubric_generation/versions/{reuse_draft['id']}/publish",
        headers=superuser_token_headers,
    )
    assert published_reuse.status_code == 200, published_reuse.text
    routes = client.get(f"{URL}/routes", headers=superuser_token_headers)
    assert routes.status_code == 200, routes.text
    grading_routes = [
        item for item in routes.json() if item["purpose"] == "subjective_grading"
    ]
    assert "gpt-5.6-terra-test-next" in {
        item["canonical_model"] for item in grading_routes if item["enabled"]
    }
    assert any(
        item["purpose"] == "rubric_generation"
        and item["canonical_model"] == "gpt-5.6-terra-test-next"
        and item["enabled"]
        for item in routes.json()
    )
    assert db.exec(
        select(ProviderAuditLog).where(ProviderAuditLog.channel_id == channel_id)
    ).all()


def test_discover_upstream_models_uses_saved_credential_without_returning_it(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "PROVIDER_CREDENTIAL_MASTER_KEY", _master_key())
    monkeypatch.setattr(provider_security.socket, "getaddrinfo", _public_dns)
    secret = "sk-discovery-never-return"
    channel = client.post(
        URL,
        headers=superuser_token_headers,
        json={
            "code": f"catalog-{random_lower_string()[:8]}",
            "display_name": "模型目录测试",
            "kind": "authorized_relay",
            "base_url": "https://relay.example/v1",
            "api_key": secret,
        },
    )
    assert channel.status_code == 200, channel.text

    def fake_get(_self, url, **kwargs):
        assert url == "https://relay.example/v1/models"
        assert kwargs["headers"]["Authorization"] == f"Bearer {secret}"
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "data": [
                    {"id": "gemini-3.5-flash"},
                    {"id": "claude-sonnet-4.5"},
                    {"id": "gemini-3.5-flash"},
                ]
            },
        )

    monkeypatch.setattr(provider_channels.httpx.Client, "get", fake_get)
    response = client.post(
        f"{URL}/{channel.json()['id']}/models/discover",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["models"] == ["claude-sonnet-4.5", "gemini-3.5-flash"]
    assert response.json()["count"] == 2
    assert secret not in response.text


def test_import_environment_channels_with_models_is_idempotent(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "PROVIDER_CREDENTIAL_MASTER_KEY", _master_key())
    monkeypatch.setattr(provider_security.socket, "getaddrinfo", _public_dns)
    for name in (
        "PROVIDER_POMOAI_API_KEY",
        "PROVIDER_FLUXNODE_GEMINI_API_KEY",
        "PROVIDER_FLUXNODE_GROK_API_KEY",
        "PROVIDER_KIMI_API_KEY",
    ):
        monkeypatch.setattr(settings, name, f"secret-{name.lower()}")

    imported = client.post(f"{URL}/import-environment", headers=superuser_token_headers)
    assert imported.status_code == 200, imported.text
    channels = {item["code"]: item for item in imported.json()["data"]}
    assert {"pomoai", "fluxnode_gemini", "fluxnode_grok", "kimi"} <= channels.keys()
    assert channels["pomoai"]["credential_configured"] is True
    assert "secret-provider" not in imported.text

    models = client.get(
        f"{URL}/{channels['pomoai']['id']}/models",
        headers=superuser_token_headers,
    )
    assert models.status_code == 200
    assert {item["canonical_model"] for item in models.json()} >= {
        "gpt-5.6-sol",
        "gemini-3.5-flash",
    }

    repeated = client.post(f"{URL}/import-environment", headers=superuser_token_headers)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["count"] == imported.json()["count"]


def test_risky_relay_requires_acknowledgement_before_enable(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "PROVIDER_CREDENTIAL_MASTER_KEY", _master_key())
    monkeypatch.setattr(provider_security.socket, "getaddrinfo", _public_dns)
    response = client.post(
        URL,
        headers=superuser_token_headers,
        json={
            "code": f"cpa-{random_lower_string()[:8]}",
            "display_name": "外部兼容服务",
            "kind": "cli_proxy_api",
            "protocol": "openai_chat",
            "base_url": "https://relay.example/v1",
            "api_key": "secret",
            "enabled": True,
            "risk_acknowledged": False,
        },
    )
    assert response.status_code == 422
    assert "风险" in response.text


def test_vision_route_rejects_text_only_mapping(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "PROVIDER_CREDENTIAL_MASTER_KEY", _master_key())
    monkeypatch.setattr(provider_security.socket, "getaddrinfo", _public_dns)
    channel = client.post(
        URL,
        headers=superuser_token_headers,
        json={
            "code": f"text-only-{random_lower_string()[:8]}",
            "display_name": "纯文本中转",
            "kind": "authorized_relay",
            "base_url": "https://relay.example/v1",
            "api_key": "secret",
        },
    )
    assert channel.status_code == 200, channel.text
    mapping = client.post(
        f"{URL}/{channel.json()['id']}/models",
        headers=superuser_token_headers,
        json={
            "canonical_model": "text-only-model",
            "upstream_model": "claude-text-only",
            "supports_vision": False,
        },
    )
    assert mapping.status_code == 200, mapping.text
    route = client.post(
        f"{URL}/routes/answer_extraction/targets",
        headers=superuser_token_headers,
        params={"canonical_model": "text-only-model"},
        json={"mapping_id": mapping.json()["id"]},
    )
    assert route.status_code == 422
    assert "图片输入" in route.text


def test_model_routes_enforce_business_purpose_families(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    _vision_channel, vision_mapping = _route_channel(
        db, model="gemini-3.6-flash-policy-test"
    )
    _reasoning_channel, reasoning_mapping = _route_channel(
        db, model="gpt-5.6-sol-policy-test"
    )

    traditional = client.put(
        f"{URL}/routes/photo_preprocessing",
        headers=superuser_token_headers,
        json={
            "canonical_model": vision_mapping.canonical_model,
            "targets": [{"mapping_id": str(vision_mapping.id)}],
        },
    )
    assert traditional.status_code == 422
    assert "传统图像处理" in traditional.text

    vision_with_reasoning_model = client.put(
        f"{URL}/routes/region_detection",
        headers=superuser_token_headers,
        json={
            "canonical_model": reasoning_mapping.canonical_model,
            "targets": [{"mapping_id": str(reasoning_mapping.id)}],
        },
    )
    assert vision_with_reasoning_model.status_code == 422
    assert "纯视觉功能" in vision_with_reasoning_model.text

    reasoning_with_vision_model = client.put(
        f"{URL}/routes/subjective_grading",
        headers=superuser_token_headers,
        json={
            "canonical_model": vision_mapping.canonical_model,
            "targets": [{"mapping_id": str(vision_mapping.id)}],
        },
    )
    assert reasoning_with_vision_model.status_code == 422
    assert "推理解题功能" in reasoning_with_vision_model.text


def test_function_keeps_multiple_published_models_and_switches_default(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    purpose = f"multi_model_{random_lower_string()[:12]}"
    _channel_a, mapping_a = _route_channel(db, model="commercial-model-a")
    _channel_b, mapping_b = _route_channel(db, model="commercial-model-b")

    _save_and_publish_route(
        client,
        superuser_token_headers,
        purpose=purpose,
        model="commercial-model-a",
        mapping_ids=[str(mapping_a.id)],
    )
    _save_and_publish_route(
        client,
        superuser_token_headers,
        purpose=purpose,
        model="commercial-model-b",
        mapping_ids=[str(mapping_b.id)],
    )

    routes = client.get(
        f"{URL}/routes", headers=superuser_token_headers, params={"purpose": purpose}
    )
    assert routes.status_code == 200, routes.text
    assert {item["canonical_model"] for item in routes.json() if item["enabled"]} == {
        "commercial-model-a",
        "commercial-model-b",
    }
    defaults = client.get(f"{URL}/routes/defaults", headers=superuser_token_headers)
    assert defaults.status_code == 200, defaults.text
    assignment = next(item for item in defaults.json() if item["purpose"] == purpose)
    assert assignment["default_canonical_model"] == "commercial-model-a"

    switched = client.put(
        f"{URL}/routes/{purpose}/default",
        headers=superuser_token_headers,
        json={"canonical_model": "commercial-model-b"},
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["default_canonical_model"] == "commercial-model-b"
    default_route = client.get(
        f"{URL}/routes/{purpose}", headers=superuser_token_headers
    )
    assert default_route.status_code == 200, default_route.text
    assert default_route.json()["canonical_model"] == "commercial-model-b"


def test_route_draft_rejects_stale_mapping_and_published_snapshot_is_immutable(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    purpose = f"snapshot_{random_lower_string()[:12]}"
    channel, mapping = _route_channel(
        db, model="snapshot-model", upstream_model="snapshot-upstream-v1"
    )
    saved = client.put(
        f"{URL}/routes/{purpose}",
        headers=superuser_token_headers,
        json={
            "canonical_model": "snapshot-model",
            "targets": [{"mapping_id": str(mapping.id)}],
        },
    )
    assert saved.status_code == 200, saved.text
    versions = client.get(
        f"{URL}/routes/{purpose}/versions",
        headers=superuser_token_headers,
        params={"canonical_model": "snapshot-model"},
    ).json()
    draft = next(item for item in versions if item["status"] == "draft")
    mapping.upstream_model = "snapshot-upstream-v2"
    db.add(mapping)
    db.commit()
    stale = client.post(
        f"{URL}/routes/{purpose}/versions/{draft['id']}/publish",
        headers=superuser_token_headers,
    )
    assert stale.status_code == 409, stale.text
    assert "重新保存草稿" in stale.text

    published = _save_and_publish_route(
        client,
        superuser_token_headers,
        purpose=purpose,
        model="snapshot-model",
        mapping_ids=[str(mapping.id)],
    )
    assert published["targets"][0]["upstream_model"] == "snapshot-upstream-v2"
    assert published["targets"][0]["base_url"] == "https://relay.example/v1"
    mapping.upstream_model = "snapshot-upstream-v3"
    channel.base_url = "https://changed.example/v1"
    db.add(mapping)
    db.add(channel)
    db.commit()

    versions_after = client.get(
        f"{URL}/routes/{purpose}/versions",
        headers=superuser_token_headers,
        params={"canonical_model": "snapshot-model"},
    )
    assert versions_after.status_code == 200, versions_after.text
    immutable = next(
        item for item in versions_after.json() if item["status"] == "published"
    )
    assert immutable["targets"][0]["upstream_model"] == "snapshot-upstream-v2"
    assert immutable["targets"][0]["base_url"] == "https://relay.example/v1"


def test_cost_first_route_requires_current_internal_rate(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    purpose = f"cost_route_{random_lower_string()[:12]}"
    channel, mapping = _route_channel(db, model="cost-model")
    saved = client.put(
        f"{URL}/routes/{purpose}",
        headers=superuser_token_headers,
        json={
            "canonical_model": "cost-model",
            "routing_mode": "cost_first",
            "targets": [{"mapping_id": str(mapping.id)}],
        },
    )
    assert saved.status_code == 200, saved.text
    versions = client.get(
        f"{URL}/routes/{purpose}/versions",
        headers=superuser_token_headers,
        params={"canonical_model": "cost-model"},
    ).json()
    draft = next(item for item in versions if item["status"] == "draft")
    rejected = client.post(
        f"{URL}/routes/{purpose}/versions/{draft['id']}/publish",
        headers=superuser_token_headers,
    )
    assert rejected.status_code == 422, rejected.text
    assert "内部费率" in rejected.text

    db.add(
        ProviderInternalRateVersion(
            channel_id=channel.id,
            canonical_model="cost-model",
            version=f"rate-{random_lower_string()[:8]}",
            effective_at=datetime.now(UTC),
            input_micrormb_per_million=1_000_000,
            output_micrormb_per_million=2_000_000,
            image_micrormb_per_million=3_000_000,
        )
    )
    db.commit()
    published = _save_and_publish_route(
        client,
        superuser_token_headers,
        purpose=purpose,
        model="cost-model",
        mapping_ids=[str(mapping.id)],
        routing_mode="cost_first",
    )
    assert published["routing_mode"] == "cost_first"
    assert published["targets"][0]["cost_rmb_per_million"] == 3


def test_new_api_bill_sync_matches_local_event_and_ignores_shared_token_usage(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "PROVIDER_CREDENTIAL_MASTER_KEY", _master_key())
    channel, _mapping = _route_channel(db, model="gpt-5.6-sol-billing-test")
    encrypted = provider_security.encrypt_credential("secret", channel_id=channel.id)
    db.add(
        ProviderCredential(
            channel_id=channel.id,
            ciphertext=encrypted.ciphertext,
            nonce=encrypted.nonce,
            fingerprint=encrypted.fingerprint,
            last_four=encrypted.last_four,
        )
    )
    db.commit()
    billing_credential = client.put(
        f"{URL}/{channel.id}/billing-credential",
        headers=superuser_token_headers,
        json={"access_token": "system-secret", "user_id": 42},
    )
    assert billing_credential.status_code == 200, billing_credential.text
    assert billing_credential.json()["billing_credential_configured"] is True
    assert billing_credential.json()["billing_user_id"] == 42
    org = db.exec(select(Organization)).first()
    assert org is not None
    created_at = datetime.now(UTC).replace(microsecond=0)
    event = ModelUsageEvent(
        org_id=org.id,
        resource_id="new-api-billing-test",
        workflow_purpose="subjective_grading",
        requested_provider=channel.code,
        requested_model="gpt-5.6-sol",
        actual_provider=channel.code,
        actual_model="gpt-5.6-sol",
        channel_id=channel.id,
        input_tokens=1465,
        output_tokens=9,
        total_tokens=1474,
        latency_ms=4_000,
        status=ModelUsageStatus.SUCCEEDED,
        customer_microcredits=0,
        internal_cost_micrormb=604,
        billing_key=f"new-api-sync:{random_lower_string()}",
        created_at=created_at,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    account = new_api_billing.NewApiAccountSnapshot(
        system_name="PomoAi",
        version="test-version",
        quota_per_unit=500_000,
        usd_exchange_rate=Decimal("7.3"),
        total_granted_quota=75_940,
        total_used_quota=354_024_570,
        total_available_quota=-353_948_630,
        unlimited_quota=True,
    )
    monkeypatch.setattr(
        new_api_billing,
        "fetch_new_api_billing",
        lambda **_kwargs: new_api_billing.NewApiBillingReport(
            account=account,
            logs=[
                new_api_billing.NewApiUsageLog(
                    request_id="new-api-request-1",
                    model_name="gpt-5.6-sol",
                    input_tokens=1465,
                    output_tokens=9,
                    quota=570,
                    cost_micrormb=8_322,
                    created_at=created_at,
                    use_time_seconds=4,
                ),
                new_api_billing.NewApiUsageLog(
                    request_id="shared-token-other-client",
                    model_name="gpt-5.5",
                    input_tokens=700,
                    output_tokens=300,
                    quota=5_000,
                    cost_micrormb=73_000,
                    created_at=created_at + timedelta(seconds=1),
                    use_time_seconds=8,
                ),
            ],
        ),
    )

    response = client.post(
        f"{URL}/{channel.id}/reconciliations/sync-new-api",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["batch"]["fetched_count"] == 2
    assert payload["batch"]["row_count"] == 1
    assert payload["batch"]["ignored_count"] == 1
    assert payload["batch"]["matched_count"] == 0
    assert payload["batch"]["mismatch_count"] == 1
    assert payload["batch"]["upstream_total_used_rmb"] == 5168.758722

    db.refresh(event)
    assert event.upstream_request_id == "new-api-request-1"
    assert event.upstream_cost_micrormb == 8_322
    assert event.reconciliation_status == UsageReconciliationStatus.MISMATCH

    batches = client.get(
        f"{URL}/{channel.id}/reconciliations",
        headers=superuser_token_headers,
    )
    assert batches.status_code == 200, batches.text
    assert batches.json()[0]["upstream_system_name"] == "PomoAi"
    db.delete(event)
    db.commit()


def test_non_new_api_channel_can_store_billing_credential_without_user_id(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "PROVIDER_CREDENTIAL_MASTER_KEY", _master_key())
    channel, _mapping = _route_channel(db, model="generic-billing-test")
    encrypted = provider_security.encrypt_credential("secret", channel_id=channel.id)
    credential = ProviderCredential(
        channel_id=channel.id,
        ciphertext=encrypted.ciphertext,
        nonce=encrypted.nonce,
        fingerprint=encrypted.fingerprint,
        last_four=encrypted.last_four,
    )
    db.add(credential)
    db.commit()

    response = client.put(
        f"{URL}/{channel.id}/billing-credential",
        headers=superuser_token_headers,
        json={"access_token": "provider-billing-secret"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["billing_credential_configured"] is True
    assert response.json()["billing_credential_last_four"] == "cret"
    assert response.json()["billing_user_id"] is None

    channel.kind = ProviderChannelKind.NEW_API
    db.add(channel)
    db.commit()
    missing_user_id = client.put(
        f"{URL}/{channel.id}/billing-credential",
        headers=superuser_token_headers,
        json={"access_token": "new-api-system-token"},
    )
    assert missing_user_id.status_code == 422, missing_user_id.text
    assert "New-Api-User ID" in missing_user_id.text
