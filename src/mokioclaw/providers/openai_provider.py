from __future__ import annotations

import os
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Mapping

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from openai import (
    APIConnectionError, APITimeoutError, AuthenticationError, BadRequestError,
    InternalServerError, PermissionDeniedError, RateLimitError,
)

from mokioclaw.providers.usage import current_usage_handler


ADAPTER_CONFIG_VERSION = 1
MAX_RETRIES = 0


class TaskProviderError(RuntimeError):
    """A fixed, public-safe failure category for task provider operations."""


def task_provider_failure_kind(error: Exception) -> str:
    """Classify SDK failures without inspecting their message, body or endpoint."""
    if isinstance(error, (AuthenticationError, PermissionDeniedError)):
        return "provider_auth_failed"
    if isinstance(error, RateLimitError):
        return "provider_rate_limited"
    if isinstance(error, BadRequestError):
        return "provider_invalid_request"
    if isinstance(error, (APIConnectionError, APITimeoutError)):
        return "provider_transport_failed"
    if isinstance(error, InternalServerError):
        return "provider_server_failed"
    return "provider_failed"


@dataclass(frozen=True, repr=False)
class ProviderSettings:
    api_key: str
    model: str
    base_url: str

    def __repr__(self) -> str:
        return f"ProviderSettings(model={self.model!r}, credentials=<redacted>)"

    @classmethod
    def from_environment(cls, source: Mapping[str, str] | None = None) -> ProviderSettings:
        source = os.environ if source is None else source
        names = ("MOKIO_TASK_API_KEY", "MOKIO_TASK_MODEL", "MOKIO_TASK_BASE_URL")
        values = tuple(source.get(name, "").strip() for name in names)
        if not all(values):
            raise TaskProviderError("task_provider_unconfigured")
        return cls(*values)


def create_task_model(settings: ProviderSettings, *, max_output_tokens: int) -> ChatOpenAI:
    if not isinstance(max_output_tokens, int) or not 1 <= max_output_tokens <= 4096:
        raise TaskProviderError("invalid_output_budget")
    try:
        return ChatOpenAI(
            api_key=settings.api_key,
            model=settings.model,
            base_url=settings.base_url,
            temperature=0,
            max_retries=MAX_RETRIES,
            max_tokens=max_output_tokens,
        )
    except Exception:
        raise TaskProviderError("provider_setup_failed") from None


def provider_runtime_identity() -> dict[str, object]:
    try:
        sdk_version = version("langchain-openai")
    except PackageNotFoundError:
        sdk_version = "unavailable"
    return {
        "adapter_config_version": ADAPTER_CONFIG_VERSION,
        "max_retries": MAX_RETRIES,
        "sdk_package": "langchain-openai",
        "sdk_version": sdk_version,
        "transport_attempt_observable": True,
    }


def create_model() -> ChatOpenAI:
    load_dotenv()

    api_key = os.getenv("API_KEY")
    model = os.getenv("MODEL")
    base_url = os.getenv("BASE_URL")

    missing = [name for name, value in {"API_KEY": api_key, "MODEL": model, "BASE_URL": base_url}.items() if not value]
    if missing:
        raise RuntimeError(f"missing required .env setting(s): {', '.join(missing)}")

    return ChatOpenAI(
        api_key=api_key,
        model=model,
        base_url=base_url,
        temperature=0,
        max_retries=MAX_RETRIES,
        callbacks=[current_usage_handler()],
    )
