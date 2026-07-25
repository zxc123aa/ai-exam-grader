"""平台级系统配置：模型与批改默认值。

DB（systemconfig 表，按 key 一行）优先，无记录时回落 env 设置。
仅 platform_superuser 可通过 /platform/system-config 读写。
"""

from typing import Any

from sqlmodel import Session, select

from app.core.config import settings
from app.models import ProviderStatus, SystemConfig, get_datetime_utc

# 与前端 grading/answers 页 providerModels 保持一致：
# provider -> 该 provider 可用的模型列表（用于校验 provider/model 组合）。
PROVIDER_MODELS: dict[str, list[str]] = {
    "pomoai": [
        "gpt-5.6-sol",
                    "gpt-5.6-terra",
        "gpt-5.6-luna",
        "gpt-5.5",
        "grok-4.5",
        "gemini-3.5-flash",
    ],
    "fluxnode_gemini": ["gemini-3.5-flash"],
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
        "fallback_models": [
            item.strip()
            for item in settings.VISION_FALLBACK_MODELS.split(",")
            if item.strip()
        ],
        "review_threshold": DEFAULT_REVIEW_THRESHOLD,
        "max_concurrency": DEFAULT_MAX_CONCURRENCY,
    }


def get_grading_defaults(session: Session) -> dict[str, Any]:
    """批改 run / 分析报告的默认模型参数：DB 覆盖优先，缺失键回落 env。"""
    defaults = _env_defaults()
    rows = session.exec(
        select(SystemConfig).where(SystemConfig.key.in_(_CONFIG_KEYS))  # type: ignore
    ).all()
    for row in rows:
        defaults[row.key] = row.value
    return defaults


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


def validate_provider_model(provider: str, model: str) -> str | None:
    """返回错误文案；组合合法时返回 None。"""
    models = PROVIDER_MODELS.get(provider)
    if models is None:
        return f"不支持的模型提供者：{provider}"
    if model not in models:
        return f"提供者 {provider} 不支持模型 {model}"
    return None


def provider_statuses() -> list[ProviderStatus]:
    """各 provider 的 API Key 配置状态（只报是否配置，不回传 key）。"""
    keys = {
        "pomoai": settings.PROVIDER_POMOAI_API_KEY,
        "fluxnode_gemini": settings.PROVIDER_FLUXNODE_GEMINI_API_KEY,
        "fluxnode_grok": settings.PROVIDER_FLUXNODE_GROK_API_KEY,
        "kimi": settings.PROVIDER_KIMI_API_KEY,
    }
    return [
        ProviderStatus(name=name, configured=bool(api_key.strip()))
        for name, api_key in keys.items()
    ]
