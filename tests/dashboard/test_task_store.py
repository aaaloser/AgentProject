from __future__ import annotations

import importlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest


def _task_api():
    models = importlib.import_module("mokioclaw.dashboard.task_models")
    store = importlib.import_module("mokioclaw.dashboard.task_store")
    return models, store


def _spec(models, *, description: str = "Repair the parser"):
    return models.TaskSpec(
        task_id="",
        repo_id="repo_12345678",
        base_sha="a" * 40,
        anchor_sha="b" * 40,
        description=description,
        source_read_scope=("src/parser.py",),
        source_write_scope=("src/parser.py",),
        task_scratch_scope=".mokioclaw/task-scratch/",
        manifest_digest="c" * 64,
        max_seconds=1800,
        max_attempts=3,
        verification_commands=("python -m pytest tests/test_parser.py",),
        max_provider_calls=20,
        max_total_tokens=100_000,
        max_output_tokens_per_call=4096,
        created_at="2026-09-28T00:00:00Z",
    )


def _running(store, spec):
    record = store.create(spec, "key-1")
    record = store.transition(record.task_id, "draft", "preparing", {})
    record = store.transition(record.task_id, "preparing", "prepared", {})
    return store.transition(
        record.task_id,
        "prepared",
        "running",
        {"attempt_id": 1, "instance_id": "instance-1", "worker_pid": 123, "worker_created_at": "start-1"},
    )


def test_idempotency_matches_request_digest_and_never_persists_description(tmp_path: Path) -> None:
    models, store_module = _task_api()
    store = store_module.TaskStore(tmp_path)
    spec = _spec(models, description="PRIVATE TASK TEXT")

    first = store.create(spec, "same-key")
    second = store.create(spec, "same-key")
    assert first.task_id == second.task_id
    assert first.task_id and first.task_id != spec.task_id
    assert first.state == "draft"
    assert store_module.TaskStore(tmp_path).create(spec, "same-key").task_id == first.task_id

    with pytest.raises(store_module.TaskConflict):
        store.create(replace(spec, description="A different request"), "same-key")

    persisted = (tmp_path / first.task_id / "record.json").read_text(encoding="utf-8")
    assert "PRIVATE TASK TEXT" not in persisted
    assert "python -m pytest" not in persisted
    assert "src/parser.py" not in persisted
    assert "same-key" not in persisted
    assert json.loads(persisted)["task_id"] == first.task_id


def test_private_spec_survives_restart_and_rejects_changed_contents(tmp_path: Path) -> None:
    models, store_module = _task_api()
    store = store_module.TaskStore(tmp_path)
    spec = _spec(models, description="PRIVATE TASK TEXT")
    record = store.create(spec, "restart-spec")
    recovered = store_module.TaskStore(tmp_path).get_spec(record.task_id)
    assert recovered == replace(spec, task_id=record.task_id, created_at=record.created_at)
    assert "PRIVATE TASK TEXT" not in (tmp_path / record.task_id / "record.json").read_text(encoding="utf-8")
    private_path = tmp_path / record.task_id / "spec.json"
    changed = json.loads(private_path.read_text(encoding="utf-8"))
    changed["description"] = "tampered"
    private_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(store_module.TaskConflict):
        store_module.TaskStore(tmp_path).get_spec(record.task_id)


def test_terminal_state_requires_confirmed_cleanup_and_rejects_late_event(tmp_path: Path) -> None:
    models, store_module = _task_api()
    store = store_module.TaskStore(tmp_path)
    running = _running(store, _spec(models))
    store.transition(running.task_id, "running", "stopping", {})

    with pytest.raises(store_module.TaskConflict):
        store.transition(running.task_id, "stopping", "completed", {})

    done = store.transition(running.task_id, "stopping", "completed", {"cleanup_confirmed": True})
    assert done.state == "completed" and done.cleanup_confirmed
    with pytest.raises(store_module.TaskConflict):
        store.transition(done.task_id, "completed", "running", {})
    with pytest.raises(store_module.TaskConflict):
        store.record_event(
            done.task_id,
            1,
            models.PublicTaskEvent(done.task_id, 1, done.sequence + 1, "2026-09-28T00:00:01Z", "stage", {"name": "late"}),
        )


def test_parent_execution_receipt_persists_without_command_or_output(tmp_path: Path) -> None:
    models, store_module = _task_api()
    store = store_module.TaskStore(tmp_path)
    running = _running(store, _spec(models))
    request_id = "request_12345678901234"
    store.register_command(running.task_id, request_id)
    receipt = models.ExecutionReceipt(
        attempt_id=1, command_request_id=request_id,
        command_sha256="a" * 64, execution_digest="b" * 64,
        exit_code=0, duration_ms=21, ok=True, output_truncated=False,
    )
    saved = store.record_execution_receipt(running.task_id, "instance-1", receipt)
    assert saved.execution_receipts == (receipt,)
    recovered = store_module.TaskStore(tmp_path).get(running.task_id)
    assert recovered.execution_receipts == (receipt,)
    persisted = (tmp_path / running.task_id / "record.json").read_text(encoding="utf-8")
    assert "python -m pytest" not in persisted and "stdout" not in persisted
    for instance, value in (("wrong-instance", receipt), ("instance-1", receipt)):
        with pytest.raises(store_module.TaskConflict):
            store.record_execution_receipt(running.task_id, instance, value)
    store.transition(running.task_id, "running", "stopping", {})
    with pytest.raises(store_module.TaskConflict):
        store.record_execution_receipt(running.task_id, "instance-1", replace(receipt, command_request_id="other_request_123456"))


def test_attempt_and_global_sequence_reject_replays_and_wrong_identity(tmp_path: Path) -> None:
    models, store_module = _task_api()
    store = store_module.TaskStore(tmp_path)
    running = _running(store, _spec(models))
    event = models.PublicTaskEvent(running.task_id, 1, running.sequence + 1, "2026-09-28T00:00:01Z", "stage", {"name": "planner"})
    stored = store.record_event(running.task_id, 1, event)
    assert stored.sequence == running.sequence + 1

    for rejected in (
        event,
        replace(event, sequence=stored.sequence + 2),
        replace(event, task_id="other-task", sequence=stored.sequence + 1),
    ):
        with pytest.raises(store_module.TaskConflict):
            store.record_event(running.task_id, 1, rejected)

    verifying = store.transition(running.task_id, "running", "verifying", {})
    retried = store.transition(verifying.task_id, "verifying", "running", {"attempt_id": 2})
    assert retried.attempt_id == 2
    with pytest.raises(store_module.TaskConflict):
        store.record_event(
            retried.task_id,
            1,
            models.PublicTaskEvent(retried.task_id, 1, retried.sequence + 1, "2026-09-28T00:00:02Z", "stage", {}),
        )


def test_cleanup_failure_stays_active_through_restart_until_reconciled(tmp_path: Path) -> None:
    models, store_module = _task_api()
    store = store_module.TaskStore(tmp_path)
    running = _running(store, _spec(models))
    store.transition(running.task_id, "running", "stopping", {})
    store.transition(running.task_id, "stopping", "cleanup_failed", {"failure_kind": "cleanup_failed"})

    reopened = store_module.TaskStore(tmp_path)
    assert reopened.get(running.task_id).state == "cleanup_failed"
    assert reopened.has_active_task()
    with pytest.raises(store_module.TaskConflict):
        reopened.transition(running.task_id, "cleanup_failed", "failed", {})

    final = reopened.transition(running.task_id, "cleanup_failed", "failed", {"cleanup_confirmed": True})
    assert final.failure_kind == "cleanup_failed"
    assert not reopened.has_active_task()


def test_reopening_waiting_task_does_not_replay_or_finish_it(tmp_path: Path) -> None:
    models, store_module = _task_api()
    store = store_module.TaskStore(tmp_path)
    running = _running(store, _spec(models))
    store.transition(running.task_id, "running", "awaiting_approval", {})

    reopened = store_module.TaskStore(tmp_path)
    record = reopened.get(running.task_id)
    assert record.state == "awaiting_approval"
    assert record.attempt_id == 1
    assert record.instance_id == "instance-1"
    assert record.worker_pid == 123
    assert not record.cleanup_confirmed
    assert reopened.has_active_task()


def test_two_concurrent_run_transitions_have_one_winner(tmp_path: Path) -> None:
    models, store_module = _task_api()
    store = store_module.TaskStore(tmp_path)
    created = store.create(_spec(models), "key-1")
    store.transition(created.task_id, "draft", "preparing", {})
    store.transition(created.task_id, "preparing", "prepared", {})

    def start(_: int) -> bool:
        try:
            store.transition(created.task_id, "prepared", "running", {"attempt_id": 1, "instance_id": "instance-1"})
            return True
        except store_module.TaskConflict:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(start, range(2))) == [False, True]
    assert store.get(created.task_id).state == "running"
