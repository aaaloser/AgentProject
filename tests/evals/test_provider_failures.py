from __future__ import annotations

import socket
import ssl

import pytest

from mokioclaw.evals.models import CaseResult, RunStatus
from mokioclaw.evals.provider_failures import FailureKind, classify_failure, derive_provider_phase


class HttpFailure(RuntimeError):
    def __init__(self, status_code: int, message: str = "provider request failed") -> None:
        super().__init__(message)
        self.status_code = status_code


class ProtocolError(RuntimeError):
    pass


@pytest.mark.parametrize(
    ("status", "expected", "retryable"),
    [
        (401, FailureKind.PROVIDER_AUTH, False),
        (403, FailureKind.PROVIDER_AUTH, False),
        (402, FailureKind.PROVIDER_BILLING, False),
        (429, FailureKind.PROVIDER_RATE_LIMIT, True),
        (400, FailureKind.PROVIDER_REQUEST_REJECTED, False),
        (404, FailureKind.PROVIDER_REQUEST_REJECTED, False),
        (499, FailureKind.PROVIDER_REQUEST_REJECTED, False),
        (500, FailureKind.PROVIDER_TRANSPORT, True),
        (502, FailureKind.PROVIDER_TRANSPORT, True),
        (503, FailureKind.PROVIDER_TRANSPORT, True),
        (504, FailureKind.PROVIDER_TRANSPORT, True),
    ],
)
def test_http_status_has_one_mechanical_failure_kind(status: int, expected: FailureKind, retryable: bool) -> None:
    result = classify_failure(
        HttpFailure(status),
        at_provider_boundary=True,
        successful_model_responses=0,
        tool_activity_count=0,
        provider_host="provider.invalid",
    )

    assert result.failure_kind is expected
    assert result.provider_status == status
    assert result.provider_phase == "before_first_model_response"
    assert result.retryable is retryable


@pytest.mark.parametrize(
    "error",
    [
        ConnectionError("connect failed"),
        TimeoutError("read timed out"),
        ssl.SSLError("tls failed"),
        socket.gaierror("dns failed"),
        ProtocolError("protocol failed"),
    ],
)
def test_transport_exceptions_map_to_provider_transport(error: BaseException) -> None:
    result = classify_failure(
        error,
        at_provider_boundary=True,
        successful_model_responses=1,
        tool_activity_count=0,
    )

    assert result.failure_kind is FailureKind.PROVIDER_TRANSPORT
    assert result.provider_status is None
    assert result.provider_phase == "after_model_response_before_first_tool"
    assert result.retryable is True


def test_provider_boundary_unknown_never_falls_back_to_worker_internal() -> None:
    result = classify_failure(
        RuntimeError("an unmapped provider-side failure"),
        at_provider_boundary=True,
        successful_model_responses=2,
        tool_activity_count=1,
    )

    assert result.failure_kind is FailureKind.PROVIDER_UNKNOWN
    assert result.provider_phase == "after_tool_activity"


@pytest.mark.parametrize(
    "local_kind",
    [FailureKind.WORKER_INTERNAL, FailureKind.CONFIG, FailureKind.SANDBOX],
)
def test_non_provider_failures_require_an_explicit_local_kind(local_kind: FailureKind) -> None:
    result = classify_failure(
        RuntimeError("local failure"),
        at_provider_boundary=False,
        local_kind=local_kind,
        successful_model_responses=0,
        tool_activity_count=0,
    )

    assert result.failure_kind is local_kind
    assert result.provider_status is None
    assert result.provider_phase is None
    assert result.retryable is False


def test_non_provider_failure_rejects_a_provider_kind_hint() -> None:
    with pytest.raises(ValueError, match="local_kind"):
        classify_failure(
            RuntimeError("local failure"),
            at_provider_boundary=False,
            local_kind=FailureKind.PROVIDER_UNKNOWN,
            successful_model_responses=0,
            tool_activity_count=0,
        )


@pytest.mark.parametrize(
    ("successful_model_responses", "tool_activity_count", "expected"),
    [
        (0, 0, "before_first_model_response"),
        (0, 9, "before_first_model_response"),
        (1, 0, "after_model_response_before_first_tool"),
        (7, 0, "after_model_response_before_first_tool"),
        (1, 1, "after_tool_activity"),
        (4, 8, "after_tool_activity"),
    ],
)
def test_provider_phase_is_mutually_exclusive_and_uses_frozen_precedence(
    successful_model_responses: int,
    tool_activity_count: int,
    expected: str,
) -> None:
    assert derive_provider_phase(successful_model_responses, tool_activity_count) == expected


def test_provider_phase_rejects_negative_counters() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        derive_provider_phase(-1, 0)


def test_sanitized_reason_never_contains_secret_endpoint_query_headers_or_payload() -> None:
    fake_key = "sk-FAKE_SECRET_DO_NOT_PERSIST"
    error = HttpFailure(
        504,
        "Authorization: Bearer "
        + fake_key
        + " https://provider.invalid/v1/chat?token=FAKE_QUERY request_body=FAKE_PROMPT response_body=FAKE_RESPONSE",
    )

    result = classify_failure(
        error,
        at_provider_boundary=True,
        successful_model_responses=0,
        tool_activity_count=0,
        provider_host="https://user:password@provider.invalid/v1/chat?token=FAKE_QUERY",
    )

    assert result.sanitized_reason == "HttpFailure; http_status=504; provider_host=provider.invalid"
    for forbidden in (
        fake_key,
        "Authorization",
        "Bearer",
        "https://",
        "/v1/chat",
        "FAKE_QUERY",
        "FAKE_PROMPT",
        "FAKE_RESPONSE",
        "user",
        "password",
    ):
        assert forbidden not in result.sanitized_reason


def test_case_result_exposes_structured_failure_fields_without_replacing_run_status() -> None:
    result = CaseResult(
        run_id="run-1",
        case_id="case-1",
        status=RunStatus.SETUP_FAILED,
        success=False,
        failure_kind=FailureKind.PROVIDER_TRANSPORT,
        provider_status=504,
        provider_phase="before_first_model_response",
        retryable=True,
        sanitized_reason="HttpFailure; http_status=504; provider_host=provider.invalid",
    )

    assert result.status is RunStatus.SETUP_FAILED
    assert result.failure_kind is FailureKind.PROVIDER_TRANSPORT
    assert result.provider_status == 504
