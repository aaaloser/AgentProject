from __future__ import annotations

import importlib
import os
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mokioclaw.dashboard.api import create_dashboard_app
from mokioclaw.dashboard.catalog import RepositoryCatalog
from mokioclaw.dashboard.git_reader import LocalGitReader
from mokioclaw.dashboard.pagination import CursorCodec


def test_projection_keeps_only_enumerated_fields_and_fixed_identity() -> None:
    events = importlib.import_module("mokioclaw.dashboard.task_events")
    raw = {
        "kind": "stage", "phase": "planner", "task_id": "task_1234567890123456",
        "attempt_id": 1, "sequence": 7, "prompt": "SECRET PROMPT", "response": "SECRET RESPONSE",
        "headers": {"Authorization": "SECRET KEY"}, "endpoint": "https://private.invalid/?token=SECRET",
        "path": "C:/private/source", "unknown": "SECRET UNKNOWN",
    }
    event = events.project_task_event(raw, "task_1234567890123456", 1, 7)
    assert event.kind == "stage" and event.data == {"phase": "planner"}
    assert "SECRET" not in repr(event) and "private" not in repr(event)


@pytest.mark.parametrize("update", [
    {"task_id": "another_task_1234567890"}, {"attempt_id": 2}, {"sequence": 6},
    {"kind": "raw_provider"}, {"kind": "stage", "phase": "SECRET PHASE"},
])
def test_projection_rejects_wrong_identity_or_unlisted_value(update: dict) -> None:
    events = importlib.import_module("mokioclaw.dashboard.task_events")
    raw = {"kind": "stage", "phase": "planner", "task_id": "task_1234567890123456", "attempt_id": 1,
           "sequence": 7, **update}
    with pytest.raises(events.TaskEventRejected):
        events.project_task_event(raw, "task_1234567890123456", 1, 7)


def test_projection_never_copies_command_or_output_text() -> None:
    events = importlib.import_module("mokioclaw.dashboard.task_events")
    raw = {"kind": "verification", "status": "passed", "exit_code": 0,
           "command": "echo SECRET", "stdout": "SECRET", "stderr": "SECRET"}
    event = events.project_task_event(raw, "task_1234567890123456", 1, 1)
    assert event.data == {"status": "passed", "exit_code": 0}


def _git(root: Path, *args: str) -> bytes:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", *args], cwd=root, env=env, check=True, capture_output=True).stdout.strip()


def _demo_client(temp_git_repo: Path, tmp_path: Path, outcome: str = "completed"):
    service_module = importlib.import_module("mokioclaw.dashboard.task_service")
    (temp_git_repo / "src").mkdir()
    (temp_git_repo / "src" / "a.py").write_bytes(b"base\n")
    _git(temp_git_repo, "add", "src/a.py")
    _git(temp_git_repo, "commit", "-q", "-m", "base")
    sha = _git(temp_git_repo, "rev-parse", "HEAD").decode("ascii")
    reader = LocalGitReader()
    catalog = RepositoryCatalog.from_paths([temp_git_repo], reader)
    service = service_module.TaskService(
        catalog, reader, tmp_path / "tasks", fake_runner=service_module.FakeTaskRunner(step_delay=0.02, outcome=outcome),
    )
    client = TestClient(create_dashboard_app(catalog, reader, CursorCodec(), task_service=service), base_url="http://127.0.0.1")
    token = client.get("/api/task-session").json()["csrf_token"]
    headers = {"Origin": "http://127.0.0.1", "X-MokioClaw-CSRF": token}
    repo_id = catalog.summaries()[0].id
    preview = client.post("/api/task-previews", headers=headers, json={
        "repo_id": repo_id, "base_sha": sha, "anchor_sha": sha, "source_read_scope": ["src/"],
    }).json()
    created = client.post("/api/tasks", headers={**headers, "Idempotency-Key": "demo-key"}, json={
        "preview_id": preview["preview_id"], "repo_id": repo_id, "base_sha": sha, "anchor_sha": sha,
        "source_read_scope": ["src/"], "description": "PRIVATE TASK DESCRIPTION", "max_seconds": 60,
        "max_attempts": 1, "verification_commands": [], "max_provider_calls": 1,
        "max_total_tokens": 1000, "max_output_tokens_per_call": 100,
    })
    assert created.status_code == 202
    task_id = created.json()["task_id"]
    _wait_state(client, task_id, {"prepared"})
    return client, headers, service, task_id


def _wait_state(client: TestClient, task_id: str, states: set[str]) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        record = client.get(f"/api/tasks/{task_id}").json()
        if record["state"] in states:
            return record
        time.sleep(0.02)
    raise AssertionError(f"Task did not reach {states}")


@pytest.mark.parametrize("outcome,expected", [
    ("completed", "completed"), ("failed", "failed"), ("cleanup_failed", "cleanup_failed"),
])
def test_fake_run_projects_states_without_private_data(temp_git_repo: Path, tmp_path: Path, outcome: str, expected: str) -> None:
    before = None
    client, headers, service, task_id = _demo_client(temp_git_repo, tmp_path, outcome)
    try:
        before = (_git(temp_git_repo, "show-ref", "--head"), (temp_git_repo / ".git" / "index").read_bytes(),
                  _git(temp_git_repo, "status", "--porcelain=v1", "-z", "--ignored"))
        started = client.post(f"/api/tasks/{task_id}/demo-run", headers=headers, json={})
        assert started.status_code == 202
        record = _wait_state(client, task_id, {expected})
        events = client.get(f"/api/tasks/{task_id}/events", params={"after": 0}).json()["events"]
        assert record["state"] == expected
        assert {event["kind"] for event in events} >= {"state", "stage", "approval_request", "verification"}
        assert [event["sequence"] for event in events] == sorted({event["sequence"] for event in events})
        body = client.get(f"/api/tasks/{task_id}").text + repr(events)
        assert "PRIVATE TASK DESCRIPTION" not in body and "SECRET" not in body
        assert (_git(temp_git_repo, "show-ref", "--head"), (temp_git_repo / ".git" / "index").read_bytes(),
                _git(temp_git_repo, "status", "--porcelain=v1", "-z", "--ignored")) == before
    finally:
        service.close()


def test_fake_run_can_be_cancelled_without_provider(temp_git_repo: Path, tmp_path: Path) -> None:
    client, headers, service, task_id = _demo_client(temp_git_repo, tmp_path)
    try:
        assert client.post(f"/api/tasks/{task_id}/demo-run", headers=headers, json={}).status_code == 202
        assert client.post(f"/api/tasks/{task_id}/demo-cancel", headers=headers, json={}).status_code == 200
        assert _wait_state(client, task_id, {"cancelled"})["state"] == "cancelled"
    finally:
        service.close()


def test_fake_runner_failure_stops_with_safe_error(temp_git_repo: Path, tmp_path: Path, monkeypatch) -> None:
    client, headers, service, task_id = _demo_client(temp_git_repo, tmp_path)
    try:
        def fail_event(*_args):
            raise RuntimeError("PRIVATE PROVIDER TOKEN")

        monkeypatch.setattr(service, "publish_demo_event", fail_event)
        assert client.post(f"/api/tasks/{task_id}/demo-run", headers=headers, json={}).status_code == 202
        record = _wait_state(client, task_id, {"failed"})
        assert record["failure_kind"] == "demo_failure"
        assert "PRIVATE" not in client.get(f"/api/tasks/{task_id}").text
    finally:
        service.close()
