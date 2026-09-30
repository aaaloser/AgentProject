"""A no-provider two-repository task fixture checks the source boundary."""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path

from mokioclaw.dashboard.catalog import RepositoryCatalog
from mokioclaw.dashboard.git_reader import LocalGitReader
from mokioclaw.dashboard.task_service import TaskService


def _git(root: Path, *arguments: str) -> bytes:
    environment = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", *arguments], cwd=root, env=environment,
                          check=True, capture_output=True).stdout


def _repository(root: Path, text: str) -> str:
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "Fixture")
    _git(root, "config", "user.email", "fixture@example.invalid")
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text(text, encoding="utf-8")
    _git(root, "add", "src/a.py")
    _git(root, "commit", "-q", "-m", "fixed source")
    (root / ".git" / "info" / "exclude").write_text("ignored-evidence/\n", encoding="utf-8")
    (root / "ignored-evidence").mkdir()
    (root / "ignored-evidence" / "keep.txt").write_bytes(b"fixture ignored bytes")
    return _git(root, "rev-parse", "HEAD").decode().strip()


def _snapshot(root: Path) -> tuple[bytes, ...]:
    return (
        _git(root, "rev-parse", "HEAD"), _git(root, "show-ref", "--head"),
        _git(root, "--no-optional-locks", "status", "--porcelain=v1", "--ignored"),
        hashlib.sha256((root / ".git" / "index").read_bytes()).digest(),
        (root / "src" / "a.py").read_bytes(),
        hashlib.sha256((root / "ignored-evidence" / "keep.txt").read_bytes()).digest(),
    )


def test_two_fixed_tasks_keep_source_head_refs_index_status_and_ignored_bytes(tmp_path: Path) -> None:
    first, second = tmp_path / "source-a", tmp_path / "source-b"
    shas = (_repository(first, "first\n"), _repository(second, "second\n"))
    before = (_snapshot(first), _snapshot(second))
    reader = LocalGitReader()
    catalog = RepositoryCatalog.from_paths([first, second], reader)
    ids = {Path(item.path): item.id for item in catalog.summaries()}
    service = TaskService(catalog, reader, tmp_path / "private-tasks")
    try:
        results = []
        for number, (root, sha) in enumerate(zip((first, second), shas, strict=True)):
            repo_id = ids[root]
            preview = service.preview({
                "repo_id": repo_id, "base_sha": sha, "anchor_sha": sha,
                "source_read_scope": ["src/"],
            })
            record = service.create_task({
                "preview_id": preview.preview_id, "repo_id": repo_id,
                "base_sha": sha, "anchor_sha": sha, "source_read_scope": ["src/"],
                "description": "fixture", "max_seconds": 30, "max_attempts": 1,
                "verification_commands": [], "max_provider_calls": 1,
                "max_total_tokens": 100, "max_output_tokens_per_call": 20,
            }, f"fixture-{number}")
            deadline = time.monotonic() + 5
            while service.get(record.task_id).state == "preparing" and time.monotonic() < deadline:
                time.sleep(0.01)
            assert service.get(record.task_id).state == "prepared"
            (service.prepared(record.task_id).work / "src" / "a.py").write_text(
                f"isolated change {number}\n", encoding="utf-8",
            )
            service.store.transition(record.task_id, "prepared", "running", {})
            service.store.transition(record.task_id, "running", "stopping", {})
            service.store.transition(record.task_id, "stopping", "completed", {"cleanup_confirmed": True})
            results.append(service.result(record.task_id))
        assert results[0].task_id != results[1].task_id
        assert results[0].repo_id != results[1].repo_id
        assert [item.base_sha for item in results] == list(shas)
        assert all(item.changed_files == ("src/a.py",) for item in results)
        assert all(item.patch_summary.status == "available" for item in results)
        assert (_snapshot(first), _snapshot(second)) == before
    finally:
        service.close()
