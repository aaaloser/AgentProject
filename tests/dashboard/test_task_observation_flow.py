"""Actual graph calibration with synthetic models, command receipts and private sinks."""
from dataclasses import asdict
import json
from types import SimpleNamespace

import pytest

from tests.dashboard.task_observation_fakes import offline_observation_guard, MemorySink, utc_clock

TASK = "task_1234567890123456"
INSTANCE = "synthetic_instance_001"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    with offline_observation_guard(monkeypatch):
        yield


def setup_observed_graph(tmp_path, monkeypatch):
    from mokioclaw.core.agent import TaskRunContext
    from mokioclaw.core.task_observation import TaskObservation
    from mokioclaw.dashboard.task_diagnostics import CalibrationObservationManager
    from mokioclaw.dashboard.task_diagnostic_ipc import WorkerDiagnosticClient, decode_frame
    root = tmp_path / "calibration"
    (root / "tasks" / TASK).mkdir(parents=True)
    record = SimpleNamespace(task_id=TASK, state="prepared", instance_id=INSTANCE,
                             attempt_id=1, cleanup_confirmed=False)
    manager = CalibrationObservationManager(root, task_lookup=lambda _: record, clock=lambda: 0)
    def viewer(kind, sequence, **values):
        return manager.receive_viewer({"schema_version": 1, "kind": kind, "sequence": sequence, **values})
    assert viewer("hello", 1)["valid"]
    assert viewer("bind", 2, task_id=TASK)["accepted"]
    record.state = "running"
    bootstrap = manager.worker_bootstrap(TASK)
    class Channel:
        def send_bytes(self, data):
            frame = decode_frame(data, role="worker")
            self.accepted = manager.receive_worker(frame)
            self.sequence = frame["sequence"]
        def poll(self, timeout): return self.accepted
        def recv_bytes(self, maxlength):
            return json.dumps({"schema_version": 1, "kind": "ack", "sequence": self.sequence}).encode()
        def close(self): pass
    client = WorkerDiagnosticClient(bootstrap, connect=lambda b: Channel())
    observer = TaskObservation(TASK, client, utc_clock=utc_clock)
    contexts = []
    original = TaskRunContext.for_fake_model
    def factory(cls, model, **kwargs):
        context = original(model, observation=observer, **kwargs)
        contexts.append(context)
        return context
    monkeypatch.setattr(TaskRunContext, "for_fake_model", classmethod(factory))
    import mokioclaw.dashboard.task_worker as worker
    original_run = worker.run_projected_workflow
    def run(*args, **kwargs):
        return original_run(*args, **kwargs, handoff_observer=client.accept_handoff)
    monkeypatch.setattr(worker, "run_projected_workflow", run)
    return manager, client, contexts, record, root


@pytest.mark.parametrize("slots", [3, 5, 7])
def test_real_graph_success_and_formal_receipts(tmp_path, monkeypatch, slots, capsys):
    from test_task_closeout_flow import test_real_graph_repairs_selftests_then_reserved_closeout
    manager, client, contexts, record, root = setup_observed_graph(tmp_path, monkeypatch)
    try:
        test_real_graph_repairs_selftests_then_reserved_closeout(tmp_path / "graph", monkeypatch, slots)
        ctx = contexts[-1]
        client.finish(ctx.usage_snapshot())
        client.close()
        record.state = "completed"
        record.cleanup_confirmed = True
        manager.close()
        status = json.loads((root / "observations" / TASK / "status.json").read_text())
        assert status["valid"]
        assert status["started_calls"] == ctx.provider_calls == {3: 12, 5: 13, 7: 15}[slots]
        assert status["unknown_calls"] == 0
        rows = [json.loads(line) for line in (root / "observations" / TASK / "calls.jsonl").read_bytes().splitlines()]
        assert sum(row["total_tokens"] or 0 for row in rows if row["kind"] == "invoke_finished") == ctx.reported_tokens
        assert any(row["kind"] == "phase_released" for row in rows) == (slots != 7)
        if slots >= 5:
            adopted = [row for row in rows if row["kind"] == "adopt_existing_call"]
            assert len(adopted) == 1
            assert next(row for row in rows if row["kind"] == "invoke_started" and row["call_no"] == adopted[0]["call_no"])["purpose"] is None
        persisted = b"".join(path.read_bytes() for path in root.rglob("*.json*"))
        assert all(s.encode() not in persisted for s in ("SOURCE_SENTINEL", "ARGUMENT_SENTINEL", "PROVIDER_SENTINEL", "COMMAND_SENTINEL"))
        assert "SENTINEL" not in str(capsys.readouterr())
    finally:
        client.close()
        manager.close()


@pytest.mark.parametrize("stage", ["handoff", "planner", "verifier", "pre", "post"])
@pytest.mark.parametrize("fault", ["usage", "hard"])
def test_real_graph_failure_and_receipts_remain(tmp_path, monkeypatch, stage, fault):
    from test_task_closeout_flow import test_real_graph_closeout_failure_preserves_formal_evidence
    manager, client, contexts, record, root = setup_observed_graph(tmp_path, monkeypatch)
    try:
        test_real_graph_closeout_failure_preserves_formal_evidence(tmp_path / "graph", stage, fault)
        ctx = contexts[-1]
        client.finish(ctx.usage_snapshot())
        client.close()
        record.state = "failed"
        record.cleanup_confirmed = True
        manager.close()
        status = json.loads((root / "observations" / TASK / "status.json").read_text())
        assert status["started_calls"] == ctx.provider_calls
        assert status["valid"] == (fault == "hard")
        assert status["unknown_calls"] == (1 if fault == "usage" else 0)
    finally:
        client.close()
        manager.close()


def test_run_real_task_uses_synthetic_settings_and_diagnostic_sink(tmp_path, monkeypatch):
    from mokioclaw.dashboard import task_worker
    from mokioclaw.core.agent import TaskRunContext
    from mokioclaw.providers.openai_provider import ProviderSettings
    from test_task_observation_context import Model
    class Sink(MemorySink):
        def accept_handoff(self, attempt, summary): self.summary = summary
        def finish(self, usage): self.usage = usage
    sink = Sink()
    work = tmp_path / TASK / "workspace" / "work"
    (work / "src").mkdir(parents=True)
    def factory(settings, **kwargs):
        assert settings.model == "synthetic"
        return TaskRunContext.for_fake_model(Model(0), **kwargs)
    def stream(description, **kwargs):
        context = kwargs["task_context"]
        context.model(stage="planner").invoke([])
        yield {"type": "custom_event", "event": {"type": "handoff_result",
               "from": "codeAgent", "to": "planner", "result": "PRIVATE_SYNTHETIC_SUMMARY"}}
    start = {"task_id": TASK, "payload": {
        "description": "PRIVATE_PROMPT", "source_read_scope": ["src/"], "source_write_scope": ["src/"],
        "task_scratch_scope": ".mokioclaw/task-scratch/", "max_attempts": 1, "max_provider_calls": 20,
        "max_total_tokens": 150000, "max_output_tokens_per_call": 3072, "verification_commands": []}}
    public = []
    with monkeypatch.context() as settings_patch:
        settings_patch.setattr(ProviderSettings, "from_environment",
                               classmethod(lambda cls: SimpleNamespace(model="synthetic")))
        task_worker._run_real_task(start, public.append, SimpleNamespace(task_gateway=True), workspace=work,
                                  context_factory=factory, stream=stream, diagnostic_client=sink)
    assert sink.summary == "PRIVATE_SYNTHETIC_SUMMARY"
    assert sink.usage["planner_calls"] == 1 and sink.usage["planner_reported_tokens"] == 0
    assert [r.kind for r in sink.records] == ["invoke_started", "invoke_finished"]
    assert "PRIVATE_" not in str(public)
    assert "PRIVATE_" not in str([asdict(r) for r in sink.records])


def test_nested_call_keeps_original_call_number():
    from mokioclaw.core.agent import TaskRunContext
    from mokioclaw.core.task_observation import TaskObservation, reconcile
    sink = MemorySink()
    class Nested:
        entered = False
        def invoke(self, *args, **kwargs):
            if not self.entered:
                self.entered = True
                ctx.model(stage="code_agent").invoke([])
            return SimpleNamespace(usage_metadata={"total_tokens": 0})
    ctx = TaskRunContext.for_fake_model(Nested(), max_provider_calls=20, max_total_tokens=150000,
                                       max_output_tokens_per_call=3072,
                                       observation=TaskObservation(TASK, sink, utc_clock=utc_clock))
    ctx.model(stage="planner").invoke([])
    assert [(r.kind, r.call_no) for r in sink.records] == [
        ("invoke_started", 1), ("invoke_started", 2), ("invoke_finished", 2), ("invoke_finished", 1)]
    assert reconcile(sink.records, ctx.usage_snapshot()).valid


@pytest.mark.parametrize("ready", [False, True])
def test_worker_waits_for_private_ready_before_started(monkeypatch, ready):
    import mokioclaw.dashboard.task_worker as worker
    from mokioclaw.dashboard.task_diagnostic_ipc import DiagnosticBootstrap, bootstrap_to_wire
    from test_task_context_flow import MemoryChannel
    bootstrap = DiagnosticBootstrap("synthetic_pipe", b"a" * 32, "worker", TASK, INSTANCE, 1)
    initial = MemoryChannel()
    worker._send(initial, {"kind": "ready"})
    worker._send(initial, {"kind": "start", "task_id": TASK, "diagnostic": bootstrap_to_wire(bootstrap)})
    channel = MemoryChannel(initial.outgoing)
    order = []
    class Client:
        def close(self): order.append("close")
    def factory(value):
        assert value == bootstrap
        assert b'"started"' not in channel.outgoing
        order.append("ready_check")
        if not ready:
            raise ValueError("PRIVATE_EXCEPTION")
        return Client()
    def runner(*args, diagnostic_client):
        assert b'"started"' in channel.outgoing
        assert type(diagnostic_client) is Client
        order.append("run")
    with monkeypatch.context() as patch:
        patch.setattr(worker.socket, "create_connection", lambda *a, **kw: channel)
        worker._worker_main(1, token_line="x" * 32, run_task=runner, diagnostic_factory=factory)
    assert order == (["ready_check", "run", "close"] if ready else ["ready_check"])
    assert (b'"started"' in channel.outgoing) == ready
    assert b"PRIVATE_EXCEPTION" not in channel.outgoing


@pytest.mark.parametrize("fault", ["sink", "viewer"])
def test_actual_graph_observation_fault_preserves_completion(tmp_path, monkeypatch, fault):
    from test_task_context_flow import graph_fixture
    from mokioclaw.core.task_observation import TaskObservation
    from mokioclaw.dashboard.task_worker import run_projected_workflow
    context, model, _, work, _, receipts = graph_fixture(tmp_path)
    class Sink:
        def emit(self, record):
            if fault == "sink":
                raise OSError("PRIVATE_EXCEPTION")
            return False
    context.observation = TaskObservation(TASK, Sink(), utc_clock=utc_clock)
    context.closeout._observer = context._observe_closeout
    events = []
    run_projected_workflow("PRIVATE_PROMPT", work, context, events.append, max_attempts=1)
    assert events[-1]["phase"] == "complete"
    assert context.provider_calls == model.calls == 12
    assert [r.exit_code for r in receipts] == [1, 0, 0]
    assert not context.observation.valid and context._terminal_root is None
    assert "PRIVATE_" not in str(events)
