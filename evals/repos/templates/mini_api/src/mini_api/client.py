from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen


Transport = Callable[[str, float, int], Any]
DEFAULT_TIMEOUT_SECONDS: float = 2.0
DEFAULT_RETRIES: int = 3


def _default_transport(path: str, timeout_seconds: float, retries: int) -> Any:
    last_error: Exception | None = None
    for _ in range(retries + 1):
        try:
            with urlopen(path, timeout=timeout_seconds) as response:
                return json.load(response)
        except (TimeoutError, URLError) as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


class MiniClient:
    def __init__(self, transport: Transport | None = None) -> None:
        self._transport = transport or _default_transport

    def request_json(
        self,
        path: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        retries: int = DEFAULT_RETRIES,
    ) -> Any:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if retries < 0:
            raise ValueError("retries cannot be negative")
        return self._transport(path, timeout_seconds, retries)
