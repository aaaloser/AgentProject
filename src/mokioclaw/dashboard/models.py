from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChangedFile:
    path: str
    previous_path: str | None
    change_type: str
    additions: int | None
    deletions: int | None


@dataclass(frozen=True)
class CommitDetail:
    sha: str
    title: str
    committed_at: str
    parent_shas: tuple[str, ...]
    files: tuple[ChangedFile, ...]
    stats_unavailable_reason: str | None = None


@dataclass(frozen=True)
class ReviewReason:
    code: str
    message: str


@dataclass(frozen=True)
class ReviewAssessment:
    sha: str
    rule_version: str
    priority: str
    signals: dict[str, object]
    reasons: tuple[ReviewReason, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class RepositoryState:
    root: Path
    name: str
    branch: str | None
    head_sha: str | None
    dirty: bool
    object_format: str


@dataclass(frozen=True)
class CommitSummary:
    sha: str
    title: str
    committed_at: str
    parent_count: int


@dataclass(frozen=True)
class RepositorySummary:
    id: str
    name: str
    path: str
    branch: str | None
    head_sha: str | None
    dirty: bool
