"""JSON byte frames and injected transport only; no actual pipes."""
import json

import pytest

from tests.dashboard.task_observation_fakes import TASK_ID, INSTANCE_ID, offline_observation_guard, utc_clock


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    with offline_observation_guard(monkeypatch):
        yield


def message(kind="handoff", **extra):
    return {"schema_version": 1, "kind": kind, "task_id": TASK_ID,
            "instance_id": INSTANCE_ID, "attempt_id": 1, "sequence": 1, **extra}


def test_json_frames_and_escape_expansion():
    from mokioclaw.dashboard.task_diagnostic_ipc import encode_frame, decode_frame
    frame = message(summary="\x00" * 65536)
    encoded = encode_frame(frame, role="worker")
    assert len(encoded) < 409600 and len(encoded) > 393216
    assert decode_frame(encoded, role="worker") == frame
    for bad in (encoded + b" ", b'{"kind":"hello","kind":"fault"}', b"x" * 409601):
        if bad == encoded + b" ":
            continue
        with pytest.raises(ValueError, match="calibration_observation_invalid"):
            decode_frame(bad, role="worker")


@pytest.mark.parametrize("kind, role", [("score", "worker"), ("bind", "worker"), ("numeric", "viewer"), ("handoff", "viewer")])
def test_roles_are_separate(kind, role):
    from mokioclaw.dashboard.task_diagnostic_ipc import encode_frame
    with pytest.raises(ValueError, match="calibration_observation_invalid"):
        encode_frame(message(kind), role=role)


@pytest.mark.parametrize("sequence", [1024, 1025, 2**63 - 1])
@pytest.mark.parametrize("kind", ["poll", "state", "ack"])
def test_viewer_sequence_limits(sequence, kind):
    from mokioclaw.dashboard.task_diagnostic_ipc import encode_frame, decode_frame
    frame = {"schema_version": 1, "kind": kind, "sequence": sequence}
    if kind == "state":
        frame.update(bound_task=None, view=None, valid=True, accepted=True)
    assert decode_frame(encode_frame(frame, role="viewer"), role="viewer") == frame


@pytest.mark.parametrize("role, sequence", [
    ("viewer", 0), ("viewer", -1), ("viewer", True), ("viewer", 1.0),
    ("viewer", 2**63), ("worker", 0), ("worker", -1),
    ("worker", True), ("worker", 1.0), ("worker", 1025),
])
@pytest.mark.parametrize("kind", ["hello", "ack"])
def test_invalid_sequence_rejected_in_both_directions(role, sequence, kind):
    from mokioclaw.dashboard.task_diagnostic_ipc import encode_frame, decode_frame
    frame = {"schema_version": 1, "kind": kind, "sequence": sequence}
    if role == "worker" and kind == "hello":
        frame.update(task_id=TASK_ID, instance_id=INSTANCE_ID, attempt_id=1)
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        encode_frame(frame, role=role)
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        decode_frame(json.dumps(frame).encode(), role=role)


@pytest.mark.parametrize("kind", ["hello", "ack"])
def test_unknown_role_cannot_bypass_validation(kind):
    from mokioclaw.dashboard.task_diagnostic_ipc import encode_frame, decode_frame
    frame = {"schema_version": 1, "kind": kind, "sequence": 1}
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        encode_frame(frame, role="unknown")
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        decode_frame(json.dumps(frame).encode(), role="unknown")


@pytest.mark.parametrize("kind", ["hello", "ack"])
def test_worker_sequence_1024_remains_accepted(kind):
    from mokioclaw.dashboard.task_diagnostic_ipc import encode_frame, decode_frame
    frame = {"schema_version": 1, "kind": kind, "sequence": 1024}
    if kind == "hello":
        frame.update(task_id=TASK_ID, instance_id=INSTANCE_ID, attempt_id=1)
    assert decode_frame(encode_frame(frame, role="worker"), role="worker") == frame


def test_worker_missing_ready_does_not_start():
    from mokioclaw.dashboard.task_diagnostic_ipc import DiagnosticBootstrap, WorkerDiagnosticClient
    class NoAck:
        def send_bytes(self, data): pass
        def poll(self, timeout): return False
        def recv_bytes(self, maxlength): raise AssertionError
        def close(self): pass
    bootstrap = DiagnosticBootstrap("synthetic_pipe", b"a" * 32, "worker", TASK_ID, INSTANCE_ID, 1)
    with pytest.raises(ValueError, match="calibration_observation_invalid"):
        WorkerDiagnosticClient(bootstrap, connect=lambda b: NoAck())


def test_worker_byte_only_background_order_and_fault():
    from mokioclaw.dashboard.task_diagnostic_ipc import DiagnosticBootstrap, WorkerDiagnosticClient
    from mokioclaw.core.task_observation import TaskObservation, ObservationRecord
    class Ack:
        def __init__(self):
            self.sent = []
            self.sequence = 0
        def send_bytes(self, data):
            self.sent.append(json.loads(data))
            self.sequence = self.sent[-1]["sequence"]
        def poll(self, timeout): return True
        def recv_bytes(self, maxlength):
            return json.dumps({"schema_version": 1, "kind": "ack", "sequence": self.sequence}).encode()
        def close(self): pass
    ack = Ack()
    bootstrap = DiagnosticBootstrap("synthetic_pipe", b"a" * 32, "worker", TASK_ID, INSTANCE_ID, 1)
    client = WorkerDiagnosticClient(bootstrap, connect=lambda b: ack)
    observer = TaskObservation(TASK_ID, client, utc_clock=utc_clock)
    assert observer.emit(ObservationRecord(TASK_ID, 1, "invoke_started", call_no=1, stage="planner", status="started"))
    assert client.accept_handoff(1, "\x00" * 65536)
    client.finish(dict.fromkeys([s + n for s in ("entry", "chat", "planner", "code_agent", "verifier", "context_compressor")
                               for n in ("_calls", "_reported_tokens")], 0))
    client.close()
    assert client.valid
    assert [m["kind"] for m in ack.sent] == ["hello", "numeric", "handoff", "end"]
    assert "summary" not in ack.sent[1]


def test_pending_summary_collision_and_queue_are_invalid():
    from mokioclaw.dashboard.task_diagnostic_ipc import DiagnosticBootstrap, WorkerDiagnosticClient
    class Block:
        def send_bytes(self, data): pass
        def poll(self, timeout): return True
        def recv_bytes(self, maxlength): return b'{"schema_version":1,"kind":"ack","sequence":1}'
        def close(self): pass
    client = WorkerDiagnosticClient(DiagnosticBootstrap("synthetic_pipe", b"a" * 32, "worker",
                                     TASK_ID, INSTANCE_ID, 1), connect=lambda b: Block(), start_thread=False)
    assert client.accept_handoff(1, "first")
    assert not client.accept_handoff(1, "second")
    assert not client.valid
    client.close()


def test_numeric_queue_cap_and_current_attempt_end():
    from mokioclaw.dashboard.task_diagnostic_ipc import DiagnosticBootstrap, WorkerDiagnosticClient
    from mokioclaw.core.task_observation import TaskObservation, ObservationRecord
    class Ack:
        def __init__(self): self.sent = []
        def send_bytes(self, data): self.sent.append(json.loads(data))
        def poll(self, timeout): return True
        def recv_bytes(self, maxlength):
            return json.dumps({"schema_version": 1, "kind": "ack", "sequence": self.sent[-1]["sequence"]}).encode()
        def close(self): pass
    ack = Ack()
    bootstrap = DiagnosticBootstrap("synthetic_pipe", b"a" * 32, "worker", TASK_ID, INSTANCE_ID, 1)
    client = WorkerDiagnosticClient(bootstrap, connect=lambda b: ack, start_thread=False)
    observer = TaskObservation(TASK_ID, client, utc_clock=utc_clock)
    for _ in range(32):
        assert observer.emit(ObservationRecord(TASK_ID, 1, "policy_decision"))
    assert not observer.emit(ObservationRecord(TASK_ID, 1, "policy_decision"))
    assert not client.valid
    client.close()
    ack = Ack()
    client = WorkerDiagnosticClient(bootstrap, connect=lambda b: ack)
    observer = TaskObservation(TASK_ID, client, utc_clock=utc_clock)
    assert observer.emit(ObservationRecord(TASK_ID, 2, "policy_decision"))
    client.finish(dict.fromkeys([s + n for s in ("entry", "chat", "planner", "code_agent", "verifier", "context_compressor")
                                for n in ("_calls", "_reported_tokens")], 0))
    client.close()
    assert client.valid and ack.sent[-1]["attempt_id"] == 2


def test_wrong_authentication_key_uses_safe_error(monkeypatch):
    import multiprocessing.connection
    from mokioclaw.dashboard.task_diagnostic_ipc import DiagnosticBootstrap, connect_pipe
    from multiprocessing import AuthenticationError
    calls = []
    def fake_client(address, *, family, authkey):
        calls.append((address, family, authkey))
        raise AuthenticationError("PRIVATE_AUTH_EXCEPTION")
    with monkeypatch.context() as patch:
        patch.setattr(multiprocessing.connection, "Client", fake_client)
        with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
            connect_pipe(DiagnosticBootstrap("synthetic_pipe", b"b" * 32, "worker", TASK_ID, INSTANCE_ID, 1))
    assert calls == [("synthetic_pipe", "AF_PIPE", b"b" * 32)]


def test_blocked_started_write_invalidates_without_waiting_for_model():
    from threading import Event
    from mokioclaw.dashboard.task_diagnostic_ipc import DiagnosticBootstrap, WorkerDiagnosticClient
    from mokioclaw.core.task_observation import TaskObservation, ObservationRecord
    blocked, released = Event(), Event()
    class Channel:
        sequence = 0
        def send_bytes(self, data):
            frame = json.loads(data)
            self.sequence = frame["sequence"]
            if frame["kind"] == "numeric":
                blocked.set()
                released.wait(4)
        def poll(self, timeout): return True
        def recv_bytes(self, maxlength):
            return json.dumps({"schema_version": 1, "kind": "ack", "sequence": self.sequence}).encode()
        def close(self): released.set()
    client = WorkerDiagnosticClient(DiagnosticBootstrap("synthetic_pipe", b"a" * 32, "worker",
                                     TASK_ID, INSTANCE_ID, 1), connect=lambda b: Channel())
    try:
        observation = TaskObservation(TASK_ID, client, utc_clock=utc_clock)
        assert observation.emit(ObservationRecord(TASK_ID, 1, "invoke_started", stage="planner",
                                                 call_no=1, status="started"))
        assert blocked.wait(1)
        assert released.wait(2)
        assert not client.valid
    finally:
        released.set()
        client.close()
