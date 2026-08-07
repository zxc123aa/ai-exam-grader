from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import secrets
import socket
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings


class ProviderSecurityError(ValueError):
    pass


@dataclass(frozen=True)
class EncryptedCredential:
    ciphertext: str
    nonce: str
    fingerprint: str
    last_four: str
    key_version: int = 1


def _master_key() -> bytes:
    raw = settings.PROVIDER_CREDENTIAL_MASTER_KEY.strip()
    if not raw:
        if settings.ENVIRONMENT == "local":
            return hashlib.sha256(
                f"dianfan-provider:{settings.SECRET_KEY}".encode()
            ).digest()
        raise ProviderSecurityError("未配置中转凭据主密钥")
    try:
        key = base64.urlsafe_b64decode(raw.encode("ascii"))
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise ProviderSecurityError("中转凭据主密钥格式无效") from exc
    if len(key) != 32:
        raise ProviderSecurityError("中转凭据主密钥必须是 Base64 编码的 32 字节密钥")
    return key


def encrypt_credential(api_key: str, *, channel_id: uuid.UUID) -> EncryptedCredential:
    value = api_key.strip()
    if not value:
        raise ProviderSecurityError("中转调用密钥不能为空")
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(_master_key()).encrypt(
        nonce, value.encode("utf-8"), str(channel_id).encode("ascii")
    )
    return EncryptedCredential(
        ciphertext=base64.urlsafe_b64encode(ciphertext).decode("ascii"),
        nonce=base64.urlsafe_b64encode(nonce).decode("ascii"),
        fingerprint=hashlib.sha256(value.encode("utf-8")).hexdigest()[:16],
        last_four=value[-4:],
    )


def decrypt_credential(ciphertext: str, nonce: str, *, channel_id: uuid.UUID) -> str:
    try:
        plaintext = AESGCM(_master_key()).decrypt(
            base64.urlsafe_b64decode(nonce.encode("ascii")),
            base64.urlsafe_b64decode(ciphertext.encode("ascii")),
            str(channel_id).encode("ascii"),
        )
        return plaintext.decode("utf-8")
    except (ValueError, UnicodeError, binascii.Error, InvalidTag) as exc:
        raise ProviderSecurityError("中转凭据无法解密") from exc


def _allowlist() -> tuple[
    set[str], list[ipaddress.IPv4Network | ipaddress.IPv6Network]
]:
    hosts: set[str] = set()
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for raw in settings.PROVIDER_PRIVATE_ENDPOINT_ALLOWLIST.split(","):
        item = raw.strip().casefold()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            hosts.add(item.rstrip("."))
    return hosts, networks


def _is_allowlisted(
    hostname: str,
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    hosts, networks = _allowlist()
    return hostname.casefold().rstrip(".") in hosts or any(
        address in network for network in networks
    )


def validate_provider_base_url(base_url: str) -> str:
    parsed = urlsplit(base_url.strip())
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ProviderSecurityError("中转地址必须是有效的 HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ProviderSecurityError("中转地址不能包含账号、查询参数或片段")
    hostname = parsed.hostname.casefold().rstrip(".")
    try:
        addresses = {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(
                hostname, parsed.port or 443, type=socket.SOCK_STREAM
            )
        }
    except (OSError, ValueError) as exc:
        raise ProviderSecurityError("中转地址无法解析") from exc
    if not addresses:
        raise ProviderSecurityError("中转地址无法解析")
    for address in addresses:
        unsafe = not address.is_global
        if unsafe and not _is_allowlisted(hostname, address):
            raise ProviderSecurityError("私网中转地址未加入服务器白名单")
    if parsed.scheme != "https" and not all(
        _is_allowlisted(hostname, address) for address in addresses
    ):
        raise ProviderSecurityError("公网中转地址必须使用 HTTPS")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
