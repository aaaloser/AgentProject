from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from mokioclaw.dashboard.git_reader import CommitNotFound, GitOutputLimit, GitReadTimeout, InvalidRepository, LocalGitReader
from mokioclaw.dashboard.priority import assess_commit


def git(root: Path, *args: str) -> str:
    environment = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0"}
    result = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, env=environment)
    return result.stdout.decode("utf-8", errors="replace").strip()


def commit(root: Path, name: str, body: bytes = b"one\n", *, title: str = "fixture commit") -> str:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    git(root, "add", "--", name)
    git(root, "commit", "-q", "-m", title)
    return git(root, "rev-parse", "HEAD")


def test_inspect_empty_dirty_and_detached_repository(temp_git_repo: Path) -> None:
    reader = LocalGitReader()
    empty = reader.inspect(temp_git_repo)
    assert empty.root == temp_git_repo.resolve()
    assert empty.branch == "main"
    assert empty.head_sha is None
    assert empty.dirty is False
    assert empty.object_format == "sha1"

    head = commit(temp_git_repo, "module.py")
    assert reader.inspect(temp_git_repo).head_sha == head
    (temp_git_repo / "untracked.txt").write_text("new", encoding="utf-8")
    assert reader.inspect(temp_git_repo).dirty is True
    git(temp_git_repo, "checkout", "-q", "--detach", head)
    detached = reader.inspect(temp_git_repo)
    assert detached.branch is None
    assert detached.head_sha == head


def test_inspect_rejects_non_repository_and_bare_repo(temp_git_repo: Path, tmp_path: Path) -> None:
    reader = LocalGitReader()
    with pytest.raises(InvalidRepository):
        reader.inspect(tmp_path / "missing")
    with pytest.raises(InvalidRepository):
        reader.inspect(tmp_path)
    bare = tmp_path / "bare.git"
    git(temp_git_repo, "init", "-q", "--bare", str(bare))
    with pytest.raises(InvalidRepository):
        reader.inspect(bare)


def test_root_commit_and_anchored_history_preserve_special_paths(temp_git_repo: Path) -> None:
    first = commit(temp_git_repo, "first.txt", b"first\n", title="first <script> & hello")
    special = "sp ace.txt"
    git(temp_git_repo, "mv", "first.txt", special)
    git(temp_git_repo, "commit", "-q", "-m", "rename")
    second = git(temp_git_repo, "rev-parse", "HEAD")
    reader = LocalGitReader()

    page_one = reader.list_commits(temp_git_repo, second, offset=0, limit=1)
    page_two = reader.list_commits(temp_git_repo, second, offset=1, limit=1)
    assert [item.sha for item in page_one] == [second]
    assert [item.sha for item in page_two] == [first]
    assert page_two[0].title == "first <script> & hello"

    rename = reader.get_commit(temp_git_repo, second, second)
    assert rename.sha == second
    assert rename.parent_shas == (first,)
    assert [(item.change_type, item.previous_path, item.path) for item in rename.files] == [("renamed", "first.txt", special)]
    assert (rename.files[0].additions, rename.files[0].deletions) == (0, 0)

    root = reader.get_commit(temp_git_repo, first, second)
    assert root.parent_shas == ()
    assert [(item.path, item.change_type, item.additions, item.deletions) for item in root.files] == [("first.txt", "added", 1, 0)]


def test_nul_parser_preserves_newline_and_html_path_bytes() -> None:
    files = LocalGitReader._combine_files(
        b"R100\x00old\nname.txt\x00sp ace<script>.txt\x00",
        b"0\t0\t\x00old\nname.txt\x00sp ace<script>.txt\x00",
    )
    assert [(item.change_type, item.previous_path, item.path) for item in files] == [
        ("renamed", "old\nname.txt", "sp ace<script>.txt")
    ]


def test_binary_and_merge_do_not_get_invented_line_counts(temp_git_repo: Path) -> None:
    root = commit(temp_git_repo, "base.txt")
    binary = commit(temp_git_repo, "asset.bin", b"\x00\x01\x02", title="binary")
    reader = LocalGitReader()
    binary_detail = reader.get_commit(temp_git_repo, binary, binary)
    assert [(item.additions, item.deletions) for item in binary_detail.files] == [(None, None)]

    git(temp_git_repo, "branch", "side", root)
    git(temp_git_repo, "checkout", "-q", "side")
    commit(temp_git_repo, "side.txt")
    git(temp_git_repo, "checkout", "-q", "main")
    git(temp_git_repo, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    merge_sha = git(temp_git_repo, "rev-parse", "HEAD")
    merge_detail = reader.get_commit(temp_git_repo, merge_sha, merge_sha)
    assert len(merge_detail.parent_shas) == 2
    assert merge_detail.files == ()


def test_shallow_commit_with_missing_parent_requires_manual_review(temp_git_repo: Path, tmp_path: Path) -> None:
    commit(temp_git_repo, "base.txt")
    tip = commit(temp_git_repo, "next.txt")
    shallow = tmp_path / "shallow"
    environment = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "clone", "-q", "--depth=1", temp_git_repo.as_uri(), str(shallow)], check=True, capture_output=True, env=environment)

    detail = LocalGitReader().get_commit(shallow, tip, tip)
    assert detail.parent_shas == ()  # Git hides parents at a shallow boundary.
    assert detail.stats_unavailable_reason == "shallow_boundary"
    assert detail.files == ()
    assert assess_commit(detail).priority == "manual_review"


def test_sha_validation_and_anchor_reachability(temp_git_repo: Path) -> None:
    root = commit(temp_git_repo, "base.txt")
    git(temp_git_repo, "branch", "side", root)
    main_head = commit(temp_git_repo, "main.txt")
    git(temp_git_repo, "checkout", "-q", "side")
    side_head = commit(temp_git_repo, "side.txt")
    reader = LocalGitReader()

    with pytest.raises(ValueError):
        reader.get_commit(temp_git_repo, "HEAD", main_head)
    with pytest.raises(ValueError):
        reader.get_commit(temp_git_repo, "f" * 64, main_head)
    with pytest.raises(CommitNotFound):
        reader.get_commit(temp_git_repo, side_head, main_head)
    assert reader.get_commit(temp_git_repo, root, main_head).sha == root


def test_sha256_repository_uses_full_sixty_four_character_ids(tmp_path: Path) -> None:
    root = tmp_path / "sha256"
    root.mkdir()
    environment = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    initialized = subprocess.run(
        ["git", "init", "-q", "--object-format=sha256", "-b", "main", str(root)],
        capture_output=True,
        env=environment,
    )
    if initialized.returncode != 0:
        pytest.skip("installed Git lacks SHA-256 object support")
    git(root, "config", "user.name", "Fixture User")
    git(root, "config", "user.email", "fixture@example.invalid")
    head = commit(root, "file.txt")

    reader = LocalGitReader()
    assert reader.inspect(root).object_format == "sha256"
    assert len(head) == 64
    assert reader.list_commits(root, head, 0)[0].sha == head
    assert reader.get_commit(root, head, head).files[0].path == "file.txt"


def test_read_limit_and_timeout_return_errors(temp_git_repo: Path) -> None:
    head = commit(temp_git_repo, "module.py")
    with pytest.raises(GitOutputLimit):
        LocalGitReader(max_output_bytes=8).list_commits(temp_git_repo, head, 0)
    with pytest.raises(GitReadTimeout):
        LocalGitReader(timeout_seconds=0.000001).inspect(temp_git_repo)


def test_repo_config_external_commands_stay_disabled_and_index_unchanged(temp_git_repo: Path) -> None:
    (temp_git_repo / ".gitattributes").write_text("module.py diff=inject\n", encoding="utf-8")
    git(temp_git_repo, "add", ".gitattributes")
    head = commit(temp_git_repo, "module.py")
    git(temp_git_repo, "config", "core.fsmonitor", "definitely-not-a-command")
    git(temp_git_repo, "config", "diff.external", "definitely-not-a-command")
    git(temp_git_repo, "config", "diff.inject.textconv", "definitely-not-a-command")
    index = temp_git_repo / ".git" / "index"
    before_index = hashlib.sha256(index.read_bytes()).hexdigest()
    before_status = git(temp_git_repo, "--no-optional-locks", "status", "--porcelain=v1")
    reader = LocalGitReader()

    assert reader.inspect(temp_git_repo).dirty is False
    assert "module.py" in {item.path for item in reader.get_commit(temp_git_repo, head, head).files}
    assert hashlib.sha256(index.read_bytes()).hexdigest() == before_index
    assert git(temp_git_repo, "--no-optional-locks", "status", "--porcelain=v1") == before_status
    assert git(temp_git_repo, "rev-parse", "HEAD") == head


def test_parent_git_environment_cannot_redirect_repository(temp_git_repo: Path, tmp_path: Path, monkeypatch) -> None:
    other = tmp_path / "other"
    other.mkdir()
    environment = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "init", "-q", str(other)], check=True, capture_output=True, env=environment)
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))

    state = LocalGitReader().inspect(temp_git_repo)
    assert state.root == temp_git_repo.resolve()
