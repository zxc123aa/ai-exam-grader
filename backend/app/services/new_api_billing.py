from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import httpx

from app.core.config import settings
from app.services.provider_security import validate_provider_base_url

MAX_BILLING_RESPONSE_BYTES = 8 * 1024 * 1024


class NewApiBillingError(RuntimeError):
    pass


@dataclass(frozen=True)
class NewApiAccountSnapshot:
    system_name: str
    version: str
    quota_per_unit: int
    usd_exchange_rate: Decimal
    total_granted_quota: int
    total_used_quota: int
    total_available_quota: int
    unlimited_quota: bool

    def quota_to_micrormb(self, quota: int) -> int:
        value = (
            Decimal(quota)
            / Decimal(self.quota_per_unit)
            * self.usd_exchange_rate
            * Decimal(1_000_000)
        )
        return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class NewApiUsageLog:
    request_id: str
    model_name: str
    input_tokens: int
    output_tokens: int
    quota: int
    cost_micrormb: int
    created_at: datetime
    use_time_seconds: int


@dataclass(frozen=True)
class NewApiBillingReport:
    account: NewApiAccountSnapshot
    logs: list[NewApiUsageLog]


def _site_base(base_url: str) -> str:
    base = validate_provider_base_url(base_url).rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


def _read_json_response(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    content_length = response.headers.get("content-length")
    if content_length and int(content_length) > MAX_BILLING_RESPONSE_BYTES:
        raise NewApiBillingError("上游账单响应过大")
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > MAX_BILLING_RESPONSE_BYTES:
            raise NewApiBillingError("上游账单响应过大")
        chunks.append(chunk)
    try:
        payload = json.loads(b"".join(chunks))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NewApiBillingError("上游账单返回格式无效") from exc
    if not isinstance(payload, dict):
        raise NewApiBillingError("上游账单返回格式无效")
    return payload


def _get_json(
    client: httpx.Client,
    url: str,
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    with client.stream("GET", url, headers=headers) as response:
        return _read_json_response(response)


def _integer(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _log_page(payload: dict[str, Any]) -> tuple[list[Any], int | None]:
    data = payload.get("data")
    if isinstance(data, list):
        return data, len(data)
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            total = _integer(data.get("total"), default=-1)
            return items, total if total >= 0 else None
    raise NewApiBillingError("上游调用日志格式不兼容")


def _system_billing_payloads(
    client: httpx.Client,
    base: str,
    *,
    access_token: str,
    user_id: int,
) -> tuple[dict[str, Any], list[Any]]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "New-Api-User": str(user_id),
        "Accept": "application/json",
    }
    account_payload = _get_json(client, f"{base}/api/user/self", headers=headers)
    logs: list[Any] = []
    for page in range(1, 11):
        payload = _get_json(
            client,
            f"{base}/api/log/self?type=2&p={page}&page_size=100",
            headers=headers,
        )
        items, total = _log_page(payload)
        logs.extend(items)
        if not items or total is None or len(logs) >= total:
            break
    return account_payload, logs[:1000]


def fetch_new_api_billing(
    *,
    base_url: str,
    api_key: str | None = None,
    billing_access_token: str | None = None,
    billing_user_id: int | None = None,
    timeout_seconds: int,
) -> NewApiBillingReport:
    base = _site_base(base_url)
    if not billing_access_token and not api_key:
        raise NewApiBillingError("未配置 New API 账单凭据")
    if billing_access_token and not billing_user_id:
        raise NewApiBillingError("未配置 New-Api-User ID")
    try:
        with httpx.Client(
            follow_redirects=False,
            trust_env=settings.ENVIRONMENT == "local",
            verify=True,
            timeout=min(timeout_seconds, 60),
        ) as client:
            status_payload = _get_json(client, f"{base}/api/status")
            if billing_access_token:
                account_payload, raw_logs = _system_billing_payloads(
                    client,
                    base,
                    access_token=billing_access_token,
                    user_id=billing_user_id or 0,
                )
                account_data = account_payload.get("data")
            else:
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                }
                account_payload = _get_json(
                    client, f"{base}/api/usage/token/", headers=headers
                )
                account_data = account_payload.get("data")
                log_payload = _get_json(
                    client, f"{base}/api/log/token", headers=headers
                )
                raw_logs, _total = _log_page(log_payload)
    except NewApiBillingError:
        raise
    except httpx.HTTPStatusError as exc:
        raise NewApiBillingError(
            f"上游账单接口返回 HTTP {exc.response.status_code}"
        ) from exc
    except httpx.HTTPError as exc:
        raise NewApiBillingError("无法连接上游账单接口") from exc

    status = status_payload.get("data")
    if not isinstance(status, dict) or not isinstance(account_data, dict):
        raise NewApiBillingError("上游不是兼容的 New API 服务")
    quota_per_unit = _integer(status.get("quota_per_unit"))
    if quota_per_unit <= 0:
        raise NewApiBillingError("上游未返回有效的额度换算单位")
    try:
        exchange_rate = Decimal(str(status.get("usd_exchange_rate") or 0))
    except Exception as exc:
        raise NewApiBillingError("上游未返回有效的汇率") from exc
    if exchange_rate <= 0:
        raise NewApiBillingError("上游未返回有效的汇率")

    remaining_quota = _integer(
        account_data.get("total_available", account_data.get("quota"))
    )
    used_quota = _integer(
        account_data.get("total_used", account_data.get("used_quota"))
    )
    account = NewApiAccountSnapshot(
        system_name=str(status.get("system_name") or "New API")[:100],
        version=str(status.get("version") or "")[:100],
        quota_per_unit=quota_per_unit,
        usd_exchange_rate=exchange_rate,
        total_granted_quota=_integer(
            account_data.get("total_granted"), default=remaining_quota + used_quota
        ),
        total_used_quota=used_quota,
        total_available_quota=remaining_quota,
        unlimited_quota=bool(account_data.get("unlimited_quota")),
    )
    logs: list[NewApiUsageLog] = []
    for item in raw_logs:
        if not isinstance(item, dict):
            continue
        log_type = _integer(item.get("type"), default=2)
        request_id = str(item.get("request_id") or "").strip()
        created_at = _integer(item.get("created_at"))
        quota = _integer(item.get("quota"))
        if log_type != 2 or not request_id or created_at <= 0 or quota < 0:
            continue
        logs.append(
            NewApiUsageLog(
                request_id=request_id[:255],
                model_name=str(item.get("model_name") or "").strip()[:200],
                input_tokens=max(0, _integer(item.get("prompt_tokens"))),
                output_tokens=max(0, _integer(item.get("completion_tokens"))),
                quota=quota,
                cost_micrormb=account.quota_to_micrormb(quota),
                created_at=datetime.fromtimestamp(created_at, UTC),
                use_time_seconds=max(0, _integer(item.get("use_time"))),
            )
        )
    logs.sort(key=lambda item: item.created_at)
    return NewApiBillingReport(account=account, logs=logs)
