from app.services import vision_grading


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


def test_json_model_metadata_preserves_gateway_token_usage(monkeypatch) -> None:
    monkeypatch.setattr(
        vision_grading, "provider_config", lambda _provider: ("https://gateway.test", "key")
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


def test_json_model_compatibility_wrapper_still_returns_three_values(monkeypatch) -> None:
    monkeypatch.setattr(
        vision_grading, "provider_config", lambda _provider: ("https://gateway.test", "key")
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


def test_usage_limit_falls_back_to_model_on_another_provider(monkeypatch) -> None:
    vision_grading.reset_provider_cooldowns()
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
