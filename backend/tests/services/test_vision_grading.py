import uuid
from contextlib import nullcontext

import pytest

from app.core.config import settings
from app.models import ProviderProtocol, StandardAnswer
from app.services import vision_grading
from app.services.billing import ModelCallContext
from app.services.provider_gateway import RuntimeTarget


class _ModelResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "choices": [{"message": {"content": '{"answer":"ok"}'}}],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 4,
                "total_tokens": 16,
            },
        }


class _ErrorResponse:
    status_code = 403
    text = "usage limit"

    def json(self) -> dict:
        return {
            "error": {
                "type": "permission_error",
                "message": (
                    "You've reached your usage limit for this billing cycle. "
                    "To continue now, purchase extra usage."
                ),
            }
        }


class _DynamicResponse(_ModelResponse):
    headers = {"X-Oneapi-Request-Id": "request-123"}


def test_json_model_metadata_preserves_gateway_token_usage(monkeypatch) -> None:
    monkeypatch.setattr(
        vision_grading,
        "provider_config",
        lambda _provider: ("https://gateway.test", "key"),
    )
    monkeypatch.setattr(
        vision_grading.httpx, "post", lambda *_args, **_kwargs: _ModelResponse()
    )

    parsed, used_model, elapsed_ms, usage = (
        vision_grading.call_json_model_with_metadata(
            provider="test-provider",
            model="test-model",
            messages=[{"role": "user", "content": "test"}],
        )
    )

    assert parsed == {"answer": "ok"}
    assert used_model == "test-model"
    assert elapsed_ms >= 0
    assert usage == {
        "prompt_tokens": 12,
        "completion_tokens": 4,
        "total_tokens": 16,
    }


def test_json_model_compatibility_wrapper_still_returns_three_values(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        vision_grading,
        "provider_config",
        lambda _provider: ("https://gateway.test", "key"),
    )
    monkeypatch.setattr(
        vision_grading.httpx, "post", lambda *_args, **_kwargs: _ModelResponse()
    )

    parsed, used_model, elapsed_ms = vision_grading.call_json_model(
        provider="test-provider",
        model="test-model",
        messages=[{"role": "user", "content": "test"}],
    )

    assert parsed == {"answer": "ok"}
    assert used_model == "test-model"
    assert elapsed_ms >= 0


def test_subjective_grading_sends_original_question_images_to_reasoning_model(
    monkeypatch,
) -> None:
    captured: dict = {}

    def fake_call(**kwargs):
        captured.update(kwargs)
        return (
            {
                "score": 5,
                "confidence": 0.95,
                "comment": "作答正确",
                "evidence": [],
            },
            "relay",
            "gpt-5.6-sol",
            10,
            {},
        )

    monkeypatch.setattr(vision_grading, "_call_model_with_route", fake_call)
    answer = StandardAnswer(
        exam_id=uuid.uuid4(),
        question_text="根据图像完成计算",
        answer_text="42",
        max_score=5,
    )

    result = vision_grading.grade_answer_text(
        student_answer="转录答案 42",
        standard_answer=answer,
        provider="pomoai",
        model="gpt-5.6-sol",
        fallback_models=["gpt-5.6-terra"],
        image_bytes_list=[b"question-image", b"continued-image"],
    )

    content = captured["messages"][0]["content"]
    assert result.score == 5
    assert isinstance(content, list)
    assert "原图是最终判分证据" in content[0]["text"]
    assert [item["type"] for item in content].count("image_url") == 2
    assert content[2]["image_url"]["url"].startswith("data:image/png;base64,")


def test_usage_limit_falls_back_to_model_on_another_provider(monkeypatch) -> None:
    vision_grading.reset_provider_cooldowns()
    monkeypatch.setattr(settings, "DYNAMIC_PROVIDER_ROUTING_ENABLED", False)
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        vision_grading,
        "provider_config",
        lambda provider: (f"https://{provider}.test", "key"),
    )

    def fake_post(url: str, *_args, **kwargs):
        calls.append((url, kwargs["json"]["model"]))
        return _ErrorResponse() if "kimi.test" in url else _ModelResponse()

    monkeypatch.setattr(vision_grading.httpx, "post", fake_post)

    parsed, used_provider, used_model, _elapsed_ms, _usage = (
        vision_grading.call_json_model_with_route(
            provider="kimi",
            model="kimi-k3",
            fallback_models=["gpt-5.5"],
            messages=[{"role": "user", "content": "test"}],
        )
    )

    assert parsed == {"answer": "ok"}
    assert used_provider == "pomoai"
    assert used_model == "gpt-5.5"
    assert calls == [
        ("https://kimi.test/v1/chat/completions", "kimi-k3"),
        ("https://pomoai.test/v1/chat/completions", "gpt-5.5"),
    ]


def test_usage_limit_circuit_skips_provider_on_following_calls(monkeypatch) -> None:
    vision_grading.reset_provider_cooldowns()
    monkeypatch.setattr(settings, "DYNAMIC_PROVIDER_ROUTING_ENABLED", False)
    calls: list[str] = []
    monkeypatch.setattr(
        vision_grading,
        "provider_config",
        lambda provider: (f"https://{provider}.test", "key"),
    )

    def fake_post(url: str, *_args, **_kwargs):
        calls.append(url)
        return _ErrorResponse() if "kimi.test" in url else _ModelResponse()

    monkeypatch.setattr(vision_grading.httpx, "post", fake_post)
    kwargs = {
        "provider": "kimi",
        "model": "kimi-k3",
        "fallback_models": ["pomoai/gpt-5.5"],
        "messages": [{"role": "user", "content": "test"}],
    }

    vision_grading.call_json_model_with_route(**kwargs)
    vision_grading.call_json_model_with_route(**kwargs)

    assert calls.count("https://kimi.test/v1/chat/completions") == 1
    assert calls.count("https://pomoai.test/v1/chat/completions") == 2


def test_missing_usage_route_only_blocks_when_enforcement_is_enabled(
    monkeypatch,
) -> None:
    calls: list[str] = []
    context = ModelCallContext(
        org_id=uuid.uuid4(),
        workflow_purpose="grading",
        resource_id="item",
        billing_key="business-revision",
    )
    monkeypatch.setattr(
        vision_grading,
        "provider_config",
        lambda _provider: ("https://gateway.test", "key"),
    )
    monkeypatch.setattr(
        vision_grading.billing,
        "route_accepts_billing",
        lambda _provider, _model: False,
    )
    monkeypatch.setattr(
        vision_grading.billing, "record_model_attempt", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        vision_grading,
        "distributed_model_slot",
        lambda **_kwargs: nullcontext(),
    )

    def fake_post(url: str, *_args, **_kwargs):
        calls.append(url)
        return _ModelResponse()

    monkeypatch.setattr(vision_grading.httpx, "post", fake_post)
    monkeypatch.setattr(settings, "BILLING_ENFORCEMENT_ENABLED", False)

    parsed, *_metadata = vision_grading.call_json_model_with_route(
        provider="test-provider",
        model="test-model",
        fallback_models=[],
        messages=[{"role": "user", "content": "test"}],
        billing_context=context,
    )

    assert parsed == {"answer": "ok"}
    assert calls == ["https://gateway.test/v1/chat/completions"]

    monkeypatch.setattr(settings, "BILLING_ENFORCEMENT_ENABLED", True)
    monkeypatch.setattr(
        vision_grading.billing,
        "authorize_next_model_call",
        lambda _context: None,
    )
    with pytest.raises(vision_grading.VisionGradingError):
        vision_grading.call_json_model_with_route(
            provider="test-provider",
            model="test-model",
            fallback_models=[],
            messages=[{"role": "user", "content": "test"}],
            billing_context=context,
        )
    assert calls == ["https://gateway.test/v1/chat/completions"]


def test_dynamic_channel_records_route_metadata_and_channel_limit(monkeypatch) -> None:
    channel_id = uuid.uuid4()
    policy_id = uuid.uuid4()
    target = RuntimeTarget(
        provider="relay-main",
        canonical_model="grader-main",
        upstream_model="gpt-upstream",
        base_url="https://relay.example/v1",
        api_key="secret",
        protocol=ProviderProtocol.OPENAI_CHAT,
        channel_id=channel_id,
        route_policy_id=policy_id,
        route_version_id=None,
        max_concurrency=11,
        timeout_seconds=30,
    )
    context = ModelCallContext(
        org_id=uuid.uuid4(),
        workflow_purpose="subjective_grading",
        resource_id="item",
        billing_key="revision-1",
    )
    slot_args: dict = {}
    recorded: dict = {}
    monkeypatch.setattr(settings, "DYNAMIC_PROVIDER_ROUTING_ENABLED", True)
    monkeypatch.setattr(
        vision_grading.provider_gateway,
        "resolve_targets",
        lambda **_kwargs: [target],
    )
    monkeypatch.setattr(
        vision_grading,
        "provider_config",
        lambda _provider: (_ for _ in ()).throw(
            vision_grading.VisionGradingError("legacy unavailable")
        ),
    )
    monkeypatch.setattr(
        vision_grading,
        "_post_dynamic_model",
        lambda *_args, **_kwargs: _DynamicResponse(),
    )
    monkeypatch.setattr(
        vision_grading,
        "distributed_model_slot",
        lambda **kwargs: slot_args.update(kwargs) or nullcontext(),
    )
    monkeypatch.setattr(
        vision_grading.provider_gateway,
        "record_success",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        vision_grading.billing,
        "record_model_attempt",
        lambda *_args, **kwargs: recorded.update(kwargs),
    )

    parsed, used_provider, used_model, _elapsed, _usage = (
        vision_grading.call_json_model_with_route(
            provider="configured-default",
            model="grader-main",
            messages=[{"role": "user", "content": "test"}],
            billing_context=context,
        )
    )

    assert parsed == {"answer": "ok"}
    assert (used_provider, used_model) == ("relay-main", "grader-main")
    assert slot_args["channel_id"] == channel_id
    assert slot_args["channel_limit"] == 11
    assert recorded["route_policy_id"] == policy_id
    assert recorded["upstream_request_id"] == "request-123"
    assert recorded["http_status"] == 200
