"""One-shot continuation of an explicitly identified, never-executed Task."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from typing import BinaryIO, Sequence

from mokioclaw.dashboard.catalog import RegisteredRepository, RepositoryCatalog
from mokioclaw.dashboard.task_copy import _verify_blob
from mokioclaw.dashboard.task_models import PublicTaskEvent, TaskRecord, TaskSpec
from mokioclaw.dashboard import task_observation_handles as handles
from mokioclaw.dashboard.task_observation_handles import ERROR, FileHandle
from mokioclaw.dashboard.task_source import ManifestEntry, TaskSource, _normalize_scope
from mokioclaw.dashboard.task_store import _digest

_ID = re.compile(r"[A-Za-z0-9_-]{16,64}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_OLD = ("calls.jsonl", "scores.json", "status.json")
_SCRATCH = (".mokioclaw/task-scratch/NOTEPAD.md", ".mokioclaw/task-scratch/HISTORY_SUMMARY.md")


def _require(value):
    if not value:
        raise ValueError(ERROR)


def _absolute(path):
    return Path(os.path.abspath(path))


@dataclass(frozen=True)
class ContinuationOptions:
    task_id: str
    expected_spec_sha256: str
    expected_source_root: Path


def parse_continuation_options(*, task_id: str | None, expected_spec_sha256: str | None,
                               expected_source_root: Path | None, calibration_root: Path | None,
                               task_root: Path | None, enable_agent: bool, task_image: str | None,
                               repo_paths: Sequence[Path]) -> ContinuationOptions | None:
    if all(value is None for value in (task_id, expected_spec_sha256, expected_source_root)):
        return None
    try:
        _require(type(task_id) is str and _ID.fullmatch(task_id) is not None)
        _require(type(expected_spec_sha256) is str and _SHA256.fullmatch(expected_spec_sha256) is not None)
        _require(expected_source_root is not None and Path(expected_source_root).is_absolute())
        _require(calibration_root is not None and Path(calibration_root).is_absolute())
        _require(task_root is not None and Path(task_root).is_absolute())
        _require(_absolute(task_root) == _absolute(calibration_root) / "tasks")
        _require(enable_agent is True and type(task_image) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", task_image))
        _require(len(repo_paths) == 1 and _absolute(repo_paths[0]) == _absolute(expected_source_root))
        return ContinuationOptions(task_id, expected_spec_sha256, _absolute(expected_source_root))
    except Exception:
        raise ValueError("calibration_config_invalid") from None


def strict_json(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result)
            result[key] = value
        return result

    def constant(value):
        raise ValueError(ERROR)
    try:
        result = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=pairs, parse_constant=constant)
        _require(type(result) is dict)
        return result
    except Exception:
        raise ValueError(ERROR) from None


def _shape(value, cls):
    _require(type(value) is dict and set(value) == {field.name for field in fields(cls)})


def _utc(value):
    _require(type(value) is str and len(value) <= 40 and value.endswith("Z"))
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _require(parsed.utcoffset().total_seconds() == 0)
    return parsed


def _spec(raw):
    value = strict_json(raw)
    _shape(value, TaskSpec)
    for name in ("task_id", "repo_id"):
        _require(type(value[name]) is str and _ID.fullmatch(value[name]))
    for name in ("base_sha", "anchor_sha"):
        _require(type(value[name]) is str and _OID.fullmatch(value[name]))
    _require(value["base_sha"] == value["anchor_sha"])
    _require(type(value["manifest_digest"]) is str and _SHA256.fullmatch(value["manifest_digest"]))
    _utc(value["created_at"])
    _require(type(value["description"]) is str and 0 < len(value["description"]) <= 4000 and value["description"].strip())
    for name in ("source_read_scope", "source_write_scope", "verification_commands"):
        _require(type(value[name]) is list and all(type(item) is str for item in value[name]))
        value[name] = tuple(value[name])
    scope = _normalize_scope(value["source_read_scope"])
    _require(scope == value["source_read_scope"] == value["source_write_scope"])
    _require(value["task_scratch_scope"] == ".mokioclaw/task-scratch/")
    _require(len(value["verification_commands"]) <= 10 and all(0 < len(item) <= 2000 for item in value["verification_commands"]))
    for name, maximum in (("max_seconds", 1800), ("max_attempts", 3), ("max_provider_calls", 24),
                          ("max_total_tokens", 300000), ("max_output_tokens_per_call", 4096)):
        _require(type(value[name]) is int and 1 <= value[name] <= maximum)
    return TaskSpec(**value)


def _record(raw, spec):
    value = strict_json(raw)
    _shape(value, TaskRecord)
    for name in ("task_id", "repo_id", "base_sha", "anchor_sha", "manifest_digest", "created_at"):
        _require(type(value[name]) is str and value[name] == getattr(spec, name))
    _require(value["state"] == "prepared" and type(value["sequence"]) is int and value["sequence"] == 2)
    _require(value["execution_started"] is False and value["cleanup_confirmed"] is False)
    for name in ("attempt_id", "instance_id", "worker_pid", "worker_created_at", "failure_kind", "verification_status"):
        _require(value[name] is None)
    for name in ("request_digest", "idempotency_digest"):
        _require(type(value[name]) is str and _SHA256.fullmatch(value[name]))
    request = asdict(spec)
    request.pop("task_id")
    request.pop("created_at")
    _require(value["request_digest"] == _digest(request))
    for name in ("owned_request_ids", "execution_receipts"):
        _require(type(value[name]) is list and not value[name])
        value[name] = ()
    _require(type(value["events"]) is list and len(value["events"]) == 2)
    events = []
    last_time = _utc(spec.created_at)
    for index, event in enumerate(value["events"], 1):
        _shape(event, PublicTaskEvent)
        _require(event["task_id"] == spec.task_id and event["attempt_id"] is None)
        _require(type(event["sequence"]) is int and event["sequence"] == index and event["kind"] == "state")
        _require(type(event["data"]) is dict and event["data"] == {"state": "preparing" if index == 1 else "prepared"})
        timestamp = _utc(event["timestamp"])
        _require(timestamp >= last_time)
        last_time = timestamp
        events.append(PublicTaskEvent(**event))
    value["events"] = tuple(events)
    return TaskRecord(**value)


def restore_continuation_catalog(catalog: RepositoryCatalog, spec: TaskSpec, expected_root: Path) -> RepositoryCatalog:
    entries = catalog._repositories
    _require(len(entries) == 1 and entries[0].root == _absolute(expected_root))
    entry = entries[0]
    return RepositoryCatalog((RegisteredRepository(spec.repo_id, entry.root, entry.state),))


def write_durable(handle: FileHandle, raw: bytes):
    handle.backend.verify(handle)
    _require(handle.stream.write(raw) == len(raw))
    handle.stream.flush()
    os.fsync(handle.stream.fileno())
    handle.backend.verify(handle)


@dataclass
class ContinuationCheck:
    spec: TaskSpec
    record: TaskRecord
    record_sha256: str
    manifest: tuple[ManifestEntry, ...]
    handles: list
    owner: object = None
    closed: bool = False
    close_failed: bool = False

    def close(self):
        if self.closed:
            return
        if self.close_failed:
            raise ValueError(ERROR)
        failed = False
        for handle in reversed(self.handles):
            try:
                handle.close()
            except Exception:
                failed = True
        if failed:
            self.close_failed = True
            if self.owner is not None:
                self.owner.cleanup_failed = True
            raise ValueError(ERROR) from None
        self.closed = True
        if self.owner is not None and self in self.owner.pending_checks:
            self.owner.pending_checks.remove(self)


class ObservationSession:
    def __init__(self, owner, session_id, directory, metadata):
        self.owner, self.session_id, self.directory, self.metadata = owner, session_id, directory, metadata
        self.metadata_sha256 = metadata.fingerprint(16384).sha256
        self._journal_files = []
        self._transferred = False
        self._created = False

    def create_journal_files(self) -> tuple[FileHandle, FileHandle, FileHandle]:
        _require(not self._created)
        self._created = True
        for name in _OLD:
            self._journal_files.append(self.owner.backend.create_file(self.directory, name))
        self._transferred = True
        return tuple(self._journal_files)

    def verify_layout(self):
        _require(self.owner.session is self and self._created and self._transferred)
        _require(set(self.owner.backend.children(self.directory, limit=4)) == {"session.json", *_OLD})
        _require(self.metadata.fingerprint(16384).sha256 == self.metadata_sha256)
        for handle in self._journal_files:
            if not handle.closed:
                self.owner.backend.verify(handle)

    def close(self):
        if not self._transferred:
            for handle in reversed(self._journal_files):
                handle.close()
        self.metadata.close()
        self.directory.close()


class PrestartObservationContinuation:
    def __init__(self, options, root, task_root, backend):
        self.options, self.root, self.task_root, self.backend = options, root, task_root, backend
        self.long_handles, self.old_files, self.previous_files = [], {}, {}
        self.session, self.sessions_directory = None, None
        self.consumed = False
        self.cleanup_failed = False
        self.pending_checks = []
        self._lease_file = None

    @classmethod
    def open(cls, options: ContinuationOptions, calibration_root: Path, task_root: Path, *, backend=None):
        backend = backend or handles.make_handle_backend()
        owner = cls(options, _absolute(calibration_root), _absolute(task_root), backend)
        try:
            _require(_ID.fullmatch(options.task_id) and _SHA256.fullmatch(options.expected_spec_sha256))
            _require(owner.task_root == owner.root / "tasks" and Path(options.expected_source_root).is_absolute())
            owner.root_handle = owner._pin(owner.root, True)
            owner.tasks_handle = owner._pin(owner.task_root, True)
            owner.task_directory = owner.task_root / options.task_id
            owner.task_handle = owner._pin(owner.task_directory, True)
            owner.observations_handle = owner._pin(owner.root / "observations", True)
            owner.obs_handle = owner._pin(owner.root / "observations" / options.task_id, True)
            owner.spec_handle = owner._pin(owner.task_directory / "spec.json", False)
            return owner
        except Exception:
            owner.close()
            raise ValueError(ERROR) from None

    def _pin(self, path, directory):
        handle = self.backend.pin_existing(path, directory=directory)
        self.long_handles.append(handle)
        return handle

    def lease_stream(self) -> BinaryIO:
        _require(self._lease_file is None)
        self._lease_file = self.backend.pin_existing(self.task_root / ".dashboard.lock", directory=False, lease=True)
        return self._lease_file.stream

    def verify_lease(self, fd: int):
        _require(self._lease_file is not None and self._lease_file.stream.fileno() == fd)
        self.backend.verify(self.tasks_handle)
        self.backend.verify(self._lease_file)

    def _root_layout(self, session):
        _require(set(self.backend.children(self.tasks_handle, limit=1000)) == {".dashboard.lock", self.options.task_id})
        _require(set(self.backend.children(self.task_handle, limit=4)) == {"spec.json", "record.json", "workspace"})
        children = set(self.backend.children(self.obs_handle, limit=4))
        if session is None:
            _require(children == set(_OLD) and not self.consumed)
        else:
            _require(session is self.session and children == {*_OLD, "sessions"})
            _require(set(self.backend.children(self.sessions_directory, limit=1)) == {session.session_id})
            session.verify_layout()

    def _legacy(self):
        for name in _OLD:
            if name not in self.old_files:
                self.old_files[name] = self._pin(self.obs_handle.identity.final_path / name, False)
        calls = self.old_files["calls.jsonl"]
        _require(calls.size() == 0)  # Refuse without ever reading nonempty legacy calls.
        scores = self.old_files["scores.json"].read_bounded(65536)
        if scores:
            value = strict_json(scores)
            _require(set(value) == {"schema_version", "task_id", "indexes"} and type(value["schema_version"]) is int
                     and value["schema_version"] == 1 and value["task_id"] == self.options.task_id
                     and type(value["indexes"]) is list and not value["indexes"])
        value = strict_json(self.old_files["status.json"].read_bounded(4096))
        _require(type(value.get("schema_version")) is int and value["schema_version"] == 1
                 and value.get("task_id") == self.options.task_id and value.get("valid") is False)
        if set(value) == {"schema_version", "task_id", "valid", "reason"}:
            _require(value["reason"] == "stream_incomplete")
        else:
            _require(set(value) == {"schema_version", "task_id", "valid", "event_count", "started_calls", "unknown_calls",
                                    "reasons", "stream_closed", "cleanup_confirmed"})
            _require(value["stream_closed"] is False and value["cleanup_confirmed"] is False)
            for name in ("event_count", "started_calls", "unknown_calls"):
                _require(type(value[name]) is int and value[name] == 0)
            reasons = value["reasons"]
            _require(type(reasons) is list and reasons and all(type(reason) is str for reason in reasons))
            _require(reasons == sorted(set(reasons)) and set(reasons) <= {
                "observer_fault", "stream_incomplete", "cleanup_unconfirmed", "record_invalid"})
        if not self.previous_files:
            self.previous_files = {name: handle.fingerprint(65536 if name == "scores.json" else 4096)
                                   for name, handle in self.old_files.items()}
        self.verify_preserved()

    def verify_preserved(self):
        for name, fingerprint in self.previous_files.items():
            _require(self.old_files[name].fingerprint(65536 if name == "scores.json" else 4096) == fingerprint)

    def _copies(self, path, files, temporary):
        _require(len(files) <= 5000 and sum(map(len, files.values())) <= 128 * 1024 * 1024)
        required_dirs = {""}
        for relative in files:
            parts = relative.split("/")
            required_dirs.update("/".join(parts[:n]) for n in range(1, len(parts)))
        seen_files, seen_dirs = set(), set()
        root = self.backend.pin_existing(path, directory=True)
        temporary.append(root)
        pending = [(root, "")]
        while pending:
            parent, relative = pending.pop()
            seen_dirs.add(relative)
            expected_names = {p[len(relative) + 1 if relative else 0:].split("/")[0]
                              for p in files if not relative or p.startswith(relative + "/")}
            names = self.backend.children(parent, limit=5000)
            _require(set(names) == expected_names)
            for name in names:
                child = relative + "/" + name if relative else name
                if child in required_dirs:
                    directory = self.backend.pin_existing(path / child, directory=True)
                    temporary.append(directory)
                    pending.append((directory, child))
                else:
                    _require(child in files)
                    handle = self.backend.pin_existing(path / child, directory=False)
                    temporary.append(handle)
                    _require(handle.read_bounded(8 * 1024 * 1024) == files[child])
                    seen_files.add(child)
        _require(seen_files == set(files) and seen_dirs == required_dirs)

    def check(self, catalog, reader, *, cached_record: TaskRecord | None, session: ObservationSession | None = None):
        temporary = []
        try:
            self._root_layout(session)
            spec_raw = self.spec_handle.read_bounded(65536)
            _require(hashlib.sha256(spec_raw).hexdigest() == self.options.expected_spec_sha256)
            spec = _spec(spec_raw)
            _require(spec.task_id == self.options.task_id)
            record_handle = self.backend.pin_existing(self.task_directory / "record.json", directory=False)
            temporary.append(record_handle)
            record_raw = record_handle.read_bounded(1048576)
            record = _record(record_raw, spec)
            if cached_record is not None:
                # JSON equality alone would equate bool/int and int/float.
                _require(type(cached_record) is TaskRecord and _digest(asdict(cached_record)) == _digest(asdict(record)))
            restored = restore_continuation_catalog(catalog, spec, self.options.expected_source_root)
            root = self.options.expected_source_root
            current = reader.inspect(root)
            _require(current.root == root and current.dirty is False and current.head_sha == spec.base_sha)
            preview = TaskSource(restored, reader).preview(spec.repo_id, spec.base_sha, spec.anchor_sha, spec.source_read_scope)
            _require(not preview.blocked_paths and preview.manifest_digest == spec.manifest_digest and preview.files)
            content = {}
            for entry in preview.files:
                blob = reader._read(root, "cat-file", "blob", entry.blob_oid)
                _verify_blob(blob, entry)
                content[entry.relative_path] = blob
            self._copies(self.task_directory / "workspace/baseline", content, temporary)
            self._copies(self.task_directory / "workspace/work", {**content, **dict.fromkeys(_SCRATCH, b"")}, temporary)
            _require(reader.inspect(root) == current)
            self._legacy()
            self._root_layout(session)
            check = ContinuationCheck(spec, record, hashlib.sha256(record_raw).hexdigest(), preview.files, temporary, self)
            self.pending_checks.append(check)
            return check
        except Exception:
            failed = False
            for handle in reversed(temporary):
                try:
                    handle.close()
                except Exception:
                    failed = True
            if failed:
                self.cleanup_failed = True
                self.long_handles.extend(handle for handle in temporary if not handle.closed)
            raise ValueError(ERROR) from None

    def create_session(self, check: ContinuationCheck):
        try:
            _require(not self.consumed and self.session is None and check.spec.task_id == self.options.task_id)
            self._root_layout(None)
            self.sessions_directory = self.backend.create_directory(self.obs_handle, "sessions")
            self.consumed = True
            self.long_handles.append(self.sessions_directory)
            session_id = secrets.token_hex(16)
            directory = self.backend.create_directory(self.sessions_directory, session_id)
            self.long_handles.append(directory)  # Retained even if metadata creation fails.
            metadata = self.backend.create_file(directory, "session.json")
            self.long_handles.append(metadata)
            data = {"schema_version": 1, "mode": "prestart_continuation", "task_id": self.options.task_id,
                    "session_id": session_id, "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "expected_spec_sha256": self.options.expected_spec_sha256,
                    "record_sha256_at_bind": check.record_sha256, "manifest_digest": check.spec.manifest_digest,
                    "previous_layout": "legacy", "previous_files": {
                        name: {"size_bytes": fingerprint.size_bytes, "sha256": fingerprint.sha256}
                        for name, fingerprint in self.previous_files.items()}}
            payload = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
            _require(len(payload) <= 16384)
            write_durable(metadata, payload)
            self.session = ObservationSession(self, session_id, directory, metadata)
            # Session owns these guards after successful metadata publication.
            self.long_handles.remove(metadata)
            self.long_handles.remove(directory)
            return self.session
        except Exception:
            raise ValueError(ERROR) from None

    def close(self):
        _require(not self.cleanup_failed and not self.pending_checks and not getattr(self.backend, "cleanup_failed", False))
        for handle in reversed(self.long_handles):
            handle.close()
