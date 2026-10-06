"""Synthetic files/Git/lease; no disk, native handles, subprocess or SDK calls."""

from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path

from mokioclaw.dashboard.catalog import RegisteredRepository, RepositoryCatalog
from mokioclaw.dashboard.models import RepositoryState
from mokioclaw.dashboard.task_models import PublicTaskEvent, TaskRecord, TaskSpec
from mokioclaw.dashboard.task_observation_handles import DirectoryHandle, FileHandle, FileIdentity, component
from task_observation_fakes import offline_observation_guard

TASK = "synthetic_task_0001"
REPO = "original_repo_0001"
SHA = "a" * 40
ROOT = Path("C:/synthetic-continuation")
SOURCE = Path("C:/synthetic-source")
UTC = "2026-10-05T00:00:00Z"
NAMES = ("calls.jsonl", "scores.json", "status.json")


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


class MemoryStream(io.BytesIO):
    def __init__(self, data, backend, path):
        super().__init__(data)
        self.backend, self.path = backend, path
        self.reads = 0

    def fileno(self):
        return -12345

    def read(self, size=-1):
        self.reads += 1
        return super().read(size)

    def write(self, data):
        self.backend.event("write:" + self.path.name)
        value = super().write(data)
        self.backend.nodes[self.path][1] = self.getvalue()
        return value

    def truncate(self, size=None):
        value = super().truncate(size)
        self.backend.nodes[self.path][1] = self.getvalue()
        return value

    def flush(self):
        self.backend.event("flush:" + self.path.name)
        super().flush()

    def close(self):
        if self.closed:
            return
        self.backend.event("close:" + self.path.name)
        super().close()


class MemoryFile(FileHandle):
    def size(self):
        self.backend.verify(self)
        return len(self.backend.nodes[self.identity.final_path][1])

    def read_bounded(self, limit):
        self.backend.verify(self)
        # Host drift is visible on the same synthetic identity.
        data = self.backend.nodes[self.identity.final_path][1]
        self.stream.reads += 1
        if len(data) > limit:
            raise ValueError("calibration_observation_invalid")
        return data


class FakeHandleBackend:
    def __init__(self):
        self.nodes = {}
        self.handles = []
        self.events = []
        self.fail = None

    def event(self, name):
        self.events.append(name)
        if self.fail == name:
            raise OSError("PRIVATE_SENTINEL")

    def put(self, path, content=None):
        path = Path(path)
        for parent in reversed(path.parents):
            self.nodes.setdefault(parent, [True, b"", len(self.nodes) + 1])
        self.nodes[path] = [content is None, content or b"", len(self.nodes) + 1]

    def _handle(self, path, directory):
        node = self.nodes[path]
        if node[0] != directory:
            raise ValueError("calibration_observation_invalid")
        identity = FileIdentity(1, node[2], path, directory, 1)
        handle = (DirectoryHandle(self, node[2], identity) if directory
                  else MemoryFile(self, node[2], identity, MemoryStream(node[1], self, path)))
        self.handles.append(handle)
        return handle

    def pin_existing(self, path, *, directory, writable=False, lease=False):
        self.event("pin:" + Path(path).name)
        return self._handle(Path(path), directory)

    def verify(self, handle):
        self.event("verify:" + handle.identity.final_path.name)
        node = self.nodes[handle.identity.final_path]
        if handle.closed or node[2] != handle.identity.file_id or node[0] != handle.identity.is_directory:
            raise ValueError("calibration_observation_invalid")
        return handle.identity

    def children(self, parent, *, limit):
        self.verify(parent)
        names = tuple(p.name for p in self.nodes if p.parent == parent.identity.final_path and p != p.parent)
        if len(names) > limit or len({n.casefold() for n in names}) != len(names):
            raise ValueError("calibration_observation_invalid")
        return names

    def _create(self, parent, name, directory):
        component(name)
        self.verify(parent)
        self.event("create:" + name)
        path = parent.identity.final_path / name
        if path in self.nodes:
            raise ValueError("calibration_observation_invalid")
        self.put(path, None if directory else b"")
        return self._handle(path, directory)

    def create_directory(self, parent, name):
        return self._create(parent, name, True)

    def create_file(self, parent, name):
        return self._create(parent, name, False)

    def _close(self, handle):
        self.event("close-dir:" + str(handle))


class FakeGit:
    def __init__(self, relative="file.py", content=b"synthetic public source\n"):
        self.relative, self.content = relative, content
        self.oid = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + self.content).hexdigest()
        self.state = RepositoryState(SOURCE, "synthetic", None, SHA, False, "sha1")
        self.calls = []
        self.hook = None

    def inspect(self, root):
        assert root == SOURCE
        self.calls.append("inspect")
        if self.hook:
            self.hook()
        return self.state

    def _validate_sha(self, root, sha):
        assert root == SOURCE and sha == SHA

    def _run(self, root, *args):
        assert root == SOURCE and args == ("merge-base", "--is-ancestor", SHA, SHA)
        return 0, b""

    def _read(self, root, *args):
        assert root == SOURCE
        self.calls.append(args)
        if args == ("ls-tree", "-r", "-z", "-l", SHA, "--"):
            return f"100644 blob {self.oid} {len(self.content)}\t{self.relative}\0".encode()
        if args == ("cat-file", "blob", self.oid):
            return self.content
        raise AssertionError("unapproved_git_arguments")


class FakeLease:
    def __init__(self, root, *, stream=None):
        self.stream, self.closed = stream, False

    def close(self):
        self.closed = True
        if self.stream is not None:
            self.stream.close()


class SyntheticTask:
    def __init__(self, *, root=ROOT, relative="file.py", content=b"synthetic public source\n", command="python synthetic_test.py"):
        self.root = root
        self.backend, self.git = FakeHandleBackend(), FakeGit(relative, content)
        self.catalog = RepositoryCatalog((RegisteredRepository("random_alias_0001", SOURCE, self.git.state),))
        manifest = [[relative, "100644", self.git.oid, len(content)]]
        manifest_digest = hashlib.sha256(json.dumps(manifest, separators=(",", ":")).encode()).hexdigest()
        self.spec = TaskSpec(TASK, REPO, SHA, SHA, "Synthetic maintenance", (relative,), (relative,),
                             ".mokioclaw/task-scratch/", manifest_digest, 1200, 1, (command,), 20, 150000, 3072, UTC)
        request = asdict(self.spec)
        for name in ("task_id", "created_at"):
            request.pop(name)
        events = tuple(PublicTaskEvent(TASK, None, n, UTC, "state", {"state": state})
                       for n, state in enumerate(("preparing", "prepared"), 1))
        self.record = TaskRecord(TASK, REPO, SHA, SHA, manifest_digest, UTC, "prepared", None, 2,
                                 digest(request), "b" * 64, events=events)
        self.task_root, self.task_dir = root / "tasks", root / "tasks" / TASK
        self.obs = root / "observations" / TASK
        b = self.backend
        b.put(self.task_root / ".dashboard.lock", b"0")
        b.put(self.task_dir / "spec.json", raw(asdict(self.spec)))
        b.put(self.task_dir / "record.json", raw(asdict(self.record)))
        for directory in ("baseline", "work"):
            b.put(self.task_dir / "workspace" / directory / relative, self.git.content)
        for name in ("NOTEPAD.md", "HISTORY_SUMMARY.md"):
            b.put(self.task_dir / "workspace/work/.mokioclaw/task-scratch" / name, b"")
        b.put(self.obs / "calls.jsonl", b"")
        b.put(self.obs / "scores.json", b"")
        b.put(self.obs / "status.json", raw({"schema_version": 1, "task_id": TASK, "valid": False, "reason": "stream_incomplete"}))
        self.spec_sha = hashlib.sha256(b.nodes[self.task_dir / "spec.json"][1]).hexdigest()

    def install(self, monkeypatch):
        import mokioclaw.dashboard.task_observation_handles as handles
        import mokioclaw.dashboard.task_source as source
        import mokioclaw.dashboard.task_service as service
        monkeypatch.setattr(handles, "make_handle_backend", lambda: self.backend)
        monkeypatch.setattr(source, "source_identity", lambda root: (1, 2, 3, 4))
        monkeypatch.setattr(service, "_TaskRootLease", FakeLease)
        # Only synthetic descriptors are permitted through the durability boundary.
        import os
        def fsync(fd):
            assert fd == -12345
            self.backend.event("fsync")
        monkeypatch.setattr(os, "fsync", fsync)


@contextmanager
def offline_continuation_guard(monkeypatch):
    with offline_observation_guard(monkeypatch):
        yield
