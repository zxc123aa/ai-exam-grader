"""平台管理员使用的外部模型中转控制面。"""

import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, delete, select

from app.api.deps import SessionDep, require_roles
from app.core.config import settings
from app.models import (
    FunctionModelAssignment,
    FunctionModelAssignmentPublic,
    FunctionModelAssignmentUpdate,
    ModelRoutePolicy,
    ModelRoutePolicyPublic,
    ModelRoutePolicyUpsert,
    ModelRouteTarget,
    ModelRouteTargetInput,
    ModelRouteTargetPublic,
    ModelRouteVersion,
    ModelRouteVersionPublic,
    ModelRouteVersionStatus,
    ModelRouteVersionTarget,
    ModelUsageEvent,
    ModelUsageStatus,
    NewApiBillingSyncPublic,
    ProviderAuditLog,
    ProviderBillingCredentialUpdate,
    ProviderChannel,
    ProviderChannelCreate,
    ProviderChannelKind,
    ProviderChannelPublic,
    ProviderChannelsPublic,
    ProviderChannelStatus,
    ProviderChannelTestRequest,
    ProviderChannelTestResult,
    ProviderChannelUpdate,
    ProviderCredential,
    ProviderCredentialUpdate,
    ProviderHealthState,
    ProviderInternalRateVersion,
    ProviderInternalRateVersionCreate,
    ProviderInternalRateVersionPublic,
    ProviderModelDiscoveryResult,
    ProviderModelMapping,
    ProviderModelMappingCreate,
    ProviderModelMappingPublic,
    ProviderModelMappingUpdate,
    ProviderProtocol,
    ProviderReconciliationBatch,
    ProviderReconciliationItem,
    ReconciliationBatchPublic,
    ReconciliationImport,
    UsageReconciliationStatus,
    User,
    UserRole,
)
from app.services import new_api_billing, provider_gateway
from app.services.model_purpose_policy import (
    PURE_VISION_PURPOSES,
    REASONING_PURPOSES,
    TRADITIONAL_IMAGE_PURPOSES,
    model_allowed_for_purpose,
)
from app.services.provider_security import (
    ProviderSecurityError,
    decrypt_credential,
    encrypt_credential,
    validate_provider_base_url,
)
from app.services.system_config import PROVIDER_MODELS

router = APIRouter(prefix="/platform/provider-channels", tags=["provider-channels"])
PlatformAdmin = Annotated[User, Depends(require_roles(UserRole.PLATFORM_SUPERUSER))]

_RISK_KINDS = {
    ProviderChannelKind.SUB2API,
    ProviderChannelKind.CLI_PROXY_API,
    ProviderChannelKind.CUSTOM,
}
_PURPOSE_RE = re.compile(r"^[a-z][a-z0-9_]{0,49}$")
_LEGACY_CHANNELS = {
    "pomoai": (
        "PomoAI 综合通道",
        "PROVIDER_POMOAI_BASE_URL",
        "PROVIDER_POMOAI_API_KEY",
        ProviderChannelKind.AUTHORIZED_RELAY,
    ),
    "fluxnode_gemini": (
        "FluxNode · Gemini",
        "PROVIDER_FLUXNODE_GEMINI_BASE_URL",
        "PROVIDER_FLUXNODE_GEMINI_API_KEY",
        ProviderChannelKind.AUTHORIZED_RELAY,
    ),
    "fluxnode_grok": (
        "FluxNode · Grok",
        "PROVIDER_FLUXNODE_GROK_BASE_URL",
        "PROVIDER_FLUXNODE_GROK_API_KEY",
        ProviderChannelKind.AUTHORIZED_RELAY,
    ),
    "kimi": (
        "Kimi 官方接口",
        "PROVIDER_KIMI_BASE_URL",
        "PROVIDER_KIMI_API_KEY",
        ProviderChannelKind.OFFICIAL_API,
    ),
}
_IMAGE_INPUT_PURPOSES = PURE_VISION_PURPOSES | REASONING_PURPOSES


def _validate_route_mapping(
    mapping: ProviderModelMapping, *, canonical_model: str, purpose: str
) -> None:
    if mapping.canonical_model != canonical_model:
        raise HTTPException(status_code=422, detail="路由目标与标准模型不匹配")
    if not mapping.supports_structured_output:
        raise HTTPException(status_code=422, detail="调用路由需要支持结构化输出")
    if purpose in TRADITIONAL_IMAGE_PURPOSES:
        raise HTTPException(status_code=422, detail="传统图像处理无需配置模型路由")
    if purpose in _IMAGE_INPUT_PURPOSES and not mapping.supports_vision:
        raise HTTPException(status_code=422, detail="该业务用途需要支持图片输入")
    if not model_allowed_for_purpose(purpose=purpose, canonical_model=canonical_model):
        detail = (
            "纯视觉功能只允许使用 Gemini 3.7/3.6/3.5 Flash"
            if purpose in PURE_VISION_PURPOSES
            else "推理解题功能只允许使用 GPT-5.6 Sol、GPT-5.6 Terra 或 Kimi"
        )
        raise HTTPException(status_code=422, detail=detail)


def _channel_or_404(session: SessionDep, channel_id: uuid.UUID) -> ProviderChannel:
    channel = session.get(ProviderChannel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="中转渠道不存在")
    return channel


def _audit(
    session: SessionDep,
    *,
    actor_id: uuid.UUID,
    action: str,
    channel_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        ProviderAuditLog(
            channel_id=channel_id,
            actor_id=actor_id,
            action=action,
            details=details or {},
        )
    )


def _credential(
    session: SessionDep, channel_id: uuid.UUID
) -> ProviderCredential | None:
    return session.exec(
        select(ProviderCredential).where(ProviderCredential.channel_id == channel_id)
    ).first()


def _channel_public(
    session: SessionDep, channel: ProviderChannel
) -> ProviderChannelPublic:
    credential = _credential(session, channel.id)
    return ProviderChannelPublic(
        **channel.model_dump(),
        credential_configured=credential is not None,
        credential_fingerprint=credential.fingerprint if credential else None,
        credential_last_four=credential.last_four if credential else None,
        billing_credential_configured=bool(
            credential and credential.billing_ciphertext and credential.billing_nonce
        ),
        billing_credential_last_four=(
            credential.billing_last_four if credential else None
        ),
        billing_user_id=credential.billing_user_id if credential else None,
        health_status=provider_gateway.channel_health_status(session, channel.id),
    )


def _reconciliation_public(
    batch: ProviderReconciliationBatch,
) -> ReconciliationBatchPublic:
    return ReconciliationBatchPublic(
        **(
            batch.model_dump()
            | {
                "upstream_total_used_rmb": float(
                    Decimal(batch.upstream_total_used_micrormb) / Decimal(1_000_000)
                )
            }
        )
    )


def _validate_enable(
    session: SessionDep,
    channel: ProviderChannel,
    *,
    credential_will_exist: bool = False,
) -> None:
    if channel.kind in _RISK_KINDS and not channel.risk_acknowledged:
        raise HTTPException(
            status_code=422, detail="启用该类中转前必须确认授权与合规风险"
        )
    if not credential_will_exist and _credential(session, channel.id) is None:
        raise HTTPException(status_code=422, detail="启用中转前必须配置调用密钥")


@router.get("", response_model=ProviderChannelsPublic)
def list_channels(session: SessionDep, _current_user: PlatformAdmin) -> Any:
    channels = list(
        session.exec(
            select(ProviderChannel).order_by(col(ProviderChannel.priority))
        ).all()
    )
    return ProviderChannelsPublic(
        data=[_channel_public(session, channel) for channel in channels],
        count=len(channels),
    )


@router.post("/import-environment", response_model=ProviderChannelsPublic)
def import_environment_channels(
    session: SessionDep, current_user: PlatformAdmin
) -> Any:
    """把旧环境变量中的 URL、Key 和模型清单纳入数据库通道管理。"""
    configured = [
        (code, metadata)
        for code, metadata in _LEGACY_CHANNELS.items()
        if str(getattr(settings, metadata[2], "")).strip()
    ]
    if not configured:
        raise HTTPException(status_code=422, detail="没有可导入的旧服务配置")

    try:
        for code, (display_name, url_attr, key_attr, kind) in configured:
            api_key = str(getattr(settings, key_attr)).strip()
            base_url = validate_provider_base_url(str(getattr(settings, url_attr)))
            channel = session.exec(
                select(ProviderChannel).where(ProviderChannel.code == code)
            ).first()
            if not channel:
                channel = ProviderChannel(
                    code=code,
                    display_name=display_name,
                    kind=kind,
                    protocol=ProviderProtocol.OPENAI_CHAT,
                    base_url=base_url,
                    enabled=True,
                    status=ProviderChannelStatus.ACTIVE,
                    created_by_id=current_user.id,
                )
                session.add(channel)
                session.flush()
            if _credential(session, channel.id) is None:
                encrypted = encrypt_credential(api_key, channel_id=channel.id)
                session.add(
                    ProviderCredential(
                        channel_id=channel.id,
                        rotated_by_id=current_user.id,
                        **encrypted.__dict__,
                    )
                )

            for canonical_model in PROVIDER_MODELS.get(code, []):
                mapping = session.exec(
                    select(ProviderModelMapping).where(
                        ProviderModelMapping.channel_id == channel.id,
                        ProviderModelMapping.canonical_model == canonical_model,
                    )
                ).first()
                if not mapping:
                    mapping = ProviderModelMapping(
                        channel_id=channel.id,
                        canonical_model=canonical_model,
                        upstream_model=canonical_model,
                        supports_vision=code != "kimi",
                        supports_structured_output=True,
                    )
                    session.add(mapping)
                    session.flush()
            _audit(
                session,
                actor_id=current_user.id,
                action="channel.import_environment",
                channel_id=channel.id,
                details={
                    "code": code,
                    "model_count": len(PROVIDER_MODELS.get(code, [])),
                },
            )
        session.commit()
    except ProviderSecurityError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    channels = list(
        session.exec(
            select(ProviderChannel).order_by(col(ProviderChannel.priority))
        ).all()
    )
    return ProviderChannelsPublic(
        data=[_channel_public(session, channel) for channel in channels],
        count=len(channels),
    )


@router.post("", response_model=ProviderChannelPublic)
def create_channel(
    session: SessionDep,
    current_user: PlatformAdmin,
    channel_in: ProviderChannelCreate,
) -> Any:
    try:
        base_url = validate_provider_base_url(channel_in.base_url)
    except ProviderSecurityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if session.exec(
        select(ProviderChannel).where(ProviderChannel.code == channel_in.code)
    ).first():
        raise HTTPException(status_code=409, detail="渠道代码已存在")
    values = channel_in.model_dump(exclude={"api_key", "base_url", "status", "enabled"})
    requested_status = channel_in.status or (
        ProviderChannelStatus.ACTIVE
        if channel_in.enabled
        else ProviderChannelStatus.DRAFT
    )
    channel = ProviderChannel(
        **values,
        base_url=base_url,
        status=requested_status,
        enabled=requested_status == ProviderChannelStatus.ACTIVE,
        created_by_id=current_user.id,
    )
    if channel.status == ProviderChannelStatus.ACTIVE:
        _validate_enable(
            session, channel, credential_will_exist=bool(channel_in.api_key)
        )
    session.add(channel)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="渠道代码已存在") from exc
    if channel_in.api_key:
        try:
            encrypted = encrypt_credential(channel_in.api_key, channel_id=channel.id)
        except ProviderSecurityError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        session.add(
            ProviderCredential(
                channel_id=channel.id,
                rotated_by_id=current_user.id,
                **encrypted.__dict__,
            )
        )
    _audit(
        session,
        actor_id=current_user.id,
        action="channel.create",
        channel_id=channel.id,
        details={"code": channel.code, "kind": channel.kind.value},
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        constraint = getattr(getattr(exc, "orig", None), "diag", None)
        constraint_name = getattr(constraint, "constraint_name", None)
        detail = (
            "渠道代码已存在"
            if constraint_name == "ix_providerchannel_code"
            else "渠道配置与现有数据冲突"
        )
        raise HTTPException(status_code=409, detail=detail) from exc
    session.refresh(channel)
    return _channel_public(session, channel)


@router.patch("/{channel_id}", response_model=ProviderChannelPublic)
def update_channel(
    session: SessionDep,
    current_user: PlatformAdmin,
    channel_id: uuid.UUID,
    channel_in: ProviderChannelUpdate,
) -> Any:
    channel = _channel_or_404(session, channel_id)
    updates = channel_in.model_dump(exclude_unset=True)
    if "base_url" in updates:
        try:
            updates["base_url"] = validate_provider_base_url(updates["base_url"])
        except ProviderSecurityError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if "status" in updates:
        updates["enabled"] = updates["status"] == ProviderChannelStatus.ACTIVE
    elif "enabled" in updates:
        updates["status"] = (
            ProviderChannelStatus.ACTIVE
            if updates["enabled"]
            else ProviderChannelStatus.DISABLED
        )
    channel.sqlmodel_update(updates)
    channel.updated_at = datetime.now(UTC)
    if channel.status == ProviderChannelStatus.ACTIVE:
        _validate_enable(session, channel)
    session.add(channel)
    _audit(
        session,
        actor_id=current_user.id,
        action="channel.update",
        channel_id=channel.id,
        details={"fields": sorted(updates)},
    )
    session.commit()
    session.refresh(channel)
    return _channel_public(session, channel)


@router.put("/{channel_id}/credential", response_model=ProviderChannelPublic)
def rotate_credential(
    session: SessionDep,
    current_user: PlatformAdmin,
    channel_id: uuid.UUID,
    credential_in: ProviderCredentialUpdate,
) -> Any:
    channel = _channel_or_404(session, channel_id)
    try:
        encrypted = encrypt_credential(credential_in.api_key, channel_id=channel.id)
    except ProviderSecurityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    credential = _credential(session, channel.id)
    values = encrypted.__dict__ | {
        "rotated_by_id": current_user.id,
        "rotated_at": datetime.now(UTC),
    }
    if credential:
        credential.sqlmodel_update(values)
    else:
        credential = ProviderCredential(channel_id=channel.id, **values)
    session.add(credential)
    _audit(
        session,
        actor_id=current_user.id,
        action="credential.rotate",
        channel_id=channel.id,
        details={"fingerprint": encrypted.fingerprint},
    )
    session.commit()
    return _channel_public(session, channel)


@router.put("/{channel_id}/billing-credential", response_model=ProviderChannelPublic)
def rotate_billing_credential(
    session: SessionDep,
    current_user: PlatformAdmin,
    channel_id: uuid.UUID,
    credential_in: ProviderBillingCredentialUpdate,
) -> Any:
    channel = _channel_or_404(session, channel_id)
    if channel.kind == ProviderChannelKind.NEW_API and not credential_in.user_id:
        raise HTTPException(
            status_code=422,
            detail="New API 账单凭据还需要 New-Api-User ID",
        )
    try:
        encrypted = encrypt_credential(
            credential_in.access_token, channel_id=channel.id
        )
    except ProviderSecurityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    credential = _credential(session, channel.id)
    if not credential:
        raise HTTPException(status_code=422, detail="请先配置模型调用密钥")
    credential.billing_ciphertext = encrypted.ciphertext
    credential.billing_nonce = encrypted.nonce
    credential.billing_key_version = encrypted.key_version
    credential.billing_fingerprint = encrypted.fingerprint
    credential.billing_last_four = encrypted.last_four
    credential.billing_user_id = credential_in.user_id
    credential.rotated_by_id = current_user.id
    credential.rotated_at = datetime.now(UTC)
    session.add(credential)
    _audit(
        session,
        actor_id=current_user.id,
        action="credential.billing_rotate",
        channel_id=channel.id,
        details={
            "fingerprint": encrypted.fingerprint,
            "billing_user_id": credential_in.user_id,
        },
    )
    session.commit()
    return _channel_public(session, channel)


@router.get("/{channel_id}/models", response_model=list[ProviderModelMappingPublic])
def list_model_mappings(
    session: SessionDep, _current_user: PlatformAdmin, channel_id: uuid.UUID
) -> Any:
    _channel_or_404(session, channel_id)
    return list(
        session.exec(
            select(ProviderModelMapping)
            .where(ProviderModelMapping.channel_id == channel_id)
            .order_by(ProviderModelMapping.canonical_model)
        ).all()
    )


@router.post(
    "/{channel_id}/models/discover",
    response_model=ProviderModelDiscoveryResult,
)
def discover_upstream_models(
    session: SessionDep,
    current_user: PlatformAdmin,
    channel_id: uuid.UUID,
) -> Any:
    """使用服务端保存的凭据读取 OpenAI 兼容中转的模型目录。"""
    channel = _channel_or_404(session, channel_id)
    credential = _credential(session, channel.id)
    if not credential:
        raise HTTPException(status_code=422, detail="请先配置调用密钥")
    try:
        base_url = validate_provider_base_url(channel.base_url).rstrip("/")
        api_key = decrypt_credential(
            credential.ciphertext,
            credential.nonce,
            channel_id=channel.id,
        )
        endpoint = (
            f"{base_url}/models"
            if base_url.endswith("/v1")
            else f"{base_url}/v1/models"
        )
        with httpx.Client(
            follow_redirects=False,
            trust_env=settings.ENVIRONMENT == "local",
            verify=True,
            timeout=channel.timeout_seconds,
        ) as client:
            response = client.get(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()
            payload = response.json()
    except ProviderSecurityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"上游返回 HTTP {exc.response.status_code}，未能读取模型列表",
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="无法读取上游模型列表") from exc

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise HTTPException(status_code=502, detail="上游模型列表格式不兼容")
    models = sorted(
        {
            str(item["id"]).strip()
            for item in data
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        }
    )[:500]
    _audit(
        session,
        actor_id=current_user.id,
        action="channel.models_discover",
        channel_id=channel.id,
        details={"count": len(models)},
    )
    session.commit()
    return ProviderModelDiscoveryResult(
        channel_id=channel.id,
        models=models,
        count=len(models),
    )


@router.post("/{channel_id}/models", response_model=ProviderModelMappingPublic)
def create_model_mapping(
    session: SessionDep,
    current_user: PlatformAdmin,
    channel_id: uuid.UUID,
    mapping_in: ProviderModelMappingCreate,
) -> Any:
    _channel_or_404(session, channel_id)
    if session.exec(
        select(ProviderModelMapping).where(
            ProviderModelMapping.channel_id == channel_id,
            ProviderModelMapping.canonical_model == mapping_in.canonical_model,
        )
    ).first():
        raise HTTPException(status_code=409, detail="该渠道已配置此标准模型")
    mapping = ProviderModelMapping(channel_id=channel_id, **mapping_in.model_dump())
    session.add(mapping)
    _audit(
        session,
        actor_id=current_user.id,
        action="model_mapping.create",
        channel_id=channel_id,
        details={
            "canonical_model": mapping.canonical_model,
            "route_assignment": "manual",
        },
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="该渠道已配置此标准模型") from exc
    session.refresh(mapping)
    return mapping


@router.patch(
    "/{channel_id}/models/{mapping_id}",
    response_model=ProviderModelMappingPublic,
)
def update_model_mapping(
    session: SessionDep,
    current_user: PlatformAdmin,
    channel_id: uuid.UUID,
    mapping_id: uuid.UUID,
    mapping_in: ProviderModelMappingUpdate,
) -> Any:
    mapping = session.get(ProviderModelMapping, mapping_id)
    if not mapping or mapping.channel_id != channel_id:
        raise HTTPException(status_code=404, detail="模型映射不存在")
    updates = mapping_in.model_dump(exclude_unset=True)
    mapping.sqlmodel_update(updates)
    mapping.updated_at = datetime.now(UTC)
    session.add(mapping)
    _audit(
        session,
        actor_id=current_user.id,
        action="model_mapping.update",
        channel_id=channel_id,
        details={"mapping_id": str(mapping.id), "fields": sorted(updates)},
    )
    session.commit()
    session.refresh(mapping)
    return mapping


def _route_public(
    session: SessionDep, policy: ModelRoutePolicy
) -> ModelRoutePolicyPublic:
    published = session.exec(
        select(ModelRouteVersion)
        .where(
            ModelRouteVersion.policy_id == policy.id,
            ModelRouteVersion.status == ModelRouteVersionStatus.PUBLISHED,
        )
        .order_by(ModelRouteVersion.version.desc())
    ).first()
    if published:
        public_version = _version_public(session, published)
        return ModelRoutePolicyPublic(
            **(
                policy.model_dump()
                | {
                    "max_attempts": published.max_attempts,
                    "routing_mode": published.routing_mode,
                    "sticky_scope": published.sticky_scope,
                    "targets": public_version.targets,
                }
            )
        )
    rows = session.exec(
        select(ModelRouteTarget, ProviderModelMapping, ProviderChannel)
        .join(
            ProviderModelMapping,
            ModelRouteTarget.mapping_id == ProviderModelMapping.id,
        )
        .join(ProviderChannel, ProviderModelMapping.channel_id == ProviderChannel.id)
        .where(ModelRouteTarget.policy_id == policy.id)
        .order_by(ModelRouteTarget.priority, ProviderChannel.priority)
    ).all()
    return ModelRoutePolicyPublic(
        **policy.model_dump(),
        targets=[
            ModelRouteTargetPublic(
                id=target.id,
                mapping_id=mapping.id,
                channel_id=channel.id,
                channel_code=channel.code,
                canonical_model=mapping.canonical_model,
                upstream_model=mapping.upstream_model,
                protocol=channel.protocol,
                base_url=channel.base_url,
                priority=target.priority,
                weight=target.weight,
                enabled=target.enabled,
            )
            for target, mapping, channel in rows
        ],
    )


def _version_public(
    session: SessionDep, version: ModelRouteVersion
) -> ModelRouteVersionPublic:
    rows = session.exec(
        select(ModelRouteVersionTarget)
        .where(ModelRouteVersionTarget.route_version_id == version.id)
        .order_by(ModelRouteVersionTarget.tier, ModelRouteVersionTarget.channel_code)
    ).all()
    return ModelRouteVersionPublic(
        **version.model_dump(),
        targets=[
            ModelRouteTargetPublic(
                id=target.id,
                mapping_id=target.mapping_id,
                channel_id=target.channel_id,
                channel_code=target.channel_code,
                canonical_model=target.canonical_model,
                upstream_model=target.upstream_model,
                protocol=target.protocol,
                base_url=target.base_url,
                priority=target.tier,
                weight=target.weight,
                enabled=target.enabled,
                cost_rmb_per_million=(
                    target.cost_micrormb_per_million / 1_000_000
                    if target.internal_rate_version_id
                    else None
                ),
            )
            for target in rows
        ],
    )


def _create_route_draft(
    session: SessionDep,
    *,
    policy: ModelRoutePolicy,
    policy_in: ModelRoutePolicyUpsert,
    actor_id: uuid.UUID,
) -> ModelRouteVersion:
    latest = session.exec(
        select(ModelRouteVersion)
        .where(ModelRouteVersion.policy_id == policy.id)
        .order_by(ModelRouteVersion.version.desc())
    ).first()
    if latest and latest.status == ModelRouteVersionStatus.DRAFT:
        session.exec(
            delete(ModelRouteVersionTarget).where(
                ModelRouteVersionTarget.route_version_id == latest.id
            )
        )
        draft = latest
    else:
        draft = ModelRouteVersion(
            policy_id=policy.id,
            version=(latest.version + 1) if latest else 1,
            created_by_id=actor_id,
        )
    draft.max_attempts = policy_in.max_attempts
    draft.routing_mode = policy_in.routing_mode
    draft.sticky_scope = policy.sticky_scope
    session.add(draft)
    session.flush()
    priority_tiers = {
        priority: index
        for index, priority in enumerate(
            sorted({item.priority for item in policy_in.targets}), start=1
        )
    }
    for item in policy_in.targets:
        mapping = session.get(ProviderModelMapping, item.mapping_id)
        if not mapping:
            raise HTTPException(status_code=422, detail="模型映射不存在")
        channel = session.get(ProviderChannel, mapping.channel_id)
        if not channel:
            raise HTTPException(status_code=422, detail="中转通道不存在")
        rate = session.exec(
            select(ProviderInternalRateVersion)
            .where(
                ProviderInternalRateVersion.channel_id == channel.id,
                ProviderInternalRateVersion.canonical_model == mapping.canonical_model,
                ProviderInternalRateVersion.effective_at <= datetime.now(UTC),
            )
            .order_by(col(ProviderInternalRateVersion.effective_at).desc())
        ).first()
        session.add(
            ModelRouteVersionTarget(
                route_version_id=draft.id,
                mapping_id=item.mapping_id,
                channel_id=channel.id,
                channel_code=channel.code,
                canonical_model=mapping.canonical_model,
                upstream_model=mapping.upstream_model,
                protocol=channel.protocol,
                base_url=channel.base_url,
                internal_rate_version_id=rate.id if rate else None,
                cost_micrormb_per_million=(
                    max(
                        rate.input_micrormb_per_million,
                        rate.output_micrormb_per_million,
                        rate.image_micrormb_per_million,
                    )
                    if rate
                    else 0
                ),
                tier=priority_tiers[item.priority],
                weight=item.weight,
                enabled=item.enabled,
            )
        )
    return draft


@router.get("/routes", response_model=list[ModelRoutePolicyPublic])
def list_route_policies(
    session: SessionDep,
    _current_user: PlatformAdmin,
    purpose: str | None = None,
) -> Any:
    statement = select(ModelRoutePolicy).order_by(
        ModelRoutePolicy.purpose, col(ModelRoutePolicy.updated_at).desc()
    )
    if purpose:
        statement = statement.where(ModelRoutePolicy.purpose == purpose)
    policies = session.exec(statement).all()
    return [_route_public(session, policy) for policy in policies]


@router.get(
    "/routes/defaults",
    response_model=list[FunctionModelAssignmentPublic],
)
def list_function_model_defaults(
    session: SessionDep, _current_user: PlatformAdmin
) -> Any:
    return list(
        session.exec(
            select(FunctionModelAssignment).order_by(FunctionModelAssignment.purpose)
        ).all()
    )


@router.put(
    "/routes/{purpose}/default",
    response_model=FunctionModelAssignmentPublic,
)
def update_function_model_default(
    session: SessionDep,
    current_user: PlatformAdmin,
    purpose: str,
    assignment_in: FunctionModelAssignmentUpdate,
) -> Any:
    if not _PURPOSE_RE.fullmatch(purpose):
        raise HTTPException(status_code=422, detail="业务用途格式无效")
    if purpose in TRADITIONAL_IMAGE_PURPOSES:
        raise HTTPException(status_code=422, detail="传统图像处理无需配置模型路由")
    if not model_allowed_for_purpose(
        purpose=purpose,
        canonical_model=assignment_in.canonical_model,
    ):
        detail = (
            "纯视觉功能只允许使用 Gemini 3.7/3.6/3.5 Flash"
            if purpose in PURE_VISION_PURPOSES
            else "推理解题功能只允许使用 GPT-5.6 Sol、GPT-5.6 Terra 或 Kimi"
        )
        raise HTTPException(status_code=422, detail=detail)
    policy = session.exec(
        select(ModelRoutePolicy).where(
            ModelRoutePolicy.purpose == purpose,
            ModelRoutePolicy.canonical_model == assignment_in.canonical_model,
            ModelRoutePolicy.enabled.is_(True),
        )
    ).first()
    if not policy:
        raise HTTPException(status_code=422, detail="默认模型必须先发布可用路由")
    published = session.exec(
        select(ModelRouteVersion.id).where(
            ModelRouteVersion.policy_id == policy.id,
            ModelRouteVersion.status == ModelRouteVersionStatus.PUBLISHED,
        )
    ).first()
    if not published:
        raise HTTPException(status_code=422, detail="默认模型必须先发布可用路由")
    assignment = session.get(FunctionModelAssignment, purpose)
    if assignment:
        assignment.default_canonical_model = assignment_in.canonical_model
        assignment.updated_by_id = current_user.id
        assignment.updated_at = datetime.now(UTC)
    else:
        assignment = FunctionModelAssignment(
            purpose=purpose,
            default_canonical_model=assignment_in.canonical_model,
            updated_by_id=current_user.id,
        )
    session.add(assignment)
    _audit(
        session,
        actor_id=current_user.id,
        action="function_model.default_update",
        details={
            "purpose": purpose,
            "canonical_model": assignment_in.canonical_model,
        },
    )
    session.commit()
    session.refresh(assignment)
    return assignment


@router.post("/routes/{purpose}/targets", response_model=ModelRoutePolicyPublic)
def add_route_target(
    session: SessionDep,
    current_user: PlatformAdmin,
    purpose: str,
    canonical_model: str,
    target_in: ModelRouteTargetInput,
) -> Any:
    if not _PURPOSE_RE.fullmatch(purpose):
        raise HTTPException(status_code=422, detail="业务用途格式无效")
    mapping = session.get(ProviderModelMapping, target_in.mapping_id)
    if not mapping:
        raise HTTPException(status_code=422, detail="模型映射不存在")
    _validate_route_mapping(mapping, canonical_model=canonical_model, purpose=purpose)
    policy = session.exec(
        select(ModelRoutePolicy).where(
            ModelRoutePolicy.purpose == purpose,
            ModelRoutePolicy.canonical_model == canonical_model,
        )
    ).first()
    if not policy:
        policy = ModelRoutePolicy(
            purpose=purpose,
            canonical_model=canonical_model,
            max_attempts=3,
            enabled=False,
        )
        session.add(policy)
        session.flush()
    existing = session.exec(
        select(ModelRouteTarget).where(
            ModelRouteTarget.policy_id == policy.id,
            ModelRouteTarget.mapping_id == target_in.mapping_id,
        )
    ).first()
    if existing:
        existing.sqlmodel_update(target_in.model_dump(exclude={"mapping_id"}))
        session.add(existing)
    else:
        session.add(ModelRouteTarget(policy_id=policy.id, **target_in.model_dump()))
    session.flush()
    legacy_targets = session.exec(
        select(ModelRouteTarget).where(ModelRouteTarget.policy_id == policy.id)
    ).all()
    draft_input = ModelRoutePolicyUpsert(
        canonical_model=canonical_model,
        enabled=policy.enabled,
        max_attempts=policy.max_attempts,
        routing_mode=policy.routing_mode,
        targets=[
            ModelRouteTargetInput(
                mapping_id=target.mapping_id,
                priority=target.priority,
                weight=target.weight,
                enabled=target.enabled,
            )
            for target in legacy_targets
        ],
    )
    draft = _create_route_draft(
        session,
        policy=policy,
        policy_in=draft_input,
        actor_id=current_user.id,
    )
    _audit(
        session,
        actor_id=current_user.id,
        action="route_target.add",
        details={
            "purpose": purpose,
            "canonical_model": canonical_model,
            "mapping_id": str(target_in.mapping_id),
            "draft_version": draft.version,
        },
    )
    session.commit()
    session.refresh(policy)
    return _route_public(session, policy)


@router.get("/routes/{purpose}", response_model=ModelRoutePolicyPublic)
def read_route_policy(
    session: SessionDep,
    _current_user: PlatformAdmin,
    purpose: str,
    canonical_model: str | None = None,
) -> Any:
    statement = select(ModelRoutePolicy).where(ModelRoutePolicy.purpose == purpose)
    if canonical_model:
        statement = statement.where(ModelRoutePolicy.canonical_model == canonical_model)
    else:
        assignment = session.get(FunctionModelAssignment, purpose)
        statement = statement.where(ModelRoutePolicy.enabled.is_(True))
        if assignment:
            statement = statement.where(
                ModelRoutePolicy.canonical_model == assignment.default_canonical_model
            )
        statement = statement.order_by(col(ModelRoutePolicy.updated_at).desc())
    policy = session.exec(statement).first()
    if not policy:
        raise HTTPException(status_code=404, detail="路由策略不存在")
    return _route_public(session, policy)


@router.put("/routes/{purpose}", response_model=ModelRoutePolicyPublic)
def upsert_route_policy(
    session: SessionDep,
    current_user: PlatformAdmin,
    purpose: str,
    policy_in: ModelRoutePolicyUpsert,
) -> Any:
    if not _PURPOSE_RE.fullmatch(purpose):
        raise HTTPException(status_code=422, detail="业务用途格式无效")
    mapping_ids = [item.mapping_id for item in policy_in.targets]
    if len(mapping_ids) != len(set(mapping_ids)):
        raise HTTPException(status_code=422, detail="路由目标不能重复")
    mappings = list(
        session.exec(
            select(ProviderModelMapping).where(
                col(ProviderModelMapping.id).in_(mapping_ids)
            )
        ).all()
    )
    if len(mappings) != len(mapping_ids):
        raise HTTPException(status_code=422, detail="存在无效的模型映射")
    for mapping in mappings:
        _validate_route_mapping(
            mapping,
            canonical_model=policy_in.canonical_model,
            purpose=purpose,
        )
    policy = session.exec(
        select(ModelRoutePolicy).where(
            ModelRoutePolicy.purpose == purpose,
            ModelRoutePolicy.canonical_model == policy_in.canonical_model,
        )
    ).first()
    if not policy:
        policy = ModelRoutePolicy(
            purpose=purpose,
            canonical_model=policy_in.canonical_model,
            enabled=False,
        )
    elif not policy_in.enabled:
        policy.enabled = False
    policy.canonical_model = policy_in.canonical_model
    policy.max_attempts = policy_in.max_attempts
    policy.routing_mode = policy_in.routing_mode
    policy.updated_at = datetime.now(UTC)
    session.add(policy)
    session.flush()
    session.exec(
        delete(ModelRouteTarget).where(ModelRouteTarget.policy_id == policy.id)
    )
    for item in policy_in.targets:
        session.add(ModelRouteTarget(policy_id=policy.id, **item.model_dump()))
    draft = _create_route_draft(
        session,
        policy=policy,
        policy_in=policy_in,
        actor_id=current_user.id,
    )
    _audit(
        session,
        actor_id=current_user.id,
        action="route_policy.upsert",
        details={
            "purpose": purpose,
            "canonical_model": policy.canonical_model,
            "target_count": len(policy_in.targets),
            "draft_version": draft.version,
        },
    )
    session.commit()
    session.refresh(policy)
    return _route_public(session, policy)


@router.get(
    "/routes/{purpose}/versions",
    response_model=list[ModelRouteVersionPublic],
)
def list_route_versions(
    session: SessionDep,
    _current_user: PlatformAdmin,
    purpose: str,
    canonical_model: str,
) -> Any:
    policy = session.exec(
        select(ModelRoutePolicy).where(
            ModelRoutePolicy.purpose == purpose,
            ModelRoutePolicy.canonical_model == canonical_model,
        )
    ).first()
    if not policy:
        raise HTTPException(status_code=404, detail="路由策略不存在")
    versions = session.exec(
        select(ModelRouteVersion)
        .where(ModelRouteVersion.policy_id == policy.id)
        .order_by(ModelRouteVersion.version.desc())
    ).all()
    return [_version_public(session, version) for version in versions]


@router.post(
    "/routes/{purpose}/versions/{version_id}/publish",
    response_model=ModelRouteVersionPublic,
)
def publish_route_version(
    session: SessionDep,
    current_user: PlatformAdmin,
    purpose: str,
    version_id: uuid.UUID,
) -> Any:
    version = session.get(ModelRouteVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="路由版本不存在")
    policy = session.get(ModelRoutePolicy, version.policy_id)
    if not policy or policy.purpose != purpose:
        raise HTTPException(status_code=404, detail="路由版本不存在")
    targets = list(
        session.exec(
            select(ModelRouteVersionTarget, ProviderModelMapping, ProviderChannel)
            .join(
                ProviderModelMapping,
                ModelRouteVersionTarget.mapping_id == ProviderModelMapping.id,
            )
            .join(
                ProviderChannel,
                ProviderModelMapping.channel_id == ProviderChannel.id,
            )
            .where(
                ModelRouteVersionTarget.route_version_id == version.id,
                ModelRouteVersionTarget.enabled.is_(True),
            )
        ).all()
    )
    if not targets:
        raise HTTPException(status_code=422, detail="路由至少需要一个可用目标")
    unavailable = [
        channel.display_name
        for _target, mapping, channel in targets
        if channel.status != ProviderChannelStatus.ACTIVE or not mapping.enabled
    ]
    if unavailable:
        raise HTTPException(
            status_code=422,
            detail=f"以下通道当前不可用：{'、'.join(unavailable)}",
        )
    for _target, mapping, _channel in targets:
        _validate_route_mapping(
            mapping,
            canonical_model=policy.canonical_model,
            purpose=purpose,
        )
    stale = [
        channel.display_name
        for target, mapping, channel in targets
        if target.channel_id != channel.id
        or target.channel_code != channel.code
        or target.canonical_model != mapping.canonical_model
        or target.upstream_model != mapping.upstream_model
        or target.protocol != channel.protocol
        or target.base_url != channel.base_url
    ]
    if stale:
        raise HTTPException(
            status_code=409,
            detail=f"以下通道配置已变化，请重新保存草稿：{'、'.join(stale)}",
        )
    invalid = [
        channel.display_name
        for _target, mapping, channel in targets
        if not mapping.usage_metering_verified
    ]
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"以下通道尚未通过用量计量检测：{'、'.join(invalid)}",
        )
    if version.routing_mode == "cost_first":
        missing_rates = [
            channel.display_name
            for target, _mapping, channel in targets
            if not target.internal_rate_version_id
        ]
        if missing_rates:
            raise HTTPException(
                status_code=422,
                detail=f"成本优先模式要求先配置内部费率：{'、'.join(missing_rates)}",
            )
    now = datetime.now(UTC)
    published = session.exec(
        select(ModelRouteVersion).where(
            ModelRouteVersion.policy_id == policy.id,
            ModelRouteVersion.status == ModelRouteVersionStatus.PUBLISHED,
        )
    ).all()
    for old in published:
        old.status = ModelRouteVersionStatus.RETIRED
        session.add(old)
    version.status = ModelRouteVersionStatus.PUBLISHED
    version.published_by_id = current_user.id
    version.published_at = now
    policy.max_attempts = version.max_attempts
    policy.routing_mode = version.routing_mode
    policy.enabled = True
    policy.updated_at = now
    assignment = session.get(FunctionModelAssignment, purpose)
    if not assignment:
        session.add(
            FunctionModelAssignment(
                purpose=purpose,
                default_canonical_model=policy.canonical_model,
                updated_by_id=current_user.id,
                updated_at=now,
            )
        )
    session.add(version)
    session.add(policy)
    _audit(
        session,
        actor_id=current_user.id,
        action="route_version.publish",
        details={
            "purpose": purpose,
            "canonical_model": policy.canonical_model,
            "version": version.version,
        },
    )
    session.commit()
    session.refresh(version)
    return _version_public(session, version)


@router.get(
    "/{channel_id}/internal-rates",
    response_model=list[ProviderInternalRateVersionPublic],
)
def list_internal_rates(
    session: SessionDep, _current_user: PlatformAdmin, channel_id: uuid.UUID
) -> Any:
    _channel_or_404(session, channel_id)
    rows = session.exec(
        select(ProviderInternalRateVersion)
        .where(ProviderInternalRateVersion.channel_id == channel_id)
        .order_by(col(ProviderInternalRateVersion.effective_at).desc())
    ).all()
    return [_rate_public(item) for item in rows]


def _rate_public(
    rate: ProviderInternalRateVersion,
) -> ProviderInternalRateVersionPublic:
    divisor = Decimal(1_000_000)
    return ProviderInternalRateVersionPublic(
        **rate.model_dump(
            exclude={
                "input_micrormb_per_million",
                "output_micrormb_per_million",
                "image_micrormb_per_million",
                "cached_input_micrormb_per_million",
            }
        ),
        input_rmb_per_million=float(Decimal(rate.input_micrormb_per_million) / divisor),
        output_rmb_per_million=float(
            Decimal(rate.output_micrormb_per_million) / divisor
        ),
        image_rmb_per_million=float(Decimal(rate.image_micrormb_per_million) / divisor),
        cached_input_rmb_per_million=float(
            Decimal(rate.cached_input_micrormb_per_million) / divisor
        ),
    )


@router.post(
    "/{channel_id}/internal-rates",
    response_model=ProviderInternalRateVersionPublic,
)
def create_internal_rate(
    session: SessionDep,
    current_user: PlatformAdmin,
    channel_id: uuid.UUID,
    rate_in: ProviderInternalRateVersionCreate,
) -> Any:
    _channel_or_404(session, channel_id)

    def micrormb(value: float) -> int:
        return int(
            (Decimal(str(value)) * 1_000_000).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )

    rate = ProviderInternalRateVersion(
        channel_id=channel_id,
        canonical_model=rate_in.canonical_model,
        version=rate_in.version,
        effective_at=rate_in.effective_at,
        input_micrormb_per_million=micrormb(rate_in.input_rmb_per_million),
        output_micrormb_per_million=micrormb(rate_in.output_rmb_per_million),
        image_micrormb_per_million=micrormb(rate_in.image_rmb_per_million),
        cached_input_micrormb_per_million=micrormb(
            rate_in.cached_input_rmb_per_million
        ),
    )
    session.add(rate)
    _audit(
        session,
        actor_id=current_user.id,
        action="internal_rate.create",
        channel_id=channel_id,
        details={"canonical_model": rate.canonical_model, "version": rate.version},
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="内部成本版本已存在") from exc
    session.refresh(rate)
    return _rate_public(rate)


@router.post("/{channel_id}/test", response_model=ProviderChannelTestResult)
def test_channel(
    session: SessionDep,
    current_user: PlatformAdmin,
    channel_id: uuid.UUID,
    test_in: ProviderChannelTestRequest,
) -> Any:
    channel = _channel_or_404(session, channel_id)
    target = None
    try:
        target = provider_gateway.resolve_channel_target(
            session,
            channel=channel,
            canonical_model=test_in.canonical_model,
            require_enabled=False,
        )
        latency_ms, usage_present, _request_id = provider_gateway.probe_target(target)
        provider_gateway.record_success(
            target,
            latency_ms=latency_ms,
            usage_present=usage_present,
            http_status=200,
        )
        result = ProviderChannelTestResult(
            ok=True,
            channel_id=channel.id,
            canonical_model=test_in.canonical_model,
            upstream_model=target.upstream_model,
            latency_ms=latency_ms,
            usage_present=usage_present,
        )
    except (
        ProviderSecurityError,
        provider_gateway.ProviderGatewayError,
        httpx.HTTPError,
    ) as exc:
        if target:
            try:
                provider_gateway.record_failure(
                    target,
                    error_code=type(exc).__name__,
                    http_status=None,
                )
            except Exception:
                pass
        # Authentication and quota failures are deterministic configuration
        # faults. Keep the key for diagnosis but remove the channel from routing.
        message = str(exc).casefold()
        if "http 401" in message or "http 403" in message:
            channel.status = ProviderChannelStatus.DISABLED
            channel.enabled = False
            channel.updated_at = datetime.now(UTC)
            session.add(channel)
        result = ProviderChannelTestResult(
            ok=False,
            channel_id=channel.id,
            canonical_model=test_in.canonical_model,
            error=str(exc)[:300],
        )
    _audit(
        session,
        actor_id=current_user.id,
        action="channel.test",
        channel_id=channel.id,
        details={"canonical_model": test_in.canonical_model, "ok": result.ok},
    )
    session.commit()
    return result


@router.post("/{channel_id}/health/reset", response_model=ProviderChannelPublic)
def reset_channel_health(
    session: SessionDep,
    current_user: PlatformAdmin,
    channel_id: uuid.UUID,
) -> Any:
    channel = _channel_or_404(session, channel_id)
    session.exec(
        delete(ProviderHealthState).where(ProviderHealthState.channel_id == channel.id)
    )
    _audit(
        session,
        actor_id=current_user.id,
        action="channel.health_reset",
        channel_id=channel.id,
    )
    session.commit()
    return _channel_public(session, channel)


@router.get(
    "/{channel_id}/reconciliations",
    response_model=list[ReconciliationBatchPublic],
)
def list_reconciliations(
    session: SessionDep,
    _current_user: PlatformAdmin,
    channel_id: uuid.UUID,
) -> Any:
    _channel_or_404(session, channel_id)
    return [
        _reconciliation_public(batch)
        for batch in session.exec(
            select(ProviderReconciliationBatch)
            .where(ProviderReconciliationBatch.channel_id == channel_id)
            .order_by(col(ProviderReconciliationBatch.created_at).desc())
            .limit(100)
        ).all()
    ]


@router.post(
    "/{channel_id}/reconciliations",
    response_model=ReconciliationBatchPublic,
)
def import_reconciliation(
    session: SessionDep,
    current_user: PlatformAdmin,
    channel_id: uuid.UUID,
    batch_in: ReconciliationImport,
) -> Any:
    _channel_or_404(session, channel_id)
    if batch_in.period_end <= batch_in.period_start:
        raise HTTPException(status_code=422, detail="对账结束时间必须晚于开始时间")
    batch = ProviderReconciliationBatch(
        channel_id=channel_id,
        source=batch_in.source,
        period_start=batch_in.period_start,
        period_end=batch_in.period_end,
        imported_by_id=current_user.id,
        row_count=len(batch_in.rows),
    )
    session.add(batch)
    session.flush()
    matched = mismatch = 0
    for row in batch_in.rows:
        event = session.exec(
            select(ModelUsageEvent).where(
                ModelUsageEvent.channel_id == channel_id,
                ModelUsageEvent.upstream_request_id == row.upstream_request_id,
            )
        ).first()
        status = UsageReconciliationStatus.MISSING_LOCAL
        if event:
            token_match = (
                event.input_tokens == row.input_tokens
                and event.output_tokens == row.output_tokens
            )
            cost_match = event.internal_cost_micrormb == round(row.cost_rmb * 1_000_000)
            status = (
                UsageReconciliationStatus.MATCHED
                if token_match and cost_match
                else UsageReconciliationStatus.MISMATCH
            )
            event.reconciliation_status = status
            event.upstream_cost_micrormb = round(row.cost_rmb * 1_000_000)
            event.upstream_billed_at = batch_in.period_end
            session.add(event)
        if status == UsageReconciliationStatus.MATCHED:
            matched += 1
        else:
            mismatch += 1
        session.add(
            ProviderReconciliationItem(
                batch_id=batch.id,
                usage_event_id=event.id if event else None,
                upstream_request_id=row.upstream_request_id,
                upstream_input_tokens=row.input_tokens,
                upstream_output_tokens=row.output_tokens,
                upstream_cost_micrormb=round(row.cost_rmb * 1_000_000),
                status=status,
                details={
                    "local_input_tokens": event.input_tokens if event else None,
                    "local_output_tokens": event.output_tokens if event else None,
                    "local_cost_micrormb": (
                        event.internal_cost_micrormb if event else None
                    ),
                },
            )
        )
    batch.matched_count = matched
    batch.mismatch_count = mismatch
    session.add(batch)
    _audit(
        session,
        actor_id=current_user.id,
        action="reconciliation.import",
        channel_id=channel_id,
        details={"rows": len(batch_in.rows), "matched": matched, "mismatch": mismatch},
    )
    session.commit()
    session.refresh(batch)
    return _reconciliation_public(batch)


@router.post(
    "/{channel_id}/reconciliations/sync-new-api",
    response_model=NewApiBillingSyncPublic,
)
def sync_new_api_reconciliation(
    session: SessionDep,
    current_user: PlatformAdmin,
    channel_id: uuid.UUID,
) -> Any:
    channel = _channel_or_404(session, channel_id)
    credential = _credential(session, channel.id)
    if (
        not credential
        or not credential.billing_ciphertext
        or not credential.billing_nonce
        or not credential.billing_user_id
    ):
        raise HTTPException(
            status_code=422,
            detail="请先配置 New API 系统访问令牌和 New-Api-User ID",
        )
    try:
        billing_access_token = decrypt_credential(
            credential.billing_ciphertext,
            credential.billing_nonce,
            channel_id=channel.id,
        )
        report = new_api_billing.fetch_new_api_billing(
            base_url=channel.base_url,
            billing_access_token=billing_access_token,
            billing_user_id=credential.billing_user_id,
            timeout_seconds=channel.timeout_seconds,
        )
    except ProviderSecurityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except new_api_billing.NewApiBillingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    now = datetime.now(UTC)
    period_start = report.logs[0].created_at if report.logs else now
    period_end = report.logs[-1].created_at if report.logs else now
    account = report.account
    batch = ProviderReconciliationBatch(
        channel_id=channel.id,
        source="new_api",
        period_start=period_start,
        period_end=period_end,
        imported_by_id=current_user.id,
        fetched_count=len(report.logs),
        upstream_system_name=account.system_name,
        upstream_version=account.version,
        upstream_total_granted_quota=account.total_granted_quota,
        upstream_total_used_quota=account.total_used_quota,
        upstream_total_available_quota=account.total_available_quota,
        upstream_total_used_micrormb=account.quota_to_micrormb(
            account.total_used_quota
        ),
        quota_per_unit=account.quota_per_unit,
        usd_exchange_rate=float(account.usd_exchange_rate),
        unlimited_quota=account.unlimited_quota,
    )
    session.add(batch)
    session.flush()

    existing_rows = session.exec(
        select(
            ProviderReconciliationItem.upstream_request_id,
            ProviderReconciliationItem.usage_event_id,
        )
        .join(
            ProviderReconciliationBatch,
            ProviderReconciliationBatch.id == ProviderReconciliationItem.batch_id,
        )
        .where(ProviderReconciliationBatch.channel_id == channel.id)
    ).all()
    existing_request_ids = {
        request_id for request_id, _event_id in existing_rows if request_id
    }
    previously_matched_event_ids = {
        event_id for _request_id, event_id in existing_rows if event_id
    }
    local_events = list(
        session.exec(
            select(ModelUsageEvent).where(
                ModelUsageEvent.channel_id == channel.id,
                ModelUsageEvent.created_at >= period_start - timedelta(minutes=3),
                ModelUsageEvent.created_at <= period_end + timedelta(minutes=3),
            )
        ).all()
    )
    by_request_id = {
        event.upstream_request_id: event
        for event in local_events
        if event.upstream_request_id
    }
    by_signature: dict[tuple[str, int, int], list[ModelUsageEvent]] = {}
    for event in local_events:
        key = (event.actual_model or "", event.input_tokens, event.output_tokens)
        by_signature.setdefault(key, []).append(event)

    used_event_ids = set(previously_matched_event_ids)
    matched = mismatch = ignored = 0
    fetched_request_ids = {item.request_id for item in report.logs}
    for upstream in report.logs:
        if upstream.request_id in existing_request_ids:
            ignored += 1
            continue
        event = by_request_id.get(upstream.request_id)
        match_method = "request_id"
        if event is None:
            candidates = [
                candidate
                for candidate in by_signature.get(
                    (
                        upstream.model_name,
                        upstream.input_tokens,
                        upstream.output_tokens,
                    ),
                    [],
                )
                if candidate.id not in used_event_ids
                and abs((candidate.created_at - upstream.created_at).total_seconds())
                <= 120
            ]
            if len(candidates) == 1:
                event = candidates[0]
                match_method = "unique_signature"
        if event is None or event.id in used_event_ids:
            ignored += 1
            continue

        token_match = (
            event.input_tokens == upstream.input_tokens
            and event.output_tokens == upstream.output_tokens
        )
        cost_match = event.internal_cost_micrormb == upstream.cost_micrormb
        status = (
            UsageReconciliationStatus.MATCHED
            if token_match and cost_match
            else UsageReconciliationStatus.MISMATCH
        )
        event.upstream_request_id = upstream.request_id
        event.upstream_cost_micrormb = upstream.cost_micrormb
        event.upstream_billed_at = upstream.created_at
        event.reconciliation_status = status
        session.add(event)
        used_event_ids.add(event.id)
        matched += int(status == UsageReconciliationStatus.MATCHED)
        mismatch += int(status != UsageReconciliationStatus.MATCHED)
        session.add(
            ProviderReconciliationItem(
                batch_id=batch.id,
                usage_event_id=event.id,
                upstream_request_id=upstream.request_id,
                upstream_input_tokens=upstream.input_tokens,
                upstream_output_tokens=upstream.output_tokens,
                upstream_cost_micrormb=upstream.cost_micrormb,
                status=status,
                details={
                    "match_method": match_method,
                    "token_match": token_match,
                    "cost_match": cost_match,
                    "upstream_model": upstream.model_name,
                    "upstream_quota": upstream.quota,
                    "upstream_created_at": upstream.created_at.isoformat(),
                    "upstream_use_time_seconds": upstream.use_time_seconds,
                    "local_input_tokens": event.input_tokens,
                    "local_output_tokens": event.output_tokens,
                    "local_cost_micrormb": event.internal_cost_micrormb,
                },
            )
        )

    for event in local_events:
        if (
            event.id in used_event_ids
            or event.status != ModelUsageStatus.SUCCEEDED
            or event.created_at < period_start
            or event.created_at > period_end
            or (
                event.upstream_request_id
                and event.upstream_request_id in fetched_request_ids
            )
        ):
            continue
        event.reconciliation_status = UsageReconciliationStatus.MISSING_UPSTREAM
        session.add(event)
        mismatch += 1
        session.add(
            ProviderReconciliationItem(
                batch_id=batch.id,
                usage_event_id=event.id,
                upstream_request_id=event.upstream_request_id,
                upstream_input_tokens=0,
                upstream_output_tokens=0,
                upstream_cost_micrormb=0,
                status=UsageReconciliationStatus.MISSING_UPSTREAM,
                details={
                    "reason": "本地成功调用未出现在上游最近账单中",
                    "local_model": event.actual_model,
                    "local_input_tokens": event.input_tokens,
                    "local_output_tokens": event.output_tokens,
                    "local_cost_micrormb": event.internal_cost_micrormb,
                },
            )
        )

    batch.row_count = matched + mismatch
    batch.ignored_count = ignored
    batch.matched_count = matched
    batch.mismatch_count = mismatch
    session.add(batch)
    _audit(
        session,
        actor_id=current_user.id,
        action="reconciliation.new_api_sync",
        channel_id=channel.id,
        details={
            "fetched": len(report.logs),
            "reconciled": batch.row_count,
            "matched": matched,
            "mismatch": mismatch,
            "ignored": ignored,
        },
    )
    session.commit()
    session.refresh(batch)
    message = (
        f"读取 {len(report.logs)} 条上游记录，对账 {batch.row_count} 条，"
        f"忽略 {ignored} 条非本系统或已同步记录"
    )
    return NewApiBillingSyncPublic(batch=_reconciliation_public(batch), message=message)
