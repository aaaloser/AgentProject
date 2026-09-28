"""Collect bounded, local-only changes from a prepared task workspace."""

from __future__ import annotations

import difflib
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from mokioclaw.dashboard.task_filesystem import TaskFilesystemError, _is_reparse, _relative, open_existing
from mokioclaw.dashboard.task_source import _excluded, _normalize_scope, _selected

if TYPE_CHECKING:
    from mokioclaw.dashboard.task_copy import PreparedTask


MAX_FILES = 5000
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_PATCH_BYTES = 32 * 1024 * 1024


class PatchUnsafe(ValueError):
    """The worktree cannot be safely represented as a complete patch."""


@dataclass(frozen=True)
class PatchSummary:
    status: str
    changed_files: tuple[str, ...] = ()
    added_lines: int = 0
    deleted_lines: int = 0
    patch_path: Path | None = None
    reason: str | None = None


def _scan(root: Path) -> dict[str, int]:
    if _is_reparse(root) or not stat.S_ISDIR(root.lstat().st_mode):
        raise PatchUnsafe("unsafe_root")
    files: dict[str, int] = {}
    total = 0
    pending = [(root, "")]
    while pending:
        directory, prefix = pending.pop()
        if _is_reparse(directory) or not stat.S_ISDIR(directory.lstat().st_mode):
            raise PatchUnsafe("unsafe_directory")
        with os.scandir(directory) as entries:
            for entry in entries:
                relative = _relative(prefix + entry.name)
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or bool(
                    getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                ):
                    raise PatchUnsafe("link_in_workspace")
                if stat.S_ISDIR(info.st_mode):
                    pending.append((Path(entry.path), relative + "/"))
                elif stat.S_ISREG(info.st_mode):
                    if info.st_size > MAX_FILE_BYTES:
                        raise PatchUnsafe("file_too_large")
                    files[relative] = info.st_size
                    total += info.st_size
                    if len(files) > MAX_FILES or total > MAX_TOTAL_BYTES:
                        raise PatchUnsafe("workspace_limit_exceeded")
                else:
                    raise PatchUnsafe("non_regular_file")
        if _is_reparse(directory):
            raise PatchUnsafe("unsafe_directory")
    return files


def _read(root: Path, relative: str, expected_size: int) -> str:
    descriptor = open_existing(root, relative)
    with os.fdopen(descriptor, "rb") as stream:
        if os.fstat(stream.fileno()).st_size != expected_size:
            raise PatchUnsafe("file_changed_during_collection")
        content = stream.read(MAX_FILE_BYTES + 1)
    if len(content) != expected_size or b"\0" in content:
        raise PatchUnsafe("binary_or_changed_file")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PatchUnsafe("invalid_utf8") from exc


def _publish(prepared: PreparedTask, patch: bytes) -> Path:
    artifacts = prepared.root / "artifacts"
    artifacts.mkdir(exist_ok=True)
    if _is_reparse(artifacts) or not stat.S_ISDIR(artifacts.lstat().st_mode):
        raise PatchUnsafe("unsafe_artifact_directory")
    fd, temporary = tempfile.mkstemp(prefix=".patch-", dir=artifacts)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(patch)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, artifacts / "patch.diff")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return artifacts / "patch.diff"


def collect_patch(
    prepared: PreparedTask,
    source_write_scope: tuple[str, ...],
    task_scratch_scope: str,
) -> PatchSummary:
    """Return a complete patch or a fixed unavailable reason, never a partial patch."""
    try:
        if task_scratch_scope != ".mokioclaw/task-scratch/":
            raise PatchUnsafe("unsupported_scratch_scope")
        scope = _normalize_scope(source_write_scope)
        baseline = _scan(prepared.baseline)
        work = _scan(prepared.work)
        changed: list[str] = []
        chunks: list[str] = []
        added = deleted = 0
        for relative in sorted(set(baseline) | set(work)):
            if relative.startswith(task_scratch_scope):
                if relative in baseline:
                    raise PatchUnsafe("scratch_in_baseline")
                continue
            if _excluded(relative):
                raise PatchUnsafe("excluded_path")
            before = _read(prepared.baseline, relative, baseline[relative]) if relative in baseline else ""
            after = _read(prepared.work, relative, work[relative]) if relative in work else ""
            if before == after:
                continue
            if not _selected(relative, scope):
                raise PatchUnsafe("change_outside_write_scope")
            changed.append(relative)
            lines = list(difflib.unified_diff(
                before.splitlines(keepends=True), after.splitlines(keepends=True),
                fromfile="a/" + relative, tofile="b/" + relative,
            ))
            added += sum(line.startswith("+") and not line.startswith("+++") for line in lines)
            deleted += sum(line.startswith("-") and not line.startswith("---") for line in lines)
            chunks.extend(lines)
            if sum(len(chunk.encode("utf-8")) for chunk in chunks) > MAX_PATCH_BYTES:
                raise PatchUnsafe("patch_too_large")
        payload = "".join(chunks).encode("utf-8")
        path = _publish(prepared, payload) if changed else None
        return PatchSummary("available", tuple(changed), added, deleted, path)
    except (OSError, ValueError, TaskFilesystemError) as exc:
        reason = str(exc) if isinstance(exc, PatchUnsafe) else "unsafe_workspace"
        return PatchSummary("patch_unavailable", reason=reason)
