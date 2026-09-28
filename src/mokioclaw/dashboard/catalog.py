from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from secrets import token_urlsafe
from typing import Sequence

from mokioclaw.dashboard.git_reader import GitOutputLimit, GitReadError, GitReadTimeout, InvalidRepository, LocalGitReader
from mokioclaw.dashboard.models import RepositoryState, RepositorySummary


@dataclass(frozen=True)
class RegistrationFailure:
    path: Path
    reason: str


class CatalogRegistrationError(Exception):
    def __init__(self, failures: tuple[RegistrationFailure, ...]) -> None:
        self.failures = failures
        super().__init__("One or more repository paths are invalid")


@dataclass(frozen=True)
class RegisteredRepository:
    id: str
    root: Path
    state: RepositoryState


class RepositoryCatalog:
    def __init__(self, repositories: tuple[RegisteredRepository, ...]) -> None:
        self._repositories = repositories
        self._by_id = {repository.id: repository for repository in repositories}

    @classmethod
    def from_paths(cls, paths: Sequence[Path], reader: LocalGitReader) -> RepositoryCatalog:
        if not paths:
            raise CatalogRegistrationError((RegistrationFailure(Path("."), "No repository path was provided"),))
        states: list[RepositoryState] = []
        failures: list[RegistrationFailure] = []
        seen: set[Path] = set()
        for path in paths:
            requested = Path(path)
            try:
                state = reader.inspect(requested)
            except (InvalidRepository, GitReadError, GitReadTimeout, GitOutputLimit) as exc:
                failures.append(RegistrationFailure(requested, str(exc)))
                continue
            if state.root not in seen:
                seen.add(state.root)
                states.append(state)
        if failures:
            raise CatalogRegistrationError(tuple(failures))
        return cls(tuple(RegisteredRepository(token_urlsafe(18), state.root, state) for state in states))

    def get(self, repo_id: str) -> RegisteredRepository | None:
        return self._by_id.get(repo_id)

    def summaries(self) -> tuple[RepositorySummary, ...]:
        return tuple(
            RepositorySummary(
                id=repository.id,
                name=repository.state.name,
                path=str(repository.root),
                branch=repository.state.branch,
                head_sha=repository.state.head_sha,
                dirty=repository.state.dirty,
            )
            for repository in self._repositories
        )
