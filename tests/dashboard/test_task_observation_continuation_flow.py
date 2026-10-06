"""Real start/controller/graph/approval/journal, synthetic external boundaries."""

from dataclasses import asdict
import hashlib
import json
import os
from types import SimpleNamespace

import pytest

from task_continuation_fakes import SOURCE, TASK, UTC, NAMES, SyntheticTask, offline_continuation_guard
from task_observation_fakes import utc_clock


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    with offline_continuation_guard(monkeypatch):
        yield


def setup_flow(tmp_path, monkeypatch):
    from mokioclaw.dashboard.task_observation_continuation import ContinuationOptions
    from mokioclaw.dashboard.task_service import TaskService
    from mokioclaw.dashboard.task_worker_control import TaskWorkerController, ProcessIdentity
    from mokioclaw.dashboard.task_approval import ApprovalBroker
    from mokioclaw.dashboard.task_diagnostic_ipc import WorkerDiagnosticClient, decode_frame
    from mokioclaw.core.agent import TaskRunContext
    from mokioclaw.core.task_observation import TaskObservation
    from mokioclaw.dashboard.task_filesystem import TaskFilesystem
    from mokioclaw.dashboard.task_context import TaskToolServices, TaskContextPolicy
    from mokioclaw.dashboard.task_graph import build_task_graph_tools
    from test_task_context_flow import GraphScript
    original_fsync = os.fsync
    case = SyntheticTask(root=tmp_path / "calibration", relative="src/a.py", content=b"SOURCE_SENTINEL\n" + b"x" * 12000,
                         command="python -m pytest -q")
    case.install(monkeypatch)
    # Original TaskFilesystem/TaskStore durability is exercised only in this
    # synthetic pytest root; continuation handles themselves are memory fakes.
    monkeypatch.setattr(os, "fsync", lambda fd: case.backend.event("fsync") if fd == -12345 else original_fsync(fd))
    for path, (directory, content, _) in case.backend.nodes.items():
        if path == case.root or case.root in path.parents:
            if directory:
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
    service = TaskService(case.catalog, case.git, case.task_root,
                          continuation_options=ContinuationOptions(TASK, case.spec_sha, SOURCE), calibration_root=case.root)
    manager = service.configure_calibration(case.root)
    assert service.receive_calibration_viewer(manager, {"schema_version": 1, "kind": "hello", "sequence": 1})["accepted"]
    assert not manager.ready_for_start(TASK)
    assert service.receive_calibration_viewer(manager, {"schema_version": 1, "kind": "bind", "sequence": 2, "task_id": TASK})["accepted"]
    decisions, launch_calls, clients, gateways = [], [], [], []
    def approve(request):
        assert request.task_id == TASK and request.attempt_id == 1 and request.command == case.spec.verification_commands[0]
        assert request.network == "none"
        decisions.append((request.command_request_id, request.canonical_digest()))
        assert broker.decide(TASK, 1, request.command_request_id, request.canonical_digest(), True)
    broker = ApprovalBroker(wait_timeout_seconds=1, on_request=approve)
    class Channel:
        def send_bytes(self, data):
            frame = decode_frame(data, role="worker")
            self.accepted = manager.receive_worker(frame)
            self.sequence = frame["sequence"]
        def poll(self, timeout):
            return self.accepted
        def recv_bytes(self, maxlength):
            return json.dumps({"schema_version": 1, "kind": "ack", "sequence": self.sequence}).encode()
        def close(self):
            pass
    class Launcher:
        def launch(self, task, work):
            assert task == TASK and work == case.task_dir / "workspace/work"
            short = [h for h in case.backend.handles if h.identity.final_path.name == "record.json"
                     or case.task_dir / "workspace" in h.identity.final_path.parents]
            assert short and all(h.closed for h in short)
            assert not service._continuation.spec_handle.closed and not service.lease.closed
            launch_calls.append("launch")
            return ProcessIdentity(12345, UTC)
        def activate(self, identity):
            bootstrap = manager.worker_bootstrap(TASK)
            clients.append(WorkerDiagnosticClient(bootstrap, connect=lambda _: Channel()))
        def exited(self, identity):
            return True
        def stop(self, identity):
            return True
    controller = TaskWorkerController(store=service.store, instance_id="synthetic_instance_001", launcher=Launcher(),
                                      containers=SimpleNamespace(cleanup_owned=lambda *args: True), broker=broker)
    service.worker_controller = controller
    service.task_image_digest = "sha256:" + "a" * 64
    service.task_model_name = "synthetic"
    images = []
    service.run_available = lambda: images.append("image") or True
    class Pool:
        def submit(self, function, task, gateway):
            assert task == TASK
            gateways.append(gateway)
        def shutdown(self, **kwargs):
            pass
    service.pool.shutdown(wait=True)
    service.pool = Pool()
    class Executor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
        def execute(self, request):
            assert decisions[-1] == (request.command_request_id, request.canonical_digest())
            self.kwargs["register_request"](request.command_request_id)
            with self.kwargs["creation_guard"](request):
                good = (case.task_dir / "workspace/work/src/a.py").read_bytes() == b"good\n"
                return {"ok": good, "exit_code": 0 if good else 1, "stdout": "COMMAND_SENTINEL", "stderr": "",
                        "duration_ms": 1, "output_truncated": False}
    monkeypatch.setattr("mokioclaw.dashboard.task_service.IsolatedCommandExecutor", Executor)
    old = {name: hashlib.sha256(case.backend.nodes[case.obs / name][1]).hexdigest() for name in NAMES}
    record = service.start_agent(TASK)
    assert record.execution_started and launch_calls == ["launch"] and images == ["image"]
    model = GraphScript()
    context = TaskRunContext.for_fake_model(model, max_provider_calls=20, max_total_tokens=150000,
        max_output_tokens_per_call=3072, observation=TaskObservation(TASK, clients[0], utc_clock=utc_clock))
    assert model.calls == 0 and context.provider_calls == 0 and manager.journal._records == []
    prepared = SimpleNamespace(task_id=TASK, work=case.task_dir / "workspace/work")
    filesystem = TaskFilesystem(prepared, case.spec.source_read_scope, case.spec.source_write_scope, case.spec.task_scratch_scope)
    services = TaskToolServices(filesystem, TaskContextPolicy())
    tools = build_task_graph_tools(filesystem, gateways[0], prepared.work, services=services)
    context.attach_tools(filesystem, tools, services=services, verification_commands=case.spec.verification_commands)
    context.task_gateway = gateways[0]
    return case, service, manager, clients[0], context, model, decisions, old


def test_continuation_fake_flow_reconciles_only_new_session(tmp_path, monkeypatch):
    from mokioclaw.dashboard.task_worker import run_projected_workflow
    case, service, manager, client, context, model, decisions, old = setup_flow(tmp_path, monkeypatch)
    events = []
    try:
        run_projected_workflow("PROMPT_SENTINEL", case.task_dir / "workspace/work", context, events.append,
                               max_attempts=1, handoff_observer=client.accept_handoff)
        client.finish(context.usage_snapshot())
        client.close()
        service.worker_controller.finish(TASK, "completed")
        receipts = service.store.get(TASK).execution_receipts
        assert [receipt.exit_code for receipt in receipts] == [1, 0, 0]
        assert len(decisions) == len({row[0] for row in decisions}) == len({row[1] for row in decisions}) == 3
        verification = next(event for event in events if event["kind"] == "verification")
        assert verification["request_id"] == receipts[-1].command_request_id
        assert all(receipt.command_sha256 == hashlib.sha256(case.spec.verification_commands[0].encode()).hexdigest() for receipt in receipts)
        assert model.calls == context.provider_calls == 12
        service.close()
        session_root = manager.session.directory.identity.final_path
        status = json.loads(case.backend.nodes[session_root / "status.json"][1])
        calls = [json.loads(line) for line in case.backend.nodes[session_root / "calls.jsonl"][1].splitlines()]
        assert status["valid"] is True and status["unknown_calls"] == 0 and status["started_calls"] == 12
        assert [row["event_sequence"] for row in calls] == list(range(1, len(calls) + 1))
        assert sum(row["total_tokens"] or 0 for row in calls if row["kind"] == "invoke_finished") == context.reported_tokens
        assert {name: hashlib.sha256(case.backend.nodes[case.obs / name][1]).hexdigest() for name in NAMES} == old
        assert hashlib.sha256(case.backend.nodes[case.task_dir / "spec.json"][1]).hexdigest() == case.spec_sha
    finally:
        client.close()
        service.close()


@pytest.mark.parametrize("fault", ["usage", "budget", "wrong_task", "replay", "old_manager"])
def test_continuation_missing_usage_and_protocol_fault(tmp_path, monkeypatch, fault):
    from mokioclaw.dashboard.task_worker import run_projected_workflow
    from mokioclaw.providers.openai_provider import TaskProviderError
    case, service, manager, client, context, model, _, old = setup_flow(tmp_path, monkeypatch)
    original = model.invoke
    if fault in {"usage", "budget"}:
        def failing(messages, **kwargs):
            response = original(messages, **kwargs)
            response.usage_metadata = None if fault == "usage" else {"input_tokens": 150000, "output_tokens": 0, "total_tokens": 150000}
            return response
        monkeypatch.setattr(model, "invoke", failing)
        with pytest.raises(TaskProviderError):
            run_projected_workflow("PROMPT_SENTINEL", case.task_dir / "workspace/work", context, lambda _: None, max_attempts=1)
        assert model.calls == 1 and context.provider_calls == 1
        client.finish(context.usage_snapshot())
    elif fault == "old_manager":
        with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
            service.receive_calibration_viewer(object(), {"schema_version": 1, "kind": "poll", "sequence": 3})
    else:
        bootstrap = manager._worker_bootstrap
        frame = {"schema_version": 1, "kind": "hello", "task_id": TASK if fault == "replay" else "another_task_0001",
                 "instance_id": bootstrap.instance_id, "attempt_id": 1, "sequence": 1}
        assert manager.receive_worker(frame) is False
    client.close()
    service.worker_controller.finish(TASK, "failed", "synthetic_failure")
    service.close()
    assert {name: hashlib.sha256(case.backend.nodes[case.obs / name][1]).hexdigest() for name in NAMES} == old
    assert sum(event == "create:sessions" for event in case.backend.events) == 1


def test_continuation_privacy_sentinel(tmp_path, monkeypatch, caplog, capsys):
    from mokioclaw.dashboard.task_worker import run_projected_workflow
    case, service, manager, client, context, _, _, _ = setup_flow(tmp_path, monkeypatch)
    events = []
    run_projected_workflow("PROMPT_SENTINEL", case.task_dir / "workspace/work", context, events.append,
                           max_attempts=1, handoff_observer=client.accept_handoff)
    client.finish(context.usage_snapshot())
    client.close()
    service.worker_controller.finish(TASK, "completed")
    service.close()
    persisted = b"".join(content for path, (_, content, _) in case.backend.nodes.items()
                         if manager.session.directory.identity.final_path in path.parents)
    public = repr(events) + repr(asdict(service.store.get(TASK))) + caplog.text + str(capsys.readouterr())
    assert b"SENTINEL" not in persisted and "SENTINEL" not in public
