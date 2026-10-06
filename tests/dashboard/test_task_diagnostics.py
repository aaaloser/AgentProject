"""Private parent journals and binding lifecycle in pytest's external temp root."""
import json
from types import SimpleNamespace

import pytest

from tests.dashboard.task_observation_fakes import TASK_ID, INSTANCE_ID, offline_observation_guard, utc_clock


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    with offline_observation_guard(monkeypatch):
        yield


def prepared(root, state="prepared"):
    taskroot = root / "tasks" / TASK_ID
    taskroot.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(task_id=TASK_ID, state=state, instance_id=INSTANCE_ID,
                           attempt_id=1, cleanup_confirmed=False)


def usage():
    from mokioclaw.core.task_observation import STAGES
    return {s + n: 0 for s in STAGES for n in ("_calls", "_reported_tokens")}


@pytest.mark.parametrize("sequence", [8193, 8195])
def test_high_viewer_sequence_still_rejects_replay_or_gap(tmp_path, sequence):
    from mokioclaw.dashboard.task_diagnostics import CalibrationObservationManager
    record = prepared(tmp_path)
    manager = CalibrationObservationManager(tmp_path, task_lookup=lambda _: record)
    try:
        manager.receive_viewer({"schema_version": 1, "kind": "hello", "sequence": 1})
        for number in range(2, 8194):
            manager.receive_viewer({"schema_version": 1, "kind": "poll", "sequence": number})
        assert manager.bind(TASK_ID) and manager.ready_for_start(TASK_ID)
        with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
            manager.receive_viewer({"schema_version": 1, "kind": "poll", "sequence": sequence})
        assert not manager.valid and not manager.ready_for_start(TASK_ID)
    finally:
        manager.close()


@pytest.mark.parametrize("fault", ["eof", "encode", "timeout", "sequence"])
def test_viewer_eof_revokes_parent_ready(tmp_path, fault, caplog, capsys):
    from queue import Queue, Empty
    from threading import Event, RLock
    from mokioclaw.dashboard.task_diagnostics import CalibrationObservationManager
    from mokioclaw.dashboard.task_diagnostic_viewer import ViewerChannel, ViewerController
    from mokioclaw.dashboard.task_handoff_observation import HandoffView, HandoffIdentity
    from mokioclaw.dashboard.task_service import TaskService
    from mokioclaw.dashboard.task_store import TaskConflict

    eof = object()
    server_closed = Event()

    class Endpoint:
        pending = None
        closed = False
        broken = False
        def __init__(self, incoming, outgoing, *, server=False):
            self.incoming, self.outgoing, self.server = incoming, outgoing, server
        def send_bytes(self, data): self.outgoing.put(data)
        def poll(self, timeout):
            if self.broken and fault == "timeout":
                return False
            if self.pending is not None:
                return True
            try:
                self.pending = self.incoming.get(timeout=timeout)
                return True
            except Empty:
                return False
        def recv_bytes(self, maxlength):
            data, self.pending = self.pending, None
            if data is eof:
                raise EOFError("PRIVATE_EOF_EXCEPTION")
            if self.broken and fault == "sequence":
                frame = json.loads(data)
                frame["sequence"] += 1
                return json.dumps(frame).encode()
            return data
        def close(self):
            if not self.closed:
                self.closed = True
                self.outgoing.put(eof)
            if self.server:
                server_closed.set()

    to_server, to_client = Queue(), Queue()
    client = Endpoint(to_client, to_server)
    server = Endpoint(to_server, to_client, server=True)

    class Listener:
        def accept(self): return server
        def close(self): pass

    def listener_factory(address, *, family, authkey):
        assert family == "AF_PIPE" and len(authkey) == 32
        return Listener()

    record = prepared(tmp_path)
    manager = CalibrationObservationManager(tmp_path, task_lookup=lambda _: record,
                                            listener_factory=listener_factory)
    try:
        manager._start_role(manager.viewer_bootstrap)
        channel = ViewerChannel(manager.viewer_bootstrap, connect=lambda _: client)
        rendered = []
        viewer = ViewerController(request=channel.request, render_text=rendered.append)
        assert viewer.bind(TASK_ID) and manager.ready_for_start(TASK_ID)
        manager.memory.accept(1, "PRIVATE_PARENT_BODY")
        viewer.render(HandoffView(HandoffIdentity(TASK_ID, 1, 1), "PRIVATE_PARENT_BODY", True))
        if fault == "eof":
            to_server.put(eof)
        else:
            client.broken = True
            if fault == "encode":
                assert not viewer.bind("!")
            else:
                viewer.poll()
            assert not viewer.valid and viewer._view is None and rendered[-1] == ""
            assert client.closed
        assert server_closed.wait(1)
        manager._threads[0].join(timeout=1)
        assert not manager._threads[0].is_alive()
        assert not manager.valid and not manager.viewer_ready and not manager.ready_for_start(TASK_ID)
        assert manager.memory._current is None and not manager.journal.valid
        service = TaskService.__new__(TaskService)
        service._lock = RLock()
        service.observation_manager = manager
        calls = []
        service.task_image_digest = "sha256:" + "a" * 64
        service.run_available = lambda: calls.append("image") or True
        def start(task):
            calls.append("worker")
            raise AssertionError("unexpected_worker_start")
        service.worker_controller = SimpleNamespace(broker=object(), start=start)
        service._fixed_spec = lambda task: None
        with pytest.raises(TaskConflict, match="^calibration_observation_invalid$"):
            service.start_agent(TASK_ID)
        assert calls == []
    finally:
        client.close()
        manager.close()
    captured = capsys.readouterr()
    assert "PRIVATE_" not in captured.out + captured.err + caplog.text
    assert "PRIVATE_" not in str([p.read_bytes() for p in (tmp_path / "observations").rglob("*.json*")])


def test_exclusive_numeric_sink(tmp_path):
    from mokioclaw.dashboard.task_diagnostics import NumericJournal
    from mokioclaw.core.task_observation import TaskObservation, ObservationRecord
    journal = NumericJournal(tmp_path, TASK_ID)
    with pytest.raises(ValueError, match="calibration_observation_invalid"):
        NumericJournal(tmp_path, TASK_ID)
    observer = TaskObservation(TASK_ID, journal, utc_clock=utc_clock)
    assert observer.emit(ObservationRecord(TASK_ID, 1, "invoke_started", call_no=1, stage="planner", status="started"))
    assert observer.emit(ObservationRecord(TASK_ID, 1, "invoke_finished", call_no=1, stage="planner",
                                         status="valid_usage", total_tokens=0))
    totals = usage()
    totals["planner_calls"] = 1
    result = journal.finalize(totals, stream_closed=True, cleanup_confirmed=True)
    assert result.valid and result.started_calls == 1
    assert json.loads((tmp_path / "observations" / TASK_ID / "status.json").read_text())["valid"]
    assert len((tmp_path / "observations" / TASK_ID / "calls.jsonl").read_bytes().splitlines()) == 2
    journal.close()


def test_incomplete_status_and_io_fault(tmp_path):
    from mokioclaw.dashboard.task_diagnostics import NumericJournal
    journal = NumericJournal(tmp_path, TASK_ID)
    assert not journal.finalize(usage(), stream_closed=False, cleanup_confirmed=False).valid
    assert not json.loads((tmp_path / "observations" / TASK_ID / "status.json").read_text())["valid"]
    journal.close()


def test_role_auth_binding_and_replay(tmp_path):
    from mokioclaw.dashboard.task_diagnostics import CalibrationObservationManager
    record = prepared(tmp_path)
    manager = CalibrationObservationManager(tmp_path, task_lookup=lambda _: record, clock=lambda: 0)
    assert manager.bind(TASK_ID)
    assert not manager.bind(TASK_ID)
    assert manager.worker_bootstrap(TASK_ID) is None
    record.state = "running"
    bootstrap = manager.worker_bootstrap(TASK_ID)
    assert bootstrap.role == "worker" and len(bootstrap.authkey) == 32
    assert bootstrap.authkey != manager.viewer_bootstrap.authkey
    base = {"schema_version": 1, "kind": "hello", "task_id": TASK_ID,
            "instance_id": INSTANCE_ID, "attempt_id": 1, "sequence": 1}
    assert manager.receive_worker(base)
    assert not manager.receive_worker(base)
    assert not manager.valid
    manager.close()


@pytest.mark.parametrize("change", ["task_id", "instance_id", "attempt_id"])
def test_wrong_identity_rejected(tmp_path, change):
    from mokioclaw.dashboard.task_diagnostics import CalibrationObservationManager
    record = prepared(tmp_path)
    manager = CalibrationObservationManager(tmp_path, task_lookup=lambda _: record, clock=lambda: 0)
    assert manager.bind(TASK_ID)
    record.state = "running"
    assert manager.worker_bootstrap(TASK_ID)
    base = {"schema_version": 1, "kind": "hello", "task_id": TASK_ID,
            "instance_id": INSTANCE_ID, "attempt_id": 1, "sequence": 1}
    base[change] = 2 if change == "attempt_id" else "wrong_identity_001"
    assert not manager.receive_worker(base)
    manager.close()


def test_cleanup_ttl_and_window_close(tmp_path):
    from mokioclaw.dashboard.task_diagnostics import CalibrationObservationManager
    record = prepared(tmp_path)
    clock = [0]
    manager = CalibrationObservationManager(tmp_path, task_lookup=lambda _: record, clock=lambda: clock[0])
    assert manager.bind(TASK_ID)
    record.state = "running"
    manager.worker_bootstrap(TASK_ID)
    manager.memory.accept(1, "PRIVATE_BODY")
    record.state = "stopping"
    manager.poll_terminal()
    assert manager.memory._current is not None
    record.state = "completed"
    record.cleanup_confirmed = True
    manager.poll_terminal()
    clock[0] = 599
    manager.poll_terminal()
    assert manager.memory._current is not None
    clock[0] = 600
    manager.poll_terminal()
    assert manager.memory._current is None
    manager.close()
    assert "PRIVATE_BODY" not in str([p.read_bytes() for p in tmp_path.rglob("*.json*")])


def test_cleanup_failed_clears_immediately(tmp_path):
    from mokioclaw.dashboard.task_diagnostics import CalibrationObservationManager
    record = prepared(tmp_path)
    manager = CalibrationObservationManager(tmp_path, task_lookup=lambda _: record, clock=lambda: 0)
    manager.bind(TASK_ID)
    manager.memory.accept(1, "PRIVATE_BODY")
    record.state = "cleanup_failed"
    manager.poll_terminal()
    assert manager.memory._current is None and not manager.valid
    manager.close()


def test_attempt_switch_clears_old_body(tmp_path):
    from mokioclaw.dashboard.task_diagnostics import CalibrationObservationManager
    record = prepared(tmp_path)
    manager = CalibrationObservationManager(tmp_path, task_lookup=lambda _: record, clock=lambda: 0)
    manager.bind(TASK_ID)
    manager.memory.accept(1, "PRIVATE_BODY")
    record.state = "running"
    record.attempt_id = 2
    manager.poll_terminal()
    assert manager.memory._current is None
    manager.close()


def test_file_failure_limits_and_symlink_rejection(tmp_path, monkeypatch):
    from mokioclaw.dashboard.task_diagnostics import NumericJournal
    from mokioclaw.core.task_observation import TaskObservation, ObservationRecord
    journal = NumericJournal(tmp_path, TASK_ID)
    class Broken:
        def write(self, data): raise OSError("PRIVATE_IO_EXCEPTION")
        def close(self): pass
    original = journal._handles[0]
    journal._handles[0] = Broken()
    observer = TaskObservation(TASK_ID, journal, utc_clock=utc_clock)
    assert not observer.emit(ObservationRecord(TASK_ID, 1, "policy_decision"))
    assert not journal.valid
    assert not journal.finalize(usage(), stream_closed=True, cleanup_confirmed=True).valid
    assert "PRIVATE_IO_EXCEPTION" not in str([p.read_bytes() for p in tmp_path.rglob("*.json*")])
    original.close()
    journal.close()
    root = tmp_path / "cap"
    journal = NumericJournal(root, TASK_ID)
    observer = TaskObservation(TASK_ID, journal, utc_clock=utc_clock)
    for _ in range(512):
        assert observer.emit(ObservationRecord(TASK_ID, 1, "policy_decision"))
    assert not observer.emit(ObservationRecord(TASK_ID, 1, "policy_decision"))
    assert not journal.finalize(usage(), stream_closed=True, cleanup_confirmed=True).valid
    journal.close()
