from __future__ import annotations

import os
import re
import subprocess
import threading
from pathlib import Path

from mokioclaw.dashboard.models import ChangedFile, CommitDetail, CommitSummary, RepositoryState


class InvalidRepository(Exception):
    pass


class CommitNotFound(Exception):
    pass


class GitReadTimeout(Exception):
    pass


class GitOutputLimit(Exception):
    pass


class GitReadError(Exception):
    pass


class LocalGitReader:
    def __init__(self, git_executable: str = "git", timeout_seconds: float = 10, max_output_bytes: int = 8_388_608) -> None:
        self.git_executable = git_executable
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes

    def inspect(self, path: Path) -> RepositoryState:
        try:
            requested = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise InvalidRepository("Repository directory is unavailable") from exc
        if not requested.is_dir():
            raise InvalidRepository("Repository path is not a directory")
        try:
            if self._read(requested, "rev-parse", "--is-inside-work-tree").strip() != b"true":
                raise InvalidRepository("A Git working tree is required")
            top = self._read(requested, "rev-parse", "--show-toplevel").decode("utf-8", errors="replace").strip()
            root = Path(top).resolve(strict=True)
            object_format = self._read(root, "rev-parse", "--show-object-format").decode("ascii").strip()
            head_code, head_output = self._run(root, "rev-parse", "--verify", "-q", "HEAD")
            head_sha = head_output.decode("ascii").strip() if head_code == 0 else None
            branch_code, branch_output = self._run(root, "symbolic-ref", "--quiet", "--short", "HEAD")
            branch = branch_output.decode("utf-8", errors="replace").strip() if branch_code == 0 else None
            dirty = bool(self._read(root, "status", "--porcelain=v1", "-z", "--untracked-files=normal"))
        except GitReadError as exc:
            raise InvalidRepository(str(exc)) from exc
        except (OSError, UnicodeError) as exc:
            raise InvalidRepository("Repository cannot be inspected") from exc
        if object_format not in {"sha1", "sha256"}:
            raise InvalidRepository("Unsupported Git object format")
        return RepositoryState(root=root, name=root.name, branch=branch, head_sha=head_sha, dirty=dirty, object_format=object_format)

    def list_commits(self, root: Path, anchor_sha: str, offset: int, limit: int = 50) -> tuple[CommitSummary, ...]:
        if offset < 0 or not 1 <= limit <= 50:
            raise ValueError("Invalid page bounds")
        self._validate_sha(root, anchor_sha)
        code, output = self._run(
            root, "log", "-z", "--no-show-signature", "--format=%H%x00%s%x00%cI%x00%P",
            f"--max-count={limit}", f"--skip={offset}", anchor_sha, "--",
        )
        if code != 0:
            raise CommitNotFound("History anchor is unavailable")
        if not output:
            return ()
        fields = output.removesuffix(b"\x00").split(b"\x00")
        if len(fields) % 4:
            raise GitReadError("Malformed commit metadata")
        summaries = []
        for index in range(0, len(fields), 4):
            sha, title, committed_at, parents = fields[index : index + 4]
            summaries.append(
                CommitSummary(
                    sha=sha.decode("ascii"),
                    title=title.decode("utf-8", errors="replace"),
                    committed_at=committed_at.decode("ascii"),
                    parent_count=len(parents.split()) if parents else 0,
                )
            )
        return tuple(summaries)

    def get_commit(self, root: Path, sha: str, anchor_sha: str) -> CommitDetail:
        self._validate_sha(root, sha)
        self._validate_sha(root, anchor_sha)
        reachability, _ = self._run(root, "merge-base", "--is-ancestor", sha, anchor_sha)
        if reachability != 0:
            raise CommitNotFound("Commit is not reachable from this history")
        metadata = self._read(root, "log", "-1", "-z", "--no-show-signature", "--format=%H%x00%s%x00%cI%x00%P", sha)
        fields = metadata.removesuffix(b"\x00").split(b"\x00")
        if len(fields) != 4:
            raise GitReadError("Malformed commit metadata")
        commit_sha, title, committed_at, parent_bytes = fields
        parents = tuple(value.decode("ascii") for value in parent_bytes.split())
        shallow_boundary = not parents and self._read(root, "rev-parse", "--is-shallow-repository").strip() == b"true"
        if len(parents) > 1 or shallow_boundary:
            files: tuple = ()
        else:
            status = self._read(root, "diff-tree", "--root", "--no-commit-id", "-r", "-M", "--no-ext-diff", "--name-status", "-z", sha)
            numstat = self._read(root, "diff-tree", "--root", "--no-commit-id", "-r", "-M", "--no-ext-diff", "--numstat", "-z", sha)
            files = self._combine_files(status, numstat)
        return CommitDetail(
            sha=commit_sha.decode("ascii"),
            title=title.decode("utf-8", errors="replace"),
            committed_at=committed_at.decode("ascii"),
            parent_shas=parents,
            files=files,
            stats_unavailable_reason="shallow_boundary" if shallow_boundary else None,
        )

    def _validate_sha(self, root: Path, sha: str) -> None:
        object_format = self._read(root, "rev-parse", "--show-object-format").decode("ascii").strip()
        length = {"sha1": 40, "sha256": 64}.get(object_format)
        if length is None or re.fullmatch(rf"[0-9a-fA-F]{{{length}}}", sha) is None:
            raise ValueError("A full Git commit SHA is required")

    def _read(self, root: Path, *arguments: str) -> bytes:
        code, output = self._run(root, *arguments)
        if code != 0:
            raise GitReadError("Git read failed")
        return output

    def _run(self, root: Path, *arguments: str) -> tuple[int, bytes]:
        command = [
            self.git_executable, "--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "diff.external=",
            *arguments,
        ]
        environment = {
            **{key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")},
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_EXTERNAL_DIFF": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
        }
        try:
            process = subprocess.Popen(
                command, cwd=root, env=environment, shell=False, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise GitReadError("Git executable is unavailable") from exc

        chunks: list[bytes] = []
        too_large = threading.Event()
        lock = threading.Lock()
        consumed = 0

        def drain(stream, keep: bool) -> None:
            nonlocal consumed
            while block := stream.read(65_536):
                with lock:
                    consumed += len(block)
                    if consumed > self.max_output_bytes:
                        too_large.set()
                        process.kill()
                    elif keep:
                        chunks.append(block)

        stdout_thread = threading.Thread(target=drain, args=(process.stdout, True), daemon=True)
        stderr_thread = threading.Thread(target=drain, args=(process.stderr, False), daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        try:
            code = process.wait(timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            stdout_thread.join()
            stderr_thread.join()
            raise GitReadTimeout("Git read timed out") from exc
        stdout_thread.join()
        stderr_thread.join()
        if too_large.is_set():
            raise GitOutputLimit("Git output limit exceeded")
        return code, b"".join(chunks)

    @staticmethod
    def _combine_files(status: bytes, numstat: bytes) -> tuple:
        status_parts = status.rstrip(b"\x00").split(b"\x00") if status else []
        numstat_parts = numstat.rstrip(b"\x00").split(b"\x00") if numstat else []
        statuses = []
        index = 0
        while index < len(status_parts):
            flag = status_parts[index].decode("ascii", errors="replace")
            index += 1
            if not flag or index >= len(status_parts):
                raise GitReadError("Malformed file status")
            first_path = status_parts[index].decode("utf-8", errors="replace")
            index += 1
            if flag[0] in {"R", "C"}:
                if index >= len(status_parts):
                    raise GitReadError("Malformed rename status")
                path = status_parts[index].decode("utf-8", errors="replace")
                index += 1
                previous = first_path
            else:
                path = first_path
                previous = None
            statuses.append((flag[0], path, previous))

        stats = []
        index = 0
        while index < len(numstat_parts):
            fields = numstat_parts[index].split(b"\t", 2)
            index += 1
            if len(fields) != 3:
                raise GitReadError("Malformed line statistics")
            add, delete, path_bytes = fields
            if path_bytes:
                path = path_bytes.decode("utf-8", errors="replace")
                previous = None
            else:
                if index + 1 >= len(numstat_parts):
                    raise GitReadError("Malformed rename statistics")
                previous = numstat_parts[index].decode("utf-8", errors="replace")
                path = numstat_parts[index + 1].decode("utf-8", errors="replace")
                index += 2
            additions = int(add) if add.isdigit() else None
            deletions = int(delete) if delete.isdigit() else None
            stats.append((path, previous, additions, deletions))
        if len(statuses) != len(stats):
            raise GitReadError("File statistics are incomplete")

        type_names = {"A": "added", "M": "modified", "D": "deleted", "R": "renamed", "C": "copied", "T": "type_changed"}
        files = []
        for (flag, path, previous), (stat_path, stat_previous, additions, deletions) in zip(statuses, stats, strict=True):
            if (path, previous) != (stat_path, stat_previous):
                raise GitReadError("File status and statistics disagree")
            files.append(
                ChangedFile(
                    path=path, previous_path=previous, change_type=type_names.get(flag, "unknown"),
                    additions=additions, deletions=deletions,
                )
            )
        return tuple(files)
