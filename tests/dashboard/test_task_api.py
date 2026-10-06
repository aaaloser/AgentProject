from __future__ import annotations

import importlib
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mokioclaw.dashboard.api import create_dashboard_app
from mokioclaw.dashboard.catalog import RepositoryCatalog
from mokioclaw.dashboard.git_reader import LocalGitReader
from mokioclaw.dashboard.pagination import CursorCodec


def _git(root: Path, *args: str) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", *args], cwd=root, env=env, capture_output=True, check=True).stdout.decode().strip()


@pytest.fixture
def task_api(temp_git_repo: Path, tmp_path: Path):
    (temp_git_repo / "src").mkdir()
    (temp_git_repo / "src" / "a.py").write_text("base\n", encoding="utf-8")
    _git(temp_git_repo, "add", "src/a.py")
    _git(temp_git_repo, "commit", "-q", "-m", "base")
    sha = _git(temp_git_repo, "rev-parse", "HEAD")
    reader = LocalGitReader()
    catalog = RepositoryCatalog.from_paths([temp_git_repo], reader)
    repo_id = catalog.summaries()[0].id
    service_module = importlib.import_module("mokioclaw.dashboard.task_service")
    service = service_module.TaskService(catalog, reader, tmp_path / "tasks")
    client = TestClient(create_dashboard_app(catalog, reader, CursorCodec(), task_service=service), base_url="http://127.0.0.1")
    token = client.get("/api/task-session").json()["csrf_token"]
    headers = {"Origin": "http://127.0.0.1", "X-MokioClaw-CSRF": token}
    yield client, headers, service, catalog, reader, repo_id, sha
    service.close()


def _preview(client: TestClient, headers: dict[str, str], repo_id: str, sha: str):
    return client.post("/api/task-previews", headers=headers, json={
        "repo_id": repo_id, "base_sha": sha, "anchor_sha": sha, "source_read_scope": ["src/"],
    })


def _task_payload(preview: dict, repo_id: str, sha: str) -> dict:
    return {
        "preview_id": preview["preview_id"], "repo_id": repo_id, "base_sha": sha, "anchor_sha": sha,
        "source_read_scope": ["src/"], "description": "Update the source file", "max_seconds": 60,
        "max_attempts": 1, "verification_commands": [], "max_provider_calls": 1,
        "max_total_tokens": 1000, "max_output_tokens_per_call": 100,
    }


def test_legacy_get_contract_and_no_task_root(temp_git_repo: Path) -> None:
    reader = LocalGitReader()
    catalog = RepositoryCatalog.from_paths([temp_git_repo], reader)
    legacy = TestClient(create_dashboard_app(catalog, reader, CursorCodec()), base_url="http://127.0.0.1")
    assert legacy.get("/api/repositories").json()[0]["id"] == catalog.summaries()[0].id
    session = legacy.get("/api/task-session").json()
    assert session["task_available"] is False
    response = legacy.post("/api/task-previews", headers={
        "Origin": "http://127.0.0.1", "X-MokioClaw-CSRF": session["csrf_token"],
    }, json={})
    assert response.status_code == 503 and response.json()["code"] == "task_unavailable"


def test_approval_api_exposes_only_pending_policy_and_requires_exact_decision(task_api, monkeypatch) -> None:
    client, headers, service, _, _, _, _ = task_api
    task_id = "task_1234567890123456"
    request_id = "request_12345678901234"
    digest = "a" * 64
    decisions = []
    monkeypatch.setattr(service, "get", lambda _task_id: object())
    monkeypatch.setattr(service, "pending_approvals", lambda _task_id: [{
        "attempt_id": 1, "command_request_id": request_id, "execution_digest": digest,
        "command": "echo fake", "image_digest": "sha256:" + "b" * 64,
    }])
    monkeypatch.setattr(service, "decide_approval", lambda *args: (decisions.append(args) or True))
    response = client.get(f"/api/tasks/{task_id}/approvals")
    assert response.status_code == 200
    assert response.json()["approvals"][0]["command"] == "echo fake"
    assert client.post(f"/api/tasks/{task_id}/approvals/{request_id}", headers=headers,
                       json={"attempt_id": 1, "execution_digest": digest,
                             "approved": True, "extra": "private"}).status_code == 400
    assert decisions == []
    assert client.post(f"/api/tasks/{task_id}/approvals/{request_id}", headers=headers,
                       json={"attempt_id": 1, "execution_digest": digest,
                             "approved": True}).status_code == 200
    assert decisions == [(task_id, 1, request_id, digest, True)]


def test_prepared_task_can_be_cancelled_without_agent_or_docker(task_api, monkeypatch) -> None:
    from mokioclaw.providers.openai_provider import ProviderSettings
    from mokioclaw.dashboard import task_executor

    client, headers, service, _, _, repo_id, sha = task_api
    monkeypatch.setattr(task_executor.DockerCLI, "run", lambda *_args, **_kwargs:
                        pytest.fail("Docker contacted"))
    preview = _preview(client, headers, repo_id, sha).json()
    response = client.post("/api/tasks", headers={**headers, "Idempotency-Key": "cancel-prepared"},
                           json=_task_payload(preview, repo_id, sha))
    task_id = response.json()["task_id"]
    deadline = time.monotonic() + 5
    while service.get(task_id).state == "preparing" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert service.get(task_id).state == "prepared"
    service.configure_agent(ProviderSettings("FAKE", "fake-model", "https://task.invalid/v1"),
                            "sha256:" + "a" * 64)
    cancelled = client.post(f"/api/tasks/{task_id}/cancel", headers=headers, json={})
    assert cancelled.status_code == 202
    assert cancelled.json()["state"] == "cancelled"
    assert service.get(task_id).cleanup_confirmed


def test_prepared_task_restores_private_runtime_limits_after_dashboard_restart(task_api) -> None:
    from mokioclaw.dashboard.task_service import TaskService

    client, headers, service, catalog, reader, repo_id, sha = task_api
    preview = _preview(client, headers, repo_id, sha).json()
    response = client.post("/api/tasks", headers={**headers, "Idempotency-Key": "restart-prepared"},
                           json=_task_payload(preview, repo_id, sha))
    task_id = response.json()["task_id"]
    deadline = time.monotonic() + 5
    while service.get(task_id).state == "preparing" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert service.get(task_id).state == "prepared"
    service.close()
    reopened = TaskService(catalog, reader, service.task_root)
    try:
        payload = reopened.worker_start_payload(task_id)
        assert payload["description"] == "Update the source file"
        assert payload["max_provider_calls"] == 1
    finally:
        reopened.close()


def test_result_api_exposes_bounded_summary_only_after_cleanup(task_api) -> None:
    from mokioclaw.dashboard.task_service import TaskService

    client, headers, service, catalog, reader, repo_id, sha = task_api
    preview = _preview(client, headers, repo_id, sha).json()
    created = client.post("/api/tasks", headers={**headers, "Idempotency-Key": "result-summary"},
                          json=_task_payload(preview, repo_id, sha)).json()
    task_id = created["task_id"]
    deadline = time.monotonic() + 5
    while service.get(task_id).state == "preparing" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert service.get(task_id).state == "prepared"
    assert client.get(f"/api/tasks/{task_id}/result").status_code == 409
    work = service.prepared(task_id).work
    (work / "src" / "a.py").write_text("modified private content\n", encoding="utf-8")
    service.store.transition(task_id, "prepared", "running", {})
    service.store.transition(task_id, "running", "stopping", {})
    service.store.transition(task_id, "stopping", "completed", {"cleanup_confirmed": True})
    response = client.get(f"/api/tasks/{task_id}/result")
    assert response.status_code == 200
    result = response.json()
    assert result["base_sha"] == sha and result["status"] == "completed"
    assert result["changed_files"] == ["src/a.py"]
    assert result["verification_status"] == "not_run"
    assert result["patch_summary"]["status"] == "available"
    assert "modified private content" not in response.text
    assert str(work) not in response.text
    assert client.get("/api/tasks/invalid/result").status_code == 404
    (work / "src" / "a.py").write_text("later local edit\nsecond line\n", encoding="utf-8")
    assert client.get(f"/api/tasks/{task_id}/result").json() == result
    service.close()
    reopened = TaskService(catalog, reader, service.task_root)
    try:
        assert reopened.result(task_id).changed_files == ("src/a.py",)
        assert reopened.result(task_id).patch_summary.added_lines == result["patch_summary"]["added_lines"]
    finally:
        reopened.close()


def test_cleanup_failed_is_not_a_final_result(task_api) -> None:
    client, headers, service, _, _, repo_id, sha = task_api
    preview = _preview(client, headers, repo_id, sha).json()
    created = client.post("/api/tasks", headers={**headers, "Idempotency-Key": "cleanup-pending"},
                          json=_task_payload(preview, repo_id, sha)).json()
    task_id = created["task_id"]
    deadline = time.monotonic() + 5
    while service.get(task_id).state == "preparing" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert service.get(task_id).state == "prepared"
    service.store.transition(task_id, "prepared", "running", {})
    service.store.transition(task_id, "running", "stopping", {})
    service.store.transition(task_id, "stopping", "cleanup_failed", {"failure_kind": "cleanup_failed"})
    response = client.get(f"/api/tasks/{task_id}/result")
    assert response.status_code == 409 and response.json()["code"] == "result_unavailable"
    assert not (service.store.root / task_id / "result.json").exists()


@pytest.mark.parametrize("headers,body", [
    ({}, {}),
    ({"Origin": "http://evil.invalid"}, {}),
    ({"Origin": "http://127.0.0.1", "X-MokioClaw-CSRF": "wrong"}, {}),
])
def test_write_security_rejects_missing_origin_or_token(task_api, headers: dict, body: dict) -> None:
    client, _, _, _, _, _, _ = task_api
    response = client.post("/api/task-previews", headers=headers, json=body)
    assert response.status_code == 403


def test_preview_rejects_unknown_and_oversize_payload(task_api) -> None:
    client, headers, _, _, _, repo_id, sha = task_api
    assert _preview(client, headers, repo_id, sha).status_code == 200
    bad = {"repo_id": repo_id, "base_sha": sha, "anchor_sha": sha, "source_read_scope": ["src/"], "extra": 1}
    assert client.post("/api/task-previews", headers=headers, json=bad).status_code == 400
    too_large = client.post("/api/task-previews", headers={**headers, "Content-Type": "application/json"},
                            content=b"{" + b"x" * 20000)
    assert too_large.status_code == 413
    wrong_host = client.post("/api/task-previews", headers={**headers, "Host": "127.0.0.1.evil.invalid"}, json=bad)
    assert wrong_host.status_code == 400


def test_task_root_has_one_dashboard_owner(task_api) -> None:
    _, _, service, catalog, reader, _, _ = task_api
    module = importlib.import_module("mokioclaw.dashboard.task_service")
    with pytest.raises(module.TaskRootBusy):
        module.TaskService(catalog, reader, service.task_root)


def test_async_prepare_idempotency_and_fixed_identity(task_api, monkeypatch) -> None:
    client, headers, service, _, _, repo_id, sha = task_api
    preview = _preview(client, headers, repo_id, sha).json()
    entered = threading.Event()
    release = threading.Event()
    actual_prepare = service.prepare

    def slow_prepare(*args):
        entered.set()
        assert release.wait(5)
        return actual_prepare(*args)

    monkeypatch.setattr(service, "prepare", slow_prepare)
    payload = _task_payload(preview, repo_id, sha)
    started = time.monotonic()
    created = client.post("/api/tasks", headers={**headers, "Idempotency-Key": "same-request"}, json=payload)
    elapsed = time.monotonic() - started
    assert created.status_code == 202 and elapsed < 1
    task_id = created.json()["task_id"]
    assert created.json()["state"] == "preparing" and entered.wait(2)
    again = client.post("/api/tasks", headers={**headers, "Idempotency-Key": "same-request"}, json=payload)
    assert again.status_code == 202 and again.json()["task_id"] == task_id
    changed = {**payload, "description": "different"}
    assert client.post("/api/tasks", headers={**headers, "Idempotency-Key": "same-request"}, json=changed).status_code == 409
    assert client.get(f"/api/tasks/{task_id}").json()["state"] == "preparing"
    release.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and client.get(f"/api/tasks/{task_id}").json()["state"] == "preparing":
        time.sleep(0.02)
    assert client.get(f"/api/tasks/{task_id}").json()["state"] == "prepared"
    assert client.get("/api/tasks/other").status_code == 404
    assert client.get(f"/api/tasks/{task_id}/events", params={"after": 0}).json()["events"]


def test_preview_mismatch_and_prepare_failure_are_safe(task_api, monkeypatch) -> None:
    client, headers, service, _, _, repo_id, sha = task_api
    preview = _preview(client, headers, repo_id, sha).json()
    wrong = _task_payload(preview, repo_id, sha)
    wrong["source_read_scope"] = ["other/"]
    assert client.post("/api/tasks", headers={**headers, "Idempotency-Key": "wrong"}, json=wrong).status_code == 400

    def fail_prepare(*_args):
        raise RuntimeError("PRIVATE PATH AND SECRET")

    monkeypatch.setattr(service, "prepare", fail_prepare)
    response = client.post("/api/tasks", headers={**headers, "Idempotency-Key": "will-fail"},
                           json=_task_payload(preview, repo_id, sha))
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and client.get(f"/api/tasks/{task_id}").json()["state"] == "preparing":
        time.sleep(0.02)
    result = client.get(f"/api/tasks/{task_id}")
    assert result.json()["state"] == "failed"
    assert "PRIVATE" not in result.text and "SECRET" not in result.text
    assert client.post(f"/api/tasks/{task_id}/run", headers=headers, json={}).status_code != 200


def test_provider_budget_ceilings_match_amended_design_maxima(task_api) -> None:
    client, headers, service, _, _, repo_id, sha = task_api
    preview = _preview(client, headers, repo_id, sha).json()
    base = _task_payload(preview, repo_id, sha)
    accepted = client.post("/api/tasks", headers={**headers, "Idempotency-Key": "budget-mid"}, json={
        **base, "max_provider_calls": 22, "max_total_tokens": 150_000})
    assert accepted.status_code == 202
    ceiling = client.post("/api/tasks", headers={**headers, "Idempotency-Key": "budget-max"}, json={
        **base, "max_provider_calls": 24, "max_total_tokens": 200_000})
    assert ceiling.status_code == 202
    assert client.post("/api/tasks", headers={**headers, "Idempotency-Key": "budget-calls-over"}, json={
        **base, "max_provider_calls": 25}).status_code == 400
    assert client.post("/api/tasks", headers={**headers, "Idempotency-Key": "budget-tokens-over"}, json={
        **base, "max_total_tokens": 300_001}).status_code == 400


@pytest.mark.parametrize("max_tokens", [200_001, 250_000, 300_000])
def test_expanded_token_budget_is_accepted_and_persisted(task_api, max_tokens: int) -> None:
    client, headers, service, _, _, repo_id, sha = task_api
    preview = _preview(client, headers, repo_id, sha).json()
    result = client.post("/api/tasks", headers={**headers, "Idempotency-Key": "expanded-budget"}, json={
        **_task_payload(preview, repo_id, sha), "max_provider_calls": 24, "max_total_tokens": max_tokens,
    })
    assert result.status_code == 202
    spec = service.store.get_spec(result.json()["task_id"])
    assert spec.max_total_tokens == max_tokens
    assert spec.max_provider_calls == 24
    assert spec.max_output_tokens_per_call == 100


@pytest.mark.parametrize("max_tokens", [0, 300_001, True, 300_000.5, "300000"])
def test_invalid_expanded_token_budget_is_rejected(task_api, max_tokens) -> None:
    client, headers, _, _, _, repo_id, sha = task_api
    preview = _preview(client, headers, repo_id, sha).json()
    result = client.post("/api/tasks", headers={**headers, "Idempotency-Key": "invalid-budget"}, json={
        **_task_payload(preview, repo_id, sha), "max_total_tokens": max_tokens,
    })
    assert result.status_code == 400


def test_run_gate_and_busy_state(task_api) -> None:
    client, headers, service, _, _, repo_id, sha = task_api
    preview = _preview(client, headers, repo_id, sha).json()
    first = client.post("/api/tasks", headers={**headers, "Idempotency-Key": "first"},
                        json=_task_payload(preview, repo_id, sha)).json()["task_id"]
    second = client.post("/api/tasks", headers={**headers, "Idempotency-Key": "second"},
                         json=_task_payload(preview, repo_id, sha)).json()["task_id"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and any(
        client.get(f"/api/tasks/{task_id}").json()["state"] == "preparing" for task_id in (first, second)
    ):
        time.sleep(0.02)
    service.store.transition(first, "prepared", "running", {})
    assert client.post(f"/api/tasks/{second}/run", headers=headers, json={}).status_code == 409
    assert client.post(f"/api/tasks/{first}/run", headers=headers, json={}).status_code == 503


def test_real_run_requires_local_image_and_exposes_fixed_review_policy(task_api, monkeypatch) -> None:
    from dataclasses import replace
    from subprocess import CompletedProcess

    from mokioclaw.providers.openai_provider import ProviderSettings
    from mokioclaw.dashboard.task_executor import DockerCLI

    client, headers, service, _, _, repo_id, sha = task_api
    preview = _preview(client, headers, repo_id, sha).json()
    payload = _task_payload(preview, repo_id, sha)
    payload["verification_commands"] = ["python -m pytest -q"]
    created = client.post("/api/tasks", headers={**headers, "Idempotency-Key": "real-run-gate"}, json=payload)
    task_id = created.json()["task_id"]
    deadline = time.monotonic() + 5
    while service.get(task_id).state == "preparing" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert service.get(task_id).state == "prepared"
    image = "sha256:" + "a" * 64
    service.configure_agent(ProviderSettings("FAKE_PRIVATE_KEY", "fake-model", "https://task.invalid/v1?secret=FAKE"), image)
    monkeypatch.setattr(DockerCLI, "run", lambda *_args, **_kwargs:
                        CompletedProcess([], 1, "", "unavailable"))
    assert client.get("/api/task-session").json()["run_available"] is False
    assert client.post(f"/api/tasks/{task_id}/run", headers=headers, json={}).status_code == 503
    assert service.get(task_id).state == "prepared"

    monkeypatch.setattr(DockerCLI, "run", lambda *_args, **_kwargs:
                        CompletedProcess([], 0, image + "\n", ""))
    assert client.get("/api/task-session").json()["run_available"] is True
    policy_response = client.get(f"/api/tasks/{task_id}/run-policy")
    assert policy_response.status_code == 200
    policy = policy_response.json()
    assert policy["task_id"] == task_id and policy["base_sha"] == sha
    assert policy["model"] == "fake-model" and policy["image_digest"] == image
    assert policy["source_read_scope"] == ["src/"]
    assert policy["verification_commands"] == ["python -m pytest -q"]
    assert policy["max_provider_calls"] == 1 and policy["max_total_tokens"] == 1000
    assert policy["network"] == "none"
    assert "FAKE_PRIVATE_KEY" not in policy_response.text and "task.invalid" not in policy_response.text

    called = []
    monkeypatch.setattr(service, "start_agent", lambda requested:
                        (called.append(requested) or replace(service.get(requested), state="running")))
    started = client.post(f"/api/tasks/{task_id}/run", headers=headers, json={})
    assert started.status_code == 202 and started.json()["state"] == "running"
    assert called == [task_id]
