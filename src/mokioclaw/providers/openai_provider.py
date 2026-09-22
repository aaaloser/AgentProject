from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from mokioclaw.providers.usage import current_usage_handler


ADAPTER_CONFIG_VERSION = 1
MAX_RETRIES = 0


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
