from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from mokioclaw.dashboard.catalog import CatalogRegistrationError, RepositoryCatalog
from mokioclaw.dashboard.git_reader import LocalGitReader
from mokioclaw.dashboard.priority import assess_commit


def clone_repo(source: Path, target: Path) -> None:
    environment = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "clone", "-q", str(source), str(target)], check=True, capture_output=True, env=environment)


def test_catalog_isolates_two_repositories_and_uses_opaque_ids(temp_git_repo: Path, tmp_path: Path) -> None:
    second = tmp_path / "second"
    clone_repo(temp_git_repo, second)
    catalog = RepositoryCatalog.from_paths([temp_git_repo, second], LocalGitReader())

    summaries = catalog.summaries()
    assert [summary.path for summary in summaries] == [str(temp_git_repo.resolve()), str(second.resolve())]
    assert [summary.name for summary in summaries] == ["repo", "second"]
    assert len({summary.id for summary in summaries}) == 2
    assert all(str(tmp_path) not in summary.id for summary in summaries)
    assert catalog.get(summaries[0].id).root == temp_git_repo.resolve()
    assert catalog.get(summaries[1].id).root == second.resolve()
    assert catalog.get("unknown") is None


def test_catalog_deduplicates_aliases_and_nested_directory(temp_git_repo: Path) -> None:
    nested = temp_git_repo / "nested"
    nested.mkdir()
    catalog = RepositoryCatalog.from_paths([temp_git_repo, temp_git_repo / ".", nested], LocalGitReader())
    assert len(catalog.summaries()) == 1
    assert catalog.summaries()[0].path == str(temp_git_repo.resolve())


def test_same_name_repositories_have_distinct_ids(temp_git_repo: Path, tmp_path: Path) -> None:
    other = tmp_path / "other-parent" / "repo"
    other.parent.mkdir()
    clone_repo(temp_git_repo, other)
    summaries = RepositoryCatalog.from_paths([temp_git_repo, other], LocalGitReader()).summaries()
    assert [summary.name for summary in summaries] == ["repo", "repo"]
    assert len({summary.id for summary in summaries}) == 2
    assert [summary.path for summary in summaries] == [str(temp_git_repo.resolve()), str(other.resolve())]


def test_missing_git_executable_has_safe_actionable_reason(temp_git_repo: Path) -> None:
    reader = LocalGitReader(git_executable="mokioclaw-git-executable-does-not-exist")
    with pytest.raises(CatalogRegistrationError) as error:
        RepositoryCatalog.from_paths([temp_git_repo], reader)
    assert len(error.value.failures) == 1
    assert error.value.failures[0].reason == "Git executable is unavailable"
    assert str(temp_git_repo) not in error.value.failures[0].reason


def test_catalog_invalid_path_fails_atomically_and_collects_errors(temp_git_repo: Path, tmp_path: Path) -> None:
    with pytest.raises(CatalogRegistrationError) as error:
        RepositoryCatalog.from_paths([temp_git_repo, tmp_path / "missing", tmp_path], LocalGitReader())
    assert len(error.value.failures) == 2
    assert {failure.path for failure in error.value.failures} == {tmp_path / "missing", tmp_path}

    with pytest.raises(CatalogRegistrationError):
        RepositoryCatalog.from_paths([], LocalGitReader())


def test_catalog_deduplicates_symlink_if_windows_allows_it(temp_git_repo: Path, tmp_path: Path) -> None:
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(temp_git_repo, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    catalog = RepositoryCatalog.from_paths([temp_git_repo, alias], LocalGitReader())
    assert len(catalog.summaries()) == 1


def test_same_commit_has_same_priority_in_different_absolute_paths(temp_git_repo: Path, tmp_path: Path) -> None:
    source = temp_git_repo / "src"
    source.mkdir()
    (source / "module.py").write_text("value = 1\n", encoding="utf-8")
    environment = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "add", "src/module.py"], cwd=temp_git_repo, check=True, capture_output=True, env=environment)
    subprocess.run(["git", "commit", "-q", "-m", "same commit"], cwd=temp_git_repo, check=True, capture_output=True, env=environment)
    clone = tmp_path / "other-location"
    clone_repo(temp_git_repo, clone)
    reader = LocalGitReader()
    original = reader.inspect(temp_git_repo)
    copied = reader.inspect(clone)

    assert original.head_sha == copied.head_sha
    assert assess_commit(reader.get_commit(original.root, original.head_sha, original.head_sha)) == assess_commit(
        reader.get_commit(copied.root, copied.head_sha, copied.head_sha)
    )
