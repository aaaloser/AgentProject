"""Authenticated private byte-only JSON IPC; never a command or provider channel."""
from dataclasses import asdict, dataclass
from collections import deque
import json
import queue
import threading
import time
from typing import Callable, Literal, Protocol

from mokioclaw.core.task_observation import OPAQUE_ID, STAGES, encode_record, record_from_dict
from mokioclaw.dashboard.task_handoff_observation import HandoffScores, valid_scores

MAX_FRAME = 409600
ERROR = "calibration_observation_invalid"


class ByteConnection(Protocol):
    def send_bytes(self, data: bytes) -> None: ...
    def recv_bytes(self, maxlength: int) -> bytes: ...
    def poll(self, timeout: float) -> bool: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class DiagnosticBootstrap:
    pipe_name: str
    authkey: bytes
    role: Literal["worker", "viewer"]
    task_id: str | None = None
    instance_id: str | None = None
    attempt_id: int | None = None

    def validate(self):
        if (type(self.pipe_name) is not str or not 1 <= len(self.pipe_name) <= 200
                or type(self.authkey) is not bytes or len(self.authkey) != 32
                or self.role not in {"worker", "viewer"}):
            raise ValueError(ERROR)
        if self.role == "worker":
            _identity(asdict(self))
        elif any(v is not None for v in (self.task_id, self.instance_id, self.attempt_id)):
            raise ValueError(ERROR)


def bootstrap_to_wire(bootstrap):
    bootstrap.validate()
    return {**asdict(bootstrap), "authkey": bootstrap.authkey.hex()}


def bootstrap_from_wire(data):
    try:
        if type(data) is not dict or data.keys() != DiagnosticBootstrap.__dataclass_fields__.keys():
            raise ValueError
        if type(data["authkey"]) is not str or len(data["authkey"]) != 64:
            raise ValueError
        result = DiagnosticBootstrap(**{**data, "authkey": bytes.fromhex(data["authkey"])})
        result.validate()
        return result
    except (ValueError, TypeError, KeyError):
        raise ValueError(ERROR) from None


def _opaque(value):
    return type(value) is str and OPAQUE_ID.fullmatch(value) is not None


def _identity(data):
    if (not _opaque(data.get("task_id")) or not _opaque(data.get("instance_id"))
            or type(data.get("attempt_id")) is not int or not 1 <= data["attempt_id"] <= 3):
        raise ValueError(ERROR)


def valid_usage(data):
    return (type(data) is dict and set(data) == {s + n for s in STAGES for n in ("_calls", "_reported_tokens")}
            and all(type(v) is int and v >= 0 for v in data.values())
            and sum(data[s + "_calls"] for s in STAGES) <= 24)


def _handoff_identity(data):
    if (type(data) is not dict or set(data) != {"task_id", "attempt_id", "ordinal"}
            or not _opaque(data["task_id"]) or type(data["attempt_id"]) is not int
            or not 1 <= data["attempt_id"] <= 3 or type(data["ordinal"]) is not int
            or not 1 <= data["ordinal"] <= 24):
        raise ValueError(ERROR)


def _validate_frame(data, role):
    if role not in ("worker", "viewer"):
        raise ValueError(ERROR)
    if type(data) is not dict or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError(ERROR)
    # Viewer polling lasts beyond a finite worker stream; neither counter wraps.
    sequence_limit = 2**63 - 1 if role == "viewer" else 1024
    if type(data.get("sequence")) is not int or not 1 <= data["sequence"] <= sequence_limit:
        raise ValueError(ERROR)
    base = {"schema_version", "kind", "sequence"}
    kind = data.get("kind")
    if type(kind) is not str:
        raise ValueError(ERROR)
    if kind == "ack":
        if set(data) != base:
            raise ValueError(ERROR)
        return
    if role == "worker":
        base |= {"task_id", "instance_id", "attempt_id"}
        _identity(data)
        extras = {"hello": set(), "numeric": {"record"}, "handoff": {"summary"},
                  "handoff_oversize": {"bytes"}, "end": {"usage"}, "fault": {"reason"}}
        if kind not in extras or set(data) != base | extras[kind]:
            raise ValueError(ERROR)
        if kind == "numeric":
            row = record_from_dict(data["record"])
            if row.task_id != data["task_id"] or row.attempt_id != data["attempt_id"]:
                raise ValueError(ERROR)
        if kind == "handoff" and (type(data["summary"]) is not str or len(data["summary"].encode("utf-8")) > 65536):
            raise ValueError(ERROR)
        if kind == "handoff_oversize" and (type(data["bytes"]) is not int or data["bytes"] <= 65536):
            raise ValueError(ERROR)
        if kind == "end" and not valid_usage(data["usage"]):
            raise ValueError(ERROR)
        if kind == "fault" and data["reason"] != ERROR:
            raise ValueError(ERROR)
    elif role == "viewer":
        extras = {"hello": set(), "poll": set(), "close": set(), "bind": {"task_id"},
                  "score": {"identity", "scores"}, "state": {"bound_task", "view", "valid", "accepted"}}
        if kind not in extras or set(data) != base | extras[kind]:
            raise ValueError(ERROR)
        if kind == "bind" and not _opaque(data["task_id"]):
            raise ValueError(ERROR)
        if kind == "score":
            _handoff_identity(data["identity"])
            if type(data["scores"]) is not dict or set(data["scores"]) != set(HandoffScores.__dataclass_fields__):
                raise ValueError(ERROR)
            if not valid_scores(HandoffScores(**data["scores"])):
                raise ValueError(ERROR)
        if kind == "state":
            if ((data["bound_task"] is not None and not _opaque(data["bound_task"]))
                    or type(data["valid"]) is not bool or type(data["accepted"]) is not bool):
                raise ValueError(ERROR)
            view = data["view"]
            if view is not None:
                if type(view) is not dict or set(view) != {"identity", "summary", "inspectable"}:
                    raise ValueError(ERROR)
                _handoff_identity(view["identity"])
                if type(view["inspectable"]) is not bool:
                    raise ValueError(ERROR)
                if view["inspectable"]:
                    if type(view["summary"]) is not str or len(view["summary"].encode("utf-8")) > 65536:
                        raise ValueError(ERROR)
                elif view["summary"] is not None:
                    raise ValueError(ERROR)
    else:
        raise ValueError(ERROR)


def encode_frame(message, *, role):
    try:
        _validate_frame(message, role)
        data = json.dumps(message, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False).encode("utf-8")
        if len(data) > MAX_FRAME:
            raise ValueError
        return data
    except (TypeError, ValueError, KeyError, UnicodeError):
        raise ValueError(ERROR) from None


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(ERROR)
        result[key] = value
    return result


def decode_frame(data, *, role):
    try:
        if type(data) is not bytes or len(data) > MAX_FRAME:
            raise ValueError
        value = json.loads(data, object_pairs_hook=_unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError(ERROR)))
        _validate_frame(value, role)
        return value
    except (TypeError, ValueError, KeyError, UnicodeError, RecursionError):
        raise ValueError(ERROR) from None


def connect_pipe(bootstrap):
    """Bound production connect, including late connection cleanup."""
    from multiprocessing.connection import Client
    bootstrap.validate()
    result = queue.Queue(maxsize=1)
    expired = threading.Event()
    def connect():
        try:
            conn = Client(bootstrap.pipe_name, family="AF_PIPE", authkey=bootstrap.authkey)
            if expired.is_set():
                conn.close()
            else:
                result.put(conn)
        except Exception:
            if not expired.is_set():
                result.put(None)
    threading.Thread(target=connect, daemon=True, name="private-diagnostic-connect").start()
    try:
        conn = result.get(timeout=3)
    except queue.Empty:
        expired.set()
        raise ValueError(ERROR) from None
    if conn is None:
        raise ValueError(ERROR)
    return conn


class WorkerDiagnosticClient:
    def __init__(self, bootstrap: DiagnosticBootstrap, *, connect: Callable = connect_pipe,
                 start_thread=True):
        bootstrap.validate()
        if bootstrap.role != "worker":
            raise ValueError(ERROR)
        self.bootstrap = bootstrap
        self.valid = True
        self._condition = threading.Condition()
        self._pending = deque()
        self._numeric_pending = 0
        self._handoff_pending = False
        self._sequence = 0
        self._ending = False
        self._closed = False
        self._inflight_deadline = None
        self._watch_stop = threading.Event()
        self._attempt = bootstrap.attempt_id
        started = time.monotonic()
        self._connection = connect(bootstrap)
        try:
            remaining = 3 - (time.monotonic() - started)
            if remaining <= 0:
                raise ValueError
            self._exchange("hello", {}, bootstrap.attempt_id, timeout=remaining)
        except Exception:
            self._connection.close()
            raise ValueError(ERROR) from None
        self._thread = threading.Thread(target=self._pump, name="private-task-observation", daemon=True)
        self._watch = threading.Thread(target=self._watch_ack, name="private-task-ack-deadline", daemon=True)
        if start_thread:
            self._thread.start()
            self._watch.start()

    def _watch_ack(self):
        while not self._watch_stop.wait(0.05):
            with self._condition:
                expired = self._inflight_deadline is not None and time.monotonic() >= self._inflight_deadline
            if expired:
                self.invalidate()
                try:
                    self._connection.close()
                except Exception:
                    pass
                return

    def _exchange(self, kind, values, attempt, timeout=1):
        self._sequence += 1
        started = time.monotonic()
        frame = {"schema_version": 1, "kind": kind, "task_id": self.bootstrap.task_id,
                 "instance_id": self.bootstrap.instance_id, "attempt_id": attempt,
                 "sequence": self._sequence, **values}
        self._connection.send_bytes(encode_frame(frame, role="worker"))
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0 or not self._connection.poll(remaining):
            raise ValueError(ERROR)
        ack = decode_frame(self._connection.recv_bytes(MAX_FRAME), role="worker")
        if ack != {"schema_version": 1, "kind": "ack", "sequence": self._sequence}:
            raise ValueError(ERROR)

    def invalidate(self):
        with self._condition:
            self.valid = False
            self._pending.clear()
            self._numeric_pending = 0
            self._handoff_pending = False
            self._condition.notify_all()

    def _enqueue(self, kind, values, attempt):
        with self._condition:
            if not self.valid or self._closed or self._ending:
                return False
            if kind == "numeric" and self._numeric_pending >= 32:
                self.invalidate()
                return False
            if kind in {"handoff", "handoff_oversize"} and self._handoff_pending:
                self.invalidate()
                return False
            if kind == "numeric":
                self._numeric_pending += 1
            if kind in {"handoff", "handoff_oversize"}:
                self._handoff_pending = True
            self._attempt = attempt
            self._pending.append((kind, values, attempt))
            self._condition.notify_all()
            return True

    def emit(self, record):
        try:
            encode_record(record)
            if record.task_id != self.bootstrap.task_id:
                raise ValueError
            return self._enqueue("numeric", {"record": asdict(record)}, record.attempt_id)
        except Exception:
            self.invalidate()
            return False

    def accept_handoff(self, attempt_id, summary):
        try:
            if type(summary) is not str or type(attempt_id) is not int or not 1 <= attempt_id <= 3:
                raise ValueError
            size = len(summary.encode("utf-8"))
            return self._enqueue("handoff" if size <= 65536 else "handoff_oversize",
                                 {"summary": summary} if size <= 65536 else {"bytes": size}, attempt_id)
        except Exception:
            self.invalidate()
            return False

    def finish(self, usage):
        if not valid_usage(usage):
            self.invalidate()
            return
        with self._condition:
            if not self.valid or self._ending:
                return
            self._pending.append(("end", {"usage": dict(usage)}, self._attempt))
            self._ending = True
            self._condition.notify_all()

    def _pump(self):
        try:
            while True:
                with self._condition:
                    self._condition.wait_for(lambda: self._pending or self._closed or not self.valid)
                    if not self.valid:
                        break
                    if not self._pending:
                        break
                    kind, values, attempt = self._pending.popleft()
                    self._inflight_deadline = time.monotonic() + 1
                self._exchange(kind, values, attempt)
                values.clear()
                with self._condition:
                    self._inflight_deadline = None
                    if kind == "numeric":
                        self._numeric_pending -= 1
                    if kind in {"handoff", "handoff_oversize"}:
                        self._handoff_pending = False
                    self._condition.notify_all()
        except Exception:
            self.invalidate()
        finally:
            self._watch_stop.set()
            if not self.valid:
                try:
                    self._exchange("fault", {"reason": ERROR}, self._attempt)
                except Exception:
                    pass
            self._connection.close()

    def close(self):
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        if self._thread.is_alive():
            self._thread.join(timeout=1)
        if self._thread.is_alive() or self._pending:
            self.invalidate()
            self._connection.close()
        elif self._thread.ident is None:
            self._connection.close()
        self._watch_stop.set()
        if self._watch.is_alive():
            self._watch.join(timeout=0.1)
