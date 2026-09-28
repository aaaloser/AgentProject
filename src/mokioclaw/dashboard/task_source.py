"""Read-only, fixed-commit source previews for local maintenance tasks."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Callable

from mokioclaw.dashboard.catalog import RepositoryCatalog
from mokioclaw.dashboard.git_reader import GitOutputLimit, GitReadError, GitReadTimeout, InvalidRepository, LocalGitReader


class InvalidTaskPreview(ValueError):
    """A preview cannot safely identify a preparable fixed source tree."""


@dataclass(frozen=True)
class ManifestEntry:
    relative_path: str
    git_mode: str
    blob_oid: str
    blob_size: int


@dataclass(frozen=True)
class BlockedPath:
    path: str
    reason: str


@dataclass(frozen=True)
class TaskPreview:
    preview_id: str
    repo_id: str
    base_sha: str
    anchor_sha: str
    source_read_scope: tuple[str, ...]
    source_write_scope: tuple[str, ...]
    task_scratch_scope: str
    request_digest: str
    manifest_digest: str
    files: tuple[ManifestEntry, ...]
    file_count: int
    total_bytes: int
    blocked_paths: tuple[BlockedPath, ...]
    expires_at: float
    content_checks_pending: bool = True


_SINGLE_FILE_LIMIT = 4 * 1024 * 1024
_TOTAL_LIMIT = 64 * 1024 * 1024
_FILE_LIMIT = 5000
_SCOPE_LIMIT = 100
_RESERVED_WINDOWS = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _safe_component(component: str) -> bool:
    if not component or component in {".", ".."} or component[-1] in {" ", "."}:
        return False
    if any(ord(char) < 32 or char in '<>:"\\|?*' for char in component):
        return False
    return component.split(".", 1)[0].upper() not in _RESERVED_WINDOWS


def _normalize_scope(scope: tuple[str, ...]) -> tuple[str, ...]:
    if not scope or len(scope) > _SCOPE_LIMIT:
        raise InvalidTaskPreview("A nonempty source scope of at most 100 paths is required")
    normalized = []
    for item in scope:
        if not isinstance(item, str) or not item or item.startswith("/") or ":" in item or "\\" in item:
            raise InvalidTaskPreview("Source scope contains an unsafe path")
        directory = item.endswith("/")
        parts = item.rstrip("/").split("/")
        if not all(_safe_component(part) for part in parts):
            raise InvalidTaskPreview("Source scope contains an unsafe path")
        normalized.append("/".join(parts) + ("/" if directory else ""))
    return tuple(sorted(set(normalized)))


def _selected(path: str, scope: tuple[str, ...]) -> bool:
    return any(path.startswith(item) if item.endswith("/") else path == item for item in scope)


def _excluded(path: str) -> bool:
    parts = [part.casefold() for part in path.split("/")]
    name = parts[-1]
    if any(part in {".git", ".mokioclaw"} for part in parts):
        return True
    if parts[:2] == ["evals", "reports"]:
        return True
    return (
        name == ".env" or name.startswith(".env.") or name.endswith((".pem", ".key"))
        or name in {"id_rsa", "id_ed25519", "credentials.json", "secrets.json"}
    )


class TaskSource:
    def __init__(self, catalog: RepositoryCatalog, reader: LocalGitReader, *, clock: Callable[[], float] | None = None) -> None:
        self.catalog = catalog
        self.reader = reader
        self.clock = clock or time.time
        self._previews: dict[str, TaskPreview] = {}

    def preview(self, repo_id: str, base_sha: str, anchor_sha: str, source_read_scope: tuple[str, ...]) -> TaskPreview:
        scope = _normalize_scope(source_read_scope)
        repository = self.catalog.get(repo_id)
        if repository is None:
            raise InvalidTaskPreview("Repository is not registered")
        root = repository.root
        try:
            current = self.reader.inspect(root)
            if current.root != repository.root or current.object_format != repository.state.object_format:
                raise InvalidTaskPreview("Repository identity changed")
            self.reader._validate_sha(root, base_sha)
            self.reader._validate_sha(root, anchor_sha)
            reachable, _ = self.reader._run(root, "merge-base", "--is-ancestor", base_sha, anchor_sha)
            if reachable != 0:
                raise InvalidTaskPreview("Base commit is not in the selected history")
            listing = self.reader._read(root, "ls-tree", "-r", "-z", "-l", base_sha, "--")
        except GitOutputLimit as exc:
            raise InvalidTaskPreview("Git preview output limit exceeded") from exc
        except GitReadTimeout as exc:
            raise InvalidTaskPreview("Git preview timed out") from exc
        except (InvalidRepository, GitReadError, ValueError) as exc:
            if isinstance(exc, InvalidTaskPreview):
                raise
            raise InvalidTaskPreview("Fixed commit cannot be previewed") from exc

        files: list[ManifestEntry] = []
        blocked: list[BlockedPath] = []
        seen_casefold: dict[str, str] = {}
        total_bytes = 0
        for row in listing.split(b"\0"):
            if not row:
                continue
            try:
                metadata, raw_path = row.split(b"\t", 1)
                mode, kind, oid, raw_size = metadata.split()
                path = raw_path.decode("utf-8", errors="strict")
            except (ValueError, UnicodeError) as exc:
                raise InvalidTaskPreview("Git tree contains an unsupported entry") from exc
            if not _selected(path, scope):
                continue
            if not all(_safe_component(part) for part in path.split("/")):
                blocked.append(BlockedPath(path, "unsafe_path"))
                continue
            folded = path.casefold()
            if folded in seen_casefold and seen_casefold[folded] != path:
                blocked.append(BlockedPath(path, "case_collision"))
                continue
            seen_casefold[folded] = path
            if _excluded(path):
                blocked.append(BlockedPath(path, "excluded_path"))
                continue
            if mode == b"120000":
                blocked.append(BlockedPath(path, "symlink"))
                continue
            if mode == b"160000":
                blocked.append(BlockedPath(path, "gitlink"))
                continue
            if mode not in {b"100644", b"100755"} or kind != b"blob" or not raw_size.isdigit():
                blocked.append(BlockedPath(path, "non_regular"))
                continue
            size = int(raw_size)
            if size > _SINGLE_FILE_LIMIT:
                blocked.append(BlockedPath(path, "file_too_large"))
                continue
            total_bytes += size
            files.append(ManifestEntry(path, mode.decode("ascii"), oid.decode("ascii"), size))
        if len(files) > _FILE_LIMIT:
            blocked.append(BlockedPath("", "too_many_files"))
        if total_bytes > _TOTAL_LIMIT:
            blocked.append(BlockedPath("", "total_too_large"))
        if not files and not blocked:
            raise InvalidTaskPreview("Source scope matches no tracked files")
        files.sort(key=lambda item: item.relative_path)
        manifest = [[item.relative_path, item.git_mode, item.blob_oid, item.blob_size] for item in files]
        digest = _canonical_digest(manifest)
        request_digest = _canonical_digest([repo_id, base_sha, anchor_sha, scope])
        preview = TaskPreview(
            preview_id=secrets.token_urlsafe(18),
            repo_id=repo_id,
            base_sha=base_sha,
            anchor_sha=anchor_sha,
            source_read_scope=scope,
            source_write_scope=scope,
            task_scratch_scope=".mokioclaw/task-scratch/",
            request_digest=request_digest,
            manifest_digest=digest,
            files=tuple(files),
            file_count=len(files),
            total_bytes=total_bytes,
            blocked_paths=tuple(blocked),
            expires_at=self.clock() + 600,
        )
        self._previews[preview.preview_id] = preview
        return preview

    def validate_preview(
        self, preview_id: str, repo_id: str, base_sha: str, anchor_sha: str, source_read_scope: tuple[str, ...]
    ) -> TaskPreview:
        preview = self._previews.get(preview_id)
        if preview is None or self.clock() >= preview.expires_at:
            raise InvalidTaskPreview("Preview has expired")
        scope = _normalize_scope(source_read_scope)
        if preview.request_digest != _canonical_digest([repo_id, base_sha, anchor_sha, scope]):
            raise InvalidTaskPreview("Preview does not match this request")
        return preview

    def require_preparable(self, preview: TaskPreview) -> None:
        if self.clock() >= preview.expires_at or preview.blocked_paths or not preview.files:
            raise InvalidTaskPreview("Preview cannot be prepared")
