from __future__ import annotations

from collections.abc import Mapping
from typing import Any


DEFAULT_SETTINGS: dict[str, Any] = {"host": "localhost", "retries": 3}


def _is_blank(value: object) -> bool:
    return value is None or value == ""


def _coerce(key: str, value: object) -> object:
    return int(value) if key == "retries" else value


def resolve_settings(
    *,
    cli: Mapping[str, object] | None = None,
    env: Mapping[str, object] | None = None,
    file: Mapping[str, object] | None = None,
) -> dict[str, object]:
    resolved = dict(DEFAULT_SETTINGS)
    for layer in (file or {}, env or {}, cli or {}):
        for key in resolved:
            if key in layer and not _is_blank(layer[key]):
                resolved[key] = _coerce(key, layer[key])
    return resolved
