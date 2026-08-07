import uuid

import pytest
from sqlmodel import Session, select

from app.core.db import engine
from app.models import (
    FunctionModelAssignment,
    ModelRoutePolicy,
    ModelRouteTarget,
    ModelRouteVersion,
    ModelRouteVersionStatus,
    ModelRouteVersionTarget,
    ProviderChannel,
    ProviderChannelKind,
    ProviderChannelStatus,
    ProviderHealthState,
    ProviderHealthStatus,
    ProviderModelMapping,
    ProviderProtocol,
)
from app.services import provider_gateway
from app.services.provider_gateway import (
    SCHOOL_ROUTE_PROVIDER,
    ProviderGatewayError,
    RuntimeTarget,
    endpoint,
    record_failure,
    record_success,
    request_payload,
    response_content,
)


def _target(protocol: ProviderProtocol) -> RuntimeTarget:
    return RuntimeTarget(
        provider="relay",
        canonical_model="grader-main",
        upstream_model="upstream-model",
        base_url="https://relay.example/v1",
        api_key="secret",
        protocol=protocol,
        channel_id=uuid.uuid4(),
        route_policy_id=None,
        route_version_id=None,
        max_concurrency=8,
        timeout_seconds=30,
    )


def test_chat_and_responses_protocol_adapters() -> None:
    chat = _target(ProviderProtocol.OPENAI_CHAT)
    responses = _target(ProviderProtocol.OPENAI_RESPONSES)
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "inspect"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,eA=="},
                },
            ],
        }
    ]

    assert endpoint(chat).endswith("/v1/chat/completions")
    assert endpoint(responses).endswith("/v1/responses")
    assert (
        request_payload(chat, messages=messages, temperature=0.1)["messages"]
        == messages
    )
    response_input = request_payload(responses, messages=messages, temperature=0.1)[
        "input"
    ][0]["content"]
    assert response_input[0] == {"type": "input_text", "text": "inspect"}
    assert response_input[1]["type"] == "input_image"
    assert (
        response_content(
            ProviderProtocol.OPENAI_CHAT,
            {"choices": [{"message": {"content": '{"ok":true}'}}]},
        )
        == '{"ok":true}'
    )
    assert (
        response_content(
            ProviderProtocol.OPENAI_RESPONSES,
            {"output": [{"content": [{"type": "output_text", "text": '{"ok":true}'}]}]},
        )
        == '{"ok":true}'
    )


def test_empty_provider_response_is_rejected() -> None:
    with pytest.raises(ProviderGatewayError):
        response_content(ProviderProtocol.OPENAI_CHAT, {"choices": []})
    with pytest.raises(ProviderGatewayError):
        response_content(ProviderProtocol.OPENAI_RESPONSES, {"output": []})


def test_health_circuit_opens_and_missing_usage_stays_network_healthy(
    db: Session,
) -> None:
    channel = ProviderChannel(
        code=f"health-{uuid.uuid4().hex[:8]}",
        display_name="健康测试",
        kind=ProviderChannelKind.AUTHORIZED_RELAY,
        protocol=ProviderProtocol.OPENAI_CHAT,
        base_url="https://relay.example/v1",
    )
    db.add(channel)
    db.flush()
    mapping = ProviderModelMapping(
        channel_id=channel.id,
        canonical_model="grader-main",
        upstream_model="upstream-model",
        usage_metering_verified=True,
    )
    db.add(mapping)
    db.commit()
    target = _target(ProviderProtocol.OPENAI_CHAT)
    target = RuntimeTarget(**(target.__dict__ | {"channel_id": channel.id}))

    for _ in range(5):
        record_failure(target, error_code="HTTPError", http_status=503)
    with Session(engine) as session:
        state = session.exec(
            select(ProviderHealthState).where(
                ProviderHealthState.channel_id == channel.id
            )
        ).one()
        assert state.status == ProviderHealthStatus.OPEN
        assert state.circuit_open_until is not None

    record_success(target, latency_ms=100, usage_present=False, http_status=200)
    with Session(engine) as session:
        disabled = session.exec(
            select(ProviderModelMapping).where(
                ProviderModelMapping.channel_id == channel.id
            )
        ).one()
        assert disabled.usage_metering_verified is False
    record_success(target, latency_ms=100, usage_present=False, http_status=200)
    record_success(target, latency_ms=100, usage_present=False, http_status=200)
    with Session(engine) as session:
        state = session.exec(
            select(ProviderHealthState).where(
                ProviderHealthState.channel_id == channel.id
            )
        ).one()
        assert state.status == ProviderHealthStatus.HEALTHY
        assert state.consecutive_missing_usage == 3


def test_function_route_overrides_legacy_requested_model(
    db: Session, monkeypatch
) -> None:
    purpose = f"gateway_test_{uuid.uuid4().hex[:12]}"
    channel = ProviderChannel(
        code=f"route-{uuid.uuid4().hex[:8]}",
        display_name="功能路由测试",
        kind=ProviderChannelKind.AUTHORIZED_RELAY,
        protocol=ProviderProtocol.OPENAI_CHAT,
        base_url="https://relay.example/v1",
        status=ProviderChannelStatus.ACTIVE,
    )
    db.add(channel)
    db.flush()
    mapping = ProviderModelMapping(
        channel_id=channel.id,
        canonical_model="assigned-model",
        upstream_model="assigned-upstream",
        usage_metering_verified=True,
    )
    db.add(mapping)
    db.flush()
    policy = ModelRoutePolicy(
        purpose=purpose,
        canonical_model="assigned-model",
        enabled=True,
    )
    db.add(policy)
    db.flush()
    db.add(ModelRouteTarget(policy_id=policy.id, mapping_id=mapping.id, priority=1))
    db.add(
        FunctionModelAssignment(
            purpose=purpose,
            default_canonical_model="assigned-model",
        )
    )
    db.commit()

    def fake_runtime_target(
        _session, *, channel, mapping, route_policy_id, route_version_id=None
    ):
        return RuntimeTarget(
            provider=channel.code,
            canonical_model=mapping.canonical_model,
            upstream_model=mapping.upstream_model,
            base_url=channel.base_url,
            api_key="test-key",
            protocol=channel.protocol,
            channel_id=channel.id,
            route_policy_id=route_policy_id,
            route_version_id=route_version_id,
            max_concurrency=channel.max_concurrency,
            timeout_seconds=channel.timeout_seconds,
        )

    monkeypatch.setattr(provider_gateway, "_runtime_target", fake_runtime_target)
    targets = provider_gateway.resolve_targets(
        provider="legacy-provider",
        model="legacy-model",
        workflow_purpose=purpose,
        sticky_key="job-1",
    )
    assert len(targets) == 1
    assert targets[0].canonical_model == "assigned-model"
    assert targets[0].upstream_model == "assigned-upstream"

    with Session(engine) as session:
        school_mapping = ProviderModelMapping(
            channel_id=channel.id,
            canonical_model="school-selected-model",
            upstream_model="school-selected-upstream",
            usage_metering_verified=True,
        )
        session.add(school_mapping)
        session.flush()
        school_policy = ModelRoutePolicy(
            purpose=purpose,
            canonical_model="school-selected-model",
            enabled=True,
        )
        session.add(school_policy)
        session.flush()
        school_version = ModelRouteVersion(
            policy_id=school_policy.id,
            version=1,
            status=ModelRouteVersionStatus.PUBLISHED,
        )
        session.add(school_version)
        session.flush()
        session.add(
            ModelRouteVersionTarget(
                route_version_id=school_version.id,
                mapping_id=school_mapping.id,
                channel_id=channel.id,
                channel_code=channel.code,
                canonical_model=school_mapping.canonical_model,
                upstream_model=school_mapping.upstream_model,
                protocol=channel.protocol,
                base_url=channel.base_url,
            )
        )
        session.commit()
    school_targets = provider_gateway.resolve_targets(
        provider=SCHOOL_ROUTE_PROVIDER,
        model="school-selected-model",
        workflow_purpose=purpose,
        sticky_key="school-job-1",
    )
    assert len(school_targets) == 1
    assert school_targets[0].canonical_model == "school-selected-model"

    fallback_targets = provider_gateway.resolve_targets(
        provider="legacy-provider",
        model="school-selected-model",
        workflow_purpose=purpose,
        sticky_key="fallback-job-1",
        prefer_assignment=False,
    )
    assert len(fallback_targets) == 1
    assert fallback_targets[0].canonical_model == "school-selected-model"


@pytest.mark.parametrize(
    ("routing_mode", "expected_upstream"),
    [("cost_first", "cheap-slow"), ("latency_first", "expensive-fast")],
)
def test_published_route_orders_same_tier_by_commercial_strategy(
    db: Session,
    monkeypatch,
    routing_mode: str,
    expected_upstream: str,
) -> None:
    purpose = f"strategy_test_{uuid.uuid4().hex[:10]}"
    model = f"strategy-model-{uuid.uuid4().hex[:8]}"
    channels: list[tuple[ProviderChannel, ProviderModelMapping, int, float]] = []
    for suffix, upstream, cost, latency in (
        ("cheap", "cheap-slow", 1_000_000, 900.0),
        ("fast", "expensive-fast", 10_000_000, 20.0),
    ):
        channel = ProviderChannel(
            code=f"{suffix}-{uuid.uuid4().hex[:8]}",
            display_name=f"策略测试 {suffix}",
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
            upstream_model=upstream,
            usage_metering_verified=True,
        )
        db.add(mapping)
        db.flush()
        db.add(
            ProviderHealthState(
                channel_id=channel.id,
                canonical_model=model,
                status=ProviderHealthStatus.HEALTHY,
                latency_ewma_ms=latency,
            )
        )
        channels.append((channel, mapping, cost, latency))
    policy = ModelRoutePolicy(
        purpose=purpose,
        canonical_model=model,
        enabled=True,
        max_attempts=1,
        routing_mode=routing_mode,
    )
    db.add(policy)
    db.flush()
    version = ModelRouteVersion(
        policy_id=policy.id,
        version=1,
        status=ModelRouteVersionStatus.PUBLISHED,
        max_attempts=1,
        routing_mode=routing_mode,
    )
    db.add(version)
    db.flush()
    for channel, mapping, cost, _latency in channels:
        db.add(
            ModelRouteVersionTarget(
                route_version_id=version.id,
                mapping_id=mapping.id,
                channel_id=channel.id,
                channel_code=channel.code,
                canonical_model=model,
                upstream_model=mapping.upstream_model,
                protocol=channel.protocol,
                base_url=channel.base_url,
                tier=1,
                weight=100,
                cost_micrormb_per_million=cost,
            )
        )
    db.add(
        FunctionModelAssignment(
            purpose=purpose,
            default_canonical_model=model,
        )
    )
    db.commit()

    def fake_runtime_target(
        _session,
        *,
        channel,
        mapping,
        route_policy_id,
        route_version_id=None,
    ):
        return RuntimeTarget(
            provider=channel.code,
            canonical_model=mapping.canonical_model,
            upstream_model=mapping.upstream_model,
            base_url=channel.base_url,
            api_key="test-key",
            protocol=channel.protocol,
            channel_id=channel.id,
            route_policy_id=route_policy_id,
            route_version_id=route_version_id,
            max_concurrency=channel.max_concurrency,
            timeout_seconds=channel.timeout_seconds,
        )

    monkeypatch.setattr(provider_gateway, "_runtime_target", fake_runtime_target)
    targets = provider_gateway.resolve_targets(
        provider="legacy-provider",
        model="legacy-model",
        workflow_purpose=purpose,
        sticky_key="commercial-routing",
    )
    assert [target.upstream_model for target in targets] == [expected_upstream]
