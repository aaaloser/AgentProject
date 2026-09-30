"""Prepare an isolated baseline/work pair from an approved Git commit."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from mokioclaw.dashboard.catalog import RepositoryCatalog
from mokioclaw.dashboard.git_reader import GitOutputLimit, GitReadError, GitReadTimeout, InvalidRepository, LocalGitReader
from mokioclaw.dashboard.task_source import InvalidTaskPreview, ManifestEntry, TaskPreview, TaskSource, source_identity


class InvalidTaskPreparation(ValueError):
    """A fixed source tree cannot be copied into a safe task workspace."""


@dataclass(frozen=True)
class SourceObservation:
    head_sha: str
    refs_digest: str
    index_digest: str
    worktree_status_digest: str


@dataclass(frozen=True)
class PreparedTask:
    task_id: str
    root: Path
    baseline: Path
    work: Path
    base_sha: str
    manifest_digest: str
    files: tuple[ManifestEntry, ...]
    source_before: SourceObservation
    source_after: SourceObservation


def _within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _validate_task_root(task_root: Path, catalog: RepositoryCatalog) -> Path:
    requested = Path(task_root)
    if not requested.is_absolute():
        raise InvalidTaskPreparation("Task root must be absolute")
    root = requested.resolve(strict=False)
    forbidden = [registered.root.resolve(strict=False) for registered in catalog._repositories]
    project_root = Path(__file__).resolve().parents[3]
    forbidden.append((project_root / "evals" / "reports").resolve(strict=False))
    if any(_within(root, path) for path in forbidden):
        raise InvalidTaskPreparation("Task root is inside a protected source or evidence tree")
    return root


def _source_observation(root: Path, reader: LocalGitReader) -> SourceObservation:
    head = reader._read(root, "rev-parse", "HEAD").decode("ascii").strip()
    refs = reader._read(root, "show-ref", "--head")
    status = reader._read(root, "status", "--porcelain=v1", "-z", "--untracked-files=normal")
    index_location = reader._read(root, "rev-parse", "--git-path", "index").decode("utf-8").strip()
    index_path = Path(index_location)
    if not index_path.is_absolute():
        index_path = root / index_path
    index_bytes = index_path.read_bytes()
    return SourceObservation(
        head_sha=head,
        refs_digest=hashlib.sha256(refs).hexdigest(),
        index_digest=hashlib.sha256(index_bytes).hexdigest(),
        worktree_status_digest=hashlib.sha256(status).hexdigest(),
    )


def _verify_blob(content: bytes, entry: ManifestEntry) -> None:
    if len(content) != entry.blob_size:
        raise InvalidTaskPreparation("Git blob size changed during preparation")
    digest = hashlib.sha256 if len(entry.blob_oid) == 64 else hashlib.sha1
    actual = digest(b"blob " + str(len(content)).encode("ascii") + b"\0" + content).hexdigest()
    if actual != entry.blob_oid:
        raise InvalidTaskPreparation("Git blob identity changed during preparation")
    if content.startswith(b"version https://git-lfs.github.com/spec/v1\n"):
        raise InvalidTaskPreparation("Git LFS pointer cannot be prepared")


def _write_regular(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    if not stat.S_ISREG(path.lstat().st_mode):
        raise InvalidTaskPreparation("Prepared path is not a regular file")


def _remove_private_stage(stage: Path, task_directory: Path) -> None:
    absolute_stage = stage.resolve(strict=False)
    absolute_task = task_directory.resolve(strict=True)
    if absolute_stage.parent != absolute_task or not stage.name.startswith(".prepare-"):
        raise InvalidTaskPreparation("Unsafe temporary workspace cleanup target")
    if stage.exists():
        shutil.rmtree(stage)


def prepare_task(
    preview: TaskPreview,
    task_id: str,
    task_root: Path,
    catalog: RepositoryCatalog,
    reader: LocalGitReader,
) -> PreparedTask:
    if re.fullmatch(r"[A-Za-z0-9_-]{16,64}", task_id) is None:
        raise InvalidTaskPreparation("Invalid task identity")
    root = _validate_task_root(task_root, catalog)
    registration = catalog.get(preview.repo_id)
    if registration is None:
        raise InvalidTaskPreparation("Source repository is no longer registered")
    source_root = registration.root
    try:
        current = reader.inspect(source_root)
        if current.root != source_root or current.object_format != registration.state.object_format:
            raise InvalidTaskPreparation("Source repository identity changed")
        if source_identity(source_root) != preview.source_identity:
            raise InvalidTaskPreparation("Source repository identity changed")
        if time.time() >= preview.expires_at:
            raise InvalidTaskPreparation("Source preview expired")
        refreshed = TaskSource(catalog, reader).preview(
            preview.repo_id, preview.base_sha, preview.anchor_sha, preview.source_read_scope
        )
        if refreshed.manifest_digest != preview.manifest_digest or refreshed.files != preview.files:
            raise InvalidTaskPreparation("Fixed source manifest changed")
        if refreshed.blocked_paths or not refreshed.files:
            raise InvalidTaskPreparation("Source preview contains blocked files")
        before = _source_observation(source_root, reader)
    except (InvalidRepository, InvalidTaskPreview, GitReadError, GitReadTimeout, GitOutputLimit, OSError, UnicodeError) as exc:
        raise InvalidTaskPreparation("Source repository cannot be prepared") from exc

    root.mkdir(parents=True, exist_ok=True)
    task_directory = root / task_id
    task_directory.mkdir(exist_ok=True)
    task_stat = task_directory.lstat()
    if (
        not stat.S_ISDIR(task_stat.st_mode)
        or getattr(task_stat, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        or task_directory.resolve(strict=True).parent != root
    ):
        raise InvalidTaskPreparation("Task directory must be a real child of task root")
    published = task_directory / "workspace"
    if published.exists():
        raise InvalidTaskPreparation("Task workspace already exists")
    stage = task_directory / f".prepare-{os.urandom(8).hex()}"
    stage.mkdir()
    baseline = stage / "baseline"
    work = stage / "work"
    baseline.mkdir()
    work.mkdir()
    try:
        for entry in refreshed.files:
            if source_identity(source_root) != preview.source_identity:
                raise InvalidTaskPreparation("Source repository identity changed")
            content = reader._read(source_root, "cat-file", "blob", entry.blob_oid)
            _verify_blob(content, entry)
            parts = entry.relative_path.split("/")
            _write_regular(baseline.joinpath(*parts), content)
            _write_regular(work.joinpath(*parts), content)
        scratch = work / ".mokioclaw" / "task-scratch"
        _write_regular(scratch / "NOTEPAD.md", b"")
        _write_regular(scratch / "HISTORY_SUMMARY.md", b"")
        after = _source_observation(source_root, reader)
        if source_identity(source_root) != preview.source_identity:
            raise InvalidTaskPreparation("Source repository identity changed")
        if published.exists():
            raise InvalidTaskPreparation("Task workspace already exists")
        os.replace(stage, published)
    except (GitReadError, GitReadTimeout, GitOutputLimit, OSError, UnicodeError, InvalidTaskPreview, InvalidTaskPreparation) as exc:
        _remove_private_stage(stage, task_directory)
        if isinstance(exc, InvalidTaskPreparation):
            raise
        raise InvalidTaskPreparation("Fixed source copy failed") from exc
    return PreparedTask(
        task_id=task_id,
        root=task_directory,
        baseline=published / "baseline",
        work=published / "work",
        base_sha=preview.base_sha,
        manifest_digest=preview.manifest_digest,
        files=refreshed.files,
        source_before=before,
        source_after=after,
    )
