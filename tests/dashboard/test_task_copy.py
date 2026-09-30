from __future__ import annotations

import importlib
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from mokioclaw.dashboard.catalog import RepositoryCatalog
from mokioclaw.dashboard.git_reader import GitReadError, LocalGitReader
from mokioclaw.dashboard.task_source import TaskSource


TASK_ID = "task_1234567890123456"


def _copy_api():
    return importlib.import_module("mokioclaw.dashboard.task_copy")


def _git(repo: Path, *arguments: str, input_bytes: bytes | None = None) -> bytes:
    environment = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", *arguments], cwd=repo, env=environment, input=input_bytes, check=True, capture_output=True).stdout.strip()


def _commit(repo: Path, name: str, content: bytes) -> str:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    _git(repo, "add", "--", name)
    _git(repo, "commit", "-q", "-m", "fixture")
    return _git(repo, "rev-parse", "HEAD").decode("ascii")


def _source(repo: Path):
    reader = LocalGitReader()
    catalog = RepositoryCatalog.from_paths([repo], reader)
    source = TaskSource(catalog, reader)
    return source, catalog, reader, catalog.summaries()[0].id


def _snapshot(repo: Path) -> tuple[bytes, bytes, bytes, bytes]:
    return (
        _git(repo, "rev-parse", "HEAD"),
        _git(repo, "show-ref"),
        (repo / ".git" / "index").read_bytes(),
        _git(repo, "status", "--porcelain=v1", "-z", "--ignored"),
    )


def test_prepare_copies_only_fixed_sha_without_changing_source(temp_git_repo: Path, tmp_path: Path) -> None:
    copy = _copy_api()
    base = _commit(temp_git_repo, "src/a.py", b"base\n")
    (temp_git_repo / ".gitignore").write_text("private.fixture\n", encoding="utf-8")
    _git(temp_git_repo, "add", ".gitignore")
    _git(temp_git_repo, "commit", "-q", "-m", "ignore")
    (temp_git_repo / "private.fixture").write_bytes(b"PRIVATE FIXTURE BYTES")
    other = tmp_path / "other-repo"
    other.mkdir()
    _git(other, "init", "-q", "-b", "main")
    _git(other, "config", "user.name", "Fixture User")
    _git(other, "config", "user.email", "fixture@example.invalid")
    _commit(other, "src/other.py", b"untouched\n")
    reader = LocalGitReader()
    catalog = RepositoryCatalog.from_paths([temp_git_repo, other], reader)
    source = TaskSource(catalog, reader)
    repo_id = catalog.summaries()[0].id
    preview = source.preview(repo_id, base, base, ("src/",))
    _commit(temp_git_repo, "src/a.py", b"new head\n")
    before = _snapshot(temp_git_repo)
    other_before = _snapshot(other)

    prepared = copy.prepare_task(preview, TASK_ID, tmp_path / "tasks", catalog, reader)
    assert prepared.task_id == TASK_ID
    assert prepared.manifest_digest == preview.manifest_digest
    assert (prepared.baseline / "src" / "a.py").read_bytes() == b"base\n"
    assert (prepared.work / "src" / "a.py").read_bytes() == b"base\n"
    scratch = prepared.work / ".mokioclaw" / "task-scratch"
    assert (scratch / "NOTEPAD.md").read_bytes() == b""
    assert (scratch / "HISTORY_SUMMARY.md").read_bytes() == b""
    assert not (prepared.baseline / ".mokioclaw").exists()
    assert not (prepared.work / "private.fixture").exists()
    assert _snapshot(temp_git_repo) == before
    assert _snapshot(other) == other_before
    assert (temp_git_repo / "private.fixture").read_bytes() == b"PRIVATE FIXTURE BYTES"

    _commit(temp_git_repo, "src/a.py", b"later head\n")
    assert (prepared.work / "src" / "a.py").read_bytes() == b"base\n"


def test_prepare_rejects_task_root_inside_source_and_blocked_preview(temp_git_repo: Path, tmp_path: Path) -> None:
    copy = _copy_api()
    base = _commit(temp_git_repo, "src/a.py", b"safe\n")
    source, catalog, reader, repo_id = _source(temp_git_repo)
    preview = source.preview(repo_id, base, base, ("src/",))
    for forbidden in (temp_git_repo / "tasks", temp_git_repo / ".git" / "tasks"):
        with pytest.raises(copy.InvalidTaskPreparation):
            copy.prepare_task(preview, TASK_ID, forbidden, catalog, reader)
        assert not forbidden.exists()

    link_oid = _git(temp_git_repo, "hash-object", "-w", "--stdin", input_bytes=b"../outside").decode("ascii")
    _git(temp_git_repo, "update-index", "--add", "--cacheinfo", f"120000,{link_oid},src/link")
    _git(temp_git_repo, "commit", "-q", "-m", "link")
    link_sha = _git(temp_git_repo, "rev-parse", "HEAD").decode("ascii")
    blocked = source.preview(repo_id, link_sha, link_sha, ("src/",))
    with pytest.raises(copy.InvalidTaskPreparation):
        copy.prepare_task(blocked, TASK_ID, tmp_path / "tasks", catalog, reader)
    assert not (tmp_path / "tasks" / TASK_ID / "workspace").exists()


def test_prepare_rejects_lfs_pointer_and_tampered_manifest(temp_git_repo: Path, tmp_path: Path) -> None:
    copy = _copy_api()
    pointer = b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"0" * 64 + b"\nsize 42\n"
    sha = _commit(temp_git_repo, "src/asset.bin", pointer)
    source, catalog, reader, repo_id = _source(temp_git_repo)
    preview = source.preview(repo_id, sha, sha, ("src/",))
    with pytest.raises(copy.InvalidTaskPreparation, match="LFS"):
        copy.prepare_task(preview, TASK_ID, tmp_path / "lfs-tasks", catalog, reader)
    assert not (tmp_path / "lfs-tasks" / TASK_ID / "workspace").exists()

    safe_sha = _commit(temp_git_repo, "src/asset.bin", b"ordinary\n")
    safe = source.preview(repo_id, safe_sha, safe_sha, ("src/",))
    with pytest.raises(copy.InvalidTaskPreparation):
        copy.prepare_task(replace(safe, manifest_digest="0" * 64), TASK_ID, tmp_path / "tampered", catalog, reader)
    assert not (tmp_path / "tampered" / TASK_ID / "workspace").exists()


def test_prepare_fails_if_source_moves_or_object_disappears(temp_git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    copy = _copy_api()
    sha = _commit(temp_git_repo, "src/a.py", b"a\n")
    source, catalog, reader, repo_id = _source(temp_git_repo)
    preview = source.preview(repo_id, sha, sha, ("src/",))
    original_read = reader._read

    def missing_blob(root: Path, *arguments: str) -> bytes:
        if arguments[:2] == ("cat-file", "blob"):
            raise GitReadError("object missing")
        return original_read(root, *arguments)

    monkeypatch.setattr(reader, "_read", missing_blob)
    with pytest.raises(copy.InvalidTaskPreparation):
        copy.prepare_task(preview, TASK_ID, tmp_path / "missing-object", catalog, reader)
    assert not (tmp_path / "missing-object" / TASK_ID / "workspace").exists()
    monkeypatch.undo()

    moved = tmp_path / "moved-source"
    temp_git_repo.rename(moved)
    with pytest.raises(copy.InvalidTaskPreparation):
        copy.prepare_task(preview, TASK_ID, tmp_path / "moved-task", catalog, reader)
    assert not (tmp_path / "moved-task" / TASK_ID / "workspace").exists()


def test_prepare_rejects_replaced_git_identity(temp_git_repo: Path, tmp_path: Path) -> None:
    copy = _copy_api()
    sha = _commit(temp_git_repo, "src/a.py", b"a\n")
    source, catalog, reader, repo_id = _source(temp_git_repo)
    preview = source.preview(repo_id, sha, sha, ("src/",))
    (temp_git_repo / ".git").rename(temp_git_repo / ".git.saved")
    shutil.copytree(temp_git_repo / ".git.saved", temp_git_repo / ".git")
    with pytest.raises(copy.InvalidTaskPreparation):
        copy.prepare_task(preview, TASK_ID, tmp_path / "replaced-task", catalog, reader)
    assert not (tmp_path / "replaced-task" / TASK_ID / "workspace").exists()


def test_prepare_rejects_task_directory_junction_escape(temp_git_repo: Path, tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows junction test")
    copy = _copy_api()
    sha = _commit(temp_git_repo, "src/a.py", b"safe\n")
    source, catalog, reader, repo_id = _source(temp_git_repo)
    preview = source.preview(repo_id, sha, sha, ("src/",))
    task_root = tmp_path / "tasks"
    task_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    junction = task_root / TASK_ID
    linked = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(outside)], capture_output=True)
    if linked.returncode != 0:
        pytest.skip("junction creation unavailable")

    with pytest.raises(copy.InvalidTaskPreparation):
        copy.prepare_task(preview, TASK_ID, task_root, catalog, reader)
    assert not (outside / "workspace").exists()
