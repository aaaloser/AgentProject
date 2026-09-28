"""Scoped host file access for a prepared Web task.

Windows uses a verified, delete-denying handle for existing files. Operations
that need an atomic relative-directory handle remain unavailable on Windows.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING

from mokioclaw.dashboard.task_source import _normalize_scope, _safe_component, _selected

if TYPE_CHECKING:
    from mokioclaw.dashboard.task_copy import PreparedTask


class TaskFilesystemError(ValueError):
    """A task file operation is outside its safe, supported boundary."""


MAX_FILE_BYTES = 8 * 1024 * 1024


def _relative(path: str) -> str:
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path or ":" in path:
        raise TaskFilesystemError("Unsafe task path")
    if not all(_safe_component(part) for part in path.rstrip("/").split("/")):
        raise TaskFilesystemError("Unsafe task path")
    if "//" in path or path == "." or path.endswith("//"):
        raise TaskFilesystemError("Unsafe task path")
    return path


def _is_reparse(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _check_components(root: Path, relative: str) -> None:
    if _is_reparse(root) or not stat.S_ISDIR(root.lstat().st_mode):
        raise TaskFilesystemError("Task work root changed")
    current = root
    for component in relative.split("/"):
        current /= component
        if _is_reparse(current):
            raise TaskFilesystemError("Task path contains a link")


def _windows_open_existing(root: Path, relative: str, *, write: bool) -> int:
    import ctypes
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                       ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    create.restype = ctypes.c_void_p
    final = kernel.GetFinalPathNameByHandleW
    final.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32]
    final.restype = ctypes.c_uint32
    close = kernel.CloseHandle
    close.argtypes = [ctypes.c_void_p]
    handle = create(str(root.joinpath(*relative.split("/"))), 0x80000000 | (0x40000000 if write else 0),
                    0x00000001, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise TaskFilesystemError("Task file cannot be opened")
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = final(handle, buffer, len(buffer), 0)
        if length == 0 or length >= len(buffer):
            raise TaskFilesystemError("Task file identity unavailable")
        actual = buffer.value.removeprefix("\\\\?\\")
        expected = str(root.joinpath(*relative.split("/")))
        if os.path.normcase(os.path.abspath(actual)) != os.path.normcase(os.path.abspath(expected)):
            raise TaskFilesystemError("Task file escaped its work root")
        _check_components(root, relative)
        descriptor = msvcrt.open_osfhandle(handle, os.O_BINARY | (os.O_RDWR if write else os.O_RDONLY))
        handle = None
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise TaskFilesystemError("Task path is not a regular file")
        return descriptor
    finally:
        if handle is not None:
            close(handle)


def _posix_open_existing(root: Path, relative: str, *, write: bool) -> int:
    nofollow = os.O_NOFOLLOW
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | nofollow)
    try:
        parts = relative.split("/")
        for component in parts[:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | nofollow, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(parts[-1], (os.O_RDWR if write else os.O_RDONLY) | nofollow, dir_fd=directory)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise TaskFilesystemError("Task path is not a regular file")
        return descriptor
    finally:
        os.close(directory)


def open_existing(root: Path, relative: str, *, write: bool = False) -> int:
    """Open an existing ordinary file only after establishing its task identity."""
    normalized = _relative(relative)
    if normalized.endswith("/"):
        raise TaskFilesystemError("A file path is required")
    try:
        if os.name == "nt":
            _check_components(root, normalized)
            return _windows_open_existing(root, normalized, write=write)
        return _posix_open_existing(root, normalized, write=write)
    except (OSError, ValueError) as exc:
        if isinstance(exc, TaskFilesystemError):
            raise
        raise TaskFilesystemError("Task file access failed") from exc


class TaskFilesystem:
    def __init__(
        self,
        prepared: PreparedTask,
        source_read_scope: tuple[str, ...],
        source_write_scope: tuple[str, ...],
        task_scratch_scope: str,
    ) -> None:
        self.prepared = prepared
        self.read_scope = _normalize_scope(source_read_scope)
        self.write_scope = _normalize_scope(source_write_scope)
        if task_scratch_scope != ".mokioclaw/task-scratch/":
            raise TaskFilesystemError("Unsupported scratch scope")
        self.scratch_scope = task_scratch_scope

    def _authorize(self, path: str, *, write: bool = False, scratch: bool = False) -> str:
        normalized = _relative(path)
        scope = (self.scratch_scope,) if scratch else self.write_scope if write else self.read_scope
        if not _selected(normalized, scope):
            raise TaskFilesystemError("Task path is outside its scope")
        return normalized

    def read_bytes(self, path: str, *, scratch: bool = False) -> bytes:
        relative = self._authorize(path, scratch=scratch)
        descriptor = open_existing(self.prepared.work, relative)
        with os.fdopen(descriptor, "rb") as stream:
            if os.fstat(stream.fileno()).st_size > MAX_FILE_BYTES:
                raise TaskFilesystemError("Task file limit exceeded")
            content = stream.read(MAX_FILE_BYTES + 1)
            if len(content) > MAX_FILE_BYTES:
                raise TaskFilesystemError("Task file limit exceeded")
            return content

    def write_bytes(self, path: str, content: bytes, *, scratch: bool = False) -> None:
        if not isinstance(content, bytes) or len(content) > MAX_FILE_BYTES:
            raise TaskFilesystemError("Task file limit exceeded")
        relative = self._authorize(path, write=True, scratch=scratch)
        descriptor = open_existing(self.prepared.work, relative, write=True)
        with os.fdopen(descriptor, "r+b") as stream:
            stream.seek(0)
            stream.write(content)
            stream.truncate()

    def create_bytes(self, path: str, content: bytes, *, scratch: bool = False) -> None:
        self._authorize(path, write=True, scratch=scratch)
        raise TaskFilesystemError("Atomic task file creation is unavailable")

    def rename(self, source: str, target: str, *, scratch: bool = False) -> None:
        self._authorize(source, write=True, scratch=scratch)
        self._authorize(target, write=True, scratch=scratch)
        raise TaskFilesystemError("Atomic task file rename is unavailable")

    def delete(self, path: str, *, scratch: bool = False) -> None:
        self._authorize(path, write=True, scratch=scratch)
        raise TaskFilesystemError("Atomic task file deletion is unavailable")

    def iter_files(self, directory: str, *, scratch: bool = False) -> tuple[str, ...]:
        self._authorize(directory, scratch=scratch)
        raise TaskFilesystemError("Safe recursive task traversal is unavailable")
