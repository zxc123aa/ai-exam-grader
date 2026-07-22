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
