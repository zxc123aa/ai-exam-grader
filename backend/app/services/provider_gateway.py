from __future__ import annotations

import hashlib
import math
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.models import (
    FunctionModelAssignment,
    ModelRoutePolicy,
    ModelRouteTarget,
    ModelRouteVersion,
    ModelRouteVersionStatus,
    ModelRouteVersionTarget,
    ProviderChannel,
    ProviderChannelStatus,
    ProviderCredential,
    ProviderHealthState,
    ProviderHealthStatus,
    ProviderModelMapping,
    ProviderProtocol,
)
from app.services.provider_security import (
    ProviderSecurityError,
    decrypt_credential,
    validate_provider_base_url,
)


class ProviderGatewayError(RuntimeError):
    pass


SCHOOL_ROUTE_PROVIDER = "school_route"


@dataclass(frozen=True)
class RuntimeTarget:
    provider: str
    canonical_model: str
    upstream_model: str
    base_url: str
    api_key: str
    protocol: ProviderProtocol
    channel_id: uuid.UUID
    route_policy_id: uuid.UUID | None
    route_version_id: uuid.UUID | None
    max_concurrency: int
    timeout_seconds: int


def _credential(session: Session, channel_id: uuid.UUID) -> ProviderCredential | None:
    return session.exec(
        select(ProviderCredential).where(ProviderCredential.channel_id == channel_id)
    ).first()


def _runtime_target(
    session: Session,
    *,
    channel: ProviderChannel,
    mapping: ProviderModelMapping,
    route_policy_id: uuid.UUID | None,
    route_version_id: uuid.UUID | None = None,
) -> RuntimeTarget | None:
    credential = _credential(session, channel.id)
    if not credential:
        return None
    try:
        base_url = validate_provider_base_url(channel.base_url)
        api_key = decrypt_credential(
            credential.ciphertext, credential.nonce, channel_id=channel.id
        )
    except ProviderSecurityError as exc:
        raise ProviderGatewayError(str(exc)) from exc
    return RuntimeTarget(
        provider=channel.code,
        canonical_model=mapping.canonical_model,
        upstream_model=mapping.upstream_model,
        base_url=base_url,
        api_key=api_key,
        protocol=channel.protocol,
        channel_id=channel.id,
        route_policy_id=route_policy_id,
        route_version_id=route_version_id,
        max_concurrency=channel.max_concurrency,
        timeout_seconds=channel.timeout_seconds,
    )


def _health_is_eligible(health: ProviderHealthState | None) -> bool:
    if not health:
        return True
    if health.status == ProviderHealthStatus.DISABLED:
        return False
    if health.status != ProviderHealthStatus.OPEN:
        return True
    return bool(
        health.circuit_open_until and health.circuit_open_until <= datetime.now(UTC)
    )


def _stable_weighted_score(seed: str, channel_id: uuid.UUID, weight: int) -> float:
    digest = hashlib.sha256(f"{seed}:{channel_id}".encode()).digest()
    value = max(1e-12, int.from_bytes(digest[:8], "big") / (2**64 - 1))
    return -math.log(value) / max(1, weight)


def resolve_targets(
    *,
    provider: str,
    model: str,
    workflow_purpose: str | None,
    sticky_key: str,
    prefer_assignment: bool = True,
) -> list[RuntimeTarget]:
    with Session(engine) as session:
        policy = None
        assignment = None
        if workflow_purpose:
            assignment = session.get(FunctionModelAssignment, workflow_purpose)
            requested_model = (
                model
                if provider == SCHOOL_ROUTE_PROVIDER
                or not assignment
                or not prefer_assignment
                else assignment.default_canonical_model
            )
            statement = select(ModelRoutePolicy).where(
                ModelRoutePolicy.purpose == workflow_purpose,
                ModelRoutePolicy.canonical_model == requested_model,
                ModelRoutePolicy.enabled.is_(True),
            )
            policy = session.exec(
                statement.order_by(ModelRoutePolicy.updated_at.desc())
            ).first()
            if not policy and not assignment and provider != SCHOOL_ROUTE_PROVIDER:
                policy = session.exec(
                    select(ModelRoutePolicy)
                    .where(
                        ModelRoutePolicy.purpose == workflow_purpose,
                        ModelRoutePolicy.enabled.is_(True),
                    )
                    .order_by(ModelRoutePolicy.updated_at.desc())
                ).first()
            if not policy and (
                assignment is not None or provider == SCHOOL_ROUTE_PROVIDER
            ):
                return []

        candidates: list[
            tuple[
                int,
                int,
                float | None,
                int,
                ProviderChannel,
                ProviderModelMapping,
            ]
        ] = []
        published_version = None
        if policy:
            published_version = session.exec(
                select(ModelRouteVersion)
                .where(
                    ModelRouteVersion.policy_id == policy.id,
                    ModelRouteVersion.status == ModelRouteVersionStatus.PUBLISHED,
                )
                .order_by(ModelRouteVersion.version.desc())
            ).first()
            if published_version:
                rows = session.exec(
                    select(
                        ModelRouteVersionTarget,
                        ProviderModelMapping,
                        ProviderChannel,
                        ProviderHealthState,
                    )
                    .join(
                        ProviderModelMapping,
                        ModelRouteVersionTarget.mapping_id == ProviderModelMapping.id,
                    )
                    .join(
                        ProviderChannel,
                        ModelRouteVersionTarget.channel_id == ProviderChannel.id,
                    )
                    .outerjoin(
                        ProviderHealthState,
                        (ProviderHealthState.channel_id == ProviderChannel.id)
                        & (
                            ProviderHealthState.canonical_model
                            == ModelRouteVersionTarget.canonical_model
                        ),
                    )
                    .where(
                        ModelRouteVersionTarget.route_version_id
                        == published_version.id,
                        ModelRouteVersionTarget.enabled.is_(True),
                        ProviderModelMapping.enabled.is_(True),
                        ProviderModelMapping.usage_metering_verified.is_(True),
                        ProviderChannel.status == ProviderChannelStatus.ACTIVE,
                    )
                ).all()
            else:
                # Compatibility path for databases not migrated to versioned routes yet.
                rows = session.exec(
                    select(
                        ModelRouteTarget,
                        ProviderModelMapping,
                        ProviderChannel,
                        ProviderHealthState,
                    )
                    .join(
                        ProviderModelMapping,
                        ModelRouteTarget.mapping_id == ProviderModelMapping.id,
                    )
                    .join(
                        ProviderChannel,
                        ProviderModelMapping.channel_id == ProviderChannel.id,
                    )
                    .outerjoin(
                        ProviderHealthState,
                        (ProviderHealthState.channel_id == ProviderChannel.id)
                        & (
                            ProviderHealthState.canonical_model
                            == ProviderModelMapping.canonical_model
                        ),
                    )
                    .where(
                        ModelRouteTarget.policy_id == policy.id,
                        ModelRouteTarget.enabled.is_(True),
                        ProviderModelMapping.enabled.is_(True),
                        ProviderModelMapping.usage_metering_verified.is_(True),
                        ProviderChannel.status == ProviderChannelStatus.ACTIVE,
                    )
                ).all()
            for target, mapping, channel, health in rows:
                if _health_is_eligible(health):
                    snapshot_mapping = mapping
                    snapshot_channel = channel
                    if published_version:
                        snapshot_mapping = mapping.model_copy(
                            update={
                                "canonical_model": target.canonical_model,
                                "upstream_model": target.upstream_model,
                            }
                        )
                        snapshot_channel = channel.model_copy(
                            update={
                                "code": target.channel_code,
                                "protocol": target.protocol,
                                "base_url": target.base_url,
                            }
                        )
                    candidates.append(
                        (
                            (
                                target.tier
                                if published_version
                                else target.priority + channel.priority
                            ),
                            target.weight * channel.weight,
                            health.latency_ewma_ms if health else None,
                            (
                                target.cost_micrormb_per_million
                                if published_version
                                else 0
                            ),
                            snapshot_channel,
                            snapshot_mapping,
                        )
                    )
        else:
            statement = (
                select(ProviderChannel, ProviderModelMapping, ProviderHealthState)
                .join(
                    ProviderModelMapping,
                    ProviderModelMapping.channel_id == ProviderChannel.id,
                )
                .outerjoin(
                    ProviderHealthState,
                    (ProviderHealthState.channel_id == ProviderChannel.id)
                    & (
                        ProviderHealthState.canonical_model
                        == ProviderModelMapping.canonical_model
                    ),
                )
                .where(
                    ProviderChannel.status == ProviderChannelStatus.ACTIVE,
                    ProviderModelMapping.canonical_model == model,
                    ProviderModelMapping.enabled.is_(True),
                    ProviderModelMapping.usage_metering_verified.is_(True),
                )
            )
            if provider != SCHOOL_ROUTE_PROVIDER:
                statement = statement.where(ProviderChannel.code == provider)
            rows = session.exec(statement).all()
            for channel, mapping, health in rows:
                if _health_is_eligible(health):
                    candidates.append(
                        (
                            channel.priority,
                            channel.weight,
                            health.latency_ewma_ms if health else None,
                            0,
                            channel,
                            mapping,
                        )
                    )

        routing_mode = (
            published_version.routing_mode
            if published_version
            else policy.routing_mode
            if policy
            else "balanced"
        )

        def candidate_sort_key(
            item: tuple[
                int,
                int,
                float | None,
                int,
                ProviderChannel,
                ProviderModelMapping,
            ],
        ) -> tuple[Any, ...]:
            weighted = _stable_weighted_score(sticky_key, item[4].id, item[1])
            latency = item[2] if item[2] is not None else float("inf")
            cost = item[3] if item[3] > 0 else float("inf")
            if routing_mode == "cost_first":
                return (item[0], cost, weighted, latency, item[4].code)
            if routing_mode == "latency_first":
                return (item[0], latency, weighted, cost, item[4].code)
            return (item[0], weighted, latency, cost, item[4].code)

        candidates.sort(key=candidate_sort_key)
        limit = (
            published_version.max_attempts
            if published_version
            else policy.max_attempts
            if policy
            else 1
        )
        result: list[RuntimeTarget] = []
        selected: list[
            tuple[
                int,
                int,
                float | None,
                int,
                ProviderChannel,
                ProviderModelMapping,
            ]
        ] = []
        # Choose one sticky target per tier before adding same-tier fallbacks.
        # This preserves primary/backup semantics while still balancing traffic.
        for tier in sorted({item[0] for item in candidates}):
            tier_candidates = [item for item in candidates if item[0] == tier]
            if tier_candidates:
                selected.append(tier_candidates[0])
            if len(selected) >= limit:
                break
        if len(selected) < limit:
            selected.extend(item for item in candidates if item not in selected)
        for (
            _priority,
            _weight,
            _latency,
            _cost,
            channel,
            mapping,
        ) in selected[:limit]:
            try:
                target = _runtime_target(
                    session,
                    channel=channel,
                    mapping=mapping,
                    route_policy_id=policy.id if policy else None,
                    route_version_id=(
                        published_version.id if published_version else None
                    ),
                )
            except ProviderGatewayError:
                continue
            if target:
                result.append(target)
        return result


def resolve_channel_target(
    session: Session,
    *,
    channel: ProviderChannel,
    canonical_model: str,
    require_enabled: bool = True,
) -> RuntimeTarget:
    if require_enabled and channel.status != ProviderChannelStatus.ACTIVE:
        raise ProviderGatewayError("中转渠道尚未启用")
    mapping = session.exec(
        select(ProviderModelMapping).where(
            ProviderModelMapping.channel_id == channel.id,
            ProviderModelMapping.canonical_model == canonical_model,
            ProviderModelMapping.enabled.is_(True),
        )
    ).first()
    if not mapping:
        raise ProviderGatewayError("该渠道未配置此模型")
    target = _runtime_target(
        session, channel=channel, mapping=mapping, route_policy_id=None
    )
    if not target:
        raise ProviderGatewayError("中转渠道未配置调用密钥")
    return target


def endpoint(target: RuntimeTarget) -> str:
    base = target.base_url.rstrip("/")
    if target.protocol == ProviderProtocol.OPENAI_RESPONSES:
        return f"{base}/responses" if base.endswith("/v1") else f"{base}/v1/responses"
    return (
        f"{base}/chat/completions"
        if base.endswith("/v1")
        else f"{base}/v1/chat/completions"
    )


def _responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        raw_content = message.get("content", "")
        if isinstance(raw_content, str):
            content = [{"type": "input_text", "text": raw_content}]
        else:
            content = []
            for item in raw_content if isinstance(raw_content, list) else []:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text":
                    content.append({"type": "input_text", "text": item.get("text", "")})
                elif item.get("type") == "image_url":
                    image = item.get("image_url") or {}
                    image_url = image.get("url") if isinstance(image, dict) else image
                    content.append({"type": "input_image", "image_url": image_url})
        result.append({"role": role, "content": content})
    return result


def request_payload(
    target: RuntimeTarget,
    *,
    messages: list[dict[str, Any]],
    temperature: float,
) -> dict[str, Any]:
    if target.protocol == ProviderProtocol.OPENAI_RESPONSES:
        return {
            "model": target.upstream_model,
            "temperature": temperature,
            "input": _responses_input(messages),
            "max_output_tokens": settings.MODEL_MAX_OUTPUT_TOKENS,
        }
    return {
        "model": target.upstream_model,
        "temperature": temperature,
        "messages": messages,
        "max_tokens": settings.MODEL_MAX_OUTPUT_TOKENS,
    }


def response_content(protocol: ProviderProtocol, payload: dict[str, Any]) -> str:
    if protocol == ProviderProtocol.OPENAI_CHAT:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderGatewayError("上游响应缺少 choices")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise ProviderGatewayError("上游响应 choices 格式无效")
        message = choice.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ProviderGatewayError("上游响应缺少文本内容")
        return message["content"]
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    texts: list[str] = []
    for output in payload.get("output") or []:
        if not isinstance(output, dict):
            continue
        for content in output.get("content") or []:
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                texts.append(content["text"])
    if not texts:
        raise ProviderGatewayError("上游响应缺少文本内容")
    return "\n".join(texts)


def probe_target(target: RuntimeTarget) -> tuple[int, bool, str | None]:
    started = time.perf_counter()
    with httpx.Client(
        follow_redirects=False,
        trust_env=settings.ENVIRONMENT == "local",
        verify=True,
        timeout=target.timeout_seconds,
    ) as client:
        response = client.post(
            endpoint(target),
            headers={
                "Authorization": f"Bearer {target.api_key}",
                "Content-Type": "application/json",
            },
            json=request_payload(
                target,
                messages=[
                    {
                        "role": "user",
                        "content": '只返回 JSON：{"ok":true}',
                    }
                ],
                temperature=(
                    1.0
                    if target.canonical_model.startswith("kimi-")
                    or target.upstream_model.startswith("kimi-")
                    else 0.1
                ),
            ),
        )
    latency_ms = round((time.perf_counter() - started) * 1000)
    if response.status_code >= 400:
        raise ProviderGatewayError(f"上游返回 HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ProviderGatewayError("上游响应格式无效")
    response_content(target.protocol, payload)
    usage = payload.get("usage")
    headers = response.headers
    request_id = (
        headers.get("x-request-id")
        or headers.get("request-id")
        or headers.get("openai-request-id")
    )
    return latency_ms, isinstance(usage, dict) and bool(usage), request_id


def record_success(
    target: RuntimeTarget, *, latency_ms: int, usage_present: bool, http_status: int
) -> None:
    with Session(engine) as session:
        state = _locked_health(session, target)
        state.success_count += 1
        state.consecutive_failures = 0
        state.consecutive_missing_usage = (
            0 if usage_present else state.consecutive_missing_usage + 1
        )
        # Billability is tracked on the mapping; a valid response is still a
        # healthy network call even when the upstream omitted usage metadata.
        state.status = ProviderHealthStatus.HEALTHY
        state.latency_ewma_ms = (
            float(latency_ms)
            if state.latency_ewma_ms is None
            else state.latency_ewma_ms * 0.8 + latency_ms * 0.2
        )
        state.circuit_open_until = None
        state.last_http_status = http_status
        state.last_error_code = None
        state.last_checked_at = state.updated_at = datetime.now(UTC)
        session.add(state)
        mapping = session.exec(
            select(ProviderModelMapping).where(
                ProviderModelMapping.channel_id == target.channel_id,
                ProviderModelMapping.canonical_model == target.canonical_model,
            )
        ).first()
        if mapping:
            if usage_present:
                mapping.usage_metering_verified = True
                mapping.usage_verified_at = datetime.now(UTC)
            elif state.consecutive_missing_usage >= 1:
                mapping.usage_metering_verified = False
            session.add(mapping)
        session.commit()


def is_managed_route(*, provider: str, model: str) -> bool:
    """Return true once a provider/model has been imported into the control plane."""
    with Session(engine) as session:
        return (
            session.exec(
                select(ProviderModelMapping.id)
                .join(
                    ProviderChannel,
                    ProviderModelMapping.channel_id == ProviderChannel.id,
                )
                .where(
                    ProviderModelMapping.canonical_model == model,
                    ProviderChannel.code == provider,
                )
            ).first()
            is not None
        )


def is_managed_purpose(*, workflow_purpose: str | None) -> bool:
    """Configured function routes are authoritative, including an unavailable route."""
    if not workflow_purpose:
        return False
    with Session(engine) as session:
        return (
            session.exec(
                select(ModelRoutePolicy.id).where(
                    ModelRoutePolicy.purpose == workflow_purpose,
                    ModelRoutePolicy.enabled.is_(True),
                )
            ).first()
            is not None
        )


def record_failure(
    target: RuntimeTarget, *, error_code: str, http_status: int | None
) -> None:
    with Session(engine) as session:
        state = _locked_health(session, target)
        state.failure_count += 1
        state.consecutive_failures += 1
        state.last_http_status = http_status
        state.last_error_code = error_code[:100]
        state.last_checked_at = state.updated_at = datetime.now(UTC)
        if state.consecutive_failures >= 5:
            state.status = ProviderHealthStatus.OPEN
            state.circuit_open_until = datetime.now(UTC) + timedelta(minutes=2)
        else:
            state.status = ProviderHealthStatus.DEGRADED
        session.add(state)
        session.commit()


def _locked_health(session: Session, target: RuntimeTarget) -> ProviderHealthState:
    state = session.exec(
        select(ProviderHealthState)
        .where(
            ProviderHealthState.channel_id == target.channel_id,
            ProviderHealthState.canonical_model == target.canonical_model,
        )
        .with_for_update()
    ).first()
    if state:
        return state
    state = ProviderHealthState(
        channel_id=target.channel_id, canonical_model=target.canonical_model
    )
    session.add(state)
    try:
        session.flush()
        return state
    except IntegrityError:
        session.rollback()
        existing = session.exec(
            select(ProviderHealthState)
            .where(
                ProviderHealthState.channel_id == target.channel_id,
                ProviderHealthState.canonical_model == target.canonical_model,
            )
            .with_for_update()
        ).first()
        if not existing:
            raise
        return existing


def channel_health_status(
    session: Session, channel_id: uuid.UUID
) -> ProviderHealthStatus:
    states = list(
        session.exec(
            select(ProviderHealthState).where(
                ProviderHealthState.channel_id == channel_id
            )
        ).all()
    )
    if not states:
        return ProviderHealthStatus.UNKNOWN
    order = {
        ProviderHealthStatus.DISABLED: 4,
        ProviderHealthStatus.OPEN: 3,
        ProviderHealthStatus.DEGRADED: 2,
        ProviderHealthStatus.UNKNOWN: 1,
        ProviderHealthStatus.HEALTHY: 0,
    }
    return max((item.status for item in states), key=order.__getitem__)
