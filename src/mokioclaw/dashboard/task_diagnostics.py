"""Parent-only numeric journals and private single-task observation lifetime."""
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import secrets
import threading
import time
from functools import wraps

from mokioclaw.core.task_observation import OPAQUE_ID, ObservationReconciliation, encode_record, reconcile
from mokioclaw.dashboard.task_handoff_observation import (
    HandoffIdentity, HandoffMemory, HandoffScores, valid_scores,
)
from mokioclaw.dashboard.task_diagnostic_ipc import (
    DiagnosticBootstrap, ERROR, MAX_FRAME, decode_frame, encode_frame, record_from_dict,
)


def _safe_path(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.exists() or part.is_symlink():
            stat = part.lstat()
            if part.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
                raise ValueError(ERROR)
    return path


def _json(data, limit):
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > limit:
        raise ValueError(ERROR)
    return encoded


def _journal_writer(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self._lock:
            if self._sealed:
                if method.__name__ in {"emit", "write_scores", "set_indexes"}:
                    return False
                if method.__name__ == "finalize" and self._result is not None:
                    return self._result
                raise ValueError(ERROR)
            return method(self, *args, **kwargs)
    return guarded


class NumericJournal:
    def __init__(self, root: Path, task_id: str, *, session=None):
        self.valid = True
        self._session = session
        self._owned_handles = []
        self._sealed = False
        self._io_failed = False
        self._close_failed = False
        self._lock = threading.RLock()
        self._records, self._scores = [], {}
        self._handles = []
        self._result = None
        try:
            if type(task_id) is not str or OPAQUE_ID.fullmatch(task_id) is None:
                raise ValueError
            self.task_id = task_id
            if session is None:
                root = _safe_path(root)
                directory = _safe_path(root / "observations" / task_id)
                directory.mkdir(parents=True, exist_ok=True)
                _safe_path(directory)
                for name in ("calls.jsonl", "scores.json", "status.json"):
                    path = _safe_path(directory / name)
                    handle = path.open("xb")
                    self._handles.append(handle)
            else:
                if session.owner.options.task_id != task_id:
                    raise ValueError(ERROR)
                self._owned_handles = list(session.create_journal_files())
                self._handles = [handle.stream for handle in self._owned_handles]
            self._write(2, {"schema_version": 1, "task_id": task_id, "valid": False,
                            "reason": "stream_incomplete"}, 4096)
            if session is not None:
                for handle in self._handles:
                    handle.flush()
                    os.fsync(handle.fileno())
        except Exception:
            if self._session is not None:
                self._session.failed_journal = self
                self.seal_and_close()
            else:
                self.close()
            raise ValueError(ERROR) from None

    def is_initial(self):
        with self._lock:
            try:
                if (self._sealed or not self.valid or self._records or self._scores or self._result is not None
                        or self._session is None):
                    return False
                self._session.verify_layout()
                if any(handle.size() != 0 for handle in self._owned_handles[:2]):
                    return False
                from mokioclaw.dashboard.task_observation_continuation import strict_json
                value = strict_json(self._owned_handles[2].read_bounded(4096))
                initial = {"schema_version": 1, "task_id": self.task_id, "valid": False, "reason": "stream_incomplete"}
                return _json(value, 4096) == _json(initial, 4096)
            except Exception:
                return False

    @_journal_writer
    def _write(self, index, data, limit):
        encoded = _json(data, limit)
        handle = self._handles[index]
        handle.seek(0)
        if handle.write(encoded) != len(encoded):
            raise ValueError(ERROR)
        handle.truncate()
        handle.flush()
        if self._session is not None:
            os.fsync(handle.fileno())

    @_journal_writer
    def emit(self, record):
        try:
            if (not self.valid or self._result is not None or record.task_id != self.task_id
                    or len(self._records) >= 512 or record.event_sequence != len(self._records) + 1):
                raise ValueError
            encoded = encode_record(record)
            if self._handles[0].write(encoded + b"\n") != len(encoded) + 1:
                raise ValueError(ERROR)
            self._handles[0].flush()
            if self._session is not None:
                os.fsync(self._handles[0].fileno())
            self._records.append(record)
            return True
        except Exception:
            self.valid = False
            self._io_failed = True
            return False

    def invalidate(self):
        self.valid = False

    @_journal_writer
    def write_scores(self, identity: HandoffIdentity, scores: HandoffScores):
        if (type(identity) is not HandoffIdentity or identity.task_id != self.task_id
                or type(identity.ordinal) is not int or not 1 <= identity.ordinal <= 24
                or type(identity.attempt_id) is not int or not 1 <= identity.attempt_id <= 3
                or not valid_scores(scores) or self._result is not None):
            return False
        self._scores[identity.ordinal] = {"identity": asdict(identity), "scores": asdict(scores),
                                         "status": "unreviewed", "bytes": 0}
        return True

    @_journal_writer
    def set_indexes(self, indexes):
        try:
            if len(indexes) > 24:
                raise ValueError
            values = {}
            for row in indexes:
                if type(row) is not dict or set(row) != {"identity", "scores", "status", "bytes"}:
                    raise ValueError
                identity, scores = HandoffIdentity(**row["identity"]), HandoffScores(**row["scores"])
                if (not self.write_scores(identity, scores) or type(row["bytes"]) is not int
                        or row["bytes"] < 0 or row["status"] not in {"pending", "reviewed", "unreviewed", "oversize", "absent"}):
                    raise ValueError
                values[identity.ordinal] = {**row, "identity": asdict(identity), "scores": asdict(scores)}
            if set(values) != set(range(1, len(values) + 1)):
                raise ValueError
            self._scores = values
            return True
        except Exception:
            self.valid = False
            return False

    @_journal_writer
    def finalize(self, final_usage, *, stream_closed, cleanup_confirmed):
        if self._result is not None:
            return self._result
        checked = reconcile(self._records, final_usage)
        reasons = set(checked.reasons)
        if not self.valid:
            reasons.add("observer_fault")
        if stream_closed is not True:
            reasons.add("stream_incomplete")
        if cleanup_confirmed is not True:
            reasons.add("cleanup_unconfirmed")
        result = ObservationReconciliation(not reasons, checked.started_calls, checked.unknown_calls, tuple(sorted(reasons)))
        try:
            self._write(1, {"schema_version": 1, "task_id": self.task_id,
                            "indexes": [self._scores[n] for n in sorted(self._scores)]}, 65536)
            self._write(2, {"schema_version": 1, "task_id": self.task_id, "valid": result.valid,
                            "event_count": len(self._records), "started_calls": result.started_calls,
                            "unknown_calls": result.unknown_calls, "reasons": result.reasons,
                            "stream_closed": stream_closed is True, "cleanup_confirmed": cleanup_confirmed is True}, 4096)
        except Exception:
            self.valid = False
            result = ObservationReconciliation(False, checked.started_calls, checked.unknown_calls, ("observer_fault",))
            self._io_failed = True
        self._result = result
        return result

    def close(self):
        if self._session is not None:
            self.seal_and_close()
            return
        for handle in getattr(self, "_handles", ()):
            try:
                handle.close()
            except Exception:
                self.valid = False

    def seal_and_close(self):
        with self._lock:
            self._sealed = True
            if self._close_failed:
                raise ValueError(ERROR)
            failed = False
            for handle in self._owned_handles or self._handles:
                try:
                    handle.close()
                    if not handle.closed:
                        failed = True
                except Exception:
                    failed = True
            if failed:
                self._close_failed = True
                raise ValueError(ERROR) from None


@dataclass(frozen=True)
class ViewerBindReservation:
    task_id: str
    sequence: int
    generation: int


@dataclass(frozen=True)
class ObservationCloseResult:
    writers_revoked: bool
    journal_closed: bool
    channels_closed: bool
    callbacks_safe: bool

    @property
    def confirmed(self):
        return all((self.writers_revoked, self.journal_closed, self.channels_closed, self.callbacks_safe))


class CalibrationObservationManager:
    def __init__(self, root: Path, *, task_lookup, clock=time.monotonic, listener_factory=None,
                 continuation_task_id=None, viewer_handler=None):
        self.root = Path(root).absolute() if continuation_task_id is not None else _safe_path(root)
        if continuation_task_id is None and not self.root.is_dir():
            raise ValueError(ERROR)
        self.continuation_task_id = continuation_task_id
        self._viewer_handler = viewer_handler
        self._generation = 0
        self.session = None
        self._lookup, self._clock = task_lookup, clock
        self._listener_factory = listener_factory
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._listeners, self._connections, self._threads = [], [], []
        self._worker_bootstrap = None
        self._sequence = 0
        self._viewer_sequence = 0
        self._terminal_at = None
        self._usage = {}
        self._stream_closed = False
        self._finalized = False
        self.task_id = None
        self.memory = None
        self.journal = None
        self.valid = True
        self.viewer_ready = False
        self.viewer_bootstrap = self._bootstrap("viewer")
        self._viewer_launch = None

    def _bootstrap(self, role, task_id=None, instance_id=None, attempt_id=None):
        pipe = "\\\\.\\pipe\\mokioclaw-observation-" + secrets.token_hex(16)
        return DiagnosticBootstrap(pipe, secrets.token_bytes(32), role, task_id, instance_id, attempt_id)

    def invalidate(self):
        with self._lock:
            self._generation += 1
            self.valid = False
            if self.memory is not None:
                self.memory.clear()
            if self.journal is not None:
                self.journal.valid = False
        # Caller/UI displays only this fixed code; no exception or body logging.

    def bind(self, task_id):
        with self._lock:
            if self.continuation_task_id is not None:
                return False
            try:
                if self.task_id is not None or not self.valid or type(task_id) is not str or not OPAQUE_ID.fullmatch(task_id):
                    return False
                record = self._lookup(task_id)
                directory = _safe_path(self.root / "tasks" / task_id)
                if record.state != "prepared" or record.task_id != task_id or not directory.is_dir():
                    return False
                if directory.resolve().parent != (self.root / "tasks").resolve():
                    return False
                self.journal = NumericJournal(self.root, task_id)
                self.memory = HandoffMemory(task_id)
                self.task_id = task_id
                return True
            except Exception:
                self.invalidate()
                return False

    def reserve_continuation_bind(self, frame):
        with self._lock:
            try:
                encode_frame(frame, role="viewer")
                if (self.continuation_task_id is None or not self.valid or self._stop.is_set()
                        or not self.viewer_ready or self.task_id is not None or frame["kind"] != "bind"
                        or frame["task_id"] != self.continuation_task_id or self._viewer_sequence == 0
                        or frame["sequence"] != self._viewer_sequence + 1):
                    raise ValueError(ERROR)
                self._viewer_sequence += 1
                return ViewerBindReservation(frame["task_id"], frame["sequence"], self._generation)
            except Exception:
                self.invalidate()
                raise ValueError(ERROR) from None

    def commit_continuation_bind(self, reservation, session, journal):
        with self._lock:
            if (reservation.generation != self._generation or self._stop.is_set() or not self.valid
                    or not self.viewer_ready or self.task_id is not None or not journal.is_initial()
                    or reservation.task_id != self.continuation_task_id or reservation.sequence != self._viewer_sequence):
                raise ValueError(ERROR)
            self.task_id, self.session, self.journal = reservation.task_id, session, journal
            self.memory = HandoffMemory(reservation.task_id)
            return self._viewer_state(reservation.sequence, True)

    def _viewer_state(self, sequence, accepted):
        view = self.memory._current if self.valid and self.memory is not None else None
        return {"schema_version": 1, "kind": "state", "sequence": sequence,
                "bound_task": self.task_id, "view": asdict(view) if view is not None else None,
                "valid": self.valid, "accepted": bool(accepted)}

    def ready_for_start(self, task_id):
        with self._lock:
            return (self.valid and not self._stop.is_set() and self.viewer_ready
                    and task_id == self.task_id and self.journal is not None and self.journal.valid)

    def worker_bootstrap(self, task_id):
        with self._lock:
            try:
                if self._stop.is_set() or task_id != self.task_id or not self.valid or self._worker_bootstrap is not None:
                    return None
                record = self._lookup(task_id)
                if record.state != "running" or record.task_id != task_id:
                    return None
                bootstrap = self._bootstrap("worker", task_id, record.instance_id, record.attempt_id)
                bootstrap.validate()
                self._worker_bootstrap = bootstrap
                if self._listeners:
                    self._start_role(bootstrap)
                return bootstrap
            except Exception:
                self.invalidate()
                return None

    def receive_worker(self, frame):
        with self._lock:
            if self._stop.is_set():
                return False
            try:
                encode_frame(frame, role="worker")
                bootstrap = self._worker_bootstrap
                record = self._lookup(self.task_id)
                if (not self.valid or bootstrap is None or self._stream_closed
                        or frame["task_id"] != self.task_id or frame["instance_id"] != bootstrap.instance_id
                        or record.instance_id != bootstrap.instance_id
                        or frame["attempt_id"] != record.attempt_id
                        or frame["sequence"] != self._sequence + 1
                        or (self._sequence == 0) != (frame["kind"] == "hello")):
                    raise ValueError
                self._sequence += 1
                kind = frame["kind"]
                self._clear_stale_attempt(record.attempt_id)
                if kind == "numeric":
                    if not self.journal.emit(record_from_dict(frame["record"])):
                        raise ValueError
                elif kind == "handoff":
                    if self.memory.accept(record.attempt_id, frame["summary"]) is None:
                        raise ValueError
                elif kind == "handoff_oversize":
                    # Preserve the size/index without accepting any partial body.
                    identity = self.memory.accept_oversize(record.attempt_id, frame["bytes"])
                    if identity is None:
                        raise ValueError
                elif kind == "end":
                    self._usage = dict(frame["usage"])
                    self._stream_closed = True
                elif kind == "fault":
                    raise ValueError
                return True
            except Exception:
                self.invalidate()
                return False

    def receive_viewer(self, frame):
        with self._lock:
            if self._stop.is_set():
                raise ValueError(ERROR)
            accepted = True
            try:
                encode_frame(frame, role="viewer")
                if frame["sequence"] != self._viewer_sequence + 1 or frame["kind"] not in {"hello", "poll", "bind", "score", "close"}:
                    raise ValueError
                if (self._viewer_sequence == 0) != (frame["kind"] == "hello"):
                    raise ValueError
                self._viewer_sequence += 1
                if frame["kind"] == "hello":
                    self.viewer_ready = True
                elif frame["kind"] == "bind":
                    accepted = self.bind(frame["task_id"])
                elif frame["kind"] == "score":
                    identity = HandoffIdentity(**frame["identity"])
                    record = self._lookup(self.task_id)
                    accepted = (self.memory is not None and identity.attempt_id == record.attempt_id
                                and self.memory.score(identity, HandoffScores(**frame["scores"])))
                elif frame["kind"] == "close":
                    self.viewer_ready = False
                    self.invalidate()
                if self.task_id is not None:
                    self._clear_stale_attempt(self._lookup(self.task_id).attempt_id)
                view = self.memory._current if self.valid and self.memory is not None else None
                return {"schema_version": 1, "kind": "state", "sequence": frame["sequence"],
                        "bound_task": self.task_id, "view": asdict(view) if view is not None else None,
                        "valid": self.valid, "accepted": bool(accepted)}
            except Exception:
                self.invalidate()
                raise ValueError(ERROR) from None

    def poll_terminal(self):
        with self._lock:
            if self._stop.is_set() or self.task_id is None or self._finalized:
                return
            try:
                record = self._lookup(self.task_id)
                self._clear_stale_attempt(record.attempt_id)
                if self._viewer_launch is not None and self._viewer_launch.process.poll() is not None:
                    self.viewer_ready = False
                    self.invalidate()
                if record.state == "cleanup_failed":
                    self.invalidate()
                    self._finalize(False)
                    return
                terminal = record.state in {"completed", "failed", "cancelled", "timed_out", "interrupted"}
                if terminal and record.cleanup_confirmed:
                    if self._terminal_at is None:
                        self._terminal_at = self._clock()
                    if not self.valid or self._clock() - self._terminal_at >= 600:
                        self._finalize(True)
            except Exception:
                self.invalidate()

    def _clear_stale_attempt(self, attempt):
        if (self.memory is not None and self.memory._current is not None
                and self.memory._current.identity.attempt_id != attempt):
            self.memory.clear()

    def _finalize(self, cleanup_confirmed):
        if self._finalized:
            return
        if self.memory is not None:
            self.memory.clear()
            self.journal.set_indexes(self.memory.indexes)
        if self.journal is not None:
            self.journal.finalize(self._usage, stream_closed=self._stream_closed,
                                  cleanup_confirmed=cleanup_confirmed)
            self.journal.close()
        self._finalized = True

    def _start_role(self, bootstrap):
        if self._listener_factory is None:
            from multiprocessing.connection import Listener
            factory = Listener
        else:
            factory = self._listener_factory
        listener = factory(bootstrap.pipe_name, family="AF_PIPE", authkey=bootstrap.authkey)
        self._listeners.append(listener)
        def serve():
            connection = None
            try:
                connection = listener.accept()
                self._connections.append(connection)
                while not self._stop.is_set():
                    if not connection.poll(1):
                        continue
                    frame = decode_frame(connection.recv_bytes(MAX_FRAME), role=bootstrap.role)
                    kind = frame["kind"]
                    if bootstrap.role == "worker":
                        if not self.receive_worker(frame):
                            break
                        reply = {"schema_version": 1, "kind": "ack", "sequence": frame["sequence"]}
                    else:
                        handler = self._viewer_handler or self.receive_viewer
                        reply = handler(frame)
                    connection.send_bytes(encode_frame(reply, role=bootstrap.role))
                    frame.clear()
                    reply.clear()
                    if kind in {"end", "close"}:
                        break
            except Exception:
                self.invalidate()
            finally:
                if connection is not None:
                    connection.close()
                if bootstrap.role == "worker" and not self._stream_closed:
                    self.invalidate()
                if bootstrap.role == "viewer":
                    self.viewer_ready = False
                    self.invalidate()
        thread = threading.Thread(target=serve, daemon=True, name="private-diagnostic-" + bootstrap.role)
        self._threads.append(thread)
        thread.start()

    def start_servers(self):
        if os.name != "nt" or self._listeners:
            raise ValueError(ERROR)
        try:
            self._start_role(self.viewer_bootstrap)
            def poll():
                while not self._stop.wait(1):
                    self.poll_terminal()
            thread = threading.Thread(target=poll, daemon=True, name="private-diagnostic-lifetime")
            self._threads.append(thread)
            thread.start()
        except Exception:
            self.close()
            raise ValueError(ERROR) from None

    def close(self):
        if self.continuation_task_id is not None:
            result = self.close_confirmed()
            if not result.confirmed:
                raise ValueError(ERROR)
            return
        self._stop.set()
        with self._lock:
            self.viewer_ready = False
            if not self._stream_closed:
                self.invalidate()
            confirmed = False
            if self.task_id is not None:
                try:
                    record = self._lookup(self.task_id)
                    confirmed = record.cleanup_confirmed is True and record.state in {
                        "completed", "failed", "cancelled", "timed_out", "interrupted"}
                except Exception:
                    self.invalidate()
            self._finalize(confirmed)
            for connection in self._connections:
                try:
                    connection.close()
                except Exception:
                    pass
            for listener in self._listeners:
                try:
                    listener.close()
                except Exception:
                    pass
        if self._viewer_launch is not None:
            self._viewer_launch.close()
        for thread in self._threads:
            if thread is not threading.current_thread():
                thread.join(timeout=0.1)

    def close_confirmed(self):
        # Callbacks check _stop under this lock; disk writers check _sealed
        # under the journal lock. A queued callback can regain neither.
        with self._lock:
            self._stop.set()
            self._generation += 1
            self.viewer_ready = False
            self.valid = False
            if not self._stream_closed and self.journal is not None:
                self.journal.invalidate()
            confirmed = False
            if self.task_id is not None:
                record = self._lookup(self.task_id)
                confirmed = record.cleanup_confirmed is True and record.state in {
                    "completed", "failed", "cancelled", "timed_out", "interrupted"}
            try:
                self._finalize(confirmed)
                if self.journal is not None:
                    self.journal.seal_and_close()
                    if self.journal._io_failed:
                        raise ValueError(ERROR)
            except Exception:
                if self.journal is not None:
                    self.journal.seal_and_close()
                raise ValueError(ERROR) from None
        try:
            for connection in self._connections:
                connection.close()
            for listener in self._listeners:
                listener.close()
            if self._viewer_launch is not None:
                self._viewer_launch.close()
                if self._viewer_launch.process.poll() is None:
                    raise ValueError(ERROR)
            for thread in self._threads:
                if thread is not threading.current_thread():
                    thread.join(timeout=1)
            # A blocked thread may remain; permanent sealing, not a short join,
            # confirms it cannot write again.
            return ObservationCloseResult(True, True, True, self.journal is None or self.journal._sealed)
        except Exception:
            raise ValueError(ERROR) from None
