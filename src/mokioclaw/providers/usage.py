from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

_usage_records: ContextVar[list[dict[str, int]] | None] = ContextVar("mokioclaw_usage_records", default=None)


def start_usage_collection() -> list[dict[str, int]]:
    records: list[dict[str, int]] = []
    _usage_records.set(records)
    return records


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
    """Append per-call token usage to the active collection scope (no-op outside one)."""

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        records = current_usage_records()
        if records is None:
            return
        llm_output = getattr(response, "llm_output", None)
        token_usage = llm_output.get("token_usage") if isinstance(llm_output, dict) else None
        if not token_usage:
            return
        records.append(
            {
                "input_tokens": int(token_usage.get("prompt_tokens", 0) or 0),
                "output_tokens": int(token_usage.get("completion_tokens", 0) or 0),
            }
        )


_handler = UsageCallbackHandler()


def current_usage_handler() -> UsageCallbackHandler:
    return _handler
