import base64
import socket
import uuid

import pytest

from app.core.config import settings
from app.services import provider_security


def _master_key() -> str:
    return base64.urlsafe_b64encode(b"k" * 32).decode("ascii")


def _dns(address: str):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 6, "", (address, 443))]


def test_credential_round_trip_and_channel_aad(monkeypatch) -> None:
    monkeypatch.setattr(settings, "PROVIDER_CREDENTIAL_MASTER_KEY", _master_key())
    channel_id = uuid.uuid4()
    encrypted = provider_security.encrypt_credential(
        "sk-secret-value", channel_id=channel_id
    )

    assert encrypted.ciphertext != "sk-secret-value"
    assert encrypted.last_four == "alue"
    assert (
        provider_security.decrypt_credential(
            encrypted.ciphertext, encrypted.nonce, channel_id=channel_id
        )
        == "sk-secret-value"
    )
    with pytest.raises(provider_security.ProviderSecurityError):
        provider_security.decrypt_credential(
            encrypted.ciphertext, encrypted.nonce, channel_id=uuid.uuid4()
        )


def test_missing_or_invalid_master_key_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "PROVIDER_CREDENTIAL_MASTER_KEY", "")
    with pytest.raises(provider_security.ProviderSecurityError):
        provider_security.encrypt_credential("secret", channel_id=uuid.uuid4())
    monkeypatch.setattr(
        settings,
        "PROVIDER_CREDENTIAL_MASTER_KEY",
        base64.urlsafe_b64encode(b"short").decode("ascii"),
    )
    with pytest.raises(provider_security.ProviderSecurityError):
        provider_security.encrypt_credential("secret", channel_id=uuid.uuid4())


def test_local_environment_has_stable_credential_key_fallback(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "local")
    monkeypatch.setattr(settings, "PROVIDER_CREDENTIAL_MASTER_KEY", "")
    channel_id = uuid.uuid4()
    encrypted = provider_security.encrypt_credential("local-secret", channel_id=channel_id)
    assert (
        provider_security.decrypt_credential(
            encrypted.ciphertext,
            encrypted.nonce,
            channel_id=channel_id,
        )
        == "local-secret"
    )


def test_provider_url_blocks_private_and_requires_public_https(monkeypatch) -> None:
    monkeypatch.setattr(
        provider_security.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _dns("93.184.216.34"),
    )
    assert (
        provider_security.validate_provider_base_url("https://relay.example/v1/")
        == "https://relay.example/v1"
    )
    with pytest.raises(provider_security.ProviderSecurityError):
        provider_security.validate_provider_base_url("http://relay.example/v1")

    monkeypatch.setattr(
        provider_security.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _dns("127.0.0.1"),
    )
    monkeypatch.setattr(settings, "PROVIDER_PRIVATE_ENDPOINT_ALLOWLIST", "")
    with pytest.raises(provider_security.ProviderSecurityError):
        provider_security.validate_provider_base_url("https://localhost:8443/v1")


def test_allowlisted_private_http_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        provider_security.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _dns("10.0.0.8"),
    )
    monkeypatch.setattr(
        settings, "PROVIDER_PRIVATE_ENDPOINT_ALLOWLIST", "relay.internal"
    )
    assert (
        provider_security.validate_provider_base_url("http://relay.internal:8080/v1")
        == "http://relay.internal:8080/v1"
    )
