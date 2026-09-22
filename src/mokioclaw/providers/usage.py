from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from mokioclaw.evals.provider_failures import classify_failure
from mokioclaw.providers.call_journal import CallJournal

_usage_records: ContextVar[list[dict[str, int]] | None] = ContextVar("mokioclaw_usage_records", default=None)
_call_journal: ContextVar[CallJournal | None] = ContextVar("mokioclaw_call_journal", default=None)
_active_model_calls: ContextVar[dict[str, int] | None] = ContextVar("mokioclaw_active_model_calls", default=None)
_provider_host: ContextVar[str | None] = ContextVar("mokioclaw_provider_host", default=None)
_successful_model_responses: ContextVar[int] = ContextVar("mokioclaw_successful_model_responses", default=0)
_tool_activity_count: ContextVar[int] = ContextVar("mokioclaw_tool_activity_count", default=0)


def start_usage_collection(
    journal: CallJournal | None = None,
    *,
    provider_host: str | None = None,
) -> list[dict[str, int]]:
    records: list[dict[str, int]] = []
    _usage_records.set(records)
    if journal is not None:
        bind_call_journal(journal, provider_host=provider_host)
    return records


def bind_call_journal(journal: CallJournal, *, provider_host: str | None = None) -> None:
    _call_journal.set(journal)
    _active_model_calls.set({})
    _provider_host.set(provider_host)
    _successful_model_responses.set(0)
    _tool_activity_count.set(0)


def record_provider_tool_activity() -> None:
    if _call_journal.get() is not None:
        _tool_activity_count.set(_tool_activity_count.get() + 1)


def current_usage_records() -> list[dict[str, int]] | None:
    return _usage_records.get()


def sum_usage(records: list[dict[str, int]] | None) -> dict[str, int | None]:
    if not records:
        return {"input_tokens": None, "output_tokens": None}
    return {
        "input_tokens": sum(record.get("input_tokens", 0) for record in records),
        "output_tokens": sum(record.get("output_tokens", 0) for record in records),
    }


class UsageCallbackHandler(BaseCallbackHandler):
    """Persist one crash-consistent journal record per logical model call."""

    @staticmethod
    def _run_key(run_id: Any) -> str:
        return str(run_id) if run_id is not None else "__default__"

    def _begin_call(self, run_id: Any) -> None:
        journal = _call_journal.get()
        if journal is None:
            return
        active = dict(_active_model_calls.get() or {})
        key = self._run_key(run_id)
        if key in active:
            return
        model_call_index = journal.begin_model_call()
        journal.begin_transport_attempt(model_call_index)
        active[key] = model_call_index
        _active_model_calls.set(active)

    def on_llm_start(self, serialized: dict[str, Any], prompts: list[str], **kwargs: Any) -> None:
        self._begin_call(kwargs.get("run_id"))

    def on_chat_model_start(self, serialized: dict[str, Any], messages: list[list[Any]], **kwargs: Any) -> None:
        self._begin_call(kwargs.get("run_id"))

    @staticmethod
    def _token_usage(response: Any) -> dict[str, int] | None:
        llm_output = getattr(response, "llm_output", None)
        token_usage = llm_output.get("token_usage") if isinstance(llm_output, dict) else None
        if not isinstance(token_usage, dict) or not token_usage:
            return None
        try:
            input_tokens = int(token_usage.get("prompt_tokens", token_usage.get("input_tokens")))
            output_tokens = int(token_usage.get("completion_tokens", token_usage.get("output_tokens")))
            total_value = token_usage.get("total_tokens")
            total_tokens = input_tokens + output_tokens if total_value is None else int(total_value)
        except (TypeError, ValueError, OverflowError):
            return {"input_tokens": "invalid", "output_tokens": "invalid"}  # type: ignore[dict-item]
        return {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total_tokens}

    def _pop_call(self, run_id: Any) -> tuple[CallJournal | None, int | None]:
        journal = _call_journal.get()
        active = dict(_active_model_calls.get() or {})
        model_call_index = active.pop(self._run_key(run_id), None)
        _active_model_calls.set(active)
        return journal, model_call_index

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        usage = self._token_usage(response)
        records = current_usage_records()
        if records is not None and usage is not None and isinstance(usage.get("input_tokens"), int):
            records.append({"input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"]})
        journal, model_call_index = self._pop_call(kwargs.get("run_id"))
        if journal is not None and model_call_index is not None:
            journal.complete_model_call(model_call_index, usage, "provider_response_metadata")
        _successful_model_responses.set(_successful_model_responses.get() + 1)

    def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        journal, model_call_index = self._pop_call(kwargs.get("run_id"))
        if journal is None or model_call_index is None:
            return
        classification = classify_failure(
            error,
            at_provider_boundary=True,
            successful_model_responses=_successful_model_responses.get(),
            tool_activity_count=_tool_activity_count.get(),
            provider_host=_provider_host.get(),
        )
        journal.fail_model_call(model_call_index, classification)


_handler = UsageCallbackHandler()


def current_usage_handler() -> UsageCallbackHandler:
    return _handler
