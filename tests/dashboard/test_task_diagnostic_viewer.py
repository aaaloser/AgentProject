"""Opt-in entry points and a fake native viewer; no process/window/service starts."""
from io import BytesIO
from types import SimpleNamespace
from threading import RLock

import pytest

from tests.dashboard.task_observation_fakes import TASK_ID, offline_observation_guard


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    with offline_observation_guard(monkeypatch):
        yield


def test_viewer_environment_has_no_credentials():
    from mokioclaw.dashboard.task_diagnostic_viewer import filtered_viewer_environment
    env = filtered_viewer_environment({"PATH": "synthetic", "MOKIO_TASK_API_KEY": "SECRET",
                                      "OPENAI_API_KEY": "SECRET", "PYTHONPATH": "UNTRUSTED"})
    assert env["PATH"] == "synthetic"
    assert "SECRET" not in str(env) and "UNTRUSTED" not in str(env)
    assert set(env) == {"PATH", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE"}


def test_viewer_long_idle_then_bind(tmp_path):
    from mokioclaw.dashboard.task_diagnostic_viewer import ViewerChannel, ViewerController
    from mokioclaw.dashboard.task_diagnostic_ipc import encode_frame, decode_frame
    from mokioclaw.dashboard.task_diagnostics import CalibrationObservationManager
    from test_task_diagnostics import prepared
    record = prepared(tmp_path)
    manager = CalibrationObservationManager(tmp_path, task_lookup=lambda _: record)

    class MemoryPeer:
        reply = None
        def send_bytes(self, data):
            self.reply = encode_frame(manager.receive_viewer(decode_frame(data, role="viewer")), role="viewer")
        def poll(self, timeout): return self.reply is not None
        def recv_bytes(self, maxlength):
            reply, self.reply = self.reply, None
            return reply
        def close(self): pass

    try:
        channel = ViewerChannel(manager.viewer_bootstrap, connect=lambda _: MemoryPeer())
        viewer = ViewerController(request=channel.request, render_text=lambda body: None)
        for _ in range(8192):
            viewer.poll()
            assert viewer.valid
        assert viewer.bind(TASK_ID)
        assert manager.ready_for_start(TASK_ID)
        for _ in range(8192):
            viewer.poll()
            assert viewer.valid
        assert viewer.bound_task == TASK_ID and manager.ready_for_start(TASK_ID)
        assert channel.sequence == 16386
        assert manager._worker_bootstrap is None and manager.memory.indexes == []
        assert (tmp_path / "observations" / TASK_ID / "calls.jsonl").read_bytes() == b""
    finally:
        manager.close()


@pytest.mark.parametrize("fault", ["encode", "send", "poll_error", "timeout", "recv", "json", "sequence", "kind"])
@pytest.mark.parametrize("close_raises", [False, True])
def test_viewer_exchange_fault_closes_channel(fault, close_raises, caplog, capsys):
    import json
    from mokioclaw.dashboard.task_diagnostic_viewer import ViewerChannel, ViewerController
    from mokioclaw.dashboard.task_diagnostic_ipc import DiagnosticBootstrap
    from mokioclaw.dashboard.task_handoff_observation import HandoffView, HandoffIdentity

    class Exchange:
        broken = False
        closed = False
        sent = 0
        sequence = 0
        def send_bytes(self, data):
            self.sent += 1
            if self.broken and fault == "send":
                raise OSError("PRIVATE_SEND_EXCEPTION")
            self.sequence = json.loads(data)["sequence"]
        def poll(self, timeout):
            if self.broken and fault == "poll_error":
                raise OSError("PRIVATE_POLL_EXCEPTION")
            return not (self.broken and fault == "timeout")
        def recv_bytes(self, maxlength):
            if self.broken and fault == "recv":
                raise EOFError("PRIVATE_RECV_EXCEPTION")
            if self.broken and fault == "json":
                return b'{"PRIVATE_MALFORMED_REPLY"'
            return json.dumps({"schema_version": 1,
                               "kind": "ack" if self.broken and fault == "kind" else "state",
                               "sequence": self.sequence + (self.broken and fault == "sequence"),
                               **({} if self.broken and fault == "kind" else
                                  {"valid": True, "accepted": True, "bound_task": TASK_ID, "view": None})}).encode()
        def close(self):
            self.closed = True
            if close_raises:
                raise OSError("PRIVATE_CLOSE_EXCEPTION")

    connection = Exchange()
    connects = []
    def connect(bootstrap):
        connects.append(bootstrap)
        return connection
    channel = ViewerChannel(DiagnosticBootstrap("synthetic_pipe", b"a" * 32, "viewer"),
                            connect=connect)
    rendered = []
    viewer = ViewerController(request=channel.request, render_text=rendered.append)
    assert viewer.bind(TASK_ID)
    viewer.render(HandoffView(HandoffIdentity(TASK_ID, 1, 1), "PRIVATE_VIEW_BODY", True))
    connection.broken = True
    if fault == "encode":
        assert not viewer.bind("!")
    else:
        viewer.poll()
    assert not viewer.valid and viewer._view is None and rendered[-1] == ""
    assert connection.closed
    sent, sequence = connection.sent, channel.sequence
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        channel.request("poll")
    assert connection.sent == sent and channel.sequence == sequence
    assert len(connects) == 1
    captured = capsys.readouterr()
    assert "PRIVATE_" not in captured.out + captured.err + caplog.text


@pytest.mark.parametrize("fault", ["send", "timeout", "recv", "json", "sequence"])
def test_failed_hello_closes_owned_connection(fault):
    import json
    from mokioclaw.dashboard.task_diagnostic_viewer import ViewerChannel
    from mokioclaw.dashboard.task_diagnostic_ipc import DiagnosticBootstrap

    class Exchange:
        closed = False
        def send_bytes(self, data):
            if fault == "send":
                raise OSError("PRIVATE_HELLO_EXCEPTION")
        def poll(self, timeout): return fault != "timeout"
        def recv_bytes(self, maxlength):
            if fault == "recv":
                raise EOFError("PRIVATE_HELLO_EXCEPTION")
            if fault == "json":
                return b"invalid"
            return json.dumps({"schema_version": 1, "kind": "state", "sequence": 2,
                               "valid": True, "accepted": True, "bound_task": None, "view": None}).encode()
        def close(self): self.closed = True

    connection = Exchange()
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        ViewerChannel(DiagnosticBootstrap("synthetic_pipe", b"a" * 32, "viewer"), connect=lambda _: connection)
    assert connection.closed


def test_launch_only_uses_stdin_auth_and_trusted_directory(tmp_path):
    from mokioclaw.dashboard.task_diagnostic_viewer import launch_viewer
    from mokioclaw.dashboard.task_diagnostic_ipc import DiagnosticBootstrap
    class Input(BytesIO):
        def close(self): self.saved = self.getvalue()
    class Process:
        pid = 424242
        stdin = Input()
        def poll(self): return None
        def terminate(self): self.terminated = True
        def wait(self, timeout): return 0
    calls, process = [], Process()
    def spawn(argv, **kwargs):
        calls.append((argv, kwargs))
        return process
    bootstrap = DiagnosticBootstrap("synthetic_pipe", b"a" * 32, "viewer")
    launch = launch_viewer(bootstrap, spawn=spawn, environment={"PATH": "synthetic", "SECRET": "NO"})
    argv, kwargs = calls[0]
    assert "synthetic_pipe" not in str(argv) and (b"a" * 32).hex() not in str(argv)
    assert b"synthetic_pipe" in process.stdin.saved
    assert kwargs["cwd"] != tmp_path
    assert "SECRET" not in str(kwargs["env"])
    assert "-P" in argv and "-B" in argv
    launch.close()
    assert process.terminated


def test_viewer_no_provider_controls_and_stale_render():
    from mokioclaw.dashboard.task_diagnostic_viewer import ViewerController
    from mokioclaw.dashboard.task_handoff_observation import HandoffView, HandoffIdentity, HandoffScores
    identity = HandoffIdentity(TASK_ID, 1, 1)
    calls, rendered = [], []
    def request(kind, **values):
        calls.append((kind, values))
        return {"accepted": True, "valid": True, "bound_task": TASK_ID, "view": None}
    viewer = ViewerController(request=request, render_text=rendered.append)
    assert viewer.bind(TASK_ID)
    viewer.render(HandoffView(identity, "https://invalid/; execute()", True))
    assert rendered[-1] == "https://invalid/; execute()"
    assert viewer.submit_scores(HandoffScores())
    viewer.render(None)
    assert rendered[-1] == ""
    assert not viewer.submit_scores(HandoffScores())
    viewer.close()
    assert {kind for kind, _ in calls} == {"bind", "score", "close"}
    assert not hasattr(viewer, "run") and not hasattr(viewer, "approve")


@pytest.mark.parametrize("enabled, offset, platform", [(False, "", "nt"), (True, "wrong", "nt"), (True, "", "posix")])
def test_calibration_validation_precedes_provider(tmp_path, enabled, offset, platform):
    from mokioclaw.dashboard.task_diagnostic_viewer import validate_calibration
    with pytest.raises(ValueError, match="calibration_config_invalid"):
        validate_calibration(tmp_path, tmp_path / (offset or "tasks"), enable_agent=enabled,
                             platform=platform, tkinter_available=True)


def test_tk_missing_is_safe(tmp_path):
    from mokioclaw.dashboard.task_diagnostic_viewer import validate_calibration
    with pytest.raises(ValueError, match="calibration_config_invalid"):
        validate_calibration(tmp_path, tmp_path / "tasks", enable_agent=True,
                             platform="nt", tkinter_available=False)


def test_configure_after_service_creation(tmp_path):
    from mokioclaw.dashboard.task_service import TaskService
    service = TaskService.__new__(TaskService)
    service.task_root = tmp_path / "tasks"
    service.store = SimpleNamespace(get=lambda task: None)
    service._lock = RLock()
    service.observation_manager = None
    service._continuation = None
    manager = SimpleNamespace(root=tmp_path)
    calls = []
    def factory(root, *, task_lookup):
        calls.append((root, task_lookup))
        return manager
    assert service.configure_calibration(tmp_path, manager_factory=factory) is manager
    assert calls == [(tmp_path, service.store.get)]


def test_bind_before_first_start_avoids_image_and_worker():
    from mokioclaw.dashboard.task_service import TaskService
    from mokioclaw.dashboard.task_store import TaskConflict
    service = TaskService.__new__(TaskService)
    service._lock = RLock()
    service.observation_manager = SimpleNamespace(ready_for_start=lambda task: False)
    calls = []
    service.task_image_digest = "sha256:" + "a" * 64
    service.run_available = lambda: calls.append("image") or True
    def start(task):
        calls.append("worker")
        raise AssertionError("unexpected_worker_start")
    service.worker_controller = SimpleNamespace(broker=object(), start=start)
    service._fixed_spec = lambda task: None
    with pytest.raises(TaskConflict, match="calibration_observation_invalid"):
        service.start_agent(TASK_ID)
    assert calls == []


def test_cli_opt_in_and_default_unchanged(monkeypatch, tmp_path):
    from typer.testing import CliRunner
    from mokioclaw.cli.app import app
    import mokioclaw.dashboard.launcher as launcher
    calls = []
    monkeypatch.setattr(launcher, "launch_dashboard", lambda *a, **kw: calls.append(kw))
    runner = CliRunner()
    assert runner.invoke(app, ["dashboard", "--no-browser"]).exit_code == 0
    assert calls == [{"open_browser": False}]
    calls.clear()
    result = runner.invoke(app, ["dashboard", "--enable-agent", "--no-browser", "--task-root",
                           str(tmp_path / "tasks"), "--task-image", "sha256:" + "a" * 64,
                           "--calibration-root", str(tmp_path)])
    assert result.exit_code == 0
    assert calls[0]["calibration_root"] == tmp_path
    result = runner.invoke(app, ["dashboard", "--calibration-root", str(tmp_path)])
    assert result.exit_code == 2


def test_native_window_builds_only_view_and_scores():
    from mokioclaw.dashboard.task_diagnostic_viewer import main
    from mokioclaw.dashboard.task_diagnostic_ipc import DiagnosticBootstrap
    labels, commands, rendered = [], {}, []
    class Variable:
        def __init__(self, value=""): self.value = value
        def get(self): return self.value
        def set(self, value): self.value = value
    class Widget:
        def __init__(self, *args, **kwargs):
            if "text" in kwargs:
                labels.append(kwargs["text"])
            if "command" in kwargs:
                commands[kwargs["text"]] = kwargs["command"]
        def pack(self): pass
        def configure(self, **kwargs): pass
        def delete(self, *args): rendered.clear()
        def insert(self, where, value): rendered.append(value)
    class Root:
        def title(self, value): pass
        def protocol(self, *args): pass
        def after(self, *args): pass
        def mainloop(self): commands["关闭"]()
        def destroy(self): pass
    class Connection:
        def close(self): pass
    class Channel:
        connection = Connection()
        def request(self, kind, **kwargs):
            assert kind == "close"
            return {"valid": False, "accepted": True}
    tk = SimpleNamespace(Tk=Root, StringVar=Variable, Entry=Widget, Label=Widget,
                         Text=Widget, Button=Widget, OptionMenu=Widget)
    main(bootstrap=DiagnosticBootstrap("synthetic_pipe", b"a" * 32, "viewer"),
         tk_module=tk, channel_factory=lambda b: Channel())
    assert set(commands) == {"关闭", "绑定观测", "提交五维评分"}
    assert rendered == [""]


def test_oversize_handoff_is_visible_without_body_or_pass(tmp_path):
    from dataclasses import asdict
    from mokioclaw.dashboard.task_diagnostics import CalibrationObservationManager
    from mokioclaw.dashboard.task_diagnostic_viewer import ViewerController
    from mokioclaw.dashboard.task_handoff_observation import HandoffScores
    from test_task_diagnostics import prepared
    from tests.dashboard.task_observation_fakes import INSTANCE_ID
    record = prepared(tmp_path)
    manager = CalibrationObservationManager(tmp_path, task_lookup=lambda _: record, clock=lambda: 0)
    assert manager.bind(TASK_ID)
    record.state = "running"
    assert manager.worker_bootstrap(TASK_ID)
    base = {"schema_version": 1, "task_id": TASK_ID, "instance_id": INSTANCE_ID, "attempt_id": 1}
    assert manager.receive_worker({**base, "kind": "hello", "sequence": 1})
    assert manager.receive_worker({**base, "kind": "handoff_oversize", "sequence": 2, "bytes": 65537})
    try:
        view = manager.memory._current
        assert view is not None and not view.inspectable and view.summary is None
        def request(*args, **kwargs):
            return {"accepted": True, "valid": True, "bound_task": TASK_ID, "view": asdict(view)}
        text = []
        viewer = ViewerController(request=request, render_text=text.append)
        viewer.poll()
        assert viewer.notice == "oversize" and text[-1] == ""
        assert not viewer.submit_scores(HandoffScores(**dict.fromkeys(HandoffScores.__dataclass_fields__, "pass")))
        assert manager.memory.indexes[-1]["status"] == "oversize"
    finally:
        manager.close()
