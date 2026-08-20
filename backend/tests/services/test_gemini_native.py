"""Gemini 原生协议转换层的纯函数测试（不需要数据库）。"""

import pytest

from app.services.provider_gateway import (
    ProviderGatewayError,
    gemini_auth_headers,
    gemini_native_contents,
    gemini_native_endpoint,
    gemini_native_text,
    gemini_native_to_openai,
)


def test_endpoint_strips_v1_and_builds_generate_content() -> None:
    assert (
        gemini_native_endpoint("https://relay.example/v1", "gemini-3.7-flash")
        == "https://relay.example/v1beta/models/gemini-3.7-flash:generateContent"
    )
    assert (
        gemini_native_endpoint("https://relay.example", "m", stream=True)
        == "https://relay.example/v1beta/models/m:streamGenerateContent?alt=sse"
    )


def test_auth_headers_cover_relay_and_google() -> None:
    headers = gemini_auth_headers("k")
    assert headers["Authorization"] == "Bearer k"
    assert headers["x-goog-api-key"] == "k"


def test_contents_convert_text_and_image() -> None:
    contents = gemini_native_contents(
        [
            {"role": "system", "content": "规则"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "看图"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,QUJD"},
                    },
                ],
            },
            {"role": "assistant", "content": "好的"},
        ]
    )
    assert contents[0] == {"role": "user", "parts": [{"text": "规则"}]}
    assert contents[1]["role"] == "user"
    assert contents[1]["parts"][1] == {
        "inline_data": {"mime_type": "image/png", "data": "QUJD"}
    }
    assert contents[2] == {"role": "model", "parts": [{"text": "好的"}]}


def test_native_text_skips_thought_parts() -> None:
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"thoughtSignature": "xxx"},
                        {"text": "思考过程", "thought": True},
                        {"text": "答案是 "},
                        {"text": "2"},
                    ]
                }
            }
        ]
    }
    assert gemini_native_text(payload) == "答案是 2"


def test_native_text_raises_when_empty() -> None:
    with pytest.raises(ProviderGatewayError):
        gemini_native_text({"candidates": []})


def test_to_openai_normalizes_content_and_usage() -> None:
    payload = {
        "candidates": [
            {
                "content": {"parts": [{"text": "好"}], "role": "model"},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 10,
            "candidatesTokenCount": 5,
            "totalTokenCount": 15,
        },
    }
    normalized = gemini_native_to_openai(payload, "gemini-3.7-flash")
    assert normalized["choices"][0]["message"]["content"] == "好"
    assert normalized["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }
