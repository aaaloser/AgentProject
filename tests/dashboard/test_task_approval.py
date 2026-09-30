from __future__ import annotations

import importlib
import base64
import hashlib
import json
import threading
import time
from dataclasses import asdict, replace
from pathlib import Path

import pytest


TASK = "task_1234567890123456"
REQUEST = "request_12345678901234"


def _approval():
    return importlib.import_module("mokioclaw.dashboard.task_approval")


def _request(tmp_path: Path, **updates):
    module = _approval()
    data = dict(
        task_id=TASK, attempt_id=1, command_request_id=REQUEST, command="echo hello",
        cwd="/workspace", timeout_seconds=30, image_digest="sha256:" + "a" * 64,
        mount_source=str(tmp_path / "task" / "workspace" / "work"), mount_target="/workspace",
        network="none", env_allowlist=("PATH", "LANG"), cpu_limit=1.0, memory_bytes=512 * 1024 * 1024,
        pids_limit=64, max_output_chars=6000, policy_version="task-command-v1",
    )
    data.update(updates)
    return module.ExecutionRequest(**data)


@pytest.mark.parametrize("change", [
    {"task_id": "task_9999999999999999"}, {"attempt_id": 2}, {"command_request_id": "request_99999999999999"},
    {"command": "echo hello "}, {"cwd": "/workspace/sub"}, {"timeout_seconds": 31},
    {"image_digest": "sha256:" + "b" * 64}, {"mount_source": "C:/other/work"},
    {"mount_target": "/different"}, {"network": "bridge"}, {"env_allowlist": ("PATH",)},
    {"cpu_limit": 2.0}, {"memory_bytes": 1024 * 1024 * 1024}, {"pids_limit": 65},
    {"max_output_chars": 6001}, {"policy_version": "task-command-v2"},
])
def test_every_execution_parameter_changes_approval_identity(tmp_path: Path, change: dict) -> None:
    request = _request(tmp_path)
    changed = replace(request, **change)
    assert changed.canonical_digest() != request.canonical_digest()


def test_command_bytes_use_standard_base64_in_canonical_digest(tmp_path: Path) -> None:
    request = _request(tmp_path, command="echo 你好\n")
    payload = asdict(request)
    payload.pop("command")
    payload["command_utf8_base64"] = base64.b64encode("echo 你好\n".encode("utf-8")).decode("ascii")
    expected = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    assert request.canonical_digest() == expected


def test_approval_is_exact_once_and_timeout_is_final(tmp_path: Path) -> None:
    approval = _approval()
    broker = approval.ApprovalBroker(wait_timeout_seconds=0.3)
    request = _request(tmp_path)
    decisions = []
    thread = threading.Thread(target=lambda: decisions.append(broker.request(request)))
    thread.start()
    deadline = time.monotonic() + 2
    while not broker.pending(TASK) and time.monotonic() < deadline:
        time.sleep(0.005)
    assert broker.pending(TASK)[0].command_request_id == REQUEST
    assert not broker.decide(TASK, 2, REQUEST, request.canonical_digest(), approved=True)
    assert not broker.decide(TASK, 1, REQUEST, "wrong", approved=True)
    assert broker.decide(TASK, 1, REQUEST, request.canonical_digest(), approved=True)
    assert not broker.decide(TASK, 1, REQUEST, request.canonical_digest(), approved=True)
    thread.join(timeout=2)
    assert decisions[0].approved
    assert broker.consume(request)
    assert not broker.consume(request)
    with pytest.raises(approval.ApprovalRejected):
        broker.request(request)

    timed = _request(tmp_path, command_request_id="request_timeout_123456")
    assert not broker.request(timed, wait_timeout_seconds=0.01).approved
    assert not broker.decide(TASK, 1, timed.command_request_id, timed.canonical_digest(), approved=True)
    assert not broker.consume(timed)


def test_request_notification_precedes_wait_and_never_grants_approval(tmp_path: Path) -> None:
    approval = _approval()
    observed = []
    broker = approval.ApprovalBroker(
        wait_timeout_seconds=0.02, on_request=lambda request: observed.append(request),
    )
    request = _request(tmp_path)
    result = broker.request(request)
    assert observed == [request]
    assert not result.approved
    assert not broker.consume(request)


def test_attempt_invalidation_rejects_pending_and_unconsumed_approval(tmp_path: Path) -> None:
    approval = _approval()
    broker = approval.ApprovalBroker(wait_timeout_seconds=0.3)
    request = _request(tmp_path)
    results = []
    thread = threading.Thread(target=lambda: results.append(broker.request(request)))
    thread.start()
    deadline = time.monotonic() + 2
    while not broker.pending(TASK) and time.monotonic() < deadline:
        time.sleep(0.005)
    broker.invalidate_attempt(TASK, 1)
    thread.join(timeout=2)
    assert not results[0].approved
    assert not broker.decide(TASK, 1, REQUEST, request.canonical_digest(), approved=True)

    next_request = _request(tmp_path, command_request_id="request_next_12345678", attempt_id=2)
    next_results = []
    next_thread = threading.Thread(target=lambda: next_results.append(broker.request(next_request)))
    next_thread.start()
    while not broker.pending(TASK) and time.monotonic() < deadline + 2:
        time.sleep(0.005)
    assert broker.decide(TASK, 2, next_request.command_request_id, next_request.canonical_digest(), approved=True)
    next_thread.join(timeout=2)
    assert next_results[0].approved
    broker.invalidate_attempt(TASK, 2)
    assert not broker.consume(next_request)


def test_command_gateway_never_executes_denied_or_changed_request(tmp_path: Path) -> None:
    approval = _approval()
    execution = importlib.import_module("mokioclaw.dashboard.task_executor")
    calls = []

    class FakeExecutor:
        def execute(self, request):
            calls.append(request)
            return {"ok": True, "exit_code": 0}

    broker = approval.ApprovalBroker(wait_timeout_seconds=0.3)
    gateway = execution.TaskCommandGateway(
        task_id=TASK, attempt_id=1, workspace=tmp_path / "task" / "workspace" / "work",
        image_digest="sha256:" + "a" * 64, broker=broker, executor=FakeExecutor(),
    )
    result = gateway.run(workspace=gateway.workspace, command="unrecognized --opaque-command",
                         timeout_seconds=5, max_output_chars=200)
    assert not result["ok"] and calls == []

    outcomes = []
    thread = threading.Thread(target=lambda: outcomes.append(gateway.run(
        workspace=gateway.workspace, command="echo hello", timeout_seconds=5, max_output_chars=200,
    )))
    thread.start()
    deadline = time.monotonic() + 2
    while not broker.pending(TASK) and time.monotonic() < deadline:
        time.sleep(0.005)
    request = broker.pending(TASK)[0]
    assert not broker.decide(TASK, 1, request.command_request_id, replace(request, command="echo changed").canonical_digest(), True)
    assert broker.decide(TASK, 1, request.command_request_id, request.canonical_digest(), True)
    thread.join(timeout=2)
    assert outcomes[0]["ok"] and len(calls) == 1 and calls[0].command == "echo hello"


def test_gateway_records_only_the_consumed_approved_execution(tmp_path: Path) -> None:
    approval = _approval()
    execution = importlib.import_module("mokioclaw.dashboard.task_executor")
    seen = []

    class FakeExecutor:
        def execute(self, request):
            return {"ok": True, "exit_code": 0, "duration_ms": 17, "output_truncated": False}

    broker = approval.ApprovalBroker(wait_timeout_seconds=1)
    gateway = execution.TaskCommandGateway(
        task_id=TASK, attempt_id=1, workspace=tmp_path / "work",
        image_digest="sha256:" + "a" * 64, broker=broker, executor=FakeExecutor(),
        record_receipt=lambda request, result: seen.append((request, result)),
    )
    outcomes = []
    thread = threading.Thread(target=lambda: outcomes.append(gateway.run(
        workspace=gateway.workspace, command="echo hello", timeout_seconds=5, max_output_chars=200,
    )))
    thread.start()
    deadline = time.monotonic() + 2
    while not broker.pending(TASK) and time.monotonic() < deadline:
        time.sleep(0.005)
    request = broker.pending(TASK)[0]
    assert broker.decide(TASK, 1, request.command_request_id, request.canonical_digest(), True)
    thread.join(timeout=2)
    assert len(seen) == 1 and seen[0][0] == request
    assert seen[0][1] == {"ok": True, "exit_code": 0, "duration_ms": 17,
                           "output_truncated": False}
    assert outcomes[0]["command_request_id"] == request.command_request_id


def test_gateway_attempt_change_invalidates_pending_command(tmp_path: Path) -> None:
    approval = _approval()
    execution = importlib.import_module("mokioclaw.dashboard.task_executor")
    calls = []

    class FakeExecutor:
        def execute(self, request):
            calls.append(request)
            return {"ok": True}

    broker = approval.ApprovalBroker(wait_timeout_seconds=0.3)
    gateway = execution.TaskCommandGateway(
        task_id=TASK, attempt_id=1, workspace=tmp_path / "work",
        image_digest="sha256:" + "a" * 64, broker=broker, executor=FakeExecutor(),
    )
    result = []
    thread = threading.Thread(target=lambda: result.append(gateway.run(
        workspace=gateway.workspace, command="echo hello", timeout_seconds=5, max_output_chars=100,
    )))
    thread.start()
    deadline = time.monotonic() + 2
    while not broker.pending(TASK) and time.monotonic() < deadline:
        time.sleep(0.005)
    old = broker.pending(TASK)[0]
    gateway.set_attempt(2)
    assert not broker.decide(TASK, 1, old.command_request_id, old.canonical_digest(), True)
    thread.join(timeout=2)
    assert not result[0]["ok"] and calls == []


def test_gateway_rejects_secret_environment_and_hides_executor_error(tmp_path: Path) -> None:
    approval = _approval()
    execution = importlib.import_module("mokioclaw.dashboard.task_executor")
    broker = approval.ApprovalBroker(wait_timeout_seconds=0.3)

    class FailingExecutor:
        def execute(self, _request):
            raise RuntimeError("PRIVATE API KEY")

    with pytest.raises(ValueError):
        execution.TaskCommandGateway(
            task_id=TASK, attempt_id=1, workspace=tmp_path / "work",
            image_digest="sha256:" + "a" * 64, broker=broker, executor=FailingExecutor(),
            policy=execution.TaskCommandPolicy(image_digest="sha256:" + "a" * 64, env_allowlist=("API_KEY",)),
        )
    gateway = execution.TaskCommandGateway(
        task_id=TASK, attempt_id=1, workspace=tmp_path / "work",
        image_digest="sha256:" + "a" * 64, broker=broker, executor=FailingExecutor(),
    )
    result = []
    thread = threading.Thread(target=lambda: result.append(gateway.run(
        workspace=gateway.workspace, command="echo hello", timeout_seconds=5, max_output_chars=100,
    )))
    thread.start()
    deadline = time.monotonic() + 2
    while not broker.pending(TASK) and time.monotonic() < deadline:
        time.sleep(0.005)
    request = broker.pending(TASK)[0]
    assert broker.decide(TASK, 1, request.command_request_id, request.canonical_digest(), True)
    thread.join(timeout=2)
    assert not result[0]["ok"] and "PRIVATE" not in repr(result[0])
