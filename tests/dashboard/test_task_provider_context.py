"""Task provider configuration and budgets use fake models only."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import openai
import pytest

from mokioclaw.providers import openai_provider
from mokioclaw.core.agent import TaskRunContext
from mokioclaw.dashboard.task_worker import filtered_worker_environment


def test_task_settings_require_only_explicit_names_without_dotenv_or_legacy_fallback(monkeypatch) -> None:
    monkeypatch.setattr(openai_provider, "load_dotenv", lambda: pytest.fail("dotenv was read"))
    monkeypatch.setenv("API_KEY", "FAKE_LEGACY_KEY")
    monkeypatch.setenv("MODEL", "legacy-model")
    monkeypatch.setenv("BASE_URL", "https://legacy.invalid/v1")
    with pytest.raises(openai_provider.TaskProviderError, match="task_provider_unconfigured"):
        openai_provider.ProviderSettings.from_environment({})
    settings = openai_provider.ProviderSettings.from_environment({
        "MOKIO_TASK_API_KEY": "FAKE_TASK_KEY", "MOKIO_TASK_MODEL": "fake-task-model",
        "MOKIO_TASK_BASE_URL": "https://task.invalid/v1?sample=FAKE_QUERY",
    })
    assert settings.model == "fake-task-model"
    assert "FAKE_TASK_KEY" not in repr(settings)
    assert "FAKE_QUERY" not in repr(settings)


def test_task_model_receives_explicit_output_cap_and_no_legacy_env(monkeypatch) -> None:
    captured = {}
    sentinel = object()

    def fake_chat_openai(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(openai_provider, "ChatOpenAI", fake_chat_openai)
    monkeypatch.setattr(openai_provider, "load_dotenv", lambda: pytest.fail("dotenv was read"))
    settings = openai_provider.ProviderSettings("FAKE_TASK_KEY", "task-model", "https://task.invalid/v1")
    assert openai_provider.create_task_model(settings, max_output_tokens=123) is sentinel
    assert captured["api_key"] == "FAKE_TASK_KEY"
    assert captured["model"] == "task-model"
    assert captured["base_url"] == "https://task.invalid/v1"
    assert captured["max_tokens"] == 123
    assert captured["max_retries"] == 0


@pytest.mark.parametrize("missing", ["MOKIO_TASK_API_KEY", "MOKIO_TASK_MODEL", "MOKIO_TASK_BASE_URL"])
def test_every_missing_task_setting_fails_closed(missing: str) -> None:
    values = {
        "MOKIO_TASK_API_KEY": "FAKE_TASK_KEY", "MOKIO_TASK_MODEL": "fake-model",
        "MOKIO_TASK_BASE_URL": "https://task.invalid/v1",
    }
    values.pop(missing)
    with pytest.raises(openai_provider.TaskProviderError, match="task_provider_unconfigured"):
        openai_provider.ProviderSettings.from_environment(values)


def test_worker_receives_only_explicit_task_settings_and_never_inherits_legacy_values() -> None:
    settings = openai_provider.ProviderSettings("FAKE_TASK_KEY", "fake-model", "https://task.invalid/v1")
    environment = filtered_worker_environment({
        "PATH": "safe-path", "API_KEY": "FAKE_LEGACY_KEY", "MODEL": "legacy",
        "BASE_URL": "https://legacy.invalid", "MOKIO_TASK_API_KEY": "inherited-key",
        "CUSTOM_SECRET": "private",
    }, provider_settings=settings)
    assert environment["MOKIO_TASK_API_KEY"] == "FAKE_TASK_KEY"
    assert environment["MOKIO_TASK_MODEL"] == "fake-model"
    assert environment["MOKIO_TASK_BASE_URL"] == "https://task.invalid/v1"
    assert "API_KEY" not in environment and "MODEL" not in environment
    assert "BASE_URL" not in environment and "CUSTOM_SECRET" not in environment


class FakeModel:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls = 0

    def invoke(self, _messages):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def bind_tools(self, _tools):
        return self


def response(input_tokens: int | None, output_tokens: int | None):
    metadata = None if input_tokens is None else {
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }
    return SimpleNamespace(content="ok", usage_metadata=metadata)


def test_budget_counts_calls_and_reported_tokens_across_bound_models() -> None:
    fake = FakeModel([response(3, 2), response(4, 3)])
    context = TaskRunContext.for_fake_model(fake, max_provider_calls=2, max_total_tokens=12,
                                             max_output_tokens_per_call=100)
    model = context.model(stage="entry").bind_tools([])
    assert model.invoke([]).content == "ok"
    assert model.invoke([]).content == "ok"
    assert context.provider_calls == 2 and context.reported_tokens == 12
    with pytest.raises(openai_provider.TaskProviderError, match="provider_budget_exhausted"):
        model.invoke([])
    assert fake.calls == 2


def test_usage_snapshot_attributes_nested_bound_calls_and_failed_invocations() -> None:
    fake = FakeModel([response(3, 2), response(4, 3), RuntimeError("FAKE_PRIVATE_ERROR")])
    context = TaskRunContext.for_fake_model(fake, max_provider_calls=4, max_total_tokens=100,
                                             max_output_tokens_per_call=100)
    context.model(stage="planner").bind_tools([]).invoke([])
    context.model(stage="code_agent").bind_tools([]).invoke([])
    with pytest.raises(openai_provider.TaskProviderError, match="provider_failed"):
        context.model(stage="code_agent").invoke([])
    assert context.usage_snapshot() == {
        "entry_calls": 0, "entry_reported_tokens": 0,
        "chat_calls": 0, "chat_reported_tokens": 0,
        "planner_calls": 1, "planner_reported_tokens": 5,
        "code_agent_calls": 2, "code_agent_reported_tokens": 7,
        "verifier_calls": 0, "verifier_reported_tokens": 0,
        "context_compressor_calls": 0, "context_compressor_reported_tokens": 0,
    }
    assert "FAKE_PRIVATE_ERROR" not in repr(context.usage_snapshot())


def test_missing_usage_stops_before_next_provider_call() -> None:
    fake = FakeModel([response(None, None), response(1, 1)])
    context = TaskRunContext.for_fake_model(fake, max_provider_calls=3, max_total_tokens=100,
                                             max_output_tokens_per_call=100)
    context.model(stage="entry").invoke([])
    with pytest.raises(openai_provider.TaskProviderError, match="usage_unavailable"):
        context.model(stage="entry").invoke([])
    assert fake.calls == 1 and context.provider_calls == 1
    assert context.usage_snapshot()["entry_calls"] == 1
    assert context.usage_snapshot()["entry_reported_tokens"] == 0


def test_last_reported_call_may_exceed_token_budget_but_cannot_start_another() -> None:
    fake = FakeModel([response(8, 4), response(1, 1)])
    context = TaskRunContext.for_fake_model(fake, max_provider_calls=3, max_total_tokens=10,
                                             max_output_tokens_per_call=100)
    context.model(stage="entry").invoke([])
    assert context.reported_tokens == 12
    assert context.usage_snapshot()["entry_reported_tokens"] == 12
    with pytest.raises(openai_provider.TaskProviderError, match="provider_budget_exhausted"):
        context.model(stage="entry").invoke([])
    assert fake.calls == 1


def test_provider_exception_is_replaced_with_fixed_nonsecret_category() -> None:
    fake = FakeModel([RuntimeError("FAKE_TASK_KEY https://task.invalid/v1?sample=FAKE_QUERY")])
    context = TaskRunContext.for_fake_model(fake, max_provider_calls=2, max_total_tokens=100,
                                             max_output_tokens_per_call=100)
    with pytest.raises(openai_provider.TaskProviderError) as error:
        context.model(stage="entry").invoke([])
    assert str(error.value) == "provider_failed"
    assert "FAKE_TASK_KEY" not in str(error.value)
    assert "FAKE_QUERY" not in str(error.value)
    assert context.usage_snapshot()["entry_calls"] == 1
    assert context.usage_snapshot()["entry_reported_tokens"] == 0


@pytest.mark.parametrize("failure,category", [
    (openai.AuthenticationError("FAKE_TASK_KEY", response=httpx.Response(
        401, request=httpx.Request("POST", "https://task.invalid/v1?secret=FAKE_QUERY")), body=None),
     "provider_auth_failed"),
    (openai.PermissionDeniedError("FAKE_TASK_KEY", response=httpx.Response(
        403, request=httpx.Request("POST", "https://task.invalid/v1?secret=FAKE_QUERY")), body=None),
     "provider_auth_failed"),
    (openai.RateLimitError("FAKE_TASK_KEY", response=httpx.Response(
        429, request=httpx.Request("POST", "https://task.invalid/v1?secret=FAKE_QUERY")), body=None),
     "provider_rate_limited"),
    (openai.BadRequestError("FAKE_TASK_KEY", response=httpx.Response(
        400, request=httpx.Request("POST", "https://task.invalid/v1?secret=FAKE_QUERY")), body=None),
     "provider_invalid_request"),
    (openai.APIConnectionError(message="FAKE_TASK_KEY", request=httpx.Request(
        "POST", "https://task.invalid/v1?secret=FAKE_QUERY")), "provider_transport_failed"),
    (openai.APITimeoutError(request=httpx.Request(
        "POST", "https://task.invalid/v1?secret=FAKE_QUERY")), "provider_transport_failed"),
    (openai.InternalServerError("FAKE_TASK_KEY", response=httpx.Response(
        500, request=httpx.Request("POST", "https://task.invalid/v1?secret=FAKE_QUERY")), body=None),
     "provider_server_failed"),
])
def test_known_provider_failures_use_only_fixed_categories(failure, category) -> None:
    context = TaskRunContext.for_fake_model(
        FakeModel([failure]), max_provider_calls=2, max_total_tokens=100,
        max_output_tokens_per_call=100,
    )
    with pytest.raises(openai_provider.TaskProviderError) as error:
        context.model(stage="entry").invoke([])
    assert str(error.value) == category
    assert "FAKE_TASK_KEY" not in repr(error.value)
    assert "FAKE_QUERY" not in repr(error.value)
    assert error.value.__cause__ is None


def test_settings_model_factory_is_lazy_and_fails_without_exposing_constructor_exception(monkeypatch) -> None:
    calls = 0

    def broken_model(**_kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("FAKE_TASK_KEY FAKE_QUERY")

    monkeypatch.setattr(openai_provider, "ChatOpenAI", broken_model)
    settings = openai_provider.ProviderSettings("FAKE_TASK_KEY", "fake-model",
                                                "https://task.invalid/v1?token=FAKE_QUERY")
    context = TaskRunContext.from_settings(settings, max_provider_calls=2, max_total_tokens=100,
                                           max_output_tokens_per_call=15)
    assert calls == 0
    with pytest.raises(openai_provider.TaskProviderError) as error:
        context.model(stage="entry")
    assert str(error.value) == "provider_setup_failed"
    assert calls == 1
