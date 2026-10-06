"""Pinned, bounded handles used only by pre-start observation continuation.

Windows excludes writers/deleters while guards live. POSIX verifies identities
through dir_fd but is not a sandbox against arbitrary host writers.
"""

from __future__ import annotations

import ctypes as c
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
from types import SimpleNamespace
from typing import BinaryIO, Protocol

ERROR = "calibration_observation_invalid"


class _TransferredHandleError(Exception):
    """The CRT took ownership; the raw Win32 handle must never be closed again."""


def component(name: str) -> str:
    if (not isinstance(name, str) or not name or name in {".", ".."}
            or any(char in name for char in '/\\:\0') or name[-1] in '. '
            or any(ord(char) < 32 for char in name)
            or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", name)):
        raise ValueError(ERROR)
    return name


@dataclass(frozen=True)
class FileIdentity:
    volume_id: int
    file_id: int
    final_path: Path
    is_directory: bool
    link_count: int


@dataclass(frozen=True)
class FileFingerprint:
    name: str
    size_bytes: int
    sha256: str


class DirectoryHandle:
    def __init__(self, backend, native_handle: int, identity: FileIdentity, parents=()):
        self.backend = backend
        self.native_handle = native_handle
        self.identity = identity
        self.parents = list(parents)
        self.closed = False

    def close(self) -> None:
        if not self.closed:
            self.backend._close(self.native_handle)
            self.closed = True
        for parent in reversed(self.parents):
            parent.close()


class FileHandle(DirectoryHandle):
    def __init__(self, backend, native_handle, identity, stream: BinaryIO, parents=()):
        super().__init__(backend, native_handle, identity, parents)
        self.stream = stream

    def read_bounded(self, limit: int) -> bytes:
        self.backend.verify(self)
        self.stream.seek(0)
        content = self.stream.read(limit + 1)
        if not isinstance(content, bytes) or len(content) > limit:
            raise ValueError(ERROR)
        self.backend.verify(self)
        return content

    def fingerprint(self, limit: int) -> FileFingerprint:
        raw = self.read_bounded(limit)
        return FileFingerprint(self.identity.final_path.name, len(raw), hashlib.sha256(raw).hexdigest())

    def size(self) -> int:
        self.backend.verify(self)
        return os.fstat(self.stream.fileno()).st_size

    def close(self) -> None:
        if not self.closed:
            self.stream.close()
            if not self.stream.closed:
                raise ValueError(ERROR)
            self.closed = True
        for parent in reversed(self.parents):
            parent.close()


class ObservationHandleBackend(Protocol):
    def pin_existing(self, path: Path, *, directory: bool, writable: bool = False,
                     lease: bool = False) -> DirectoryHandle | FileHandle: ...
    def children(self, parent: DirectoryHandle, *, limit: int) -> tuple[str, ...]: ...
    def create_directory(self, parent: DirectoryHandle, name: str) -> DirectoryHandle: ...
    def create_file(self, parent: DirectoryHandle, name: str) -> FileHandle: ...
    def verify(self, handle: DirectoryHandle | FileHandle) -> FileIdentity: ...


def _names(names, limit):
    result = []
    seen = set()
    for name in names:
        if name in {".", ".."}:
            continue
        component(name)
        if name.casefold() in seen or len(result) >= limit:
            raise ValueError(ERROR)
        seen.add(name.casefold())
        result.append(name)
    return tuple(result)


def decode_directory_page(raw: bytes) -> tuple[str, ...]:
    """FILE_ID_BOTH_DIR_INFO; validate every variable-size record."""
    offset, names = 0, []
    while True:
        if len(raw) - offset < 104:
            raise ValueError(ERROR)
        next_offset = int.from_bytes(raw[offset:offset + 4], "little")
        name_size = int.from_bytes(raw[offset + 60:offset + 64], "little")
        if not name_size or name_size % 2 or offset + 104 + name_size > len(raw):
            raise ValueError(ERROR)
        try:
            names.append(raw[offset + 104:offset + 104 + name_size].decode("utf-16-le", errors="strict"))
        except UnicodeError:
            raise ValueError(ERROR) from None
        if not next_offset:
            break
        if next_offset % 8 or next_offset < 104 + name_size or offset + next_offset >= len(raw):
            raise ValueError(ERROR)
        offset += next_offset
    return tuple(names)


class WindowsObservationHandleBackend:
    def __init__(self, *, api=None):
        self.api = api if api is not None else _WindowsApi()
        self.cleanup_failed = False
        self._unconfirmed = []

    def _close(self, native_handle):
        try:
            self.api.close(native_handle)
        except Exception:
            self.cleanup_failed = True
            self._unconfirmed.append(native_handle)
            raise ValueError(ERROR) from None

    def _identity(self, native, path, directory):
        info = self.api.identity(native)
        if (info.reparse or info.filesystem != "NTFS" or not info.local or not info.file_id
                or info.is_directory != directory or info.final_path != path
                or (not directory and info.link_count != 1)):
            raise ValueError(ERROR)
        return FileIdentity(info.volume_id, info.file_id, info.final_path, directory, info.link_count)

    def _wrap(self, native, path, directory, parents=(), writable=False):
        try:
            identity = self._identity(native, path, directory)
            if directory:
                return DirectoryHandle(self, native, identity, parents)
            stream = self.api.stream(native, writable=writable)
            return FileHandle(self, native, identity, stream, parents)
        except _TransferredHandleError:
            if getattr(self.api, "cleanup_failed", False):
                self.cleanup_failed = True
            raise ValueError(ERROR) from None
        except Exception:
            self._close(native)
            raise ValueError(ERROR) from None

    def pin_existing(self, path, *, directory, writable=False, lease=False):
        parents = []
        try:
            path = Path(os.path.abspath(path))
            if str(path).startswith('\\\\') or not path.drive or writable and not lease:
                raise ValueError(ERROR)
            paths = [Path(path.anchor)]
            for part in path.parts[1:]:
                component(part)
                paths.append(paths[-1] / part)
            for candidate in paths[:-1]:
                native = self.api.open_existing(candidate, directory=True, lease=False)
                parents.append(self._wrap(native, candidate, True))
                if len(parents) > 1 and parents[-1].identity.volume_id != parents[-2].identity.volume_id:
                    raise ValueError(ERROR)
            native = self.api.open_existing(path, directory=directory, lease=lease)
            result = self._wrap(native, path, directory, parents, writable=lease)
            if parents and result.identity.volume_id != parents[-1].identity.volume_id:
                result.close()
                raise ValueError(ERROR)
            return result
        except Exception:
            for parent in reversed(parents):
                parent.close()
            raise ValueError(ERROR) from None

    def verify(self, handle):
        if handle.closed or self._identity(handle.native_handle, handle.identity.final_path,
                                           handle.identity.is_directory) != handle.identity:
            raise ValueError(ERROR)
        return handle.identity

    def children(self, parent, *, limit):
        self.verify(parent)
        names, restart = [], True
        try:
            for page_no in range(limit + 1):
                page = self.api.enumerate_page(parent.native_handle, restart)
                restart = False
                if page is None:
                    break
                names.extend(page)
                _names(names, limit)
            else:
                raise ValueError(ERROR)
            self.verify(parent)
            return _names(names, limit)
        except Exception:
            raise ValueError(ERROR) from None

    def _create(self, parent, name, directory):
        component(name)
        self.verify(parent)
        result = None
        try:
            native, status, information = self.api.create_relative(
                parent.native_handle, name, directory=directory, disposition=2,
                options=0x21 if directory else 0x60,
                # NtCreateFile requires explicit SYNCHRONIZE for synchronous I/O.
                access=0x1000a1 if directory else 0xc0100000, share=1)
            if status != 0 or information != 2 or native in (None, 0, -1):
                if native not in (None, 0, -1):
                    self._close(native)
                raise ValueError(ERROR)
            result = self._wrap(native, parent.identity.final_path / name, directory, writable=not directory)
            if result.identity.volume_id != parent.identity.volume_id:
                result.close()
                raise ValueError(ERROR)
            self.verify(parent)
            return result
        except Exception:
            if result is not None and not result.closed:
                try:
                    result.close()
                except Exception:
                    self.cleanup_failed = True
                    self._unconfirmed.append(result)
            raise ValueError(ERROR) from None

    def create_directory(self, parent, name):
        return self._create(parent, name, True)

    def create_file(self, parent, name):
        return self._create(parent, name, False)


class _WindowsApi:
    """Lazy native ABI. No DLL loading when merely importing the module."""
    def __init__(self):
        if os.name != "nt" or c.sizeof(c.c_wchar) != 2:
            raise ValueError(ERROR)
        from ctypes import wintypes as w
        self.k = c.WinDLL("kernel32", use_last_error=True)
        self.n = c.WinDLL("ntdll", use_last_error=True)

        class UnicodeString(c.Structure):
            _fields_ = [("Length", c.c_uint16), ("MaximumLength", c.c_uint16), ("Buffer", c.c_void_p)]

        class ObjectAttributes(c.Structure):
            _fields_ = [("Length", c.c_uint32), ("RootDirectory", c.c_void_p), ("ObjectName", c.POINTER(UnicodeString)),
                        ("Attributes", c.c_uint32), ("SecurityDescriptor", c.c_void_p), ("SecurityQualityOfService", c.c_void_p)]

        class StatusUnion(c.Union):
            _fields_ = [("Status", c.c_int32), ("Pointer", c.c_void_p)]

        class IoStatus(c.Structure):
            _fields_ = [("u", StatusUnion), ("Information", c.c_size_t)]

        class ByHandleInfo(c.Structure):
            _fields_ = [("attributes", c.c_uint32), ("creation", w.FILETIME), ("access", w.FILETIME),
                        ("write", w.FILETIME), ("volume", c.c_uint32), ("size_high", c.c_uint32),
                        ("size_low", c.c_uint32), ("links", c.c_uint32), ("index_high", c.c_uint32),
                        ("index_low", c.c_uint32)]

        self.US, self.OA, self.IO, self.Info = UnicodeString, ObjectAttributes, IoStatus, ByHandleInfo
        if tuple(map(c.sizeof, (self.US, self.OA, self.IO))) != ((16, 48, 16) if c.sizeof(c.c_void_p) == 8 else (8, 24, 8)):
            raise ValueError(ERROR)
        definitions = [
            (self.k.CreateFileW, [c.c_wchar_p, c.c_uint32, c.c_uint32, c.c_void_p, c.c_uint32, c.c_uint32, c.c_void_p], c.c_void_p),
            (self.k.CloseHandle, [c.c_void_p], c.c_int32),
            (self.k.GetFileInformationByHandle, [c.c_void_p, c.POINTER(ByHandleInfo)], c.c_int32),
            (self.k.GetFinalPathNameByHandleW, [c.c_void_p, c.c_wchar_p, c.c_uint32, c.c_uint32], c.c_uint32),
            (self.k.GetVolumeInformationByHandleW, [c.c_void_p, c.c_wchar_p, c.c_uint32, c.POINTER(c.c_uint32),
                                                 c.POINTER(c.c_uint32), c.POINTER(c.c_uint32), c.c_wchar_p, c.c_uint32], c.c_int32),
            (self.k.GetDriveTypeW, [c.c_wchar_p], c.c_uint32),
            (self.k.GetFileInformationByHandleEx, [c.c_void_p, c.c_int32, c.c_void_p, c.c_uint32], c.c_int32),
            (self.n.NtCreateFile, [c.POINTER(c.c_void_p), c.c_uint32, c.POINTER(ObjectAttributes), c.POINTER(IoStatus),
                                 c.c_void_p, c.c_uint32, c.c_uint32, c.c_uint32, c.c_uint32, c.c_void_p, c.c_uint32], c.c_int32),
        ]
        for function, args, result in definitions:
            function.argtypes, function.restype = args, result

    def open_existing(self, path, *, directory, lease):
        access = 0x1000a1 if directory else (0xc0000000 if lease else 0x80000000)
        handle = self.k.CreateFileW(str(path), access, 3 if lease else 1, None, 3,
                                    0x00200000 | (0x02000000 if directory else 0), None)
        if handle in (None, 0, c.c_void_p(-1).value):
            raise ValueError(ERROR)
        return handle

    def close(self, handle):
        if not self.k.CloseHandle(handle):
            raise ValueError(ERROR)

    def identity(self, handle):
        info = self.Info()
        path_buffer, fs_buffer = c.create_unicode_buffer(32768), c.create_unicode_buffer(64)
        if not self.k.GetFileInformationByHandle(handle, c.byref(info)):
            raise ValueError(ERROR)
        length = self.k.GetFinalPathNameByHandleW(handle, path_buffer, len(path_buffer), 0)
        if not length or length >= len(path_buffer):
            raise ValueError(ERROR)
        raw = path_buffer.value
        if not raw.startswith('\\\\?\\') or raw.startswith('\\\\?\\UNC\\'):
            raise ValueError(ERROR)
        path = Path(raw[4:])
        if not self.k.GetVolumeInformationByHandleW(handle, None, 0, None, None, None, fs_buffer, len(fs_buffer)):
            raise ValueError(ERROR)
        return SimpleNamespace(volume_id=info.volume, file_id=(info.index_high << 32) | info.index_low,
                               final_path=path, is_directory=bool(info.attributes & 0x10), link_count=info.links,
                               reparse=bool(info.attributes & 0x400), filesystem=fs_buffer.value,
                               local=self.k.GetDriveTypeW(path.anchor) == 3)

    def create_relative(self, parent, name, *, directory, disposition, options, access, share):
        name_buffer = c.create_unicode_buffer(name)
        size = len(name.encode("utf-16-le"))
        us = self.US(size, size + 2, c.cast(name_buffer, c.c_void_p))
        oa = self.OA(c.sizeof(self.OA), parent, c.pointer(us), 0x40, None, None)
        io, handle = self.IO(), c.c_void_p()
        status = self.n.NtCreateFile(c.byref(handle), access, c.byref(oa), c.byref(io), None,
                                    0x80, share, disposition, options, None, 0)
        return handle.value, status, io.Information

    def stream(self, handle, *, writable):
        import msvcrt
        fd = msvcrt.open_osfhandle(handle, os.O_BINARY | (os.O_RDWR if writable else os.O_RDONLY))
        try:
            return os.fdopen(fd, "r+b" if writable else "rb")
        except Exception:
            try:
                os.close(fd)
            except Exception:
                self.cleanup_failed = True
                if not hasattr(self, "_unconfirmed_descriptors"):
                    self._unconfirmed_descriptors = []
                self._unconfirmed_descriptors.append(fd)
            raise _TransferredHandleError() from None

    def enumerate_page(self, handle, restart):
        buffer = c.create_string_buffer(65536)
        if not self.k.GetFileInformationByHandleEx(handle, 11 if restart else 10, buffer, len(buffer)):
            if c.get_last_error() == 18:
                return None
            raise ValueError(ERROR)
        return decode_directory_page(buffer.raw)


class PosixObservationHandleBackend:
    def __init__(self):
        self.cleanup_failed = False
        self._unconfirmed = []

    def _discard_created(self, fd, result):
        try:
            if result is not None:
                result.close()
            elif fd is not None:
                os.close(fd)
        except Exception:
            self.cleanup_failed = True
            self._unconfirmed.append(result if result is not None else fd)

    def _close(self, handle):
        os.close(handle)

    def _identity(self, fd, path, directory):
        info = os.fstat(fd)
        if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1):
            raise ValueError(ERROR)
        return FileIdentity(info.st_dev, info.st_ino, path, directory, info.st_nlink)

    def verify(self, handle):
        if handle.closed or self._identity(handle.native_handle, handle.identity.final_path,
                                          handle.identity.is_directory) != handle.identity:
            raise ValueError(ERROR)
        # The name must still identify the pinned object, never follow a replaced link.
        info = os.stat(handle.identity.final_path, follow_symlinks=False)
        if (info.st_dev, info.st_ino) != (handle.identity.volume_id, handle.identity.file_id):
            raise ValueError(ERROR)
        return handle.identity

    def pin_existing(self, path, *, directory, writable=False, lease=False):
        parents = []
        fd = None
        try:
            if writable and not lease:
                raise ValueError(ERROR)
            path = Path(os.path.abspath(path))
            fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            cursor = Path(path.anchor)
            for part in path.parts[1:]:
                component(part)
                parents.append(DirectoryHandle(self, fd, self._identity(fd, cursor, True)))
                cursor = cursor / part
                is_dir = cursor != path or directory
                fd = os.open(part, (os.O_RDWR if lease and not is_dir else os.O_RDONLY) | os.O_NOFOLLOW
                             | (os.O_DIRECTORY if is_dir else 0), dir_fd=parents[-1].native_handle)
            identity = self._identity(fd, path, directory)
            if directory:
                return DirectoryHandle(self, fd, identity, parents)
            return FileHandle(self, fd, identity, os.fdopen(fd, "r+b" if lease else "rb"), parents)
        except Exception:
            if fd is not None and not any(p.native_handle == fd for p in parents):
                os.close(fd)
            for parent in reversed(parents):
                parent.close()
            raise ValueError(ERROR) from None

    def children(self, parent, *, limit):
        self.verify(parent)
        with os.scandir(parent.native_handle) as entries:
            result = _names((entry.name for entry in entries), limit)
        self.verify(parent)
        return result

    def create_directory(self, parent, name):
        component(name)
        self.verify(parent)
        fd = result = None
        try:
            os.mkdir(name, dir_fd=parent.native_handle)
            fd = os.open(name, os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent.native_handle)
            result = DirectoryHandle(self, fd, self._identity(fd, parent.identity.final_path / name, True))
            self.verify(result)
            self.verify(parent)
            return result
        except Exception:
            self._discard_created(fd, result)
            raise ValueError(ERROR) from None

    def create_file(self, parent, name):
        component(name)
        self.verify(parent)
        fd = result = None
        try:
            fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent.native_handle)
            identity = self._identity(fd, parent.identity.final_path / name, False)
            result = FileHandle(self, fd, identity, os.fdopen(fd, "r+b"))
            self.verify(result)
            self.verify(parent)
            return result
        except Exception:
            self._discard_created(fd, result)
            raise ValueError(ERROR) from None


def make_handle_backend() -> ObservationHandleBackend:
    return WindowsObservationHandleBackend() if os.name == "nt" else PosixObservationHandleBackend()
