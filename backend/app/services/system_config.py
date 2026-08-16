"""平台级系统配置：模型与批改默认值。

DB（systemconfig 表，按 key 一行）优先，无记录时回落 env 设置。
仅 platform_superuser 可通过 /platform/system-config 读写。
"""

import uuid
from typing import Any

from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    OrganizationModelSelection,
    PlatformModelOffering,
    ProviderChannel,
    ProviderChannelStatus,
    ProviderCredential,
    ProviderModelMapping,
    ProviderStatus,
    SchoolModelScope,
    SystemConfig,
    get_datetime_utc,
)
from app.services.provider_gateway import SCHOOL_ROUTE_PROVIDER

# 与前端 grading/answers 页 providerModels 保持一致：
# provider -> 该 provider 可用的模型列表（用于校验 provider/model 组合）。
PROVIDER_MODELS: dict[str, list[str]] = {
    "pomoai": [
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "gpt-5.5",
        "grok-4.5",
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
    ],
    "fluxnode_gemini": [
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
    ],
    "fluxnode_grok": ["grok-4.5"],
    "kimi": [
        "kimi-k3",
        "kimi-k2.7-code",
        "kimi-k2.7-code-highspeed",
        "kimi-k2.6",
        "kimi-k2.5",
    ],
}

DEFAULT_REVIEW_THRESHOLD = 0.8
DEFAULT_MAX_CONCURRENCY = 32

_CONFIG_KEYS = (
    "vision_provider",
    "vision_model",
    "grading_provider",
    "grading_model",
    "region_provider",
    "region_model",
    "recognition_provider",
    "recognition_model",
    "fallback_models",
    "vision_fallback_models",
    "reasoning_fallback_models",
    "review_threshold",
    "max_concurrency",
)


def _env_defaults() -> dict[str, Any]:
    return {
        "vision_provider": settings.VISION_DEFAULT_PROVIDER,
        "vision_model": settings.VISION_DEFAULT_MODEL,
        "grading_provider": settings.GRADING_DEFAULT_PROVIDER,
        "grading_model": settings.GRADING_DEFAULT_MODEL,
        # 检测题目区域 / 识别题目内容缺键时回落视觉提取默认
        "region_provider": settings.VISION_DEFAULT_PROVIDER,
        "region_model": settings.VISION_DEFAULT_MODEL,
        "recognition_provider": settings.VISION_DEFAULT_PROVIDER,
        "recognition_model": settings.VISION_DEFAULT_MODEL,
        "vision_fallback_models": [
            item.strip()
            for item in settings.VISION_FALLBACK_MODELS.split(",")
            if item.strip()
        ],
        "reasoning_fallback_models": [
            item.strip()
            for item in settings.REASONING_FALLBACK_MODELS.split(",")
            if item.strip()
        ],
        # Legacy API field. New code uses the purpose-specific lists above.
        "fallback_models": [
            item.strip()
            for item in settings.REASONING_FALLBACK_MODELS.split(",")
            if item.strip()
        ],
        "review_threshold": DEFAULT_REVIEW_THRESHOLD,
        "max_concurrency": DEFAULT_MAX_CONCURRENCY,
    }


def _offering_runtime_target(
    session: Session, offering: PlatformModelOffering
) -> tuple[str, str] | None:
    """Resolve a provider-neutral offering to any active route-capable channel."""
    statement = (
        select(ProviderChannel, ProviderModelMapping)
        .join(
            ProviderModelMapping,
            ProviderModelMapping.channel_id == ProviderChannel.id,
        )
        .where(
            ProviderChannel.status == ProviderChannelStatus.ACTIVE,
            ProviderModelMapping.enabled.is_(True),
            ProviderModelMapping.usage_metering_verified.is_(True),
            ProviderModelMapping.supports_structured_output.is_(True),
            ProviderModelMapping.canonical_model == offering.canonical_model,
        )
    )
    if offering.scope in {SchoolModelScope.VISION, SchoolModelScope.REFERENCE_ANSWER}:
        statement = statement.where(ProviderModelMapping.supports_vision.is_(True))
    rows = list(session.exec(statement).all())
    if not rows:
        return None
    return SCHOOL_ROUTE_PROVIDER, offering.canonical_model


def get_grading_defaults(
    session: Session, org_id: uuid.UUID | None = None
) -> dict[str, Any]:
    """返回平台默认值，并按学校已发布的模型选择覆盖对应任务。"""
    defaults = _env_defaults()
    rows = session.exec(
        select(SystemConfig).where(SystemConfig.key.in_(_CONFIG_KEYS))  # type: ignore
    ).all()
    for row in rows:
        defaults[row.key] = row.value
    if any(row.key == "fallback_models" for row in rows) and not any(
        row.key == "reasoning_fallback_models" for row in rows
    ):
        defaults["reasoning_fallback_models"] = defaults["fallback_models"]
    defaults["fallback_models"] = defaults["reasoning_fallback_models"]
    if org_id is not None:
        selections = session.exec(
            select(OrganizationModelSelection, PlatformModelOffering)
            .join(
                PlatformModelOffering,
                OrganizationModelSelection.offering_id == PlatformModelOffering.id,
            )
            .where(
                OrganizationModelSelection.org_id == org_id,
                PlatformModelOffering.published.is_(True),
                PlatformModelOffering.school_selectable.is_(True),
                PlatformModelOffering.scope == OrganizationModelSelection.scope,
            )
        ).all()
        for selection, offering in selections:
            target = _offering_runtime_target(session, offering)
            if not target:
                continue
            provider, model = target
            if selection.scope == SchoolModelScope.VISION:
                for prefix in ("vision", "region", "recognition"):
                    defaults[f"{prefix}_provider"] = provider
                    defaults[f"{prefix}_model"] = model
            elif selection.scope == SchoolModelScope.GRADING:
                defaults["grading_provider"] = provider
                defaults["grading_model"] = model
    return defaults


def get_school_model_target(
    session: Session,
    *,
    org_id: uuid.UUID | None,
    scope: SchoolModelScope,
    fallback_provider: str,
    fallback_model: str,
) -> tuple[str, str]:
    """解析学校选择；未选择、已下架或用途不符时安全回落平台默认。"""
    if org_id is None:
        return fallback_provider, fallback_model
    row = session.exec(
        select(PlatformModelOffering)
        .join(
            OrganizationModelSelection,
            OrganizationModelSelection.offering_id == PlatformModelOffering.id,
        )
        .where(
            OrganizationModelSelection.org_id == org_id,
            OrganizationModelSelection.scope == scope,
            PlatformModelOffering.scope == scope,
            PlatformModelOffering.published.is_(True),
            PlatformModelOffering.school_selectable.is_(True),
        )
    ).first()
    if not row:
        return fallback_provider, fallback_model
    return _offering_runtime_target(session, row) or (
        fallback_provider,
        fallback_model,
    )


def save_grading_defaults(session: Session, updates: dict[str, Any]) -> None:
    """按 key 逐条 upsert（调用方负责 commit）。"""
    for key, value in updates.items():
        if key not in _CONFIG_KEYS:
            raise ValueError(f"不支持的配置键：{key}")
        row = session.get(SystemConfig, key)
        if row:
            row.value = value
            row.updated_at = get_datetime_utc()
        else:
            row = SystemConfig(key=key, value=value)
        session.add(row)


def validate_provider_model(
    provider: str, model: str, session: Session | None = None
) -> str | None:
    """返回错误文案；组合合法时返回 None。"""
    if session is not None:
        dynamic = session.exec(
            select(ProviderModelMapping)
            .join(
                ProviderChannel, ProviderModelMapping.channel_id == ProviderChannel.id
            )
            .where(
                ProviderChannel.code == provider,
                ProviderChannel.status == ProviderChannelStatus.ACTIVE,
                ProviderModelMapping.canonical_model == model,
                ProviderModelMapping.enabled.is_(True),
            )
        ).first()
        if dynamic:
            return None
    models = PROVIDER_MODELS.get(provider)
    if models is None:
        return f"不支持的模型提供者：{provider}"
    if model not in models:
        return f"提供者 {provider} 不支持模型 {model}"
    return None


def provider_statuses(session: Session | None = None) -> list[ProviderStatus]:
    """各 provider 的 API Key 配置状态（只报是否配置，不回传 key）。"""
    keys = {
        "pomoai": settings.PROVIDER_POMOAI_API_KEY,
        "fluxnode_gemini": settings.PROVIDER_FLUXNODE_GEMINI_API_KEY,
        "fluxnode_grok": settings.PROVIDER_FLUXNODE_GROK_API_KEY,
        "kimi": settings.PROVIDER_KIMI_API_KEY,
    }
    result = [
        ProviderStatus(name=name, configured=bool(api_key.strip()))
        for name, api_key in keys.items()
    ]
    if session is not None:
        rows = session.exec(
            select(ProviderChannel, ProviderCredential)
            .outerjoin(
                ProviderCredential,
                ProviderCredential.channel_id == ProviderChannel.id,
            )
            .order_by(ProviderChannel.code)
        ).all()
        legacy_names = {item.name for item in result}
        result.extend(
            ProviderStatus(name=channel.code, configured=credential is not None)
            for channel, credential in rows
            if channel.code not in legacy_names
        )
    return result
