"""N1–N4: real NTFS handles with synthetic contracts, no live service or IPC."""

from contextlib import contextmanager
import ctypes as c
import hashlib
import os
from pathlib import Path
import subprocess
import sys
from threading import Event, RLock, Thread
from types import SimpleNamespace

import pytest

from task_continuation_fakes import NAMES, SOURCE, TASK, SyntheticTask
from test_task_observation_handles_native import (
    backend, native_gate as native_gate, root as root, set_synthetic_junction,
)

pytestmark = pytest.mark.continuation_native_files


def sharing_conflict(action):
    with pytest.raises(OSError) as error:
        action()
    assert error.value.winerror == 32


def raw_open(api, path, access, *, disposition=3):
    handle = api.k.CreateFileW(str(path), access, 7, None, disposition, 0x02200000, None)
    if handle in (None, 0, c.c_void_p(-1).value):
        raise c.WinError(c.get_last_error())
    return handle


@pytest.mark.parametrize("relative", [
    "ancestor", "ancestor/nested", "ancestor/nested/calibration",
    "ancestor/nested/calibration/tasks", "ancestor/nested/calibration/tasks/synthetic_task_0001",
    "ancestor/nested/calibration/observations", "ancestor/nested/calibration/observations/synthetic_task_0001",
    "ancestor/nested/calibration/observations/synthetic_task_0001/sessions",
])
def test_native_each_directory_guard_prevents_swap(root, relative):
    # Losing any synthetic ancestor guard could redirect a later relative create.
    leaf = root / "ancestor/nested/calibration/observations" / TASK / "sessions"
    leaf.mkdir(parents=True)
    (root / "ancestor/nested/calibration/tasks" / TASK).mkdir(parents=True)
    target = root / relative
    alternate = root / "alternate"
    alternate.mkdir()
    b = backend()
    guard = b.pin_existing(target, directory=True)
    created = None
    try:
        sharing_conflict(lambda: target.rename(target.with_name(target.name + "-swapped")))
        sharing_conflict(target.rmdir)
        sharing_conflict(lambda: raw_open(b.api, target, 0x40000000))
        sharing_conflict(lambda: set_synthetic_junction(target, alternate, root))
        created = b.create_file(guard, "proof.json")
        from mokioclaw.dashboard.task_observation_continuation import write_durable
        write_durable(created, b"native-relative-proof")
        assert created.identity.final_path == target / "proof.json"
        assert created.read_bounded(64) == b"native-relative-proof"
        assert not tuple(alternate.iterdir())
    finally:
        if created is not None:
            created.close()
        guard.close()


@pytest.mark.parametrize("name", NAMES)
def test_native_each_legacy_file_shared_holders_and_identity(root, name, monkeypatch):
    # READ share must reject an already writable holder even when that holder shares all.
    path, replacement = root / name, root / "replacement"
    path.write_bytes(b"")
    replacement.write_bytes(b"replacement")
    b = backend()
    holder = raw_open(b.api, path, 0xc0000000)
    conflicts = []
    original = b.api.open_existing
    def observed_open(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        except ValueError:
            conflicts.append(c.get_last_error())
            raise
    try:
        with monkeypatch.context() as patch:
            patch.setattr(b.api, "open_existing", observed_open)
            with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
                b.pin_existing(path, directory=False)
        assert conflicts == [32]
    finally:
        b.api.close(holder)
    holder = raw_open(b.api, path, 0x80000000)
    guard = None
    try:
        guard = b.pin_existing(path, directory=False)
        identity = guard.identity
        fingerprint = guard.fingerprint(4096)
        assert fingerprint.size_bytes == 0
        assert fingerprint.sha256 == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        sharing_conflict(lambda: raw_open(b.api, path, 0x40000000))
        # CRT path.open maps Win32 sharing errors to errno 13 and drops winerror.
        # TRUNCATE_EXISTING tests truncation with the precise native error instead.
        sharing_conflict(lambda: raw_open(b.api, path, 0x40000000, disposition=5))
        sharing_conflict(lambda: os.replace(replacement, path))
        sharing_conflict(path.unlink)
        assert b.verify(guard) == identity and identity.final_path == path
        assert guard.fingerprint(4096) == fingerprint
    finally:
        if guard is not None:
            guard.close()
        b.api.close(holder)
    os.link(path, root / "hardlink")
    assert path.stat().st_nlink == 2
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        b.pin_existing(path, directory=False)


def fixed_peer(spawn, root):
    # No caller-supplied executable, body, environment, or command suffix.
    child = Path(__file__).with_name("task_continuation_native_lease_child.py")
    environment = {key: value for key, value in os.environ.items() if key.upper() in {"SYSTEMROOT", "TEMP", "TMP"}}
    environment.update(PYTHONDONTWRITEBYTECODE="1", MOKIOCLAW_CONTINUATION_NATIVE_FILES="1")
    return spawn([sys.executable, "-B", str(child), "--root", str(root)], stdin=subprocess.PIPE,
                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=environment, shell=False)


@contextmanager
def peer(spawn, root):
    process = fixed_peer(spawn, root)
    try:
        yield process
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        process.stdin.close()
        process.stdout.close()


def peer_held(spawn, task_root):
    with peer(spawn, task_root) as process:
        output, _ = process.communicate("release\n", timeout=5)
        assert process.returncode == 2 and output == ""


def peer_free(spawn, task_root):
    with peer(spawn, task_root) as process:
        output, _ = process.communicate("release\n", timeout=5)
        assert process.returncode == 0 and output == "locked\nreleased\n"


def test_native_fixed_peer_accepts_only_synthetic_tasks_child(root, native_gate):
    task_root = root / "tasks"
    task_root.mkdir()
    (task_root / ".dashboard.lock").write_bytes(b"0")
    peer_free(native_gate, task_root)
    other = root / "unapproved"
    other.mkdir()
    (other / ".dashboard.lock").write_bytes(b"0")
    peer_held(native_gate, other)  # Exit 2 here means path rejection, not lock evidence.


def materialize(root, monkeypatch):
    case = SyntheticTask(root=root)
    for path, node in sorted(case.backend.nodes.items(), key=lambda row: len(row[0].parts)):
        if not path.is_relative_to(root):
            continue
        if node[0]:
            path.mkdir(exist_ok=True)
        else:
            path.write_bytes(node[1])
    import mokioclaw.dashboard.task_source as source
    monkeypatch.setattr(source, "source_identity", lambda source_root: (1, 2, 3, 4))
    return case


def open_owner(case):
    from mokioclaw.dashboard.task_observation_continuation import ContinuationOptions, PrestartObservationContinuation
    from mokioclaw.dashboard.task_service import _TaskRootLease
    options = ContinuationOptions(TASK, case.spec_sha, SOURCE)
    owner = PrestartObservationContinuation.open(options, case.root, case.task_root, backend=backend())
    lease = None
    try:
        lease = _TaskRootLease(case.task_root, stream=owner.lease_stream())
        owner.verify_lease(lease.stream.fileno())
    except Exception:
        cleanup(owner, lease)
        raise
    return owner, lease


def cleanup(owner, lease, extra=()):
    """Test cleanup after assertions; never retry TaskService.close."""
    for check in tuple(owner.pending_checks):
        check.close()
    session = owner.session
    handles = list(extra)
    if session is not None:
        handles += session._journal_files + [session.metadata, session.directory]
    handles += list(reversed(owner.long_handles))
    for handle in handles:
        handle.close()
    if owner._lease_file is not None:
        for parent in reversed(owner._lease_file.parents):
            parent.close()
    if lease is not None:
        lease.close()
        owner._lease_file.closed = True
    elif owner._lease_file is not None:
        owner._lease_file.close()


class FaultStream:
    def __init__(self, stream, operation, hits):
        self.stream, self.operation, self.hits = stream, operation, hits
        self.enabled = True

    def __getattr__(self, name):
        value = getattr(self.stream, name)
        if name != self.operation or not callable(value):
            return value
        def failed(*args, **kwargs):
            if self.enabled:
                self.hits.append(name)
                raise OSError("synthetic_native_fault")
            return value(*args, **kwargs)
        return failed


@pytest.mark.parametrize("fault", [
    "sessions-before", "sessions-after", "session", "session.json", "calls.jsonl", "scores.json", "status.json",
    "metadata-write", "metadata-flush", "metadata-fsync", "status-write", "status-flush", "status-fsync",
    "calls-flush", "calls-fsync", "scores-flush", "scores-fsync",
])
def test_native_bind_fault_preserves_partial_and_next_check_rejects(root, native_gate, monkeypatch, fault, record_property):
    # Failures after exclusive sessions creation must never restore fresh bind eligibility.
    from mokioclaw.dashboard.task_diagnostics import NumericJournal
    case = materialize(root, monkeypatch)
    owner, lease = open_owner(case)
    created, proxies, hits = [], [], []
    random_calls = []
    try:
        before = {name: hashlib.sha256((case.obs / name).read_bytes()).hexdigest() for name in NAMES}
        check = owner.check(case.catalog, case.git, cached_record=case.record)
        check.close()
        with monkeypatch.context() as patch:
            import mokioclaw.dashboard.task_observation_continuation as continuation
            patch.setattr(continuation.secrets, "token_hex", lambda size: random_calls.append(size) or "a" * 32)
            create_dir, create_file, fsync = owner.backend.create_directory, owner.backend.create_file, os.fsync
            def directory(parent, name):
                if (fault == "sessions-before" and name == "sessions") or (fault == "session" and name == "a" * 32):
                    hits.append(fault)
                    raise OSError("synthetic_native_fault")
                handle = create_dir(parent, name)
                created.append(handle)
                if fault == "sessions-after" and name == "sessions":
                    hits.append(fault)
                    handle.close()
                    raise OSError("synthetic_native_fault")
                return handle
            def file(parent, name):
                if fault == name:
                    hits.append(fault)
                    raise OSError("synthetic_native_fault")
                handle = create_file(parent, name)
                created.append(handle)
                label = {"session.json": "metadata", "status.json": "status", "calls.jsonl": "calls", "scores.json": "scores"}[name]
                if fault in {label + "-write", label + "-flush"}:
                    handle.stream = FaultStream(handle.stream, fault.split("-")[1], hits)
                    proxies.append(handle.stream)
                return handle
            def sync(fd):
                label = fault.removesuffix("-fsync")
                target = {"metadata": "session.json", "status": "status.json", "calls": "calls.jsonl", "scores": "scores.json"}.get(label)
                if fault.endswith("-fsync") and any(not h.identity.is_directory and h.identity.final_path.name == target
                                                     and not h.closed and h.stream.fileno() == fd for h in created):
                    hits.append(fault)
                    raise OSError("synthetic_native_fault")
                return fsync(fd)
            patch.setattr(owner.backend, "create_directory", directory)
            patch.setattr(owner.backend, "create_file", file)
            patch.setattr(os, "fsync", sync)
            with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
                session = owner.create_session(check)
                NumericJournal(root, TASK, session=session)
        assert hits and random_calls == ([] if fault.startswith("sessions-") else [16])
        marked = fault != "sessions-before"
        assert (case.obs / "sessions").exists() is marked
        assert owner.consumed is (fault not in {"sessions-before", "sessions-after"})
        if marked:
            names = tuple(p.name for p in (case.obs / "sessions").iterdir())
            assert names == (() if fault in {"sessions-after", "session"} else ("a" * 32,))
            if names:
                expected = {"session.json": set(), "calls.jsonl": {"session.json"},
                            "scores.json": {"session.json", "calls.jsonl"},
                            "status.json": {"session.json", "calls.jsonl", "scores.json"}}.get(fault)
                if expected is None:
                    expected = {"session.json"} if fault.startswith("metadata-") else {"session.json", *NAMES}
                assert {p.name for p in (case.obs / "sessions" / names[0]).iterdir()} == expected
        if marked:
            with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
                owner.create_session(check)
        assert not lease.stream.closed
        assert all(not handle.closed for handle in owner.old_files.values())
        owner.verify_preserved()
        peer_held(native_gate, case.task_root)
        record_property("sessions_marker", marked)
        record_property("consumed", owner.consumed)
        for proxy in proxies:
            proxy.enabled = False
        # With a failed bind there is no committed manager journal. Exercise the
        # real close branch, including session.failed_journal/partial ownership.
        from mokioclaw.dashboard.task_service import TaskService
        context = SimpleNamespace(_continuation=owner, _lock=RLock(), _closed=False, _closing=False,
                                  _close_failed=False, observation_manager=None, _uncommitted_journals=[],
                                  worker_controller=None, pool=SimpleNamespace(shutdown=lambda **kwargs: None), lease=lease)
        TaskService.close(context)
        assert context._closed and lease.stream.closed
    finally:
        for proxy in proxies:
            proxy.enabled = False
        cleanup(owner, lease, created)
    assert {name: hashlib.sha256((case.obs / name).read_bytes()).hexdigest() for name in NAMES} == before
    peer_free(native_gate, case.task_root)
    next_owner, next_lease = open_owner(case)
    try:
        if marked:
            with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
                next_owner.check(case.catalog, case.git, cached_record=case.record)
        else:
            fresh = next_owner.check(case.catalog, case.git, cached_record=case.record)
            fresh.close()
    finally:
        cleanup(next_owner, next_lease)


def close_context(owner, lease, journal, record):
    from mokioclaw.dashboard.task_diagnostics import CalibrationObservationManager
    manager = CalibrationObservationManager(owner.root, task_lookup=lambda task: record, continuation_task_id=TASK)
    manager.task_id, manager.session, manager.journal = TASK, owner.session, journal
    return SimpleNamespace(_continuation=owner, _lock=RLock(), _closed=False, _closing=False, _close_failed=False,
                           observation_manager=manager, _uncommitted_journals=[], worker_controller=None,
                           pool=SimpleNamespace(shutdown=lambda **kwargs: None), lease=lease)


@pytest.mark.parametrize("fault", [None, "calls-close", "scores-close", "status-close", "metadata-close",
                                    "session-close", "sessions-close", "old-hash"])
def test_native_close_order_late_writer_and_failed_close_retains_lease(root, native_gate, monkeypatch, fault, record_property):
    # Early unlock, missing sealing, or ignored close/proof failure exposes a second owner.
    from mokioclaw.dashboard.task_diagnostics import NumericJournal
    from mokioclaw.dashboard.task_service import TaskService, _retained_close_failures
    case = materialize(root, monkeypatch)
    owner, lease = open_owner(case)
    journal = context = thread = None
    release, finished, entered = Event(), Event(), Event()
    late_result, events = [], []
    try:
        check = owner.check(case.catalog, case.git, cached_record=case.record)
        check.close()
        session = owner.create_session(check)
        journal = NumericJournal(root, TASK, session=session)
        assert journal.is_initial()
        context = close_context(owner, lease, journal, case.record)
        def late():
            entered.set()
            assert release.wait(5)
            late_result.append(journal.set_indexes([]))
            # A late low-level status write must be rejected before touching its stream.
            with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
                journal._write(2, {"late": True}, 4096)
            finished.set()
        thread = Thread(target=late)
        thread.start()
        assert entered.wait(5)
        with monkeypatch.context() as patch:
            def trace_close(handle, label):
                original = handle.close
                def close():
                    try:
                        original()
                    except Exception:
                        events.append("fault:" + label)
                        raise
                    events.append(label)
                patch.setattr(handle, "close", close)
                if fault == label:
                    if handle.identity.is_directory:
                        api_close = owner.backend.api.close
                        def failed_native_close(native):
                            if native == handle.native_handle:
                                raise OSError("synthetic_native_fault")
                            return api_close(native)
                        patch.setattr(owner.backend.api, "close", failed_native_close)
                    else:
                        patch.setattr(handle, "stream", FaultStream(handle.stream, "close", []))
            for handle, label in zip(journal._owned_handles, ("calls-close", "scores-close", "status-close")):
                trace_close(handle, label)
            trace_close(session.metadata, "metadata-close")
            trace_close(session.directory, "session-close")
            trace_close(owner.sessions_directory, "sessions-close")
            for name, handle in owner.old_files.items():
                trace_close(handle, "old-close:" + name)
            preserved = owner.verify_preserved
            def verify():
                assert journal._sealed and all(h.closed for h in journal._owned_handles)
                assert all(not h.closed for h in owner.old_files.values())
                preserved()
                events.append("old-hash")
            patch.setattr(owner, "verify_preserved", verify)
            if fault == "old-hash":
                old = owner.old_files["status.json"]
                fingerprint = old.fingerprint
                def failed_fingerprint(limit):
                    fingerprint(limit)  # Real same-handle read/hash precedes injected proof failure.
                    events.append("fault:old-hash")
                    raise OSError("synthetic_native_fault")
                patch.setattr(old, "fingerprint", failed_fingerprint)
            lease_close = lease.close
            def unlock():
                assert all(h.closed for h in owner.long_handles)
                assert session.metadata.closed and session.directory.closed
                assert all(p.closed for p in owner._lease_file.parents)
                lease_close()
                events.append("lease-close")
            patch.setattr(lease, "close", unlock)
            if fault is None:
                TaskService.close(context)
                assert context._closed and lease.stream.closed
                assert max(events.index(label) for label in ("calls-close", "scores-close", "status-close")) < events.index("old-hash")
                assert events.index("old-hash") < events.index("metadata-close") < events.index("session-close")
                assert all(events.index("old-hash") < events.index("old-close:" + name) for name in NAMES)
                assert events[-1] == "lease-close"
                peer_free(native_gate, case.task_root)
            else:
                with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
                    TaskService.close(context)
                assert context._close_failed and not context._closed and not lease.stream.closed
                assert "lease-close" not in events and "fault:" + fault in events
                peer_held(native_gate, case.task_root)
                with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
                    TaskService.close(context)
                peer_held(native_gate, case.task_root)
            assert journal._sealed
            snapshot = {h.identity.final_path: h.identity.final_path.read_bytes() for h in journal._owned_handles}
            release.set()
            assert finished.wait(5) and late_result == [False]
            thread.join(5)
            assert not thread.is_alive()
            assert {p: p.read_bytes() for p in snapshot} == snapshot
            record_property("close_events", ",".join(events))
            record_property("lease_retained_on_failure", fault is not None and not lease.stream.closed)
        if fault is not None:
            # These bytes/guards remain protected even after the failed close.
            sharing_conflict(lambda: raw_open(owner.backend.api, case.obs / "calls.jsonl", 0x40000000))
    finally:
        release.set()
        if thread is not None:
            thread.join(5)
        cleanup(owner, lease)
        if context is not None and context in _retained_close_failures:
            _retained_close_failures.remove(context)
    peer_free(native_gate, case.task_root)
