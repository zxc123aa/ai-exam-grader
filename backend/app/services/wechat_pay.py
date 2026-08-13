from __future__ import annotations

import base64
import json
import time
import uuid

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings


class WeChatPayError(RuntimeError):
    pass


def _private_key():
    try:
        return serialization.load_pem_private_key(
            settings.WECHAT_PAY_PRIVATE_KEY_PEM.encode(), password=None
        )
    except (TypeError, ValueError) as exc:
        raise WeChatPayError("微信支付商户私钥配置无效") from exc


def _authorization(method: str, path: str, body: str) -> str:
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    message = f"{method}\n{path}\n{timestamp}\n{nonce}\n{body}\n".encode()
    signature = base64.b64encode(
        _private_key().sign(message, padding.PKCS1v15(), hashes.SHA256())
    ).decode()
    token = (
        f'mchid="{settings.WECHAT_PAY_MCH_ID}",nonce_str="{nonce}",'
        f'signature="{signature}",timestamp="{timestamp}",'
        f'serial_no="{settings.WECHAT_PAY_CERT_SERIAL_NO}"'
    )
    return f"WECHATPAY2-SHA256-RSA2048 {token}"


def create_native_payment(
    *, order_no: str, description: str, amount_cents: int
) -> dict:
    required = (
        settings.WECHAT_PAY_MCH_ID,
        settings.WECHAT_PAY_APP_ID,
        settings.WECHAT_PAY_CERT_SERIAL_NO,
        settings.WECHAT_PAY_PRIVATE_KEY_PEM,
        settings.WECHAT_PAY_NOTIFY_URL,
    )
    if not all(required):
        raise WeChatPayError("微信支付尚未配置")
    path = "/v3/pay/transactions/native"
    payload = {
        "mchid": settings.WECHAT_PAY_MCH_ID,
        "appid": settings.WECHAT_PAY_APP_ID,
        "description": description[:127],
        "out_trade_no": order_no,
        "notify_url": settings.WECHAT_PAY_NOTIFY_URL,
        "amount": {"total": amount_cents, "currency": "CNY"},
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    headers = {
        "Authorization": _authorization("POST", path, body),
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "dianfan-grading/1.0",
    }
    response = httpx.post(
        f"https://api.mch.weixin.qq.com{path}",
        content=body.encode(),
        headers=headers,
        timeout=15,
    )
    if response.status_code != 200:
        raise WeChatPayError(f"微信支付下单失败：HTTP {response.status_code}")
    data = response.json()
    if not data.get("code_url"):
        raise WeChatPayError("微信支付未返回付款码")
    return data


def verify_notification(
    *, timestamp: str, nonce: str, signature: str, body: bytes
) -> None:
    try:
        certificate = x509.load_pem_x509_certificate(
            settings.WECHAT_PAY_PLATFORM_CERT_PEM.encode()
        )
        certificate.public_key().verify(
            base64.b64decode(signature),
            f"{timestamp}\n{nonce}\n{body.decode()}\n".encode(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except Exception as exc:
        raise WeChatPayError("微信支付回调验签失败") from exc


def decrypt_notification_resource(resource: dict) -> dict:
    key = settings.WECHAT_PAY_API_V3_KEY.encode()
    if len(key) != 32:
        raise WeChatPayError("微信支付 API v3 Key 配置无效")
    try:
        plaintext = AESGCM(key).decrypt(
            resource["nonce"].encode(),
            base64.b64decode(resource["ciphertext"]),
            (resource.get("associated_data") or "").encode(),
        )
        return json.loads(plaintext)
    except Exception as exc:
        raise WeChatPayError("微信支付回调解密失败") from exc
