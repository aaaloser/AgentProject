"""Opt-in, no-provider Docker acceptance against a disposable repository."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
from pathlib import Path

import pytest

from mokioclaw.dashboard.task_approval import ExecutionRequest
from mokioclaw.dashboard.task_executor import DockerCLI, IsolatedCommandExecutor, TaskExecutionError
from mokioclaw.dashboard.task_models import TaskSpec
from mokioclaw.dashboard.task_store import TaskStore
from mokioclaw.dashboard.task_worker_control import (
    DockerOwnershipCleanup, ProcessIdentity, TaskWorkerController,
)


pytestmark = pytest.mark.docker
TASK = "task_docker_acceptance_1234"
INSTANCE = "instance_docker_acceptance_1234"
REQUEST = "request_docker_acceptance_1234"


def _image() -> str:
    image = os.environ.get("MOKIO_TASK_DOCKER_TEST_IMAGE", "")
    if not image.startswith("sha256:") or len(image) != 71:
        pytest.skip("Set MOKIO_TASK_DOCKER_TEST_IMAGE to an existing sha256 image ID")
    return image


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "--no-optional-locks", *args], cwd=root, check=True,
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"},
    )
    return result.stdout.strip()


def _source_state(root: Path) -> tuple[str, str, str, str]:
    index = root / ".git" / "index"
    return (
        _git(root, "rev-parse", "HEAD"), _git(root, "show-ref", "--head"),
        hashlib.sha256(index.read_bytes()).hexdigest(), _git(root, "status", "--porcelain=v1"),
    )


def _request(work: Path, image: str, command: str, *, timeout: int = 10, request_id: str = REQUEST) -> ExecutionRequest:
    return ExecutionRequest(
        task_id=TASK, attempt_id=1, command_request_id=request_id, command=command,
        cwd="/workspace", timeout_seconds=timeout, image_digest=image, mount_source=str(work),
        mount_target="/workspace", network="none", env_allowlist=("PATH", "LANG"),
        cpu_limit=1.0, memory_bytes=512 * 1024 * 1024, pids_limit=64,
        max_output_chars=4000, policy_version="task-command-v1",
    )


class InspectingDocker(DockerCLI):
    def __init__(self) -> None:
        self.host_config: dict | None = None

    def run(self, args: list[str], *, timeout_seconds: int, max_output_chars: int = 12000):
        result = super().run(args, timeout_seconds=timeout_seconds, max_output_chars=max_output_chars)
        if args[1] == "create" and result.returncode == 0:
            inspected = super().run(
                ["docker", "inspect", result.stdout.strip(), "--format", "{{json .HostConfig}}"],
                timeout_seconds=10, max_output_chars=12000,
            )
            assert inspected.returncode == 0
            self.host_config = json.loads(inspected.stdout)
        return result


def test_real_container_boundary_and_source_immutability(temp_git_repo: Path, tmp_path: Path, monkeypatch) -> None:
    image = _image()
    (temp_git_repo / ".gitignore").write_text("ignored.fixture\n", encoding="utf-8")
    (temp_git_repo / "approved.txt").write_text("approved\n", encoding="utf-8")
    _git(temp_git_repo, "add", ".gitignore", "approved.txt")
    _git(temp_git_repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-q", "-m", "fixture")
    ignored = temp_git_repo / "ignored.fixture"
    ignored.write_bytes(b"private ignored fixture - do not mount")
    before, ignored_hash = _source_state(temp_git_repo), hashlib.sha256(ignored.read_bytes()).hexdigest()
    task_root = tmp_path / "tasks"
    baseline = task_root / TASK / "workspace" / "baseline"
    work = task_root / TASK / "workspace" / "work"
    baseline.mkdir(parents=True)
    work.mkdir(parents=True)
    (baseline / "approved.txt").write_text("approved\n", encoding="utf-8")
    (work / "approved.txt").write_text("approved\n", encoding="utf-8")
    monkeypatch.setenv("MOKIO_TASK_API_KEY", "FAKE_CANARY_NOT_A_SECRET")
    docker = InspectingDocker()
    executor = IsolatedCommandExecutor(
        task_root=task_root, task_id=TASK, instance_id=INSTANCE, image_digest=image,
        docker=docker, register_request=lambda _request_id: None,
    )
    command = (
        "set -eu; "
        "test \"$(id -u)\" = 65534; test \"$(id -g)\" = 65534; "
        "test -f /workspace/approved.txt; "
        "test ! -e /workspace/ignored.fixture; test ! -e /workspace/../baseline/approved.txt; "
        "test ! -e /var/run/docker.sock; test ! -e /root/.docker/config.json; "
        "test -z \"${MOKIO_TASK_API_KEY+x}\"; "
        "python -c 'import socket,sys; s=socket.socket(); s.settimeout(1); "
        "sys.exit(0 if s.connect_ex((\"1.1.1.1\",53)) != 0 else 1)'; "
        "touch /workspace/created.txt; echo isolation-ok"
    )
    try:
        result = executor.execute(_request(work, image, command))
        assert result["ok"] and result["exit_code"] == 0 and "isolation-ok" in result["stdout"]
        assert (work / "created.txt").exists()
        config = docker.host_config
        assert config is not None
        assert config["NetworkMode"] == "none"
        assert config["ReadonlyRootfs"] is True
        assert config["Privileged"] is False
        assert config["UsernsMode"] in ("", None)
        assert config["Memory"] == 512 * 1024 * 1024
        assert config["PidsLimit"] == 64
        assert config["NanoCpus"] == 1_000_000_000
        mounts = config["Mounts"]
        assert len(mounts) == 1 and mounts[0]["Target"] == "/workspace"
        assert Path(mounts[0]["Source"]).resolve() == work.resolve()
        capped = executor.execute(_request(
            work, image, "python -c 'print(\"x\" * 10000)'",
            request_id="request_output_acceptance_1234",
        ))
        assert capped["ok"] and len(capped["stdout"]) == 4000
        assert _source_state(temp_git_repo) == before
        assert hashlib.sha256(ignored.read_bytes()).hexdigest() == ignored_hash
    finally:
        assert DockerOwnershipCleanup(docker).cleanup_owned(INSTANCE, TASK)


def test_real_timeout_removes_owned_container(tmp_path: Path) -> None:
    image = _image()
    task_root = tmp_path / "tasks"
    work = task_root / TASK / "workspace" / "work"
    work.mkdir(parents=True)
    docker = DockerCLI()
    executor = IsolatedCommandExecutor(
        task_root=task_root, task_id=TASK, instance_id=INSTANCE, image_digest=image,
        docker=docker, register_request=lambda _request_id: None,
    )
    try:
        with pytest.raises(TaskExecutionError, match="container_wait_failed"):
            executor.execute(_request(work, image, "sleep 10", timeout=1, request_id="request_timeout_acceptance_1234"))
        listing = docker.run([
            "docker", "ps", "-a", "--filter", f"label=mokioclaw.instance_id={INSTANCE}",
            "--filter", f"label=mokioclaw.task_id={TASK}", "--format", "{{.ID}}",
        ], timeout_seconds=10)
        assert listing.returncode == 0 and not listing.stdout.strip()
    finally:
        assert DockerOwnershipCleanup(docker).cleanup_owned(INSTANCE, TASK)


class InertWorker:
    def __init__(self) -> None:
        self.live = True

    def launch(self, task_id: str, work: Path) -> ProcessIdentity:
        return ProcessIdentity(12345, "inert-birth-12345")

    def activate(self, identity: ProcessIdentity) -> None:
        pass

    def stop(self, identity: ProcessIdentity) -> bool:
        if identity != ProcessIdentity(12345, "inert-birth-12345"):
            return False
        self.live = False
        return True

    def exited(self, identity: ProcessIdentity) -> bool:
        return not self.live


def _prepared_store(root: Path) -> tuple[TaskStore, str]:
    store = TaskStore(root)
    spec = TaskSpec(
        task_id="", repo_id="repo_12345678", base_sha="a" * 40, anchor_sha="a" * 40,
        description="No provider fixture", source_read_scope=("approved.txt",),
        source_write_scope=("approved.txt",), task_scratch_scope=".mokioclaw/task-scratch/",
        manifest_digest="b" * 64, max_seconds=30, max_attempts=1, verification_commands=(),
        max_provider_calls=1, max_total_tokens=1, max_output_tokens_per_call=1, created_at="",
    )
    record = store.create(spec, secrets.token_urlsafe(20))
    store.transition(record.task_id, "draft", "preparing", {})
    store.transition(record.task_id, "preparing", "prepared", {})
    (root / record.task_id / "workspace" / "work").mkdir(parents=True)
    return store, record.task_id


def _create_sleep_container(
    docker: DockerCLI, image: str, *, instance_id: str, task_id: str,
) -> str:
    name = "mokioclaw-acceptance-" + secrets.token_hex(10)
    created = docker.run([
        "docker", "create", "--name", name,
        "--label", f"mokioclaw.instance_id={instance_id}",
        "--label", f"mokioclaw.task_id={task_id}",
        "--label", "mokioclaw.command_request_id=request_acceptance_1234",
        "--network", "none", "--entrypoint", "/bin/sh", image, "-c", "sleep 60",
    ], timeout_seconds=15)
    assert created.returncode == 0 and created.stdout.strip()
    container = created.stdout.strip()
    started = docker.run(["docker", "start", container], timeout_seconds=15)
    assert started.returncode == 0
    return container


def test_real_cancel_cleans_only_exact_task_containers(tmp_path: Path) -> None:
    image = _image()
    docker = DockerCLI()
    store, task_id = _prepared_store(tmp_path / "tasks")
    worker = InertWorker()
    control = TaskWorkerController(
        store=store, instance_id=INSTANCE, launcher=worker, containers=DockerOwnershipCleanup(docker),
    )
    control.start(task_id)
    owned = unrelated = None
    try:
        owned = _create_sleep_container(docker, image, instance_id=INSTANCE, task_id=task_id)
        unrelated = _create_sleep_container(docker, image, instance_id="unrelated_instance_1234", task_id=task_id)
        cancelled = control.cancel(task_id)
        assert cancelled.state == "cancelled" and cancelled.cleanup_confirmed
        assert worker.exited(ProcessIdentity(12345, "inert-birth-12345"))
        assert docker.run(["docker", "inspect", unrelated, "--format", "{{.State.Running}}"], timeout_seconds=10).stdout.strip() == "true"
        assert docker.run(["docker", "inspect", owned, "--format", "{{.Id}}"], timeout_seconds=10).returncode != 0
    finally:
        for container in (owned, unrelated):
            if container is not None:
                docker.run(["docker", "rm", "-f", container], timeout_seconds=15)
        assert DockerOwnershipCleanup(docker).cleanup_owned(INSTANCE, task_id)


def test_real_restart_reconciles_orphan_container(tmp_path: Path) -> None:
    image = _image()
    docker = DockerCLI()
    task_root = tmp_path / "tasks"
    store, task_id = _prepared_store(task_root)
    worker = InertWorker()
    TaskWorkerController(
        store=store, instance_id=INSTANCE, launcher=worker, containers=DockerOwnershipCleanup(docker),
    ).start(task_id)
    orphan = None
    try:
        orphan = _create_sleep_container(docker, image, instance_id=INSTANCE, task_id=task_id)
        restarted = TaskStore(task_root)
        TaskWorkerController(
            store=restarted, instance_id="new_instance_12345678", launcher=worker,
            containers=DockerOwnershipCleanup(docker),
        ).reconcile()
        assert restarted.get(task_id).state == "interrupted"
        assert restarted.get(task_id).cleanup_confirmed
        assert docker.run(["docker", "inspect", orphan, "--format", "{{.Id}}"], timeout_seconds=10).returncode != 0
    finally:
        if orphan is not None:
            docker.run(["docker", "rm", "-f", orphan], timeout_seconds=15)
        assert DockerOwnershipCleanup(docker).cleanup_owned(INSTANCE, task_id)
