from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


IMMEDIATE_FAILURE_KINDS = frozenset(
    {
        "provider_auth",
        "provider_billing",
        "provider_rate_limit",
        "provider_request_rejected",
        "provider_unknown",
        "config",
        "sandbox",
        "worker_internal",
    }
)

FORBIDDEN_GATE_KEYS = frozenset(
    {
        "architecture",
        "architectures",
        "case",
        "case_id",
        "case_ids",
        "cell",
        "cells",
        "q1",
        "q2",
        "budget_priority",
        "budget-priority",
        "deep",
        "deep_progress",
        "resource_migration",
        "react_drift",
    }
)
FORBIDDEN_GATE_VALUES = ("react drift", "react_drift", "budget-priority", "budget priority")


@dataclass(frozen=True)
class CandidateReview:
    candidate_id: str
    subsystem_id: str
    passed: bool


@dataclass(frozen=True)
class CaseSelection:
    status: str
    case_ids: tuple[str, ...]
    run_budget: int


def select_case_protocol(
    reviews: Iterable[CandidateReview], *, agent_results_seen: bool = False
) -> CaseSelection:
    if agent_results_seen:
        raise RuntimeError("Case selection cannot change after Agent results exist")
    ordered = list(reviews)
    passing = [review for review in ordered if review.passed]
    if passing:
        first = passing[0]
        second = next((review for review in passing[1:] if review.subsystem_id != first.subsystem_id), None)
        if second is not None:
            return CaseSelection("frozen", (first.candidate_id, second.candidate_id), 72)
    if len(ordered) < 4:
        return CaseSelection("pending", (), 0)
    if passing:
        return CaseSelection("frozen", (passing[0].candidate_id,), 36)
    return CaseSelection("stop", (), 0)


@dataclass(frozen=True)
class StopDecision:
    stopped: bool
    reason: str | None
    consecutive_transport: int
    round_transport: int


class StopController:
    def __init__(self, *, case_count: int) -> None:
        if case_count not in {1, 2}:
            raise ValueError("formal protocol requires one or two Cases")
        self.case_count = case_count
        self._reason: str | None = None
        self._consecutive_transport = 0
        self._round_transport: Counter[str] = Counter()

    def observe(
        self,
        *,
        round_name: str,
        failure_kind: str | None = None,
        successful_model_response: bool = False,
        token_usage_present: bool = True,
        transport_observable: bool = True,
        integrity_issues: Iterable[str] = (),
    ) -> StopDecision:
        if self._reason is not None:
            return self._decision(round_name)
        issues = tuple(integrity_issues)
        if issues:
            self._reason = f"integrity:{issues[0]}"
        elif not transport_observable:
            self._reason = "transport_not_observable"
        elif successful_model_response and not token_usage_present:
            self._reason = "successful_response_missing_usage"
        elif failure_kind in IMMEDIATE_FAILURE_KINDS:
            self._reason = f"immediate_failure:{failure_kind}"
        elif failure_kind == "provider_transport":
            self._consecutive_transport += 1
            self._round_transport[round_name] += 1
            if self._consecutive_transport >= 2:
                self._reason = "consecutive_provider_transport:2"
            else:
                threshold = 3 if self.case_count == 2 else 2
                if self._round_transport[round_name] >= threshold:
                    self._reason = f"round_provider_transport:{threshold}"
        else:
            self._consecutive_transport = 0
        return self._decision(round_name)

    def _decision(self, round_name: str) -> StopDecision:
        return StopDecision(
            stopped=self._reason is not None,
            reason=self._reason,
            consecutive_transport=self._consecutive_transport,
            round_transport=self._round_transport[round_name],
        )


def assert_gate_safe(value: Any, *, location: str = "summary") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower().replace(" ", "_")
            if normalized in FORBIDDEN_GATE_KEYS:
                raise ValueError(f"gate-safe summary contains forbidden field at {location}.{key}")
            assert_gate_safe(item, location=f"{location}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            assert_gate_safe(item, location=f"{location}[{index}]")
        return
    if isinstance(value, str):
        normalized_value = value.strip().lower()
        if any(marker in normalized_value for marker in FORBIDDEN_GATE_VALUES):
            raise ValueError(f"gate-safe summary contains forbidden value at {location}")


def build_gate_safe_summary(
    rows: Iterable[Mapping[str, Any]],
    *,
    scheduled: int,
    started: int,
    closed: int,
    not_started: int,
    integrity: Mapping[str, Any],
    stop_status: Mapping[str, Any],
) -> dict[str, Any]:
    materialized = list(rows)
    failure_kinds = Counter(str(row["failure_kind"]) for row in materialized if row.get("failure_kind"))
    provider_phases = Counter(str(row["provider_phase"]) for row in materialized if row.get("provider_phase"))
    coverage = Counter(str(row.get("telemetry_coverage") or "unavailable") for row in materialized)
    unavailable_reasons = Counter(
        str(row["telemetry_unavailable_reason"])
        for row in materialized
        if row.get("telemetry_unavailable_reason")
    )
    summary = {
        "schema_version": 1,
        "slots": {"scheduled": scheduled, "started": started, "closed": closed, "not_started": not_started},
        "failure_kinds": dict(sorted(failure_kinds.items())),
        "provider_phases": dict(sorted(provider_phases.items())),
        "coverage": {name: coverage.get(name, 0) for name in ("full", "partial", "unavailable")},
        "coverage_unavailable_reasons": dict(sorted(unavailable_reasons.items())),
        "token_totals": {
            "input": sum(int(row.get("input_tokens") or 0) for row in materialized),
            "output": sum(int(row.get("output_tokens") or 0) for row in materialized),
            "total": sum(int(row.get("total_tokens") or 0) for row in materialized),
        },
        "integrity": dict(integrity),
        "stop_status": dict(stop_status),
    }
    assert_gate_safe(summary)
    return summary
