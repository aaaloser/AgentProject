"""Worker lifecycle tests use a fake process and labeled container inventory."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
import threading

import pytest

from mokioclaw.dashboard.task_models import TaskSpec
from mokioclaw.dashboard.task_store import TaskConflict, TaskStore
from mokioclaw.dashboard.task_worker_control import ProcessIdentity, TaskWorkerController
from mokioclaw.dashboard.task_worker import TaskWorkerLauncher, filtered_worker_environment
from mokioclaw.dashboard.catalog import RepositoryCatalog
from mokioclaw.dashboard.git_reader import LocalGitReader
from mokioclaw.dashboard.task_service import TaskService
from mokioclaw.dashboard.task_approval import ApprovalBroker, ExecutionRequest


class FakeLauncher:
    def __init__(self) -> None:
        self.live: dict[int, str] = {}
        self.stopped: list[tuple[int, str]] = []
        self.activated: list[int] = []

    def launch(self, task_id: str, work: Path) -> ProcessIdentity:
        pid = 100 + len(self.live)
        created = f"birth-{pid}"
        self.live[pid] = created
        return ProcessIdentity(pid, created)

    def activate(self, identity: ProcessIdentity) -> None:
        self.activated.append(identity.pid)

    def stop(self, identity: ProcessIdentity) -> bool:
        if self.live.get(identity.pid) != identity.created_at:
            return False
        self.stopped.append((identity.pid, identity.created_at))
        self.live.pop(identity.pid)
        return True

    def exited(self, identity: ProcessIdentity) -> bool:
        return self.live.get(identity.pid) != identity.created_at


class FakeContainers:
    def __init__(self) -> None:
        self.owned: set[tuple[str, str, str]] = set()
        self.fail_cleanup = False
        self.cleaned: list[tuple[str, str]] = []

    def cleanup_owned(self, instance_id: str, task_id: str) -> bool:
        self.cleaned.append((instance_id, task_id))
        if self.fail_cleanup:
            return False
        self.owned = {item for item in self.owned if item[:2] != (instance_id, task_id)}
        return True


def spec() -> TaskSpec:
    return TaskSpec(
        task_id="", repo_id="repo_12345678", base_sha="a" * 40, anchor_sha="b" * 40,
        description="repair", source_read_scope=("src/",), source_write_scope=("src/",),
        task_scratch_scope=".mokioclaw/task-scratch/", manifest_digest="c" * 64,
        max_seconds=1800, max_attempts=1, verification_commands=(), max_provider_calls=1,
        max_total_tokens=100, max_output_tokens_per_call=10, created_at="",
    )


def prepared(store: TaskStore, key: str) -> str:
    record = store.create(spec(), key)
    store.transition(record.task_id, "draft", "preparing", {})
    store.transition(record.task_id, "preparing", "prepared", {})
    work = store.root / record.task_id / "workspace" / "work"
    work.mkdir(parents=True)
    return record.task_id


def controller(store: TaskStore, launcher: FakeLauncher, containers: FakeContainers) -> TaskWorkerController:
    return TaskWorkerController(
        store=store, instance_id="instance_123456789012", launcher=launcher, containers=containers,
    )


def test_service_close_interrupts_awaiting_approval_and_stops_owned_resources(
    temp_git_repo: Path, tmp_path: Path,
) -> None:
    reader = LocalGitReader()
    catalog = RepositoryCatalog.from_paths([temp_git_repo], reader)
    launcher, containers = FakeLauncher(), FakeContainers()
    broker = ApprovalBroker(wait_timeout_seconds=30)
    service = TaskService(
        catalog, reader, tmp_path / "tasks",
        worker_controller_factory=lambda store: TaskWorkerController(
            store=store, instance_id="instance_123456789012", launcher=launcher,
            containers=containers, broker=broker,
        ),
    )
    task_id = prepared(service.store, "shutdown-approval")
    started = service.worker_controller.start(task_id)
    service.store.transition(task_id, "running", "awaiting_approval", {})
    request = ExecutionRequest(
        task_id=task_id, attempt_id=started.attempt_id, command_request_id="request_12345678901234",
        command="echo fake", cwd="/workspace", timeout_seconds=30,
        image_digest="sha256:" + "a" * 64, mount_source=str(service.store.root / task_id / "workspace" / "work"),
        mount_target="/workspace", network="none", env_allowlist=("PATH", "LANG"),
        cpu_limit=1.0, memory_bytes=512 * 1024 * 1024, pids_limit=64,
        max_output_chars=100, policy_version="task-command-v1",
    )
    waiting = service.pool.submit(broker.request, request)
    deadline = time.monotonic() + 3
    while not broker.pending(task_id) and time.monotonic() < deadline:
        time.sleep(0.005)
    assert broker.pending(task_id)
    began = time.monotonic()
    service.close()
    assert time.monotonic() - began < 3
    assert not waiting.result().approved
    assert service.store.get(task_id).state == "interrupted"
    assert service.store.get(task_id).cleanup_confirmed
    assert launcher.stopped and containers.cleaned


def test_only_one_worker_starts_under_concurrent_run(tmp_path: Path) -> None:
    store = TaskStore(tmp_path)
    ids = [prepared(store, "first"), prepared(store, "second")]
    launcher, containers = FakeLauncher(), FakeContainers()
    control = controller(store, launcher, containers)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda task_id: attempt_start(control, task_id), ids))
    assert outcomes.count("running") == 1
    assert outcomes.count("busy") == 1
    assert len(launcher.live) == 1 and len(launcher.activated) == 1


def attempt_start(control: TaskWorkerController, task_id: str) -> str:
    try:
        return control.start(task_id).state
    except TaskConflict:
        return "busy"


def test_cancel_stops_exact_worker_and_all_task_containers_before_terminal(tmp_path: Path) -> None:
    store = TaskStore(tmp_path)
    task_id = prepared(store, "first")
    launcher, containers = FakeLauncher(), FakeContainers()
    control = controller(store, launcher, containers)
    running = control.start(task_id)
    containers.owned.update({
        (running.instance_id, task_id, "request-one"),
        (running.instance_id, task_id, "request-two"),
        ("other-instance", "other-task", "request-safe"),
    })
    cancelled = control.cancel(task_id)
    assert cancelled.state == "cancelled" and cancelled.cleanup_confirmed
    assert launcher.stopped == [(running.worker_pid, running.worker_created_at)]
    assert containers.owned == {("other-instance", "other-task", "request-safe")}
    assert containers.cleaned == [(running.instance_id, task_id)]


def test_cleanup_failure_blocks_new_run_until_reconcile(tmp_path: Path) -> None:
    store = TaskStore(tmp_path)
    first, second = prepared(store, "first"), prepared(store, "second")
    launcher, containers = FakeLauncher(), FakeContainers()
    control = controller(store, launcher, containers)
    running = control.start(first)
    containers.owned.add((running.instance_id, first, "orphan"))
    containers.fail_cleanup = True
    failed = control.cancel(first)
    assert failed.state == "cleanup_failed" and failed.failure_kind == "cleanup_failed"
    with pytest.raises(TaskConflict):
        control.start(second)
    containers.fail_cleanup = False
    control.reconcile()
    assert store.get(first).state == "failed"
    assert store.get(first).cleanup_confirmed
    assert control.start(second).state == "running"


def test_restart_reconcile_interrupts_only_recorded_instance(tmp_path: Path) -> None:
    store = TaskStore(tmp_path)
    task_id = prepared(store, "first")
    launcher, containers = FakeLauncher(), FakeContainers()
    running = controller(store, launcher, containers).start(task_id)
    containers.owned.add((running.instance_id, task_id, "orphan"))
    containers.owned.add(("unrelated", task_id, "safe"))
    restarted = TaskStore(tmp_path)
    controller(restarted, launcher, containers).reconcile()
    assert restarted.get(task_id).state == "interrupted"
    assert restarted.get(task_id).cleanup_confirmed
    assert ("unrelated", task_id, "safe") in containers.owned
    assert (running.instance_id, task_id, "orphan") not in containers.owned


def test_finish_after_worker_exit_still_removes_orphan_container(tmp_path: Path) -> None:
    store = TaskStore(tmp_path)
    task_id = prepared(store, "first")
    launcher, containers = FakeLauncher(), FakeContainers()
    control = controller(store, launcher, containers)
    running = control.start(task_id)
    launcher.live.pop(running.worker_pid)
    containers.owned.add((running.instance_id, task_id, "late-child"))
    done = control.finish(task_id, "completed")
    assert done.state == "completed" and done.cleanup_confirmed
    assert containers.owned == set()


def test_command_ownership_is_durable_before_container_creation(tmp_path: Path) -> None:
    store = TaskStore(tmp_path)
    task_id = prepared(store, "first")
    control = controller(store, FakeLauncher(), FakeContainers())
    control.start(task_id)
    request_id = "request_12345678901234"
    registered = control.register_command(task_id, request_id)
    assert registered.owned_request_ids == (request_id,)
    assert TaskStore(tmp_path).get(task_id).owned_request_ids == (request_id,)
    with pytest.raises(TaskConflict):
        control.register_command(task_id, request_id)
    control.cancel(task_id)
    with pytest.raises(TaskConflict):
        control.register_command(task_id, "request_99999999999999")


def test_worker_environment_excludes_provider_and_inherited_private_values() -> None:
    environment = filtered_worker_environment({
        "PATH": "safe-path", "SystemRoot": "C:\\Windows", "PYTHONPATH": "untrusted-path",
        "MOKIO_TASK_API_KEY": "fake-private-value", "API_KEY": "legacy-private-value",
        "HOME": "private-home", "CUSTOM_SECRET": "other-private-value",
    })
    assert environment["PATH"] == "safe-path"
    assert environment["PYTHONPATH"] != "untrusted-path"
    assert "MOKIO_TASK_API_KEY" not in environment and "API_KEY" not in environment
    assert "HOME" not in environment and "CUSTOM_SECRET" not in environment


def test_loopback_worker_uses_creation_identity_and_stops_without_agent(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    launcher = TaskWorkerLauncher()
    identity = launcher.launch("task_1234567890123456", work)
    try:
        assert identity.pid > 0 and identity.created_at
        assert not launcher.exited(identity)
        launcher.activate(identity)
        assert not launcher.stop(ProcessIdentity(identity.pid, "wrong-creation"))
        assert not launcher.exited(identity)
    finally:
        assert launcher.stop(identity)
    assert launcher.exited(identity)


def test_worker_never_imports_module_from_task_work(tmp_path: Path) -> None:
    work = tmp_path / "work"
    malicious = work / "mokioclaw" / "dashboard"
    malicious.mkdir(parents=True)
    (work / "mokioclaw" / "__init__.py").write_text("", encoding="utf-8")
    (malicious / "__init__.py").write_text("", encoding="utf-8")
    marker = tmp_path / "imported.txt"
    (malicious / "task_worker.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported')\n", encoding="utf-8",
    )
    launcher = TaskWorkerLauncher()
    identity = launcher.launch("task_1234567890123456", work)
    try:
        launcher.activate(identity)
        assert not marker.exists()
    finally:
        assert launcher.stop(identity)


def test_inert_worker_stays_available_while_waiting_for_control(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    launcher = TaskWorkerLauncher()
    identity = launcher.launch("task_1234567890123456", work)
    try:
        launcher.activate(identity)
        time.sleep(5.2)
        assert not launcher.exited(identity)
    finally:
        launcher.stop(identity)


@pytest.mark.skipif(__import__("os").name != "nt", reason="Recorded-process identity uses Windows process handles")
def test_restart_can_stop_exact_recorded_worker_identity(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    original = TaskWorkerLauncher()
    identity = original.launch("task_1234567890123456", work)
    original.activate(identity)
    restarted = TaskWorkerLauncher()
    try:
        assert restarted.stop(identity)
        assert restarted.exited(identity)
    finally:
        original.stop(identity)


def test_service_startup_reconciles_recorded_worker_before_new_tasks(temp_git_repo: Path, tmp_path: Path) -> None:
    task_root = tmp_path / "tasks"
    store = TaskStore(task_root)
    task_id = prepared(store, "first")
    launcher, containers = FakeLauncher(), FakeContainers()
    running = controller(store, launcher, containers).start(task_id)
    containers.owned.add((running.instance_id, task_id, "orphan"))
    reader = LocalGitReader()
    catalog = RepositoryCatalog.from_paths([temp_git_repo], reader)
    service = TaskService(
        catalog, reader, task_root,
        worker_controller_factory=lambda loaded: controller(loaded, launcher, containers),
    )
    try:
        assert service.get(task_id).state == "interrupted"
        assert containers.owned == set()
    finally:
        service.close()


def test_cancel_invalidates_current_approval_before_stopping_worker(tmp_path: Path) -> None:
    store = TaskStore(tmp_path)
    task_id = prepared(store, "first")
    broker = ApprovalBroker(wait_timeout_seconds=2)
    launcher, containers = FakeLauncher(), FakeContainers()
    control = TaskWorkerController(
        store=store, instance_id="instance_123456789012", launcher=launcher,
        containers=containers, broker=broker,
    )
    control.start(task_id)
    request = ExecutionRequest(
        task_id=task_id, attempt_id=1, command_request_id="request_12345678901234",
        command="echo hello", cwd="/workspace", timeout_seconds=5,
        image_digest="sha256:" + "a" * 64,
        mount_source=str(tmp_path / task_id / "workspace" / "work"), mount_target="/workspace",
        network="none", env_allowlist=("PATH", "LANG"), cpu_limit=1.0,
        memory_bytes=512 * 1024 * 1024, pids_limit=64, max_output_chars=200,
        policy_version="task-command-v1",
    )
    decisions = []
    waiter = threading.Thread(target=lambda: decisions.append(broker.request(request)))
    waiter.start()
    deadline = time.monotonic() + 2
    while not broker.pending(task_id) and time.monotonic() < deadline:
        time.sleep(0.005)
    assert broker.pending(task_id)
    assert control.cancel(task_id).state == "cancelled"
    waiter.join(timeout=2)
    assert len(decisions) == 1 and not decisions[0].approved
    assert not broker.decide(task_id, 1, request.command_request_id, request.canonical_digest(), True)
    assert launcher.live == {}


def test_timeout_and_completion_race_never_publish_two_outcomes(tmp_path: Path) -> None:
    store = TaskStore(tmp_path)
    task_id = prepared(store, "first")
    launcher, containers = FakeLauncher(), FakeContainers()
    control = controller(store, launcher, containers)
    running = control.start(task_id)
    containers.owned.add((running.instance_id, task_id, "request-one"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(control.finish, task_id, outcome) for outcome in ("timed_out", "completed")]
        outcomes = [future.result().state for future in futures]
    assert len(set(outcomes)) == 1
    assert outcomes[0] in {"timed_out", "completed"}
    assert store.get(task_id).cleanup_confirmed
    assert launcher.live == {} and containers.owned == set()
