"""Behavioral contracts for numeric observation; no real dependencies."""

from dataclasses import replace
import json
import pytest

from task_observation_fakes import TASK_ID, MemorySink, offline_observation_guard, utc_clock


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    with offline_observation_guard(monkeypatch):
        yield


def module():
    import mokioclaw.core.task_observation as observation
    return observation


def record(kind="invoke_started", **values):
    m = module()
    return m.ObservationRecord(
        task_id=TASK_ID, attempt_id=1, kind=kind, stage="planner", call_no=1,
        status="started" if kind == "invoke_started" else "valid_usage",
        before=m.LedgerNumbers(0, 0, 20, 150000),
        after=m.LedgerNumbers(1, 0, 19, 150000), **values,
    )


@pytest.mark.parametrize("metadata,want", [
    ({"total_tokens": 0, "input_tokens": 0, "output_tokens": 0}, (0, 0, 0, "available")),
    ({"total_tokens": 7, "input_tokens": 4, "output_tokens": 3}, (7, 4, 3, "available")),
    ({"total_tokens": 7, "input_tokens": 4, "output_tokens": 4}, (7, None, None, "unavailable")),
    ({"total_tokens": 7, "input_tokens": True, "output_tokens": 6}, (7, None, None, "unavailable")),
    ({"total_tokens": True}, (None, None, None, "unavailable")),
    ({"total_tokens": -1}, (None, None, None, "unavailable")),
    ({}, (None, None, None, "unavailable")), (None, (None, None, None, "unavailable")),
])
def test_usage_zero_invalid_split(metadata, want):
    u = module().normalize_usage(metadata)
    assert (u.total_tokens, u.input_tokens, u.output_tokens, u.split_status) == want


def test_record_strict_schema_and_caps():
    m = module()
    sink = MemorySink()
    obs = m.TaskObservation(TASK_ID, sink, utc_clock=utc_clock, monotonic_clock=lambda: 3)
    for _ in range(512):
        assert obs.emit(record())
    assert not obs.emit(record())
    assert not obs.valid and len(sink.records) == 512
    assert [r.event_sequence for r in sink.records] == list(range(1, 513))
    encoded = m.encode_record(sink.records[0])
    assert len(encoded) <= 4096
    assert json.loads(encoded)["utc_time"] == "2026-10-04T00:00:00Z"
    for change in ({"stage": "PRIVATE_SENTINEL"}, {"task_id": "x" * 5000},
                   {"elapsed_ms": float("nan")}, {"total_tokens": True},
                   {"reasons": ("private",)}, {"policy": {"private": "SENTINEL"}}):
        with pytest.raises(ValueError, match="observation_invalid"):
            m.encode_record(replace(sink.records[0], **change))


def test_unpaired_start_unknown():
    m = module()
    row = replace(record(), event_sequence=1, utc_time="2026-10-04T00:00:00Z")
    totals = {f"{s}_{suffix}": 0 for s in m.STAGES for suffix in ("calls", "reported_tokens")}
    totals["planner_calls"] = 1
    result = m.reconcile([row], totals)
    assert not result.valid and result.started_calls == 1 and result.unknown_calls == 1


def test_failed_call_is_paired_but_usage_unknown():
    m = module()
    start = replace(record(), event_sequence=1, utc_time="2026-10-04T00:00:00Z")
    failed = replace(start, kind="invoke_failed", status="provider_failed", event_sequence=2)
    totals = {f"{s}_{suffix}": 0 for s in m.STAGES for suffix in ("calls", "reported_tokens")}
    totals["planner_calls"] = 1
    result = m.reconcile([start, failed], totals)
    assert result.valid and result.started_calls == 1 and result.unknown_calls == 1
    assert failed.total_tokens is None


@pytest.mark.parametrize("mutation", ["duplicate_start", "duplicate_finish", "gap", "bad_total"])
def test_reconcile_rejects_unreliable_records(mutation):
    m = module()
    start = replace(record(), event_sequence=1, utc_time="2026-10-04T00:00:00Z")
    finish = replace(start, kind="invoke_finished", status="valid_usage", event_sequence=2,
                     total_tokens=0)
    rows = [start, finish]
    if mutation == "duplicate_start":
        rows = [start, replace(start, event_sequence=2)]
    elif mutation == "duplicate_finish":
        rows.append(replace(finish, event_sequence=3))
    elif mutation == "gap":
        rows[1] = replace(finish, event_sequence=3)
    else:
        rows[1] = replace(finish, status="usage_unavailable", total_tokens=None)
    totals = {f"{s}_{suffix}": 0 for s in m.STAGES for suffix in ("calls", "reported_tokens")}
    totals["planner_calls"] = 1
    assert not m.reconcile(rows, totals).valid


def test_observer_sink_failure_never_raises():
    class BrokenSink:
        def emit(self, record):
            raise RuntimeError("PRIVATE_EXCEPTION_SENTINEL")
    obs = module().TaskObservation(TASK_ID, BrokenSink())
    assert not obs.emit(record()) and not obs.valid


def test_swallowed_guard_still_fails(monkeypatch):
    import multiprocessing.connection
    with pytest.raises(AssertionError, match="offline_boundary_touched"):
        with offline_observation_guard(monkeypatch):
            try:
                multiprocessing.connection.Client("forbidden")
            except AssertionError:
                pass


def test_invalidation_propagates_and_reconciliation_is_strict():
    m = module()
    class Sink(MemorySink):
        invalidated = False
        def invalidate(self):
            self.invalidated = True
    sink = Sink()
    obs = m.TaskObservation(TASK_ID, sink, utc_clock=utc_clock)
    obs.invalidate()
    assert sink.invalidated
    start = replace(record(), event_sequence=1, utc_time="2026-10-04T00:00:00Z")
    finish = replace(start, kind="invoke_finished", status="valid_usage", total_tokens=0,
                     event_sequence=2)
    totals = {s + n: 0 for s in m.STAGES for n in ("_calls", "_reported_tokens")}
    totals["planner_calls"] = 1
    assert not m.reconcile([start, replace(finish, task_id="another_task_0001")], totals).valid
    totals["entry_calls"] = False
    assert not m.reconcile([start, finish], totals).valid


@pytest.mark.parametrize("values", [
    {"utc_time": "2026-02-30T00:00:00Z"},
    {"kind": "policy_decision", "status": "observed", "call_no": None, "total_tokens": 0},
    {"status": "observed"},
])
def test_rejects_impossible_semantics(values):
    m = module()
    row = replace(record(), event_sequence=1, utc_time="2026-10-04T00:00:00Z", **{})
    with pytest.raises(ValueError, match="observation_invalid"):
        m.encode_record(replace(row, **values))
