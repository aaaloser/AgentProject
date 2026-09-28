from __future__ import annotations

import importlib
import os
from pathlib import Path
from types import SimpleNamespace


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
