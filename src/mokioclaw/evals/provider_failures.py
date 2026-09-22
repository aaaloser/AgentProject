from __future__ import annotations

import re
import socket
import ssl
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit


class FailureKind(str, Enum):
    PROVIDER_TRANSPORT = "provider_transport"
    PROVIDER_AUTH = "provider_auth"
    PROVIDER_BILLING = "provider_billing"
    PROVIDER_RATE_LIMIT = "provider_rate_limit"
    PROVIDER_REQUEST_REJECTED = "provider_request_rejected"
    PROVIDER_UNKNOWN = "provider_unknown"
    WORKER_INTERNAL = "worker_internal"
    CONFIG = "config"
    SANDBOX = "sandbox"


PROVIDER_PHASES = frozenset(
    {
        "before_first_model_response",
        "after_model_response_before_first_tool",
        "after_tool_activity",
    }
)
LOCAL_FAILURE_KINDS = frozenset({FailureKind.WORKER_INTERNAL, FailureKind.CONFIG, FailureKind.SANDBOX})


@dataclass(frozen=True)
class FailureClassification:
    failure_kind: FailureKind
    provider_status: int | None
    provider_phase: str | None
    retryable: bool
    sanitized_reason: str


def derive_provider_phase(successful_model_responses: int, tool_activity_count: int) -> str:
    if successful_model_responses < 0 or tool_activity_count < 0:
        raise ValueError("provider phase counters must be non-negative")
    if successful_model_responses == 0:
        return "before_first_model_response"
    if tool_activity_count == 0:
        return "after_model_response_before_first_tool"
    return "after_tool_activity"


def _provider_status(error: BaseException) -> int | None:
    candidates = [getattr(error, "status_code", None)]
    response = getattr(error, "response", None)
    if response is not None:
        candidates.append(getattr(response, "status_code", None))
    for candidate in candidates:
        if isinstance(candidate, bool):
            continue
        try:
            status = int(candidate)
        except (TypeError, ValueError, OverflowError):
            continue
        if 100 <= status <= 599:
            return status
    return None


def _is_transport_error(error: BaseException) -> bool:
    if isinstance(error, (ConnectionError, TimeoutError, socket.gaierror, ssl.SSLError)):
        return True
    name = type(error).__name__.lower()
    return any(
        marker in name
        for marker in (
            "apiconnection",
            "apitimeout",
            "connecterror",
            "connectionerror",
            "dnserror",
            "protocolerror",
            "readerror",
            "readtimeout",
            "tlserror",
            "transporterror",
        )
    )


def _kind_from_provider_error(error: BaseException, status: int | None) -> FailureKind:
    if status in {401, 403}:
        return FailureKind.PROVIDER_AUTH
    if status == 402:
        return FailureKind.PROVIDER_BILLING
    if status == 429:
        return FailureKind.PROVIDER_RATE_LIMIT
    if status is not None and 400 <= status <= 499:
        return FailureKind.PROVIDER_REQUEST_REJECTED
    if status is not None and 500 <= status <= 599:
        return FailureKind.PROVIDER_TRANSPORT
    if _is_transport_error(error):
        return FailureKind.PROVIDER_TRANSPORT
    return FailureKind.PROVIDER_UNKNOWN


def sanitize_provider_host(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    parsed = urlsplit(candidate if "://" in candidate else f"//{candidate}")
    host = parsed.hostname
    if not host:
        return None
    return host.lower().rstrip(".")


def _safe_exception_name(error: BaseException) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", type(error).__name__) or "Exception"


def _sanitized_reason(error: BaseException, status: int | None, provider_host: str | None) -> str:
    parts = [_safe_exception_name(error)]
    if status is not None:
        parts.append(f"http_status={status}")
    host = sanitize_provider_host(provider_host)
    if host:
        parts.append(f"provider_host={host}")
    return "; ".join(parts)


def classify_failure(
    error: BaseException,
    *,
    at_provider_boundary: bool,
    successful_model_responses: int,
    tool_activity_count: int,
    local_kind: FailureKind = FailureKind.WORKER_INTERNAL,
    provider_host: str | None = None,
) -> FailureClassification:
    if at_provider_boundary:
        status = _provider_status(error)
        kind = _kind_from_provider_error(error, status)
        phase = derive_provider_phase(successful_model_responses, tool_activity_count)
        retryable = kind in {FailureKind.PROVIDER_TRANSPORT, FailureKind.PROVIDER_RATE_LIMIT}
    else:
        if local_kind not in LOCAL_FAILURE_KINDS:
            raise ValueError("local_kind must be worker_internal, config, or sandbox")
        status = None
        kind = local_kind
        phase = None
        retryable = False
    return FailureClassification(
        failure_kind=kind,
        provider_status=status,
        provider_phase=phase,
        retryable=retryable,
        sanitized_reason=_sanitized_reason(error, status, provider_host if at_provider_boundary else None),
    )
