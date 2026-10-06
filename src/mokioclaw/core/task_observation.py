"""Private numeric task observations. No provider, filesystem or transport imports."""

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
import json
import re
import time
from typing import Callable, Mapping, Protocol, Sequence

STAGES = ("entry", "chat", "planner", "code_agent", "verifier", "context_compressor")
PURPOSES = ("repair", "handoff", "planner", "pre_compress", "verifier", "post_compress")
SLOTS = ("handoff", "planner", "pre_compress", "verifier", "post_compress")
OPAQUE_ID = re.compile(r"[A-Za-z0-9_-]{16,64}")


class ObservationKind(StrEnum):
    STARTED = "invoke_started"
    FINISHED = "invoke_finished"
    FAILED = "invoke_failed"
    REFUSED = "invoke_refused"
    POLICY = "policy_decision"
    RELEASED = "phase_released"
    ADOPTED = "adopt_existing_call"


class ObservationGate(StrEnum):
    KNOWN = "known_failure"
    USAGE = "usage"
    CALLS = "total_calls"
    TOKENS = "total_tokens"
    CONTEXT = "context"
    PHASE = "phase"
    DELEGATION = "delegation"
    ATTEMPT = "attempt"


class ObservationReason(StrEnum):
    CALLS = "calls"
    TOKENS = "tokens"
    ITERATIONS = "iterations"


@dataclass(frozen=True)
class UsageNumbers:
    total_tokens: int | None
    input_tokens: int | None
    output_tokens: int | None
    split_status: str


@dataclass(frozen=True)
class LedgerNumbers:
    calls_used: int
    reported_tokens: int
    calls_left: int
    tokens_left: int


@dataclass(frozen=True)
class ObservationRecord:
    task_id: str
    attempt_id: int
    kind: str
    schema_version: int = 1
    event_sequence: int = 0
    call_no: int | None = None
    stage: str | None = None
    purpose: str | None = None
    utc_time: str = ""
    elapsed_ms: int = 0
    status: str = "observed"
    gate: str | None = None
    reasons: tuple[str, ...] = ()
    total_tokens: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    split_status: str = "unavailable"
    before: LedgerNumbers | None = None
    after: LedgerNumbers | None = None
    policy: dict | None = None


class ObservationSink(Protocol):
    def emit(self, record: ObservationRecord) -> bool: ...


@dataclass(frozen=True)
class ObservationReconciliation:
    valid: bool
    started_calls: int
    unknown_calls: int
    reasons: tuple[str, ...]


def _number(value, *, nullable=False, negative=False):
    return (nullable and value is None) or (type(value) is int and (negative or value >= 0))


def normalize_usage(metadata: object) -> UsageNumbers:
    if not isinstance(metadata, dict) or not _number(metadata.get("total_tokens")):
        return UsageNumbers(None, None, None, "unavailable")
    total = metadata["total_tokens"]
    incoming, outgoing = metadata.get("input_tokens"), metadata.get("output_tokens")
    if _number(incoming) and _number(outgoing) and incoming + outgoing == total:
        return UsageNumbers(total, incoming, outgoing, "available")
    return UsageNumbers(total, None, None, "unavailable")


def _validate(data):
    bad = ValueError("observation_invalid")
    if (data.keys() != ObservationRecord.__dataclass_fields__.keys()
            or type(data["task_id"]) is not str or not OPAQUE_ID.fullmatch(data["task_id"])
            or type(data["schema_version"]) is not int or data["schema_version"] != 1
            or type(data["attempt_id"]) is not int or not 1 <= data["attempt_id"] <= 3
            or not _number(data["event_sequence"]) or not 1 <= data["event_sequence"] <= 512
            or not _number(data["elapsed_ms"])
            or type(data["utc_time"]) is not str
            or re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z", data["utc_time"]) is None):
        raise bad
    datetime.fromisoformat(data["utc_time"])
    for key, allowed in (
        ("kind", set(ObservationKind)), ("gate", set(ObservationGate) | {None}),
        ("stage", set(STAGES) | {None}), ("purpose", set(PURPOSES) | {None}),
        ("status", {"started", "valid_usage", "usage_unavailable", "provider_failed", "refused", "observed"}),
        ("split_status", {"available", "unavailable"}),
    ):
        if not isinstance(data[key], (str, type(None))) or data[key] not in allowed:
            raise bad
    if (not isinstance(data["reasons"], (tuple, list))
            or any(type(r) is not str or r not in set(ObservationReason) for r in data["reasons"])
            or len(set(data["reasons"])) != len(data["reasons"])):
        raise bad
    if not _number(data["call_no"], nullable=True) or (data["call_no"] is not None and not 1 <= data["call_no"] <= 24):
        raise bad
    for key in ("total_tokens", "input_tokens", "output_tokens"):
        if not _number(data[key], nullable=True):
            raise bad
    kind = data["kind"]
    statuses = {"invoke_started": "started", "invoke_failed": "provider_failed",
                "invoke_refused": "refused", "policy_decision": "observed",
                "phase_released": "observed", "adopt_existing_call": "observed"}
    if kind in statuses and data["status"] != statuses[kind]:
        raise bad
    if kind != "invoke_finished" and any(data[k] is not None for k in ("total_tokens", "input_tokens", "output_tokens")):
        raise bad
    if kind in {"invoke_started", "invoke_finished", "invoke_failed"} and (
            data["call_no"] is None or data["stage"] is None):
        raise bad
    if kind in {"invoke_refused", "policy_decision", "phase_released"} and data["call_no"] is not None:
        raise bad
    if kind == "adopt_existing_call" and data["call_no"] is None:
        raise bad
    if kind == "invoke_finished" and (
            data["status"] != ("usage_unavailable" if data["total_tokens"] is None else "valid_usage")):
        raise bad
    if data["split_status"] == "available":
        if (any(data[k] is None for k in ("total_tokens", "input_tokens", "output_tokens"))
                or data["input_tokens"] + data["output_tokens"] != data["total_tokens"]):
            raise bad
    elif data["input_tokens"] is not None or data["output_tokens"] is not None:
        raise bad
    for name in ("before", "after"):
        value = data[name]
        if value is not None and (
                type(value) is not dict or value.keys() != LedgerNumbers.__dataclass_fields__.keys()
                or any(not _number(v, negative=k == "tokens_left") for k, v in value.items())):
            raise bad
    policy = data["policy"]
    if policy is not None:
        keys = {"mode", "E_repair", "R_calls", "R_tokens", "iterations_left", "slots"}
        if (type(policy) is not dict or policy.keys() != keys
                or policy["mode"] not in {"inactive", "repair", "closing", "finished", "failed"}
                or any(not _number(policy[k]) for k in ("E_repair", "R_calls", "R_tokens"))
                or not _number(policy["iterations_left"], nullable=True)
                or type(policy["slots"]) is not dict or set(policy["slots"]) != set(SLOTS)
                or any(not _number(v) or v > 2 for v in policy["slots"].values())):
            raise bad


def encode_record(record: ObservationRecord) -> bytes:
    try:
        if type(record) is not ObservationRecord:
            raise ValueError
        data = asdict(record)
        _validate(data)
        encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(encoded) > 4096:
            raise ValueError
        return encoded
    except (TypeError, ValueError, OverflowError):
        raise ValueError("observation_invalid") from None


def record_from_dict(data: dict) -> ObservationRecord:
    try:
        _validate(data)
        values = dict(data)
        for name in ("before", "after"):
            if values[name] is not None:
                values[name] = LedgerNumbers(**values[name])
        values["reasons"] = tuple(values["reasons"])
        record = ObservationRecord(**values)
        encode_record(record)
        return record
    except (TypeError, ValueError, KeyError):
        raise ValueError("observation_invalid") from None


class TaskObservation:
    def __init__(self, task_id: str, sink: ObservationSink, *,
                 utc_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 monotonic_clock: Callable[[], float] = time.monotonic):
        if type(task_id) is not str or OPAQUE_ID.fullmatch(task_id) is None:
            raise ValueError("observation_invalid")
        self.task_id, self.sink = task_id, sink
        self._utc, self._clock = utc_clock, monotonic_clock
        self._origin = monotonic_clock()
        self._sequence = 0
        self.valid = True

    def invalidate(self) -> None:
        was_valid = self.valid
        self.valid = False
        if was_valid:
            try:
                callback = getattr(self.sink, "invalidate", None)
                if callable(callback):
                    callback()
            except Exception:
                pass

    def emit(self, record: ObservationRecord) -> bool:
        if not self.valid:
            return False
        try:
            if record.task_id != self.task_id or self._sequence >= 512:
                raise ValueError
            row = replace(record, event_sequence=self._sequence + 1,
                          utc_time=self._utc().astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                          elapsed_ms=max(0, int((self._clock() - self._origin) * 1000)))
            encode_record(row)
            if self.sink.emit(row) is not True:
                raise ValueError
            self._sequence += 1
            return True
        except Exception:
            self.invalidate()
            return False


def reconcile(records: Sequence[ObservationRecord], final_usage: Mapping[str, int]) -> ObservationReconciliation:
    reasons = set()
    started, ended, adopted = {}, {}, set()
    counts, tokens = dict.fromkeys(STAGES, 0), dict.fromkeys(STAGES, 0)
    try:
        if (set(final_usage) != {s + n for s in STAGES for n in ("_calls", "_reported_tokens")}
                or any(not _number(v) for v in final_usage.values())
                or sum(final_usage[s + "_calls"] for s in STAGES) > 24):
            raise ValueError
        if len(records) > 512:
            raise ValueError
        for i, row in enumerate(records, 1):
            encode_record(row)
            if records and (row.task_id != records[0].task_id or
                            (i > 1 and row.attempt_id < records[i - 2].attempt_id)):
                reasons.add("identity_invalid")
            if row.event_sequence != i:
                reasons.add("sequence_gap")
            if row.kind == ObservationKind.STARTED:
                if row.call_no in started or row.call_no != len(started) + 1 or row.stage is None:
                    reasons.add("call_duplicate")
                started[row.call_no] = row
                counts[row.stage] += 1
            elif row.kind in {ObservationKind.FINISHED, ObservationKind.FAILED}:
                origin = started.get(row.call_no)
                if (origin is None or row.call_no in ended or origin.stage != row.stage
                        or origin.attempt_id != row.attempt_id or origin.purpose != row.purpose):
                    reasons.add("call_pair_invalid")
                ended[row.call_no] = row
                if row.kind == ObservationKind.FINISHED:
                    if row.total_tokens is None or row.status != "valid_usage":
                        reasons.add("usage_unavailable")
                    else:
                        tokens[row.stage] += row.total_tokens
            elif row.kind == ObservationKind.ADOPTED:
                if (row.call_no not in ended or row.call_no in adopted
                        or started[row.call_no].stage != "planner" or started[row.call_no].attempt_id != row.attempt_id):
                    reasons.add("adoption_invalid")
                adopted.add(row.call_no)
            elif row.kind == ObservationKind.REFUSED and row.call_no is not None:
                reasons.add("call_pair_invalid")
        for stage in STAGES:
            if final_usage.get(stage + "_calls") != counts[stage] or final_usage.get(stage + "_reported_tokens") != tokens[stage]:
                reasons.add("totals_mismatch")
        unknown = sum(n not in ended or ended[n].total_tokens is None for n in started)
        if any(n not in ended for n in started):
            reasons.add("call_unpaired")
    except (TypeError, ValueError, KeyError):
        reasons.add("record_invalid")
        unknown = len(started)
    return ObservationReconciliation(not reasons, len(started), unknown, tuple(sorted(reasons)))
