from __future__ import annotations

import importlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


def _prepared(tmp_path: Path):
    root = tmp_path / "task_1234567890123456"
    baseline = root / "workspace" / "baseline"
    work = root / "workspace" / "work"
    for directory in (baseline / "src", work / "src"):
        directory.mkdir(parents=True)
    (baseline / "src" / "a.py").write_bytes(b"before\n")
    (work / "src" / "a.py").write_bytes(b"before\n")
    return SimpleNamespace(root=root, baseline=baseline, work=work, files=(), task_id=root.name)


def test_patch_changes_only_allowed_regular_files(tmp_path: Path) -> None:
    patch = importlib.import_module("mokioclaw.dashboard.task_patch")
    prepared = _prepared(tmp_path)
    (prepared.work / "src" / "a.py").write_bytes(b"after\n")
    (prepared.work / "src" / "new.py").write_bytes(b"new\n")
    result = patch.collect_patch(prepared, ("src/",), ".mokioclaw/task-scratch/")
    assert result.status == "available"
    assert result.changed_files == ("src/a.py", "src/new.py")
    assert result.added_lines >= 1
    assert result.patch_path is not None and result.patch_path.is_file()
    assert prepared.root in result.patch_path.parents


def test_scratch_excluded_and_out_of_scope_change_unavailable(tmp_path: Path) -> None:
    patch = importlib.import_module("mokioclaw.dashboard.task_patch")
    prepared = _prepared(tmp_path)
    scratch = prepared.work / ".mokioclaw" / "task-scratch"
    scratch.mkdir(parents=True)
    (scratch / "note.txt").write_bytes(b"scratch secret")
    result = patch.collect_patch(prepared, ("src/",), ".mokioclaw/task-scratch/")
    assert result.status == "available" and result.changed_files == ()
    (prepared.work / "outside.txt").write_bytes(b"unauthorized")
    result = patch.collect_patch(prepared, ("src/",), ".mokioclaw/task-scratch/")
    assert result.status == "patch_unavailable"
    assert result.patch_path is None


def test_symlink_and_size_limit_never_publish_partial_patch(tmp_path: Path, monkeypatch) -> None:
    patch = importlib.import_module("mokioclaw.dashboard.task_patch")
    prepared = _prepared(tmp_path)
    (prepared.work / "src" / "a.py").write_bytes(b"changed\n")
    monkeypatch.setattr(patch, "MAX_FILE_BYTES", 2)
    result = patch.collect_patch(prepared, ("src/",), ".mokioclaw/task-scratch/")
    assert result.status == "patch_unavailable"
    assert result.patch_path is None
    assert not (prepared.root / "artifacts" / "patch.diff").exists()
    monkeypatch.setattr(patch, "MAX_FILE_BYTES", 8 * 1024 * 1024)
    external = tmp_path / "external"
    external.write_bytes(b"private")
    try:
        (prepared.work / "src" / "link").symlink_to(external)
    except OSError:
        if os.name == "nt":
            return
        raise
    result = patch.collect_patch(prepared, ("src/",), ".mokioclaw/task-scratch/")
    assert result.status == "patch_unavailable"
    assert result.patch_path is None


def test_file_count_and_total_limits(tmp_path: Path, monkeypatch) -> None:
    patch = importlib.import_module("mokioclaw.dashboard.task_patch")
    prepared = _prepared(tmp_path)
    monkeypatch.setattr(patch, "MAX_FILES", 0)
    assert patch.collect_patch(prepared, ("src/",), ".mokioclaw/task-scratch/").status == "patch_unavailable"
    monkeypatch.setattr(patch, "MAX_FILES", 5000)
    monkeypatch.setattr(patch, "MAX_TOTAL_BYTES", 1)
    assert patch.collect_patch(prepared, ("src/",), ".mokioclaw/task-scratch/").status == "patch_unavailable"


def test_empty_directory_count_is_bounded(tmp_path: Path, monkeypatch) -> None:
    patch = importlib.import_module("mokioclaw.dashboard.task_patch")
    prepared = _prepared(tmp_path)
    (prepared.work / "src" / "empty").mkdir()
    monkeypatch.setattr(patch, "MAX_DIRECTORIES", 2)
    result = patch.collect_patch(prepared, ("src/",), ".mokioclaw/task-scratch/")
    assert result.status == "patch_unavailable" and result.reason == "workspace_limit_exceeded"


def test_directory_limit_stops_enumeration_before_queue_grows(tmp_path: Path, monkeypatch) -> None:
    patch = importlib.import_module("mokioclaw.dashboard.task_patch")
    prepared = _prepared(tmp_path)
    parent = prepared.work / "src"
    for index in range(3):
        (parent / f"empty-{index}").mkdir()
    real_scandir = patch.os.scandir

    class BoundedListing:
        def __init__(self, path):
            self.path = Path(path)
            self.stream = real_scandir(path)

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def __iter__(self):
            for index, item in enumerate(self.stream):
                if self.path == parent and index >= 3:
                    raise AssertionError("Directory enumeration passed its bound")
                yield item

    monkeypatch.setattr(patch.os, "scandir", BoundedListing)
    monkeypatch.setattr(patch, "MAX_DIRECTORIES", 3)
    with pytest.raises(patch.PatchUnsafe, match="workspace_limit_exceeded"):
        patch._scan(prepared.work)


def test_failed_recollection_removes_stale_patch_and_rejects_suspected_secret(tmp_path: Path) -> None:
    patch = importlib.import_module("mokioclaw.dashboard.task_patch")
    prepared = _prepared(tmp_path)
    target = prepared.work / "src" / "a.py"
    target.write_text("after\n", encoding="utf-8")
    first = patch.collect_patch(prepared, ("src/",), ".mokioclaw/task-scratch/")
    assert first.status == "available" and first.patch_path is not None
    target.write_text('api_key = "sk-test-placeholder-1234567890123456"\n', encoding="utf-8")
    second = patch.collect_patch(prepared, ("src/",), ".mokioclaw/task-scratch/")
    assert second.status == "patch_unavailable" and second.reason == "suspected_secret"
    assert not first.patch_path.exists()


def test_deleted_file_and_invalid_utf8_fail_closed(tmp_path: Path) -> None:
    patch = importlib.import_module("mokioclaw.dashboard.task_patch")
    prepared = _prepared(tmp_path)
    (prepared.work / "src" / "a.py").unlink()
    deleted = patch.collect_patch(prepared, ("src/",), ".mokioclaw/task-scratch/")
    assert deleted.status == "available" and deleted.changed_files == ("src/a.py",)
    assert deleted.deleted_lines == 1
    (prepared.work / "src" / "a.py").write_bytes(b"\xff")
    invalid = patch.collect_patch(prepared, ("src/",), ".mokioclaw/task-scratch/")
    assert invalid.status == "patch_unavailable" and invalid.reason == "invalid_utf8"
    assert not deleted.patch_path.exists()


def test_binary_content_is_unavailable_without_partial_artifact(tmp_path: Path) -> None:
    patch = importlib.import_module("mokioclaw.dashboard.task_patch")
    prepared = _prepared(tmp_path)
    (prepared.work / "src" / "a.py").write_bytes(b"binary\x00content")
    result = patch.collect_patch(prepared, ("src/",), ".mokioclaw/task-scratch/")
    assert result.status == "patch_unavailable" and result.reason == "binary_or_changed_file"
    assert not (prepared.root / "artifacts" / "patch.diff").exists()


def test_missing_final_newline_never_claims_a_complete_patch(tmp_path: Path) -> None:
    patch = importlib.import_module("mokioclaw.dashboard.task_patch")
    prepared = _prepared(tmp_path)
    (prepared.work / "src" / "a.py").write_bytes(b"after")
    result = patch.collect_patch(prepared, ("src/",), ".mokioclaw/task-scratch/")
    assert result.status == "patch_unavailable"
    assert result.reason == "missing_final_newline"
    assert not (prepared.root / "artifacts" / "patch.diff").exists()
