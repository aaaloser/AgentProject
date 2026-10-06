"""The continuation handle gate must reject ambiguous identity before writing."""

import importlib
import ctypes
import io
from pathlib import Path
from pathlib import PurePosixPath
import stat
from types import SimpleNamespace

import pytest

from task_observation_fakes import offline_observation_guard


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    with offline_observation_guard(monkeypatch):
        yield


def handles():
    return importlib.import_module("mokioclaw.dashboard.task_observation_handles")


class FakeWinApi:
    def __init__(self):
        self.nodes = {1: (Path("C:/"), True), 2: (Path("C:/safe"), True)}
        self.calls = []
        self.closed = []
        self.bad = None
        self.pages = [(), None]
        self.content = b"synthetic"
        self.status, self.information = 0, 2

    def open_existing(self, path, *, directory, lease):
        self.calls.append(("open", path, directory, lease))
        if self.bad == "sharing":
            raise OSError("sensitive")
        for key, (root, is_dir) in self.nodes.items():
            if root == path and is_dir == directory:
                return key
        raise OSError("missing")

    def identity(self, handle):
        path, directory = self.nodes[handle]
        return SimpleNamespace(volume_id=2 if self.bad == "volume" and handle != 1 else 1,
                               file_id=handle + (1 if self.bad == "id" else 0),
                               final_path=Path("C:/other") if self.bad == "path" else path,
                               is_directory=directory, link_count=2 if self.bad == "links" else 1,
                               reparse=self.bad == "reparse", filesystem="ReFS" if self.bad == "fs" else "NTFS",
                               local=self.bad != "remote")

    def create_relative(self, parent, name, *, directory, disposition, options, access, share):
        self.calls.append(("create", parent, name, directory, disposition, options, access, share))
        handle = max(self.nodes) + 1
        self.nodes[handle] = (self.nodes[parent][0] / name, directory)
        return handle, self.status, self.information

    def stream(self, handle, *, writable):
        api = self
        class Stream(io.BytesIO):
            def close(self):
                if not self.closed:
                    api.close(handle)
                super().close()
        return Stream(self.content)

    def enumerate_page(self, handle, restart):
        return self.pages.pop(0)

    def close(self, handle):
        self.closed.append(handle)


def test_relative_create_contract():
    module = handles()
    api = FakeWinApi()
    backend = module.WindowsObservationHandleBackend(api=api)
    parent = backend.pin_existing(Path("C:/safe"), directory=True)
    child = backend.create_directory(parent, "sessions")
    call = next(call for call in api.calls if call[0] == "create")
    assert call[1:6] == (parent.native_handle, "sessions", True, 2, 0x21)
    assert child.identity.final_path == Path("C:/safe/sessions")
    assert call[7] == 1
    child.close()
    parent.close()
    assert set(api.closed) == {1, 2, 3}


@pytest.mark.parametrize("name", ["../x", "a/b", "a\\b", "C:x", "x\0", "x.", "x ", "CON", "nul.txt", ".."])
def test_relative_create_rejects_components(name):
    module = handles()
    api = FakeWinApi()
    backend = module.WindowsObservationHandleBackend(api=api)
    parent = backend.pin_existing(Path("C:/safe"), directory=True)
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        backend.create_directory(parent, name)
    assert not any(call[0] == "create" for call in api.calls)
    parent.close()


@pytest.mark.parametrize("fault", ["reparse", "sharing", "path", "fs", "remote", "volume"])
def test_open_pin_and_identity_rejects(fault):
    module = handles()
    api = FakeWinApi()
    api.bad = fault
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        module.WindowsObservationHandleBackend(api=api).pin_existing(Path("C:/safe"), directory=True)
    assert not any(call[0] == "create" for call in api.calls)
    if fault == "reparse":
        assert api.closed == [1]


@pytest.mark.parametrize("fault", ["links", "reparse", "path", "fs", "remote"])
def test_file_rejected_before_stream_conversion(fault):
    api = FakeWinApi()
    api.nodes[3] = (Path("C:/safe/old.json"), False)
    original = api.identity
    def identity(handle):
        info = original(handle)
        if handle == 3:
            if fault == "links":
                info.link_count = 2
            elif fault == "path":
                info.final_path = Path("C:/other")
            elif fault == "fs":
                info.filesystem = "ReFS"
            elif fault == "remote":
                info.local = False
            else:
                info.reparse = True
        return info
    api.identity = identity
    api.stream = lambda *args, **kwargs: pytest.fail("unsafe identity reached stream")
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        handles().WindowsObservationHandleBackend(api=api).pin_existing(Path("C:/safe/old.json"), directory=False)
    assert set(api.closed) == {1, 2, 3}


def test_file_same_handle_read_and_changed_identity():
    api = FakeWinApi()
    api.nodes[3] = (Path("C:/safe/old.json"), False)
    b = handles().WindowsObservationHandleBackend(api=api)
    file = b.pin_existing(Path("C:/safe/old.json"), directory=False)
    opens = len(api.calls)
    assert file.read_bounded(9) == b"synthetic"
    assert file.fingerprint(9).size_bytes == 9 and len(api.calls) == opens
    with pytest.raises(ValueError):
        file.read_bounded(8)
    api.bad = "id"
    with pytest.raises(ValueError):
        b.verify(file)
    api.bad = None
    file.close()
    file.close()
    assert sorted(api.closed) == [1, 2, 3]


@pytest.mark.parametrize("status,information", [(-1, 2), (1, 2), (0, 1)])
def test_relative_create_requires_created_success(status, information):
    api = FakeWinApi()
    b = handles().WindowsObservationHandleBackend(api=api)
    parent = b.pin_existing(Path("C:/safe"), directory=True)
    api.status, api.information = status, information
    with pytest.raises(ValueError):
        b.create_directory(parent, "sessions")
    assert api.closed == [3]
    parent.close()


def test_native_abi_and_relative_object_lifetime(monkeypatch):
    calls = []
    class Function:
        def __init__(self, name):
            self.name = name
        def __call__(self, *args):
            assert self.argtypes and self.restype is not None
            if self.name == "NtCreateFile":
                oa, io_status = args[2]._obj, args[3]._obj
                name = ctypes.wstring_at(oa.ObjectName.contents.Buffer, oa.ObjectName.contents.Length // 2)
                calls.append((oa.RootDirectory, name, args[6], args[7], args[8]))
                args[0]._obj.value = 99
                io_status.Information = 2
                return 0
            raise AssertionError("unexpected_native_boundary")
    class Library:
        def __init__(self):
            self.functions = {}
        def __getattr__(self, name):
            return self.functions.setdefault(name, Function(name))
    libraries = []
    def dll(*args, **kwargs):
        library = Library()
        libraries.append(library)
        return library
    monkeypatch.setattr(ctypes, "WinDLL", dll)
    api = handles()._WindowsApi()
    assert [ctypes.sizeof(item) for item in (api.US, api.OA, api.IO)] == [16, 48, 16]
    assert api.US.Length.size == 2 and api.OA.Length.size == 4 and api.IO.Information.size == ctypes.sizeof(ctypes.c_void_p)
    assert all(function.argtypes and function.restype for library in libraries for function in library.functions.values())
    assert api.create_relative(55, "sessions", directory=True, disposition=2, options=0x21, access=0x1000a1, share=1) == (99, 0, 2)
    assert calls == [(55, "sessions", 1, 2, 0x21)]


def test_enumeration_must_terminate():
    api = FakeWinApi()
    b = handles().WindowsObservationHandleBackend(api=api)
    parent = b.pin_existing(Path("C:/safe"), directory=True)
    pages = []
    def incomplete(*args):
        pages.append(1)
        if len(pages) > 1002:
            raise OSError("incomplete_enumeration")
        return ()
    api.enumerate_page = incomplete
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        b.children(parent, limit=1000)
    assert len(pages) <= 1001
    parent.close()


@pytest.mark.parametrize("names", [("a", "A"), ("a", "a"), tuple(str(i) for i in range(1001))])
def test_directory_enumeration_bounded(names):
    module = handles()
    api = FakeWinApi()
    api.pages = [names, None]
    backend = module.WindowsObservationHandleBackend(api=api)
    parent = backend.pin_existing(Path("C:/safe"), directory=True)
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        backend.children(parent, limit=1000)
    parent.close()


def test_directory_enumeration_complete():
    module = handles()
    api = FakeWinApi()
    api.pages = [tuple(str(i) for i in range(1000)), None]
    backend = module.WindowsObservationHandleBackend(api=api)
    parent = backend.pin_existing(Path("C:/safe"), directory=True)
    assert len(backend.children(parent, limit=1000)) == 1000
    parent.close()


def test_malformed_native_enumeration():
    module = handles()
    for data in (b"x", bytes(104), (8).to_bytes(4, "little") + bytes(100)):
        with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
            module.decode_directory_page(data)


def test_created_handle_closed_if_parent_verification_fails():
    api = FakeWinApi()
    b = handles().WindowsObservationHandleBackend(api=api)
    parent = b.pin_existing(Path("C:/safe"), directory=True)
    original = api.identity
    def identity(handle):
        info = original(handle)
        if handle == 2 and any(call[0] == "create" for call in api.calls):
            info.file_id += 1
        return info
    api.identity = identity
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        b.create_directory(parent, "sessions")
    assert 3 in api.closed
    parent.close()


def test_failed_fdopen_never_double_closes_transferred_native_handle(monkeypatch):
    import msvcrt
    import os
    module = handles()
    native_api = module._WindowsApi.__new__(module._WindowsApi)
    api = FakeWinApi()
    api.nodes[3] = (Path("C:/safe/old.json"), False)
    api.stream = lambda native, **kwargs: native_api.stream(native, **kwargs)
    closed = []
    monkeypatch.setattr(msvcrt, "open_osfhandle", lambda native, flags: 123)
    def fdopen(fd, mode):
        raise OSError("synthetic_fdopen_failure")
    monkeypatch.setattr(os, "fdopen", fdopen)
    monkeypatch.setattr(os, "close", closed.append)
    b = module.WindowsObservationHandleBackend(api=api)
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        b.pin_existing(Path("C:/safe/old.json"), directory=False)
    assert closed == [123] and set(api.closed) == {1, 2}


@pytest.mark.parametrize("failure", [None, "directory", "file"])
def test_posix_relative_exclusive_contract_without_native_calls(monkeypatch, failure):
    import os
    module = handles()
    nodes = {PurePosixPath("/"): True, PurePosixPath("/safe"): True}
    descriptors, opened, closed, created = {}, [], [], []
    def open_fd(path, flags, mode=0o600, *, dir_fd=None):
        path = PurePosixPath(path)
        target = descriptors[dir_fd] / path if dir_fd is not None else path
        opened.append((target, flags, dir_fd))
        if flags & os.O_CREAT:
            if target in nodes:
                raise FileExistsError
            nodes[target] = False
        assert target in nodes
        fd = 100 + len(descriptors)
        descriptors[fd] = target
        return fd
    def info(path):
        return SimpleNamespace(st_dev=1, st_ino=1 + list(nodes).index(path),
                               st_nlink=1, st_mode=stat.S_IFDIR if nodes[path] else stat.S_IFREG)
    def mkdir(path, *, dir_fd):
        target = descriptors[dir_fd] / path
        if target in nodes:
            raise FileExistsError
        created.append((target, dir_fd))
        nodes[target] = True
    class Stream(io.BytesIO):
        def __init__(self, fd):
            super().__init__()
            self.fd = fd
        def close(self):
            if not self.closed:
                closed.append(self.fd)
            super().close()
    with monkeypatch.context() as patch:
        patch.setattr(module, "Path", PurePosixPath)
        patch.setattr(os.path, "abspath", lambda path: str(path))
        patch.setattr(os, "O_NOFOLLOW", 0x100000, raising=False)
        patch.setattr(os, "O_DIRECTORY", 0x200000, raising=False)
        patch.setattr(os, "open", open_fd)
        patch.setattr(os, "fstat", lambda fd: info(descriptors[fd]))
        patch.setattr(os, "stat", lambda path, **kwargs: info(PurePosixPath(path)))
        patch.setattr(os, "mkdir", mkdir)
        patch.setattr(os, "close", closed.append)
        patch.setattr(os, "fdopen", lambda fd, mode: Stream(fd))
        b = module.PosixObservationHandleBackend()
        parent = b.pin_existing(PurePosixPath("/safe"), directory=True)
        original_identity = b._identity
        def identity(fd, path, directory):
            if failure == "directory" and path.name == "sessions" or failure == "file" and path.name == "calls.jsonl":
                raise ValueError("synthetic_identity_failure")
            return original_identity(fd, path, directory)
        b._identity = identity
        if failure == "directory":
            with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
                b.create_directory(parent, "sessions")
            assert closed == [102]
            parent.close()
            return
        directory = b.create_directory(parent, "sessions")
        if failure == "file":
            with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
                b.create_file(directory, "calls.jsonl")
            assert closed == [103]
            directory.close()
            parent.close()
            return
        file = b.create_file(directory, "calls.jsonl")
        assert created == [(PurePosixPath("/safe/sessions"), parent.native_handle)]
        assert opened[-1][1] & os.O_EXCL and opened[-1][1] & os.O_NOFOLLOW
        assert opened[-1][2] == directory.native_handle
        with pytest.raises(ValueError):
            b.create_file(directory, "calls.jsonl")
        file.close()
        directory.close()
        parent.close()
    assert len(closed) == 4 and len(set(closed)) == 4
