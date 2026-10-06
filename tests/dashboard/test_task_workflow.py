"""Worker-side projection uses fake streams and never passes raw graph data."""

from __future__ import annotations

from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
import json
import socket
import threading
import time

import pytest

from mokioclaw.core.agent import TaskRunContext
from mokioclaw.dashboard.task_worker import run_projected_workflow
from mokioclaw.dashboard import task_worker
from mokioclaw.dashboard.task_models import TaskSpec
from mokioclaw.dashboard.task_service import TaskService
from mokioclaw.dashboard.task_store import TaskConflict
from mokioclaw.dashboard.task_store import TaskStore
from mokioclaw.dashboard.task_executor import TaskExecutionError
from mokioclaw.dashboard.task_worker_control import ProcessIdentity, TaskWorkerController
from mokioclaw.providers.openai_provider import ProviderSettings
from mokioclaw.dashboard.catalog import RepositoryCatalog
from mokioclaw.dashboard.git_reader import LocalGitReader
from mokioclaw.providers.openai_provider import TaskProviderError


class FakeContext:
    current_attempt = 1


def test_worker_emits_one_complete_usage_snapshot_before_completion(tmp_path: Path) -> None:
    class Model:
        def bind_tools(self, _tools):
            return self

        def invoke(self, _messages):
            return SimpleNamespace(usage_metadata={"total_tokens": 5})

    context = TaskRunContext.for_fake_model(Model(), max_provider_calls=3,
                                             max_total_tokens=30, max_output_tokens_per_call=10)
    sent = []

    def fake_stream(_description, **_kwargs):
        context.model(stage="entry").invoke([])
        context.model(stage="code_agent").bind_tools([]).invoke([])
        yield {"type": "graph_event", "event": {"final": {"response": "FAKE_PRIVATE_RESPONSE"}}}

    run_projected_workflow("repair", tmp_path, context, sent.append, stream=fake_stream)
    assert sent == [{
        "attempt_id": 1, "kind": "budget_usage",
        "entry_calls": 1, "entry_reported_tokens": 5,
        "chat_calls": 0, "chat_reported_tokens": 0,
        "planner_calls": 0, "planner_reported_tokens": 0,
        "code_agent_calls": 1, "code_agent_reported_tokens": 5,
        "verifier_calls": 0, "verifier_reported_tokens": 0,
        "context_compressor_calls": 0, "context_compressor_reported_tokens": 0,
    }, {"attempt_id": 1, "kind": "stage", "phase": "complete"}]
    assert "FAKE_PRIVATE_RESPONSE" not in repr(sent)


def test_worker_emits_partial_usage_snapshot_before_budget_failure(tmp_path: Path) -> None:
    class Model:
        def invoke(self, _messages):
            return SimpleNamespace(usage_metadata={"total_tokens": 6})

    context = TaskRunContext.for_fake_model(Model(), max_provider_calls=3,
                                             max_total_tokens=10, max_output_tokens_per_call=10)
    sent = []

    def fake_stream(_description, **_kwargs):
        context.model(stage="entry").invoke([])
        context.current_attempt = 2
        context.model(stage="code_agent").invoke([])
        context.model(stage="code_agent").invoke([])
        yield {"type": "graph_event", "event": {"final": {"response": "wrong"}}}

    with pytest.raises(TaskProviderError, match="provider_budget_exhausted"):
        run_projected_workflow("repair", tmp_path, context, sent.append, stream=fake_stream)
    assert len(sent) == 1
    assert sent[0]["kind"] == "budget_usage" and sent[0]["attempt_id"] == 2
    assert sent[0]["entry_calls"] == 1 and sent[0]["entry_reported_tokens"] == 6
    assert sent[0]["code_agent_calls"] == 1 and sent[0]["code_agent_reported_tokens"] == 6
    assert sum(value for key, value in sent[0].items() if key.endswith("_calls")) == 2


@pytest.mark.parametrize("response,max_calls,failure,reported", [
    (SimpleNamespace(usage_metadata={"total_tokens": 3}), 1, "provider_budget_exhausted", 3),
    (RuntimeError("FAKE_PRIVATE_PROVIDER_DETAIL"), 3, "provider_failed", 0),
    (SimpleNamespace(usage_metadata=None), 3, "usage_unavailable", 0),
])
def test_worker_reports_usage_for_other_terminal_provider_paths(
    tmp_path: Path, response: object, max_calls: int, failure: str, reported: int,
) -> None:
    class Model:
        def invoke(self, _messages):
            if isinstance(response, Exception):
                raise response
            return response

    context = TaskRunContext.for_fake_model(Model(), max_provider_calls=max_calls,
                                             max_total_tokens=30, max_output_tokens_per_call=10)
    sent = []

    def fake_stream(_description, **_kwargs):
        context.model(stage="entry").invoke([])
        if failure != "usage_unavailable":
            context.model(stage="planner").invoke([])
        yield {"type": "graph_event", "event": {"final": {"response": "FAKE_PRIVATE_RESPONSE"}}}

    with pytest.raises(TaskProviderError, match=failure):
        run_projected_workflow("repair", tmp_path, context, sent.append, stream=fake_stream)
    assert len(sent) == 1 and sent[0]["kind"] == "budget_usage"
    assert sent[0]["entry_calls"] == 1 and sent[0]["entry_reported_tokens"] == reported
    assert sent[0]["planner_calls"] == 0 and sent[0]["planner_reported_tokens"] == 0
    assert "FAKE_PRIVATE" not in repr(sent)


def test_worker_projects_before_sending_any_event(tmp_path: Path) -> None:
    context = FakeContext()
    sent = []

    def fake_stream(_description, *, workspace, task_context):
        assert workspace == tmp_path and task_context is context
        yield {"type": "workspace", "path": "C:/SECRET/private"}
        yield {"type": "graph_event", "event": {"planner": {"prompt": "SECRET PROMPT"}}}
        yield {"type": "custom_event", "event": {"type": "tool_result", "node": "verifier",
               "name": "BashTool", "result": {"ok": True, "exit_code": 0,
               "command": "echo SECRET", "stdout": "SECRET OUTPUT", "duration_ms": 10}}}
        context.current_attempt = 2
        yield {"type": "graph_event", "event": {"final": {"response": "SECRET RESPONSE"}}}

    run_projected_workflow("repair", tmp_path, context, sent.append, stream=fake_stream)
    assert sent == [
        {"attempt_id": 1, "kind": "stage", "phase": "planner"},
        {"attempt_id": 1, "kind": "verification", "status": "passed", "exit_code": 0,
         "duration_ms": 10},
        {"attempt_id": 2, "kind": "stage", "phase": "complete"},
    ]
    assert "SECRET" not in repr(sent)


def test_worker_cannot_report_success_after_last_response_omits_usage(tmp_path: Path) -> None:
    context = FakeContext()
    context.usage_unavailable = True

    def fake_stream(*_args, **_kwargs):
        yield {"type": "graph_event", "event": {"final": {"final_answer": "claimed done"}}}

    sent = []
    with pytest.raises(TaskProviderError, match="usage_unavailable"):
        run_projected_workflow("repair", tmp_path, context, sent.append, stream=fake_stream)
    assert sent == []


def test_service_accepts_only_current_worker_and_current_attempt_summary(
    temp_git_repo: Path, tmp_path: Path,
) -> None:
    reader = LocalGitReader()
    catalog = RepositoryCatalog.from_paths([temp_git_repo], reader)
    service = TaskService(catalog, reader, tmp_path / "tasks")
    try:
        spec = TaskSpec(
            task_id="", repo_id="repo_12345678", base_sha="a" * 40, anchor_sha="b" * 40,
            description="repair", source_read_scope=("src/",), source_write_scope=("src/",),
            task_scratch_scope=".mokioclaw/task-scratch/", manifest_digest="c" * 64,
            max_seconds=1800, max_attempts=2, verification_commands=(), max_provider_calls=3,
            max_total_tokens=100, max_output_tokens_per_call=20, created_at="",
        )
        record = service.store.create(spec, "worker-event-test")
        task_id = record.task_id
        service.store.transition(task_id, "draft", "preparing", {})
        service.store.transition(task_id, "preparing", "prepared", {})
        service._specs[task_id] = replace(spec, task_id=task_id)
        (service.store.root / task_id / "workspace" / "work").mkdir(parents=True)
        payload = service.worker_start_payload(task_id)
        assert payload["description"] == "repair"
        assert payload["verification_commands"] == []
        assert "api_key" not in repr(payload).lower()
        service.store.transition(task_id, "prepared", "running", {"instance_id": "instance_123456789012"})
        event = service.publish_worker_event(task_id, "instance_123456789012", {
            "attempt_id": 1, "kind": "stage", "phase": "planner", "prompt": "FAKE_PRIVATE_PROMPT",
        })
        assert event.data == {"phase": "planner"}
        assert "FAKE_PRIVATE_PROMPT" not in repr(service.store.get(task_id))
        for instance, attempt in (("wrong_instance_123456", 1), ("instance_123456789012", 2)):
            with pytest.raises(TaskConflict):
                service.publish_worker_event(task_id, instance, {
                    "attempt_id": attempt, "kind": "stage", "phase": "planner",
                })
        service.store.transition(task_id, "running", "verifying", {})
        next_record = service.advance_worker_attempt(task_id, "instance_123456789012", 1)
        assert next_record.state == "running" and next_record.attempt_id == 2
        with pytest.raises(TaskConflict):
            service.publish_worker_event(task_id, "instance_123456789012", {
                "attempt_id": 1, "kind": "stage", "phase": "planner",
            })
        assert service.publish_worker_event(task_id, "instance_123456789012", {
            "attempt_id": 2, "kind": "stage", "phase": "planner",
        }).attempt_id == 2
    finally:
        service.close()


def test_worker_loopback_sends_only_projected_fake_events(tmp_path: Path) -> None:
    token = "test-token-123456789012345678901234567890"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(3)

        def fake_run(start, emit, gateway):
            assert start["task_id"] == "task_1234567890123456"
            assert gateway.channel.gettimeout() is None
            emit({"attempt_id": 1, "kind": "stage", "phase": "planner", "prompt": "FAKE_PRIVATE_PROMPT"})

        worker = threading.Thread(target=task_worker._worker_main, args=(listener.getsockname()[1],),
                                  kwargs={"token_line": token, "run_task": fake_run}, daemon=True)
        worker.start()
        channel, _ = listener.accept()
        with channel:
            channel.settimeout(3)
            assert task_worker._receive(channel) == {"kind": "hello", "token": token}
            task_worker._send(channel, {"kind": "ready"})
            task_worker._send(channel, {"kind": "start", "task_id": "task_1234567890123456"})
            assert task_worker._receive(channel) == {"kind": "started"}
            event = task_worker._receive(channel)
            done = task_worker._receive(channel)
            assert event == {"kind": "event", "summary": {"attempt_id": 1, "kind": "stage", "phase": "planner"}}
            assert done == {"kind": "done", "outcome": "completed"}
        worker.join(timeout=3)
        assert not worker.is_alive()


@pytest.mark.parametrize("failure,kind", [
    (TaskProviderError("usage_unavailable"), "usage_unavailable"),
    (TaskProviderError("provider_budget_exhausted"), "provider_budget_exhausted"),
    (TaskProviderError("provider_auth_failed"), "provider_auth_failed"),
    (TaskProviderError("provider_rate_limited"), "provider_rate_limited"),
    (TaskProviderError("provider_invalid_request"), "provider_invalid_request"),
    (TaskProviderError("provider_transport_failed"), "provider_transport_failed"),
    (TaskProviderError("provider_server_failed"), "provider_server_failed"),
    (TaskProviderError("FAKE_PRIVATE_PROVIDER_DETAIL"), "provider_failed"),
    (TaskExecutionError("verification_command_failed"), "verification_command_failed"),
    (TaskExecutionError("FAKE_PRIVATE_TOOL_DETAIL"), "task_tool_failed"),
])
def test_worker_reports_fixed_failure_kind_without_private_detail(failure, kind) -> None:
    token = "test-token-123456789012345678901234567890"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(3)

        def fake_run(_start, _emit, _gateway):
            raise failure

        worker = threading.Thread(target=task_worker._worker_main, args=(listener.getsockname()[1],),
                                  kwargs={"token_line": token, "run_task": fake_run}, daemon=True)
        worker.start()
        channel, _ = listener.accept()
        with channel:
            channel.settimeout(3)
            assert task_worker._receive(channel) == {"kind": "hello", "token": token}
            task_worker._send(channel, {"kind": "ready"})
            task_worker._send(channel, {"kind": "start", "task_id": "task_1234567890123456"})
            assert task_worker._receive(channel) == {"kind": "started"}
            message = task_worker._receive(channel)
            assert message == {"kind": "done", "outcome": "failed", "failure_kind": kind}
            assert "FAKE_PRIVATE" not in repr(message)
        worker.join(timeout=3)


def test_parent_consumes_only_valid_worker_event_and_done_messages() -> None:
    received = []
    done = []
    left, right = socket.socketpair()
    try:
        task_worker._send(right, {"kind": "event", "summary": {
            "attempt_id": 1, "kind": "stage", "phase": "planner",
        }})
        task_worker._send(right, {"kind": "done", "outcome": "completed"})
        task_worker.consume_worker_messages(left, "task_1234567890123456", received.append, done.append)
        assert received == [{"attempt_id": 1, "kind": "stage", "phase": "planner"}]
        assert done == [{"outcome": "completed"}]
    finally:
        left.close()
        right.close()


@pytest.mark.parametrize("calls", [20, 21, 24])
def test_parent_accepts_only_projected_budget_usage_from_worker(calls: int) -> None:
    usage = {f"{stage}_{metric}": 0 for stage in (
        "entry", "chat", "planner", "code_agent", "verifier", "context_compressor",
    ) for metric in ("calls", "reported_tokens")}
    usage["entry_calls"] = 1
    usage["entry_reported_tokens"] = 5
    usage["code_agent_calls"] = calls - 1
    usage["code_agent_reported_tokens"] = calls - 1
    left, right = socket.socketpair()
    try:
        task_worker._send(right, {"kind": "event", "summary": {
            "attempt_id": 1, "kind": "budget_usage", **usage,
            "response": "FAKE_PRIVATE_RESPONSE",
        }})
        task_worker._send(right, {"kind": "done", "outcome": "completed"})
        received = []
        task_worker.consume_worker_messages(left, "task_1234567890123456", received.append,
                                            lambda _done: None)
        assert received == [{"attempt_id": 1, "kind": "budget_usage", **usage}]
        assert "FAKE_PRIVATE_RESPONSE" not in repr(received)
    finally:
        left.close()
        right.close()


@pytest.mark.parametrize("kind", [
    "provider_budget_exhausted", "provider_auth_failed", "provider_rate_limited",
    "provider_invalid_request", "provider_transport_failed", "provider_server_failed",
])
def test_parent_accepts_only_fixed_provider_failure_kinds(kind) -> None:
    left, right = socket.socketpair()
    try:
        task_worker._send(right, {"kind": "done", "outcome": "failed", "failure_kind": kind})
        finished = []
        task_worker.consume_worker_messages(left, "task_1234567890123456", lambda _event: None,
                                            finished.append)
        assert finished == [{"outcome": "failed", "failure_kind": kind}]
    finally:
        left.close()
        right.close()


def test_maximum_bounded_command_output_fits_worker_channel() -> None:
    class Sink:
        data = b""

        def sendall(self, payload):
            self.data = payload

    result = {"kind": "command_result", "result": {
        "ok": True, "exit_code": 0, "stdout": "\u0001" * 12000,
        "stderr": "\u0002" * 12000,
    }}
    sink = Sink()
    task_worker._send(sink, result)
    assert json.loads(sink.data) == result


def test_launcher_follows_only_its_recorded_worker_channel(monkeypatch) -> None:
    launcher = task_worker.TaskWorkerLauncher()
    left, right = socket.socketpair()
    try:
        identity = task_worker.ProcessIdentity(1234, "birth-one")
        launcher._workers[1234] = (None, left, "birth-one", "task_1234567890123456")
        monkeypatch.setattr(task_worker, "_creation_identity", lambda _pid: "birth-one")
        task_worker._send(right, {"kind": "done", "outcome": "completed"})
        finished = []
        launcher.follow(identity, lambda _event: None, finished.append)
        assert finished == [{"outcome": "completed"}]
        with pytest.raises(ValueError, match="Worker identity changed"):
            launcher.follow(task_worker.ProcessIdentity(1234, "other-birth"),
                            lambda _event: None, finished.append)
    finally:
        left.close()
        right.close()


def test_worker_command_and_attempt_requests_round_trip_to_parent_fake_gateway(tmp_path: Path) -> None:
    left, right = socket.socketpair()
    left.settimeout(3)
    right.settimeout(3)
    requests = []
    advanced = []
    worker_result = []
    task_id = "task_1234567890123456"

    def worker_side():
        gateway = task_worker.RemoteTaskGateway(right, task_id, tmp_path)
        worker_result.append(gateway.run(workspace=tmp_path, command="echo fake", timeout_seconds=5,
                                         max_output_chars=100))
        gateway.set_attempt(2)
        task_worker._send(right, {"kind": "done", "outcome": "completed"})

    thread = threading.Thread(target=worker_side, daemon=True)
    try:
        thread.start()
        done = []
        task_worker.consume_worker_messages(
            left, task_id, lambda _event: None, done.append,
            on_command=lambda request: (requests.append(request) or {
                "ok": True, "exit_code": 0, "stdout": "fake", "stderr": "", "command_request_id": "req-one",
            }),
            on_attempt=lambda previous, next_attempt: advanced.append((previous, next_attempt)),
        )
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert requests[0]["command"] == "echo fake" and requests[0]["attempt_id"] == 1
        assert advanced == [(1, 2)]
        assert worker_result[0]["exit_code"] == 0
        assert done == [{"outcome": "completed"}]
    finally:
        left.close()
        right.close()


def test_service_follows_fake_worker_through_attempt_and_cleanup(temp_git_repo: Path, tmp_path: Path) -> None:
    reader = LocalGitReader()
    catalog = RepositoryCatalog.from_paths([temp_git_repo], reader)

    class FakeLauncher:
        def launch(self, _task_id, _work):
            return ProcessIdentity(4321, "birth-4321")

        def activate(self, _identity):
            pass

        def exited(self, _identity):
            return True

        def stop(self, _identity):
            return True

        def follow(self, _identity, on_event, on_done, *, on_command, on_attempt):
            on_event({"attempt_id": 1, "kind": "stage", "phase": "planner"})
            on_event({"attempt_id": 1, "kind": "stage", "phase": "verifier"})
            assert on_command({"attempt_id": 1, "command": "echo fake", "timeout_seconds": 5,
                               "max_output_chars": 100})["ok"]
            on_attempt(1, 2)
            on_event({"attempt_id": 2, "kind": "stage", "phase": "planner"})
            on_done({"outcome": "completed"})

    class FakeContainers:
        def cleanup_owned(self, _instance_id, _task_id):
            return True

    launcher = FakeLauncher()

    def control_factory(store: TaskStore):
        return TaskWorkerController(store=store, instance_id="instance_123456789012",
                                    launcher=launcher, containers=FakeContainers())

    service = TaskService(catalog, reader, tmp_path / "tasks", worker_controller_factory=control_factory)
    try:
        spec = TaskSpec(
            task_id="", repo_id="repo_12345678", base_sha="a" * 40, anchor_sha="b" * 40,
            description="repair", source_read_scope=("src/",), source_write_scope=("src/",),
            task_scratch_scope=".mokioclaw/task-scratch/", manifest_digest="c" * 64,
            max_seconds=1800, max_attempts=2, verification_commands=(), max_provider_calls=3,
            max_total_tokens=100, max_output_tokens_per_call=20, created_at="",
        )
        record = service.store.create(spec, "worker-follow-test")
        task_id = record.task_id
        service._specs[task_id] = replace(spec, task_id=task_id)
        service.store.transition(task_id, "draft", "preparing", {})
        service.store.transition(task_id, "preparing", "prepared", {})
        (service.store.root / task_id / "workspace" / "work").mkdir(parents=True)
        service.worker_controller.start(task_id)

        class FakeGateway:
            def __init__(self):
                self.advanced = []

            def run(self, **kwargs):
                assert kwargs["command"] == "echo fake"
                return {"ok": True, "exit_code": 0}

            def set_attempt(self, value):
                self.advanced.append(value)

        gateway = FakeGateway()
        service.follow_worker(task_id, gateway)
        final = service.store.get(task_id)
        assert final.state == "completed" and final.cleanup_confirmed
        assert final.attempt_id == 2 and gateway.advanced == [2]
        assert [event.sequence for event in final.events] == list(range(1, final.sequence + 1))
    finally:
        service.close()


def test_service_deadline_stops_fake_worker_before_timed_out_state(temp_git_repo: Path, tmp_path: Path) -> None:
    reader = LocalGitReader()
    catalog = RepositoryCatalog.from_paths([temp_git_repo], reader)
    stopped = threading.Event()

    class FakeLauncher:
        def launch(self, _task_id, _work):
            return ProcessIdentity(4322, "birth-4322")

        def activate(self, _identity):
            pass

        def exited(self, _identity):
            return stopped.is_set()

        def stop(self, _identity):
            stopped.set()
            return True

        def follow(self, _identity, _on_event, _on_done, *, on_command, on_attempt):
            assert stopped.wait(3)

    class FakeContainers:
        def cleanup_owned(self, _instance_id, _task_id):
            assert stopped.is_set()
            return True

    def control_factory(store: TaskStore):
        return TaskWorkerController(store=store, instance_id="instance_123456789012",
                                    launcher=FakeLauncher(), containers=FakeContainers())

    service = TaskService(catalog, reader, tmp_path / "tasks", worker_controller_factory=control_factory)
    try:
        spec = TaskSpec(
            task_id="", repo_id="repo_12345678", base_sha="a" * 40, anchor_sha="b" * 40,
            description="repair", source_read_scope=("src/",), source_write_scope=("src/",),
            task_scratch_scope=".mokioclaw/task-scratch/", manifest_digest="c" * 64,
            max_seconds=1, max_attempts=1, verification_commands=(), max_provider_calls=1,
            max_total_tokens=100, max_output_tokens_per_call=20, created_at="",
        )
        task_id = service.store.create(spec, "worker-timeout-test").task_id
        service._specs[task_id] = replace(spec, task_id=task_id)
        service.store.transition(task_id, "draft", "preparing", {})
        service.store.transition(task_id, "preparing", "prepared", {})
        (service.store.root / task_id / "workspace" / "work").mkdir(parents=True)
        service.worker_controller.start(task_id)
        result = service.follow_worker(task_id, gateway=object())
        assert result.state == "timed_out" and result.cleanup_confirmed
        assert result.failure_kind == "timed_out" and stopped.is_set()
    finally:
        service.close()


def test_internal_start_connects_fixed_worker_gateway_and_follow_without_provider(
    temp_git_repo: Path, tmp_path: Path, monkeypatch,
) -> None:
    from mokioclaw.dashboard import task_service

    reader = LocalGitReader()
    catalog = RepositoryCatalog.from_paths([temp_git_repo], reader)
    captured = {}

    class FakeLauncher:
        def launch(self, task_id, work):
            captured["launched"] = (task_id, work)
            return ProcessIdentity(4333, "birth-4333")

        def activate(self, _identity):
            captured["activated"] = True

        def exited(self, _identity):
            return True

        def stop(self, _identity):
            return True

        def follow(self, _identity, _on_event, on_done, *, on_command, on_attempt):
            captured["followed"] = True
            on_done({"outcome": "completed"})

    class FakeContainers:
        def cleanup_owned(self, _instance_id, _task_id):
            return True

    class FakeExecutor:
        def __init__(self, **kwargs):
            captured["executor"] = kwargs

    class FakeGateway:
        def __init__(self, **kwargs):
            captured["gateway"] = kwargs

    class FakeBroker:
        def invalidate_attempt(self, _task_id, _attempt_id):
            pass

    monkeypatch.setattr(task_service, "IsolatedCommandExecutor", FakeExecutor, raising=False)
    monkeypatch.setattr(task_service, "TaskCommandGateway", FakeGateway, raising=False)

    def control_factory(store: TaskStore):
        return TaskWorkerController(store=store, instance_id="instance_123456789012",
                                    launcher=FakeLauncher(), containers=FakeContainers(), broker=FakeBroker())

    service = TaskService(catalog, reader, tmp_path / "tasks", worker_controller_factory=control_factory)
    try:
        spec = TaskSpec(
            task_id="", repo_id="repo_12345678", base_sha="a" * 40, anchor_sha="b" * 40,
            description="repair", source_read_scope=("src/",), source_write_scope=("src/",),
            task_scratch_scope=".mokioclaw/task-scratch/", manifest_digest="c" * 64,
            max_seconds=30, max_attempts=1, verification_commands=(), max_provider_calls=1,
            max_total_tokens=100, max_output_tokens_per_call=20, created_at="",
        )
        task_id = service.store.create(spec, "start-bridge").task_id
        service.store.transition(task_id, "draft", "preparing", {})
        service.store.transition(task_id, "preparing", "prepared", {})
        work = service.store.root / task_id / "workspace" / "work"
        work.mkdir(parents=True)
        service.task_image_digest = "sha256:" + "a" * 64
        monkeypatch.setattr(service, "run_available", lambda: True)
        started = service.start_agent(task_id)
        assert started.state == "running" and captured["activated"]
        deadline = time.monotonic() + 2
        while service.get(task_id).state not in {"completed", "failed", "cleanup_failed"} and time.monotonic() < deadline:
            time.sleep(0.01)
        assert service.get(task_id).state == "completed" and captured["followed"]
        assert captured["launched"] == (task_id, work)
        assert captured["executor"]["image_digest"] == service.task_image_digest
        assert captured["gateway"]["workspace"] == work
    finally:
        service.close()


def test_worker_builds_task_context_from_explicit_payload_without_provider_call(
    tmp_path: Path, monkeypatch,
) -> None:
    work = tmp_path / "task_1234567890123456" / "workspace" / "work"
    (work / "src").mkdir(parents=True)
    monkeypatch.setenv("MOKIO_TASK_API_KEY", "FAKE_TASK_KEY")
    monkeypatch.setenv("MOKIO_TASK_MODEL", "fake-model")
    monkeypatch.setenv("MOKIO_TASK_BASE_URL", "https://task.invalid/v1")
    captured = {}

    class FakeContext:
        current_attempt = 1
        usage_unavailable = False

        def attach_tools(self, filesystem, tools, *, services, gateway, verification_commands):
            assert services.filesystem is filesystem
            captured["filesystem"] = filesystem
            captured["tools"] = {tool.name for tool in tools}
            captured["commands"] = verification_commands
            captured["gateway"] = gateway

    fake_context = FakeContext()

    def fake_context_factory(settings, **budgets):
        captured["model"] = settings.model
        captured["budgets"] = budgets
        return fake_context

    def fake_stream(description, *, workspace, task_context, max_attempts):
        assert description == "repair" and workspace == work and task_context is fake_context
        assert max_attempts == 2
        yield {"type": "graph_event", "event": {"final": {"response": "FAKE_PRIVATE"}}}

    start = {"kind": "start", "task_id": "task_1234567890123456", "payload": {
        "description": "repair", "source_read_scope": ["src/"], "source_write_scope": ["src/"],
        "task_scratch_scope": ".mokioclaw/task-scratch/", "max_attempts": 2,
        "max_provider_calls": 3, "max_total_tokens": 100,
        "max_output_tokens_per_call": 20, "verification_commands": ["python -m pytest -q"],
    }}
    sent = []
    gateway = type("FakeGateway", (), {"task_gateway": True})()
    task_worker._run_real_task(start, sent.append, gateway, workspace=work,
                               context_factory=fake_context_factory, stream=fake_stream)
    assert captured["model"] == "fake-model"
    assert captured["budgets"] == {"max_provider_calls": 3, "max_total_tokens": 100,
                                    "max_output_tokens_per_call": 20}
    assert captured["commands"] == ("python -m pytest -q",)
    assert captured["gateway"] is gateway
    assert "BashTool" in captured["tools"] and "FileReadTool" in captured["tools"]
    assert sent == [{"attempt_id": 1, "kind": "stage", "phase": "complete"}]


@pytest.mark.parametrize("max_calls,max_tokens", [
    (20, 150_000), (22, 150_000), (24, 200_000),
    (24, 200_001), (24, 250_000), (24, 300_000),
])
def test_worker_starts_with_amended_budgets_using_real_task_context(
    tmp_path: Path, monkeypatch, max_calls: int, max_tokens: int,
) -> None:
    from mokioclaw.providers import openai_provider

    work = tmp_path / "task_1234567890123456" / "workspace" / "work"
    (work / "src").mkdir(parents=True)
    monkeypatch.setenv("MOKIO_TASK_API_KEY", "FAKE_TASK_KEY")
    monkeypatch.setenv("MOKIO_TASK_MODEL", "fake-model")
    monkeypatch.setenv("MOKIO_TASK_BASE_URL", "https://task.invalid/v1")
    monkeypatch.setattr(openai_provider, "ChatOpenAI", lambda **_kwargs: pytest.fail("provider initialized"))

    def fake_stream(description, *, workspace, task_context, max_attempts):
        assert description == "repair" and workspace == work and max_attempts == 1
        assert isinstance(task_context, TaskRunContext)
        assert task_context.max_provider_calls == max_calls
        assert task_context.max_total_tokens == max_tokens
        assert task_context.fixed_verification_commands == ("python -m pytest -q",)
        yield {"type": "graph_event", "event": {"final": {"response": "FAKE_PRIVATE"}}}

    start = {"kind": "start", "task_id": "task_1234567890123456", "payload": {
        "description": "repair", "source_read_scope": ["src/"], "source_write_scope": ["src/"],
        "task_scratch_scope": ".mokioclaw/task-scratch/", "max_attempts": 1,
        "max_provider_calls": max_calls, "max_total_tokens": max_tokens,
        "max_output_tokens_per_call": 3072, "verification_commands": ["python -m pytest -q"],
    }}
    sent = []
    gateway = type("FakeGateway", (), {"task_gateway": True})()
    task_worker._run_real_task(start, sent.append, gateway, workspace=work, stream=fake_stream)

    assert [event["kind"] for event in sent] == ["budget_usage", "stage"]
    usage = sent[0]
    assert usage["entry_calls"] == 0 and usage["entry_reported_tokens"] == 0
    assert sent[1] == {"attempt_id": 1, "kind": "stage", "phase": "complete"}
    assert "FAKE_PRIVATE" not in repr(sent)


@pytest.mark.parametrize("max_calls,max_tokens", [(0, 150_000), (20, 0), (25, 150_000), (24, 300_001)])
def test_task_context_rejects_budgets_outside_amended_limits(max_calls: int, max_tokens: int) -> None:
    with pytest.raises(TaskProviderError, match="^invalid_provider_budget$"):
        TaskRunContext.from_settings(
            ProviderSettings("FAKE_TASK_KEY", "fake-model", "https://task.invalid/v1"),
            max_provider_calls=max_calls, max_total_tokens=max_tokens, max_output_tokens_per_call=3072,
        )


def test_configuring_agent_capability_constructs_no_provider_or_container(
    temp_git_repo: Path, tmp_path: Path, monkeypatch,
) -> None:
    from mokioclaw.dashboard import task_executor
    from mokioclaw.providers import openai_provider

    monkeypatch.setattr(openai_provider, "ChatOpenAI", lambda **_kwargs: pytest.fail("provider initialized"))
    monkeypatch.setattr(task_executor.DockerCLI, "run", lambda *_args, **_kwargs:
                        pytest.fail("Docker contacted"))
    reader = LocalGitReader()
    catalog = RepositoryCatalog.from_paths([temp_git_repo], reader)
    service = TaskService(catalog, reader, tmp_path / "tasks")
    try:
        settings = ProviderSettings("FAKE_TASK_KEY", "fake-model", "https://task.invalid/v1")
        service.configure_agent(settings, "sha256:" + "a" * 64)
        assert service.worker_controller is not None
        assert service.task_image_digest == "sha256:" + "a" * 64
    finally:
        service.close()


def test_live_approval_is_bound_to_current_attempt_and_restores_state(
    temp_git_repo: Path, tmp_path: Path,
) -> None:
    from mokioclaw.dashboard.task_approval import ExecutionRequest

    reader = LocalGitReader()
    catalog = RepositoryCatalog.from_paths([temp_git_repo], reader)
    service = TaskService(catalog, reader, tmp_path / "tasks")
    try:
        service.configure_agent(ProviderSettings("FAKE", "fake-model", "https://task.invalid/v1"),
                                "sha256:" + "a" * 64)
        spec = TaskSpec(
            task_id="", repo_id="repo_12345678", base_sha="a" * 40, anchor_sha="b" * 40,
            description="repair", source_read_scope=("src/",), source_write_scope=("src/",),
            task_scratch_scope=".mokioclaw/task-scratch/", manifest_digest="c" * 64,
            max_seconds=1800, max_attempts=2, verification_commands=(), max_provider_calls=3,
            max_total_tokens=100, max_output_tokens_per_call=20, created_at="",
        )
        task_id = service.store.create(spec, "live-approval-test").task_id
        service.store.transition(task_id, "draft", "preparing", {})
        service.store.transition(task_id, "preparing", "prepared", {})
        instance = service.worker_controller.instance_id
        service.store.transition(task_id, "prepared", "running", {"instance_id": instance})
        service.store.transition(task_id, "running", "verifying", {})
        private_work = service.store.root / task_id / "workspace" / "work"
        request = ExecutionRequest(
            task_id=task_id, attempt_id=1, command_request_id="request_12345678901234",
            command="echo fake", cwd="/workspace", timeout_seconds=5,
            image_digest="sha256:" + "a" * 64, mount_source=str(private_work),
            mount_target="/workspace", network="none", env_allowlist=("PATH", "LANG"),
            cpu_limit=1.0, memory_bytes=512 * 1024 * 1024, pids_limit=64,
            max_output_chars=100, policy_version="task-command-v1",
        )
        broker = service.worker_controller.broker
        outcomes = []
        thread = threading.Thread(target=lambda: outcomes.append(broker.request(request)), daemon=True)
        thread.start()
        deadline = time.monotonic() + 2
        while service.store.get(task_id).state != "awaiting_approval" and time.monotonic() < deadline:
            time.sleep(0.005)
        assert service.store.get(task_id).state == "awaiting_approval"
        pending = service.pending_approvals(task_id)
        assert pending[0]["command"] == "echo fake"
        assert pending[0]["execution_digest"] == request.canonical_digest()
        assert str(private_work) not in repr(pending)
        assert not service.decide_approval(task_id, 2, request.command_request_id,
                                           request.canonical_digest(), True)
        assert service.decide_approval(task_id, 1, request.command_request_id,
                                       request.canonical_digest(), True)
        thread.join(timeout=2)
        assert not thread.is_alive() and outcomes[0].approved
        assert service.store.get(task_id).state == "verifying"
        assert not service.decide_approval(task_id, 1, request.command_request_id,
                                           request.canonical_digest(), True)
    finally:
        service.close()


@pytest.mark.parametrize("calls,finish,outcome,failure", [
    (20, "complete", "completed", None),
    (21, "complete", "completed", None),
    (24, "complete", "completed", None),
    (24, "budget", "failed", "provider_budget_exhausted"),
    (21, "tool", "failed", "task_tool_failed"),
    (21, "worker", "failed", "worker_failed"),
])
def test_worker_loopback_preserves_amended_usage_and_original_outcome(
    tmp_path: Path, monkeypatch, calls: int, finish: str, outcome: str, failure: str | None,
) -> None:
    from mokioclaw.providers import openai_provider

    monkeypatch.setattr(openai_provider, "ChatOpenAI", lambda **_kwargs: pytest.fail("provider initialized"))

    class Model:
        def invoke(self, _messages):
            return SimpleNamespace(usage_metadata={"total_tokens": 1})

    context = TaskRunContext.for_fake_model(
        Model(), max_provider_calls=24, max_total_tokens=200_000, max_output_tokens_per_call=3072,
    )

    def fake_stream(*_args, **_kwargs):
        context.model(stage="entry").invoke([])
        for _ in range(calls - 1):
            context.model(stage="code_agent").invoke([])
        if finish == "budget":
            context.model(stage="code_agent").invoke([])
        if finish == "tool":
            raise TaskExecutionError("FAKE_PRIVATE_TOOL_DETAIL")
        if finish == "worker":
            raise RuntimeError("FAKE_PRIVATE_WORKER_DETAIL")
        yield {"type": "graph_event", "event": {"final": {"response": "FAKE_PRIVATE_RESPONSE"}}}

    def fake_run(_start, emit, _gateway):
        run_projected_workflow("fake repair", tmp_path, context, emit, stream=fake_stream)

    task_id = "task_1234567890123456"
    token = "test-token-123456789012345678901234567890"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(3)
        worker = threading.Thread(target=task_worker._worker_main, args=(listener.getsockname()[1],),
                                  kwargs={"token_line": token, "run_task": fake_run}, daemon=True)
        worker.start()
        channel, _ = listener.accept()
        with channel:
            channel.settimeout(3)
            assert task_worker._receive(channel) == {"kind": "hello", "token": token}
            task_worker._send(channel, {"kind": "ready"})
            task_worker._send(channel, {"kind": "start", "task_id": task_id})
            assert task_worker._receive(channel) == {"kind": "started"}
            sent, done = [], []
            task_worker.consume_worker_messages(channel, task_id, sent.append, done.append)
        worker.join(timeout=3)
        assert not worker.is_alive()

    expected_done = {"outcome": outcome}
    if failure is not None:
        expected_done["failure_kind"] = failure
    assert done == [expected_done]
    assert [event["kind"] for event in sent] == (["budget_usage", "stage"] if outcome == "completed" else ["budget_usage"])
    assert sent[0]["entry_calls"] == 1 and sent[0]["entry_reported_tokens"] == 1
    assert sent[0]["code_agent_calls"] == calls - 1 and sent[0]["code_agent_reported_tokens"] == calls - 1
    assert "FAKE_PRIVATE" not in repr(sent) + repr(done)


def test_worker_gateway_rejects_invalid_command_arguments_before_sending(tmp_path: Path) -> None:
    left, right = socket.socketpair()
    right.settimeout(1)
    left.settimeout(1)
    task_id = "task_1234567890123456"
    gateway = task_worker.RemoteTaskGateway(right, task_id, tmp_path)
    try:
        for timeout, output in ((1200, 100), (0, 100), (5, 0), (5, 20000)):
            result = gateway.run(workspace=tmp_path, command="echo fake",
                                 timeout_seconds=timeout, max_output_chars=output)
            assert result == {"ok": False, "error": "invalid_task_command"}
        result = gateway.run(workspace=tmp_path, command="echo fake\0x",
                             timeout_seconds=5, max_output_chars=100)
        assert result == {"ok": False, "error": "invalid_task_command"}
        with pytest.raises(socket.timeout):
            left.recv(1)
    finally:
        left.close()
        right.close()
