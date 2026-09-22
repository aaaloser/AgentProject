from __future__ import annotations

import json

from mokioclaw.providers import openai_provider


def test_create_model_disables_sdk_retries_and_registers_usage_callback(monkeypatch) -> None:
    captured: dict = {}
    sentinel = object()

    def fake_chat_openai(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setenv("API_KEY", "FAKE_KEY_DO_NOT_PERSIST")
    monkeypatch.setenv("MODEL", "fake-model")
    monkeypatch.setenv("BASE_URL", "https://provider.invalid/v1?token=FAKE_QUERY")
    monkeypatch.setattr(openai_provider, "load_dotenv", lambda: None)
    monkeypatch.setattr(openai_provider, "ChatOpenAI", fake_chat_openai)

    model = openai_provider.create_model()

    assert model is sentinel
    assert captured["temperature"] == 0
    assert captured["max_retries"] == 0
    assert captured["callbacks"] == [openai_provider.current_usage_handler()]


def test_provider_runtime_identity_is_safe_and_records_zero_retry_policy() -> None:
    payload = openai_provider.provider_runtime_identity()
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["sdk_package"] == "langchain-openai"
    assert isinstance(payload["sdk_version"], str) and payload["sdk_version"]
    assert payload["adapter_config_version"] == 1
    assert payload["max_retries"] == 0
    assert payload["transport_attempt_observable"] is True
    for forbidden in ("api_key", "authorization", "base_url", "https://", "/v1", "query"):
        assert forbidden not in serialized.lower()
