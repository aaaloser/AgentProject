from __future__ import annotations

from copy import deepcopy

import pytest

from mokioclaw.evals.protocol import (
    CandidateReview,
    StopController,
    assert_gate_safe,
    build_gate_safe_summary,
    select_case_protocol,
)


def reviews(*rows: tuple[str, str, bool]) -> list[CandidateReview]:
    return [CandidateReview(candidate_id=name, subsystem_id=subsystem, passed=passed) for name, subsystem, passed in rows]


def test_adaptive_gate_selects_first_two_passes_from_different_subsystems() -> None:
    selection = select_case_protocol(
        reviews(
            ("candidate-1", "parser", True),
            ("candidate-2", "parser", True),
            ("candidate-3", "formatter", True),
            ("candidate-4", "runner", True),
        )
    )

    assert selection.status == "frozen"
    assert selection.case_ids == ("candidate-1", "candidate-3")
    assert selection.run_budget == 72


def test_adaptive_gate_uses_one_case_after_four_reviews_without_second_subsystem() -> None:
    selection = select_case_protocol(
        reviews(
            ("candidate-1", "parser", True),
            ("candidate-2", "parser", True),
            ("candidate-3", "runner", False),
            ("candidate-4", "docs", False),
        )
    )

    assert selection.status == "frozen"
    assert selection.case_ids == ("candidate-1",)
    assert selection.run_budget == 36


def test_adaptive_gate_waits_for_four_reviews_with_only_one_pass() -> None:
    selection = select_case_protocol(reviews(("candidate-1", "parser", True), ("candidate-2", "runner", False)))

    assert selection.status == "pending"
    assert selection.case_ids == ()
    assert selection.run_budget == 0


def test_adaptive_gate_stops_after_four_reviews_with_zero_passes() -> None:
    selection = select_case_protocol(
        reviews(
            ("candidate-1", "parser", False),
            ("candidate-2", "formatter", False),
            ("candidate-3", "runner", False),
            ("candidate-4", "docs", False),
        )
    )

    assert selection.status == "stop"
    assert selection.case_ids == ()
    assert selection.run_budget == 0


def test_adaptive_gate_cannot_reselect_after_agent_results_exist() -> None:
    with pytest.raises(RuntimeError, match="Agent results"):
        select_case_protocol(reviews(("candidate-1", "parser", True)), agent_results_seen=True)


@pytest.mark.parametrize(
    "failure_kind",
    [
        "provider_auth",
        "provider_billing",
        "provider_rate_limit",
        "provider_request_rejected",
        "provider_unknown",
        "config",
        "sandbox",
        "worker_internal",
    ],
)
def test_immediate_failure_kinds_stop_on_first_observation(failure_kind: str) -> None:
    decision = StopController(case_count=2).observe(round_name="R1", failure_kind=failure_kind)

    assert decision.stopped is True
    assert decision.reason == f"immediate_failure:{failure_kind}"


def test_two_consecutive_transport_failures_stop() -> None:
    controller = StopController(case_count=2)

    assert not controller.observe(round_name="R1", failure_kind="provider_transport").stopped
    assert controller.observe(round_name="R1", failure_kind="provider_transport").reason == "consecutive_provider_transport:2"


@pytest.mark.parametrize(("case_count", "threshold"), [(2, 3), (1, 2)])
def test_round_transport_thresholds_stop_even_when_not_consecutive(case_count: int, threshold: int) -> None:
    controller = StopController(case_count=case_count)
    for _ in range(threshold - 1):
        assert not controller.observe(round_name="R1", failure_kind="provider_transport").stopped
        assert not controller.observe(round_name="R1").stopped

    decision = controller.observe(round_name="R1", failure_kind="provider_transport")
    assert decision.stopped
    assert decision.reason == f"round_provider_transport:{threshold}"


def test_single_provider_5xx_below_threshold_is_retained_and_continues() -> None:
    decision = StopController(case_count=2).observe(round_name="R1", failure_kind="provider_transport")

    assert not decision.stopped
    assert decision.reason is None


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"successful_model_response": True, "token_usage_present": False}, "successful_response_missing_usage"),
        ({"transport_observable": False}, "transport_not_observable"),
        ({"integrity_issues": ("ledger_drift",)}, "integrity:ledger_drift"),
        ({"integrity_issues": ("fingerprint_drift",)}, "integrity:fingerprint_drift"),
        ({"integrity_issues": ("artifact_drift",)}, "integrity:artifact_drift"),
    ],
)
def test_usage_observability_and_integrity_failures_stop_immediately(kwargs: dict, reason: str) -> None:
    decision = StopController(case_count=2).observe(round_name="R1", **kwargs)

    assert decision.stopped
    assert decision.reason == reason


def safe_rows() -> list[dict]:
    return [
        {
            "status": "passed",
            "failure_kind": None,
            "provider_phase": None,
            "telemetry_coverage": "full",
            "telemetry_unavailable_reason": None,
            "input_tokens": 10,
            "output_tokens": 4,
            "total_tokens": 14,
        },
        {
            "status": "setup_failed",
            "failure_kind": "provider_transport",
            "provider_phase": "mid_stream",
            "telemetry_coverage": "partial",
            "telemetry_unavailable_reason": "provider_usage_missing",
            "input_tokens": 3,
            "output_tokens": 1,
            "total_tokens": 4,
        },
    ]


def test_gate_safe_summary_contains_only_allowed_aggregates() -> None:
    summary = build_gate_safe_summary(
        safe_rows(),
        scheduled=4,
        started=2,
        closed=2,
        not_started=2,
        integrity={"call_journal": True, "transport_ledger": True, "secret_scan": True, "fingerprint": True, "artifacts": True},
        stop_status={"stopped": False, "reason": None, "consecutive_transport": 1},
    )

    assert summary["slots"] == {"scheduled": 4, "started": 2, "closed": 2, "not_started": 2}
    assert summary["failure_kinds"] == {"provider_transport": 1}
    assert summary["provider_phases"] == {"mid_stream": 1}
    assert summary["coverage"] == {"full": 1, "partial": 1, "unavailable": 0}
    assert summary["token_totals"] == {"input": 13, "output": 5, "total": 18}
    assert_gate_safe(summary)


@pytest.mark.parametrize(
    "path,value",
    [
        (("architecture",), "react"),
        (("case_id",), "click-parser"),
        (("cell",), "B"),
        (("effect", "q1"), "positive"),
        (("effect", "q2"), True),
        (("effect", "budget_priority"), True),
        (("effect", "deep_progress"), 1),
        (("note",), "ReAct drift observed"),
    ],
)
def test_gate_safe_recursive_scan_rejects_effect_keys_and_values(path: tuple[str, ...], value: object) -> None:
    payload: dict = {}
    cursor = payload
    for part in path[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[path[-1]] = value

    with pytest.raises(ValueError, match="gate-safe"):
        assert_gate_safe(payload)


def test_gate_summary_rejects_effect_data_smuggled_through_integrity() -> None:
    integrity = {"call_journal": True, "note": "react drift"}

    with pytest.raises(ValueError, match="gate-safe"):
        build_gate_safe_summary(
            deepcopy(safe_rows()),
            scheduled=2,
            started=2,
            closed=2,
            not_started=0,
            integrity=integrity,
            stop_status={"stopped": False, "reason": None},
        )
