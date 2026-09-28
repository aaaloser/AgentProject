from __future__ import annotations

import importlib
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


def _filesystem(tmp_path: Path):
    work = tmp_path / "task" / "workspace" / "work"
    baseline = work.parent / "baseline"
    work.mkdir(parents=True)
    baseline.mkdir()
    (work / "src").mkdir()
    (work / "src" / "a.py").write_bytes(b"original\n")
    module = importlib.import_module("mokioclaw.dashboard.task_filesystem")
    prepared = SimpleNamespace(task_id="task_1234567890123456", work=work, baseline=baseline, root=work.parents[1])
    fs = module.TaskFilesystem(prepared, ("src/",), ("src/",), ".mokioclaw/task-scratch/")
    return module, fs, work


@pytest.mark.parametrize("path", ["/src/a.py", "../src/a.py", "src/../a.py", "C:/src/a.py", "src\\a.py", "src//a.py"])
def test_rejects_unsafe_paths(tmp_path: Path, path: str) -> None:
    module, fs, _ = _filesystem(tmp_path)
    with pytest.raises(module.TaskFilesystemError):
        fs.read_bytes(path)


def test_existing_regular_file_read_and_write(tmp_path: Path) -> None:
    _, fs, work = _filesystem(tmp_path)
    assert fs.read_bytes("src/a.py") == b"original\n"
    fs.write_bytes("src/a.py", b"updated\n")
    assert (work / "src" / "a.py").read_bytes() == b"updated\n"


def test_host_file_access_obeys_single_file_soft_limit(tmp_path: Path, monkeypatch) -> None:
    module, fs, work = _filesystem(tmp_path)
    monkeypatch.setattr(module, "MAX_FILE_BYTES", 4)
    with pytest.raises(module.TaskFilesystemError):
        fs.read_bytes("src/a.py")
    with pytest.raises(module.TaskFilesystemError):
        fs.write_bytes("src/a.py", b"long content")
    assert (work / "src" / "a.py").read_bytes() == b"original\n"


def test_scope_and_scratch_are_distinct(tmp_path: Path) -> None:
    module, fs, work = _filesystem(tmp_path)
    (work / "src" / "private.txt").write_bytes(b"private")
    (work / "other.txt").write_bytes(b"outside")
    for path in ("other.txt", ".mokioclaw/task-scratch/note.txt", "../baseline/src/a.py"):
        with pytest.raises(module.TaskFilesystemError):
            fs.read_bytes(path)
    with pytest.raises(module.TaskFilesystemError):
        fs.write_bytes("other.txt", b"change")
    assert (work / "other.txt").read_bytes() == b"outside"


def test_rejects_link_replacement_between_calls(tmp_path: Path) -> None:
    module, fs, work = _filesystem(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.py").write_bytes(b"SECRET")
    assert fs.read_bytes("src/a.py") == b"original\n"
    (work / "src" / "a.py").unlink()
    (work / "src").rmdir()
    try:
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(work / "src"), str(outside)], check=True, capture_output=True)
        else:
            (work / "src").symlink_to(outside, target_is_directory=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        pytest.skip(f"Link fixture unavailable: {exc}")
    with pytest.raises(module.TaskFilesystemError):
        fs.read_bytes("src/a.py")
    with pytest.raises(module.TaskFilesystemError):
        fs.write_bytes("src/a.py", b"hijack")
    assert (outside / "a.py").read_bytes() == b"SECRET"


def test_mutating_and_recursive_operations_fail_closed_when_unsupported(tmp_path: Path) -> None:
    module, fs, work = _filesystem(tmp_path)
    (work / "src" / "b.py").write_bytes(b"b")
    for operation in (
        lambda: fs.create_bytes("src/new.py", b"new"),
        lambda: fs.rename("src/a.py", "other.py"),
        lambda: fs.rename("other.py", "src/new.py"),
        lambda: fs.delete("other.py"),
        lambda: fs.iter_files("other"),
    ):
        with pytest.raises(module.TaskFilesystemError):
            operation()
    if os.name == "nt":
        for operation in (
            lambda: fs.create_bytes("src/new.py", b"new"),
            lambda: fs.rename("src/a.py", "src/new.py"),
            lambda: fs.delete("src/a.py"),
            lambda: fs.iter_files("src/"),
        ):
            with pytest.raises(module.TaskFilesystemError):
                operation()
    assert (work / "src" / "a.py").read_bytes() == b"original\n"
