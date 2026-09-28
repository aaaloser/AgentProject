from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from mokioclaw.dashboard.catalog import RepositoryCatalog
from mokioclaw.dashboard.git_reader import LocalGitReader


def _source_api():
    return importlib.import_module("mokioclaw.dashboard.task_source")


def _git(repo: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    environment = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", *args], cwd=repo, env=environment, input=input_bytes, check=True, capture_output=True).stdout.strip()


def _commit(repo: Path, files: dict[str, bytes]) -> str:
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    _git(repo, "add", "--", ".")
    _git(repo, "commit", "-q", "-m", "fixture")
    return _git(repo, "rev-parse", "HEAD").decode("ascii")


def _source(repo: Path, reader: LocalGitReader | None = None, clock=None):
    reader = reader or LocalGitReader()
    catalog = RepositoryCatalog.from_paths([repo], reader)
    registration = catalog.summaries()[0]
    return _source_api().TaskSource(catalog, reader, clock=clock), registration.id


def test_preview_binds_fixed_sha_and_canonical_manifest(temp_git_repo: Path) -> None:
    base = _commit(temp_git_repo, {"src/a.py": b"one\n", "src/b.py": b"two\n"})
    source, repo_id = _source(temp_git_repo)
    preview = source.preview(repo_id, base, base, ("src/",))

    oid_a = hashlib.sha1(b"blob 4\0one\n").hexdigest()
    oid_b = hashlib.sha1(b"blob 4\0two\n").hexdigest()
    manifest = [["src/a.py", "100644", oid_a, 4], ["src/b.py", "100644", oid_b, 4]]
    expected = hashlib.sha256(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    assert preview.manifest_digest == expected
    assert preview.base_sha == base
    assert preview.file_count == 2 and preview.total_bytes == 8
    assert preview.blocked_paths == ()
    assert preview.source_write_scope == preview.source_read_scope == ("src/",)
    assert preview.content_checks_pending

    _commit(temp_git_repo, {"src/a.py": b"changed\n"})
    assert source.validate_preview(preview.preview_id, repo_id, base, base, ("src/",)).manifest_digest == expected


def test_preview_rejects_wrong_repo_unreachable_sha_and_unsafe_scope(temp_git_repo: Path, tmp_path: Path) -> None:
    source_module = _source_api()
    first = _commit(temp_git_repo, {"src/a.py": b"a\n"})
    second = _commit(temp_git_repo, {"src/a.py": b"b\n"})
    source, repo_id = _source(temp_git_repo)
    with pytest.raises(source_module.InvalidTaskPreview):
        source.preview(repo_id, second, first, ("src/",))
    with pytest.raises(source_module.InvalidTaskPreview):
        source.preview(repo_id, "HEAD", second, ("src/",))
    with pytest.raises(source_module.InvalidTaskPreview):
        source.preview("unknown-repo", first, second, ("src/",))
    for scope in ((), ("../outside",), ("C:/outside",), ("/outside",), ("src\\a.py",), ("src/../a.py",)):
        with pytest.raises(source_module.InvalidTaskPreview):
            source.preview(repo_id, first, second, scope)

    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q", "-b", "main")
    _git(other, "config", "user.name", "Fixture User")
    _git(other, "config", "user.email", "fixture@example.invalid")
    other_sha = _commit(other, {"src/other.py": b"other\n"})
    with pytest.raises(source_module.InvalidTaskPreview):
        source.preview(repo_id, other_sha, second, ("src/",))


def test_preview_expiry_and_request_identity(temp_git_repo: Path) -> None:
    source_module = _source_api()
    sha = _commit(temp_git_repo, {"src/a.py": b"a\n", "tests/a.py": b"t\n"})
    now = [1000.0]
    source, repo_id = _source(temp_git_repo, clock=lambda: now[0])
    preview = source.preview(repo_id, sha, sha, ("src/",))
    assert preview.expires_at == 1600.0
    with pytest.raises(source_module.InvalidTaskPreview):
        source.validate_preview(preview.preview_id, repo_id, sha, sha, ("tests/",))
    with pytest.raises(source_module.InvalidTaskPreview):
        source.validate_preview(preview.preview_id, "other", sha, sha, ("src/",))
    now[0] = 1600.0
    with pytest.raises(source_module.InvalidTaskPreview):
        source.validate_preview(preview.preview_id, repo_id, sha, sha, ("src/",))


def test_excluded_secret_and_symlink_are_visible_blockers_without_blob_reads(temp_git_repo: Path) -> None:
    source_module = _source_api()
    _commit(temp_git_repo, {"src/ok.py": b"safe\n", ".env": b"DO_NOT_READ\n"})
    link_oid = _git(temp_git_repo, "hash-object", "-w", "--stdin", input_bytes=b"../outside").decode("ascii")
    _git(temp_git_repo, "update-index", "--add", "--cacheinfo", f"120000,{link_oid},src/link")
    _git(temp_git_repo, "commit", "-q", "-m", "link")
    sha = _git(temp_git_repo, "rev-parse", "HEAD").decode("ascii")

    class ObservingReader(LocalGitReader):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[tuple[str, ...]] = []

        def _run(self, root: Path, *arguments: str) -> tuple[int, bytes]:
            self.calls.append(arguments)
            return super()._run(root, *arguments)

    reader = ObservingReader()
    source, repo_id = _source(temp_git_repo, reader)
    preview = source.preview(repo_id, sha, sha, ("src/", ".env"))
    assert preview.file_count == 1
    assert {item.path for item in preview.blocked_paths} == {".env", "src/link"}
    assert all(call[0] not in {"show", "cat-file"} for call in reader.calls)
    with pytest.raises(source_module.InvalidTaskPreview):
        source.require_preparable(preview)


def test_casefold_collision_and_oversize_file_block_preparation(temp_git_repo: Path) -> None:
    source_module = _source_api()
    oid = _git(temp_git_repo, "hash-object", "-w", "--stdin", input_bytes=b"x").decode("ascii")
    _git(temp_git_repo, "update-index", "--add", "--cacheinfo", f"100644,{oid},src/A.py")
    _git(temp_git_repo, "update-index", "--add", "--cacheinfo", f"100644,{oid},src/a.py")
    _git(temp_git_repo, "commit", "-q", "-m", "collision")
    sha = _git(temp_git_repo, "rev-parse", "HEAD").decode("ascii")
    source, repo_id = _source(temp_git_repo)
    preview = source.preview(repo_id, sha, sha, ("src/",))
    assert "case_collision" in {item.reason for item in preview.blocked_paths}
    with pytest.raises(source_module.InvalidTaskPreview):
        source.require_preparable(preview)

    large = _commit(temp_git_repo, {"big.bin": b"z" * (4 * 1024 * 1024 + 1)})
    oversized = source.preview(repo_id, large, large, ("big.bin",))
    assert "file_too_large" in {item.reason for item in oversized.blocked_paths}


def test_gitlink_and_windows_device_name_cannot_enter_manifest(temp_git_repo: Path) -> None:
    source_module = _source_api()
    initial = _commit(temp_git_repo, {"ordinary.txt": b"ordinary\n"})
    _git(temp_git_repo, "update-index", "--add", "--cacheinfo", f"160000,{initial},module")
    _git(temp_git_repo, "commit", "-q", "-m", "unsupported")
    sha = _git(temp_git_repo, "rev-parse", "HEAD").decode("ascii")
    source, repo_id = _source(temp_git_repo)

    preview = source.preview(repo_id, sha, sha, ("module",))
    assert {(item.path, item.reason) for item in preview.blocked_paths} == {("module", "gitlink")}
    assert preview.files == ()
    with pytest.raises(source_module.InvalidTaskPreview):
        source.require_preparable(preview)
    with pytest.raises(source_module.InvalidTaskPreview):
        source.preview(repo_id, sha, sha, ("CON.py",))


def test_sha256_preview_requires_full_id_and_uses_sha256_blob_oid(tmp_path: Path) -> None:
    source_module = _source_api()
    root = tmp_path / "sha256"
    root.mkdir()
    _git(root, "init", "-q", "--object-format=sha256", "-b", "main")
    _git(root, "config", "user.name", "Fixture User")
    _git(root, "config", "user.email", "fixture@example.invalid")
    sha = _commit(root, {"src/a.py": b"x\n"})
    assert len(sha) == 64
    source, repo_id = _source(root)

    preview = source.preview(repo_id, sha, sha, ("src/",))
    expected_oid = hashlib.sha256(b"blob 2\0x\n").hexdigest()
    assert preview.files[0].blob_oid == expected_oid
    with pytest.raises(source_module.InvalidTaskPreview):
        source.preview(repo_id, sha[:40], sha, ("src/",))


def test_git_output_limit_is_a_safe_preview_failure(temp_git_repo: Path) -> None:
    source_module = _source_api()
    sha = _commit(temp_git_repo, {"src/a.py": b"a\n"})
    source, repo_id = _source(temp_git_repo)
    source.reader = LocalGitReader(max_output_bytes=1)
    with pytest.raises(source_module.InvalidTaskPreview, match="output limit"):
        source.preview(repo_id, sha, sha, ("src/",))
