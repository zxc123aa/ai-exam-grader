import base64

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    ModelRoutePolicy,
    ModelRouteVersion,
    ModelRouteVersionStatus,
    ModelRouteVersionTarget,
    OrganizationModelSelection,
    PlatformModelOffering,
    ProviderChannel,
    ProviderChannelKind,
    ProviderModelMapping,
    ProviderProtocol,
    SchoolModelScope,
    User,
    UserCreate,
    UserRole,
)
from app.services import provider_security
from app.services.provider_gateway import SCHOOL_ROUTE_PROVIDER
from app.services.system_config import get_grading_defaults
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string

CHANNEL_URL = f"{settings.API_V1_STR}/platform/provider-channels"
OFFERING_URL = f"{settings.API_V1_STR}/platform/model-offerings"

SCOPE_PURPOSES = {
    SchoolModelScope.VISION: (
        "region_detection",
        "question_recognition",
        "score_structure_recognition",
        "answer_document_parsing",
        "rubric_question_recognition",
        "answer_recognition",
        "answer_extraction",
    ),
    SchoolModelScope.REFERENCE_ANSWER: (
        "answer_preparation",
        "rubric_generation",
        "rubric_validation",
    ),
    SchoolModelScope.GRADING: ("subjective_grading",),
}


def _master_key() -> str:
    return base64.urlsafe_b64encode(b"m" * 32).decode("ascii")


def _public_dns(*_args, **_kwargs):
    return [(2, 1, 6, "", ("93.184.216.34", 443))]


def _publish_scope_routes(
    db: Session,
    *,
    scope: SchoolModelScope,
    channel: ProviderChannel,
    mapping: ProviderModelMapping,
) -> None:
    for purpose in SCOPE_PURPOSES[scope]:
        policy = ModelRoutePolicy(
            purpose=purpose,
            canonical_model=mapping.canonical_model,
            enabled=True,
        )
        db.add(policy)
        db.flush()
        version = ModelRouteVersion(
            policy_id=policy.id,
            version=1,
            status=ModelRouteVersionStatus.PUBLISHED,
        )
        db.add(version)
        db.flush()
        db.add(
            ModelRouteVersionTarget(
                route_version_id=version.id,
                mapping_id=mapping.id,
                channel_id=channel.id,
                channel_code=channel.code,
                canonical_model=mapping.canonical_model,
                upstream_model=mapping.upstream_model,
                protocol=channel.protocol,
                base_url=channel.base_url,
            )
        )
    db.commit()


def _role_headers(client: TestClient, db: Session, role: UserRole) -> dict[str, str]:
    password = random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(),
            password=password,
            role=role,
        ),
    )
    return user_authentication_headers(
        client=client, email=user.email, password=password
    )


def test_only_platform_superuser_can_manage_offerings(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    assert client.get(OFFERING_URL, headers=superuser_token_headers).status_code == 200
    for role in (UserRole.PLATFORM_ADMIN, UserRole.PLATFORM_SUPPORT):
        assert (
            client.get(
                OFFERING_URL, headers=_role_headers(client, db, role)
            ).status_code
            == 403
        )


def test_one_channel_key_can_publish_multiple_model_families(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "PROVIDER_CREDENTIAL_MASTER_KEY", _master_key())
    monkeypatch.setattr(provider_security.socket, "getaddrinfo", _public_dns)
    channel = client.post(
        CHANNEL_URL,
        headers=superuser_token_headers,
        json={
            "code": "multi-family-relay",
            "display_name": "综合模型中转",
            "kind": "authorized_relay",
            "base_url": "https://relay.example/v1",
            "api_key": "one-key-for-many-models",
            "enabled": True,
        },
    )
    assert channel.status_code == 200, channel.text
    channel_id = channel.json()["id"]
    mappings: dict[str, ProviderModelMapping] = {}
    for canonical, upstream, vision in (
        ("gemini-3.6-flash-test", "gemini-upstream", True),
        ("gpt-5.6-sol-test", "reasoning-upstream", True),
    ):
        response = client.post(
            f"{CHANNEL_URL}/{channel_id}/models",
            headers=superuser_token_headers,
            json={
                "canonical_model": canonical,
                "upstream_model": upstream,
                "supports_vision": vision,
            },
        )
        assert response.status_code == 200, response.text
        mapping = db.get(ProviderModelMapping, response.json()["id"])
        assert mapping is not None
        mapping.usage_metering_verified = True
        db.add(mapping)
        mappings[canonical] = mapping
    db.commit()
    stored_channel = db.get(ProviderChannel, channel_id)
    assert stored_channel is not None
    _publish_scope_routes(
        db,
        scope=SchoolModelScope.VISION,
        channel=stored_channel,
        mapping=mappings["gemini-3.6-flash-test"],
    )
    _publish_scope_routes(
        db,
        scope=SchoolModelScope.GRADING,
        channel=stored_channel,
        mapping=mappings["gpt-5.6-sol-test"],
    )

    vision = client.post(
        OFFERING_URL,
        headers=superuser_token_headers,
        json={
            "code": "dianfan-vision-standard",
            "display_name": "点凡视觉标准",
            "description": "适合日常试卷识别",
            "scope": "vision",
            "provider_code": "multi-family-relay",
            "canonical_model": "gemini-3.6-flash-test",
            "published": True,
        },
    )
    grading = client.post(
        OFFERING_URL,
        headers=superuser_token_headers,
        json={
            "code": "dianfan-grading-deep",
            "display_name": "点凡深度判分",
            "scope": "grading",
            "provider_code": "multi-family-relay",
            "canonical_model": "gpt-5.6-sol-test",
            "published": True,
        },
    )
    assert vision.status_code == 200, vision.text
    assert grading.status_code == 200, grading.text
    assert vision.json()["mapped_channel_count"] == 1


def test_school_selects_public_name_without_provider_details(
    client: TestClient,
    db: Session,
    school_owner_token_headers: dict[str, str],
    school_owner_user: tuple[User, str],
) -> None:
    channel = ProviderChannel(
        code="school-visible-relay",
        display_name="学校模型中转",
        kind=ProviderChannelKind.AUTHORIZED_RELAY,
        protocol=ProviderProtocol.OPENAI_CHAT,
        base_url="https://relay.example/v1",
        enabled=True,
        status="active",
    )
    db.add(channel)
    db.flush()
    mapping = ProviderModelMapping(
        channel_id=channel.id,
        canonical_model="gemini-3.5-flash-school",
        upstream_model="gemini-private-name",
        usage_metering_verified=True,
    )
    db.add(mapping)
    db.flush()
    _publish_scope_routes(
        db,
        scope=SchoolModelScope.VISION,
        channel=channel,
        mapping=mapping,
    )
    offering = PlatformModelOffering(
        code="school-dianfan-vision-standard",
        display_name="点凡视觉标准",
        description="适合日常试卷识别",
        scope=SchoolModelScope.VISION,
        provider_code=channel.code,
        canonical_model="gemini-3.5-flash-school",
        published=True,
    )
    db.add(offering)
    db.commit()
    catalog = client.get(
        f"{settings.API_V1_STR}/org/model-settings",
        headers=school_owner_token_headers,
    )
    assert catalog.status_code == 200, catalog.text
    body = catalog.json()
    raw = catalog.text
    assert "点凡视觉标准" in raw
    assert "school-visible-relay" not in raw
    assert "gemini-private-name" not in raw
    vision_scope = next(item for item in body["scopes"] if item["scope"] == "vision")
    visible_option = next(
        item
        for item in vision_scope["options"]
        if item["code"] == "school-dianfan-vision-standard"
    )
    selected = client.put(
        f"{settings.API_V1_STR}/org/model-settings/vision",
        headers=school_owner_token_headers,
        json={"offering_id": visible_option["id"]},
    )
    assert selected.status_code == 200, selected.text

    owner = school_owner_user[0]
    assert owner and owner.org_id
    defaults = get_grading_defaults(db, owner.org_id)
    assert defaults["vision_provider"] == SCHOOL_ROUTE_PROVIDER
    assert defaults["vision_model"] == "gemini-3.5-flash-school"
    assert defaults["recognition_model"] == "gemini-3.5-flash-school"

    offering.published = False
    db.add(offering)
    db.commit()
    fallback = get_grading_defaults(db, owner.org_id)
    assert fallback["vision_provider"] != SCHOOL_ROUTE_PROVIDER
    assert fallback["vision_model"] != "gemini-3.5-flash-school"

    offering.published = True
    channel.enabled = False
    channel.status = "disabled"
    db.add(offering)
    db.add(channel)
    db.commit()
    disabled_channel = get_grading_defaults(db, owner.org_id)
    assert disabled_channel["vision_provider"] != SCHOOL_ROUTE_PROVIDER
    selection = db.exec(
        select(OrganizationModelSelection).where(
            OrganizationModelSelection.org_id == owner.org_id
        )
    ).first()
    if selection:
        db.delete(selection)
    db.delete(offering)
    db.commit()


def test_school_cannot_select_unpublished_model(
    client: TestClient,
    db: Session,
    school_owner_token_headers: dict[str, str],
) -> None:
    hidden = PlatformModelOffering(
        code="hidden-grading-option",
        display_name="未发布判分方案",
        scope=SchoolModelScope.GRADING,
        provider_code="hidden-provider",
        canonical_model="hidden-model",
        published=False,
    )
    db.add(hidden)
    db.commit()
    response = client.put(
        f"{settings.API_V1_STR}/org/model-settings/grading",
        headers=school_owner_token_headers,
        json={"offering_id": str(hidden.id)},
    )
    assert response.status_code == 422


def test_published_offering_requires_complete_function_route_coverage(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    model = f"gemini-3.6-flash-incomplete-{random_lower_string()[:8]}"
    channel = ProviderChannel(
        code=f"incomplete-{random_lower_string()[:8]}",
        display_name="未完成路由的通道",
        kind=ProviderChannelKind.AUTHORIZED_RELAY,
        protocol=ProviderProtocol.OPENAI_CHAT,
        base_url="https://relay.example/v1",
        enabled=True,
        status="active",
    )
    db.add(channel)
    db.flush()
    db.add(
        ProviderModelMapping(
            channel_id=channel.id,
            canonical_model=model,
            upstream_model=model,
            usage_metering_verified=True,
        )
    )
    db.commit()
    response = client.post(
        OFFERING_URL,
        headers=superuser_token_headers,
        json={
            "code": f"offering-{random_lower_string()[:8]}",
            "display_name": "未完成路由的方案",
            "scope": "vision",
            "provider_code": "route",
            "canonical_model": model,
            "published": True,
        },
    )
    assert response.status_code == 422, response.text
    assert "版面分析" in response.text
    assert "答题识别" in response.text
