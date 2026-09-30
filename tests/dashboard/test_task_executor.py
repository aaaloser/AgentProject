"""Parameter-level evidence for the task command container; never starts Docker."""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from mokioclaw.dashboard.task_approval import ExecutionRequest
from mokioclaw.dashboard.task_executor import IsolatedCommandExecutor, TaskExecutionError
from mokioclaw.dashboard.task_worker_control import DockerOwnershipCleanup
from mokioclaw.dashboard.task_worker_control import ProcessIdentity, TaskWorkerController
from mokioclaw.dashboard.task_models import TaskSpec
from mokioclaw.dashboard.task_store import TaskStore


TASK = "task_1234567890123456"
INSTANCE = "instance_123456789012"
REQUEST = "request_12345678901234"
IMAGE = "sha256:" + "a" * 64


class FakeDocker:
    def __init__(self, *, fail: str | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.fail = fail

    def run(self, args: list[str], *, timeout_seconds: int, max_output_chars: int = 12000):
        self.calls.append(tuple(args))
        verb = args[1]
        if verb == self.fail:
            return subprocess.CompletedProcess(args, 1, "", "private backend detail")
        output = {"image": IMAGE, "create": "container123\n", "wait": "0\n", "logs": "hello\n", "ps": ""}.get(verb, "")
        return subprocess.CompletedProcess(args, 0, output, "")


def request(root: Path, **changes) -> ExecutionRequest:
    work = root / TASK / "workspace" / "work"
    work.mkdir(parents=True, exist_ok=True)
    values = dict(
        task_id=TASK, attempt_id=1, command_request_id=REQUEST, command="printf hello",
        cwd="/workspace", timeout_seconds=5, image_digest=IMAGE, mount_source=str(work),
        mount_target="/workspace", network="none", env_allowlist=("PATH", "LANG"),
        cpu_limit=1.0, memory_bytes=512 * 1024 * 1024, pids_limit=64,
        max_output_chars=200, policy_version="task-command-v1",
    )
    values.update(changes)
    return ExecutionRequest(**values)


def test_exact_work_mount_and_restricted_container_arguments(tmp_path: Path) -> None:
    backend = FakeDocker()
    registered: list[str] = []
    executor = IsolatedCommandExecutor(
        task_root=tmp_path, task_id=TASK, instance_id=INSTANCE, image_digest=IMAGE,
        docker=backend, register_request=registered.append,
    )
    result = executor.execute(request(tmp_path))
    assert result["ok"] and result["exit_code"] == 0
    assert registered == [REQUEST]
    create = next(call for call in backend.calls if call[1] == "create")
    joined = " ".join(create)
    assert "--network none" in joined
    assert "--read-only" in create and "--cap-drop ALL" in joined
    assert "--security-opt no-new-privileges" in joined
    assert "--cpus 1.0" in joined and "--memory 536870912" in joined
    assert "--pids-limit 64" in joined and "--user 65534:65534" in joined
    assert "--mount" in create and sum(arg.startswith("type=bind,") for arg in create) == 1
    mount = create[create.index("--mount") + 1]
    assert mount == f"type=bind,src={tmp_path / TASK / 'workspace' / 'work'},dst=/workspace"
    assert "baseline" not in joined and "docker.sock" not in joined
    assert "MOKIO_TASK_API_KEY" not in joined and "--env" not in create
    assert f"mokioclaw.instance_id={INSTANCE}" in joined
    assert f"mokioclaw.task_id={TASK}" in joined
    assert f"mokioclaw.command_request_id={REQUEST}" in joined
    assert create[create.index("--entrypoint") + 1] == "/bin/sh"
    assert create[-3:] == (IMAGE, "-c", "printf hello")
    assert any(call[1] == "rm" for call in backend.calls)


def test_cancel_waits_for_container_creation_then_cleans_before_terminal(tmp_path: Path) -> None:
    creating = threading.Event()
    release = threading.Event()

    class BlockingDocker(FakeDocker):
        def __init__(self):
            super().__init__()
            self.owned = False
            self.started = False

        def run(self, args, *, timeout_seconds, max_output_chars=12000):
            verb = args[1]
            if verb == "create":
                creating.set()
                assert release.wait(3)
                self.owned = True
            elif verb == "start":
                self.started = True
            elif verb == "ps":
                return subprocess.CompletedProcess(args, 0, "container123\n" if self.owned else "", "")
            elif verb == "rm":
                self.owned = False
            return super().run(args, timeout_seconds=timeout_seconds, max_output_chars=max_output_chars)

    class FakeLauncher:
        def launch(self, _task_id, _work):
            return ProcessIdentity(1234, "birth-1234")

        def activate(self, _identity):
            pass

        def exited(self, _identity):
            return True

        def stop(self, _identity):
            return True

    store = TaskStore(tmp_path)
    spec = TaskSpec(
        task_id="", repo_id="repo_12345678", base_sha="a" * 40, anchor_sha="b" * 40,
        description="repair", source_read_scope=("src/",), source_write_scope=("src/",),
        task_scratch_scope=".mokioclaw/task-scratch/", manifest_digest="c" * 64,
        max_seconds=60, max_attempts=1, verification_commands=(), max_provider_calls=1,
        max_total_tokens=100, max_output_tokens_per_call=20, created_at="",
    )
    task_id = store.create(spec, "creation-race").task_id
    assert task_id != TASK
    store.transition(task_id, "draft", "preparing", {})
    store.transition(task_id, "preparing", "prepared", {})
    work = tmp_path / task_id / "workspace" / "work"
    work.mkdir(parents=True)
    backend = BlockingDocker()
    control = TaskWorkerController(
        store=store, instance_id=INSTANCE, launcher=FakeLauncher(),
        containers=DockerOwnershipCleanup(backend),
    )
    control.start(task_id)
    req = request(tmp_path, task_id=task_id, mount_source=str(work))
    executor = IsolatedCommandExecutor(
        task_root=tmp_path, task_id=task_id, instance_id=INSTANCE, image_digest=IMAGE,
        docker=backend, register_request=lambda value: control.register_command(task_id, value),
        creation_guard=lambda item: control.command_creation(task_id, item.attempt_id),
    )
    execution = threading.Thread(target=lambda: executor.execute(req), daemon=True)
    execution.start()
    assert creating.wait(2)
    cancelled = []
    cancellation = threading.Thread(target=lambda: cancelled.append(control.cancel(task_id)), daemon=True)
    cancellation.start()
    time.sleep(0.05)
    assert not cancelled and store.get(task_id).state == "running"
    release.set()
    execution.join(timeout=3)
    cancellation.join(timeout=3)
    assert not execution.is_alive() and not cancellation.is_alive()
    assert cancelled[0].state == "cancelled" and cancelled[0].cleanup_confirmed
    assert backend.started and not backend.owned


def test_cancel_during_image_check_prevents_late_container_create(tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingImage(FakeDocker):
        def run(self, args, *, timeout_seconds, max_output_chars=12000):
            if args[1] == "image":
                entered.set()
                assert release.wait(3)
            return super().run(args, timeout_seconds=timeout_seconds, max_output_chars=max_output_chars)

    backend = BlockingImage()
    checked = []

    def guard(_request):
        if not checked:
            raise TaskExecutionError("stale_task_attempt")
        raise AssertionError("guard unexpectedly opened")

    executor = IsolatedCommandExecutor(
        task_root=tmp_path, task_id=TASK, instance_id=INSTANCE, image_digest=IMAGE,
        docker=backend, register_request=lambda _value: None, creation_guard=guard,
    )
    outcome = []

    def execute():
        try:
            executor.execute(request(tmp_path))
        except TaskExecutionError as exc:
            outcome.append(str(exc))

    worker = threading.Thread(target=execute, daemon=True)
    worker.start()
    assert entered.wait(2)
    release.set()
    worker.join(timeout=3)
    assert outcome == ["stale_task_attempt"]
    assert all(call[1] != "create" for call in backend.calls)


def test_cross_task_or_changed_policy_refuses_before_docker(tmp_path: Path) -> None:
    backend = FakeDocker()
    executor = IsolatedCommandExecutor(
        task_root=tmp_path, task_id=TASK, instance_id=INSTANCE, image_digest=IMAGE, docker=backend,
        register_request=lambda _value: None,
    )
    original = request(tmp_path)
    other = tmp_path / "task_9999999999999999" / "workspace" / "work"
    other.mkdir(parents=True)
    for changed in (
        replace(original, mount_source=str(other)), replace(original, network="bridge"),
        replace(original, image_digest="sha256:" + "b" * 64),
        replace(original, env_allowlist=("API_KEY",)),
    ):
        with pytest.raises(TaskExecutionError):
            executor.execute(changed)
    assert backend.calls == []


def test_unavailable_image_refuses_without_creating_container(tmp_path: Path) -> None:
    backend = FakeDocker(fail="image")
    executor = IsolatedCommandExecutor(
        task_root=tmp_path, task_id=TASK, instance_id=INSTANCE, image_digest=IMAGE, docker=backend,
        register_request=lambda _value: None,
    )
    with pytest.raises(TaskExecutionError, match="docker_unavailable"):
        executor.execute(request(tmp_path))
    assert all(call[1] != "create" for call in backend.calls)


def test_create_failure_does_not_expose_backend_error(tmp_path: Path) -> None:
    backend = FakeDocker(fail="create")
    executor = IsolatedCommandExecutor(
        task_root=tmp_path, task_id=TASK, instance_id=INSTANCE, image_digest=IMAGE, docker=backend,
        register_request=lambda _value: None,
    )
    with pytest.raises(TaskExecutionError) as error:
        executor.execute(request(tmp_path))
    assert "private backend detail" not in str(error.value)


def test_workspace_growth_during_command_stops_container(tmp_path: Path) -> None:
    work = tmp_path / TASK / "workspace" / "work"

    class GrowingDocker(FakeDocker):
        def __init__(self) -> None:
            super().__init__()
            self.removed = threading.Event()

        def run(self, args, *, timeout_seconds, max_output_chars=12000):
            if args[1] == "start":
                (work / "large.bin").write_bytes(b"x" * (8 * 1024 * 1024 + 1))
            if args[1] == "wait":
                if not self.removed.wait(3):
                    return subprocess.CompletedProcess(args, 1, "", "wait hung")
                return subprocess.CompletedProcess(args, 0, "137\n", "")
            if args[1] == "rm":
                self.removed.set()
            return super().run(args, timeout_seconds=timeout_seconds, max_output_chars=max_output_chars)

    backend = GrowingDocker()
    executor = IsolatedCommandExecutor(
        task_root=tmp_path, task_id=TASK, instance_id=INSTANCE, image_digest=IMAGE,
        docker=backend, register_request=lambda _value: None, scan_interval_seconds=0.01,
    )
    with pytest.raises(TaskExecutionError, match="workspace_limit_exceeded"):
        executor.execute(request(tmp_path))
    assert backend.removed.is_set()


def test_orphan_cleanup_uses_exact_labels_and_verifies_empty_inventory() -> None:
    class InventoryDocker(FakeDocker):
        def __init__(self) -> None:
            super().__init__()
            self.items = ["owned-one", "owned-two"]

        def run(self, args, *, timeout_seconds, max_output_chars=12000):
            self.calls.append(tuple(args))
            if args[1] == "ps":
                return subprocess.CompletedProcess(args, 0, "\n".join(self.items), "")
            if args[1] == "rm":
                self.items.remove(args[-1])
            return subprocess.CompletedProcess(args, 0, "", "")

    backend = InventoryDocker()
    assert DockerOwnershipCleanup(backend).cleanup_owned(INSTANCE, TASK)
    assert backend.items == []
    ps = [call for call in backend.calls if call[1] == "ps"]
    assert ps and all(f"label=mokioclaw.instance_id={INSTANCE}" in call for call in ps)
    assert all(f"label=mokioclaw.task_id={TASK}" in call for call in ps)
    assert all("other-task" not in " ".join(call) for call in backend.calls)


def test_command_never_reports_success_if_owned_container_remains(tmp_path: Path) -> None:
    class StuckDocker(FakeDocker):
        def run(self, args, *, timeout_seconds, max_output_chars=12000):
            if args[1] == "ps":
                self.calls.append(tuple(args))
                return subprocess.CompletedProcess(args, 0, "container123\n", "")
            return super().run(args, timeout_seconds=timeout_seconds, max_output_chars=max_output_chars)

    backend = StuckDocker()
    executor = IsolatedCommandExecutor(
        task_root=tmp_path, task_id=TASK, instance_id=INSTANCE, image_digest=IMAGE,
        docker=backend, register_request=lambda _value: None,
    )
    with pytest.raises(TaskExecutionError, match="container_cleanup_failed"):
        executor.execute(request(tmp_path))
