"""Separately authorized Windows acceptance. Default collection never probes DLLs."""

import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from threading import Event, Thread
from types import SimpleNamespace
import uuid

import pytest

from task_observation_fakes import offline_observation_guard

pytestmark = pytest.mark.continuation_native_files


@pytest.fixture(autouse=True)
def native_gate(monkeypatch):
    if os.name != "nt" or os.environ.get("MOKIOCLAW_CONTINUATION_NATIVE_FILES") != "1":
        pytest.skip("separate Windows native file acceptance requires explicit authorization")
    original_spawn = subprocess.Popen
    with offline_observation_guard(monkeypatch):
        yield original_spawn


@pytest.fixture
def root(tmp_path):
    # Keep the complete synthetic workspace below Win32 MAX_PATH without changing OS settings.
    root = tmp_path.parent / ("mokioclaw-continuation-native-" + uuid.uuid4().hex)
    root.mkdir()
    return root


def backend():
    from mokioclaw.dashboard.task_observation_handles import WindowsObservationHandleBackend
    return WindowsObservationHandleBackend()


def set_synthetic_junction(directory, target, root):
    """Only ordinary descendants pointing inside this test's Temp root may change."""
    import ctypes as c
    from mokioclaw.dashboard.task_observation_handles import _WindowsApi
    assert root.is_absolute() and root.name.startswith("mokioclaw-continuation-native-")
    assert root.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
    assert directory != target and directory.is_relative_to(root) and target.is_relative_to(root)
    paths = {root, directory, target}
    for descendant in (directory, target):
        paths.update(p for p in descendant.parents if p.is_relative_to(root))
    for path in paths:
        assert path.is_dir() and not path.is_symlink()
        assert not getattr(path.lstat(), "st_file_attributes", 0) & 0x400
    substitute = ("\\??\\" + str(target)).encode("utf-16-le")
    printed = str(target).encode("utf-16-le")
    names = substitute + b"\0\0" + printed + b"\0\0"
    data = struct.pack("<HHHH", 0, len(substitute), len(substitute) + 2, len(printed)) + names
    payload = struct.pack("<IHH", 0xa0000003, len(data), 0) + data
    assert len(payload) < 16384
    api = _WindowsApi()
    control = api.k.DeviceIoControl
    control.argtypes = [c.c_void_p, c.c_uint32, c.c_void_p, c.c_uint32,
                        c.c_void_p, c.c_uint32, c.POINTER(c.c_uint32), c.c_void_p]
    control.restype = c.c_int32
    handle = api.k.CreateFileW(str(directory), 0x40000000, 1, None, 3, 0x02200000, None)
    if handle in (None, 0, c.c_void_p(-1).value):
        raise c.WinError(c.get_last_error())
    try:
        buffer, returned = c.create_string_buffer(payload), c.c_uint32()
        if not control(handle, 0x000900a4, buffer, len(payload), None, 0, c.byref(returned), None):
            raise c.WinError(c.get_last_error())
    finally:
        api.close(handle)


def test_native_relative_create_and_child_write(root):
    from mokioclaw.dashboard.task_observation_continuation import ObservationSession, write_durable
    from mokioclaw.dashboard.task_diagnostics import NumericJournal
    b = backend()
    parent = directory = metadata = session = journal = None
    try:
        parent = b.pin_existing(root, directory=True)
        directory = b.create_directory(parent, "session")
        metadata = b.create_file(directory, "session.json")
        write_durable(metadata, b"{}")
        owner = SimpleNamespace(backend=b, options=SimpleNamespace(task_id="synthetic_task_0001"), session=None)
        session = ObservationSession(owner, "a" * 32, directory, metadata)
        owner.session = session
        journal = NumericJournal(root, "synthetic_task_0001", session=session)
        assert journal.is_initial()
        with pytest.raises(ValueError):
            b.create_directory(parent, "session")
        assert set(b.children(directory, limit=4)) == {"session.json", "calls.jsonl", "scores.json", "status.json"}
    finally:
        try:
            if journal is not None:
                journal.seal_and_close()
        finally:
            try:
                if session is not None:
                    session.close()
                else:
                    if metadata is not None:
                        metadata.close()
                    if directory is not None:
                        directory.close()
            finally:
                if parent is not None:
                    parent.close()


def test_native_pins_reject_rename_delete_reparse(root, record_property):
    target = root / "guarded"
    target.mkdir()
    b = backend()
    guard = b.pin_existing(target, directory=True)
    try:
        with pytest.raises(OSError):
            target.rename(root / "replaced")
        with pytest.raises(OSError):
            target.rmdir()
        alias = root / "alias"
        try:
            alias.symlink_to(target, target_is_directory=True)
            record_property("reparse_fixture", "symbolic_link")
        except OSError as symlink_error:
            record_property("symlink_winerror", symlink_error.winerror)
            alias.mkdir()
            try:
                set_synthetic_junction(alias, target, root)
                record_property("reparse_fixture", "junction")
            except OSError as junction_error:
                pytest.skip(f"reparse fixture unavailable: symlink={symlink_error.winerror}, "
                            f"junction={junction_error.winerror}; native gate remains unaccepted")
        assert getattr(alias.lstat(), "st_file_attributes", 0) & 0x400
        with pytest.raises(ValueError):
            b.pin_existing(alias, directory=True)
        alternate = root / "alternate"
        alternate.mkdir()
        with pytest.raises(OSError) as pinned_error:
            set_synthetic_junction(target, alternate, root)
        assert pinned_error.value.winerror == 32
        record_property("guarded_reparse_winerror", pinned_error.value.winerror)
    finally:
        guard.close()


def test_native_legacy_write_replace_and_preexisting_writer(root):
    path = root / "calls.jsonl"
    path.write_bytes(b"")
    b = backend()
    with path.open("r+b"):
        with pytest.raises(ValueError):
            b.pin_existing(path, directory=False)
    guard = b.pin_existing(path, directory=False)
    try:
        with pytest.raises(OSError):
            path.open("wb")
        replacement = root / "replacement"
        replacement.write_bytes(b"changed")
        with pytest.raises(OSError):
            os.replace(replacement, path)
        assert guard.fingerprint(4096).size_bytes == 0
    finally:
        guard.close()
    link = root / "hardlink"
    os.link(path, link)
    with pytest.raises(ValueError):
        b.pin_existing(path, directory=False)


def test_native_partial_session_blocks_next_owner(root):
    b = backend()
    parent = b.pin_existing(root, directory=True)
    sessions = b.create_directory(parent, "sessions")
    child = b.create_directory(sessions, "a" * 32)
    child.close()
    sessions.close()
    parent.close()
    next_parent = b.pin_existing(root, directory=True)
    try:
        with pytest.raises(ValueError):
            b.create_directory(next_parent, "sessions")
        assert "sessions" in b.children(next_parent, limit=1000)
    finally:
        next_parent.close()


def test_native_lease_and_delayed_writer_shutdown(root, native_gate):
    from mokioclaw.dashboard.task_service import _TaskRootLease
    from mokioclaw.dashboard.task_diagnostics import NumericJournal
    lease = journal = None
    (root / ".dashboard.lock").write_bytes(b"0")
    child_path = Path(__file__).with_name("task_continuation_native_lease_child.py")
    command = [sys.executable, "-B", str(child_path), "--root", str(root)]
    environment = {key: value for key, value in os.environ.items() if key.upper() in {"SYSTEMROOT", "TEMP", "TMP"}}
    environment.update(PYTHONDONTWRITEBYTECODE="1", MOKIOCLAW_CONTINUATION_NATIVE_FILES="1")
    process = native_gate(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          text=True, env=environment, shell=False)
    try:
        ready, output = Event(), []
        def read_ready():
            output.append(process.stdout.readline())
            ready.set()
        reader = Thread(target=read_ready, daemon=True)
        reader.start()
        assert ready.wait(5) and output == ["locked\n"]
        with pytest.raises(RuntimeError):
            _TaskRootLease(root)
        process.stdin.write("release\n")
        process.stdin.flush()
        process.wait(timeout=5)
        assert process.returncode == 0 and process.stdout.readline() == "released\n"
        lease = _TaskRootLease(root)
        journal = NumericJournal(root, "synthetic_task_0001")
        release, finished = Event(), Event()
        result = []
        def late():
            assert release.wait(5)
            result.append(journal.set_indexes([]))
            finished.set()
        thread = Thread(target=late)
        thread.start()
        journal.seal_and_close()
        release.set()
        assert finished.wait(5) and result == [False]
        thread.join(5)
        assert not thread.is_alive()
        lease.close()
    finally:
        try:
            if journal is not None:
                journal.seal_and_close()
        finally:
            try:
                if lease is not None:
                    lease.close()
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
                process.stdin.close()
                process.stdout.close()
