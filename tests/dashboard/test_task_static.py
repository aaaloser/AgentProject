from __future__ import annotations

from pathlib import Path
import os
import socket
import subprocess
import time
from threading import Thread

import httpx
import uvicorn

from mokioclaw.dashboard.api import create_dashboard_app
from mokioclaw.dashboard.catalog import RepositoryCatalog
from mokioclaw.dashboard.git_reader import LocalGitReader
from mokioclaw.dashboard.pagination import CursorCodec
from mokioclaw.dashboard.task_service import FakeTaskRunner, TaskService


STATIC = Path(__file__).parents[2] / "src" / "mokioclaw" / "dashboard" / "static"


def test_task_panel_keeps_review_workspace_and_labels_demo() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="repo-list"' in html and 'id="commit-list"' in html and 'id="detail-panel"' in html
    assert 'id="task-panel"' in html and 'id="task-preview"' in html and 'id="task-create"' in html
    assert 'id="task-demo-run"' in html and "演示" in html and "无 provider" in html
    assert "真实 Agent" in html and "未启用" in html


def test_task_ui_uses_text_nodes_and_rejects_late_responses() -> None:
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "taskEpoch" in script and "taskRepoId" in script and "taskId" in script
    assert "textContent" in script and "innerHTML" not in script
    assert "after=" in script and "/api/tasks/" in script
    assert "AbortController" in script


def _git(root: Path, *args: str) -> bytes:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", *args], cwd=root, env=env, check=True, capture_output=True).stdout.strip()


def _commit_fixture(root: Path, filename: str) -> str:
    (root / "src").mkdir()
    (root / "src" / filename).write_text("fixed\n", encoding="utf-8")
    _git(root, "add", "src")
    _git(root, "commit", "-q", "-m", "fixture")
    return _git(root, "rev-parse", "HEAD").decode("ascii")


def test_two_repository_task_flow_over_real_loopback(temp_git_repo: Path, tmp_path: Path) -> None:
    first = temp_git_repo
    second = tmp_path / "second"
    second.mkdir()
    _git(second, "init", "-q", "-b", "main")
    _git(second, "config", "user.name", "Fixture User")
    _git(second, "config", "user.email", "fixture@example.invalid")
    first_sha = _commit_fixture(first, "first.py")
    second_sha = _commit_fixture(second, "second.py")
    before = [(_git(root, "show-ref", "--head"), (root / ".git" / "index").read_bytes(),
               _git(root, "status", "--porcelain=v1", "-z", "--ignored")) for root in (first, second)]
    reader = LocalGitReader()
    catalog = RepositoryCatalog.from_paths([first, second], reader)
    service = TaskService(catalog, reader, tmp_path / "tasks", fake_runner=FakeTaskRunner(step_delay=0.01))
    app = create_dashboard_app(catalog, reader, CursorCodec(), task_service=service)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(32)
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False, log_level="error"))
        thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started
            origin = f"http://127.0.0.1:{port}"
            with httpx.Client(base_url=origin, trust_env=False, timeout=5) as client:
                repositories = client.get("/api/repositories").json()
                assert len(repositories) == 2
                assert client.get("/").status_code == 200
                session = client.get("/api/task-session").json()
                headers = {"Origin": origin, "X-MokioClaw-CSRF": session["csrf_token"]}
                second_id = repositories[1]["id"]
                assert client.post("/api/task-previews", headers=headers, json={
                    "repo_id": second_id, "base_sha": first_sha, "anchor_sha": first_sha,
                    "source_read_scope": ["src/"],
                }).status_code == 400
                preview = client.post("/api/task-previews", headers=headers, json={
                    "repo_id": second_id, "base_sha": second_sha, "anchor_sha": second_sha,
                    "source_read_scope": ["src/"],
                }).json()
                created = client.post("/api/tasks", headers={**headers, "Idempotency-Key": "loopback-demo"}, json={
                    "preview_id": preview["preview_id"], "repo_id": second_id, "base_sha": second_sha,
                    "anchor_sha": second_sha, "source_read_scope": ["src/"], "description": "local fixture",
                    "max_seconds": 60, "max_attempts": 1, "verification_commands": [],
                    "max_provider_calls": 1, "max_total_tokens": 1000, "max_output_tokens_per_call": 100,
                })
                assert created.status_code == 202
                task_id = created.json()["task_id"]
                while time.monotonic() < deadline + 5 and client.get(f"/api/tasks/{task_id}").json()["state"] == "preparing":
                    time.sleep(0.02)
                assert client.get(f"/api/tasks/{task_id}").json()["state"] == "prepared"
                assert client.post(f"/api/tasks/{task_id}/demo-run", headers=headers, json={}).status_code == 202
                while time.monotonic() < deadline + 5 and client.get(f"/api/tasks/{task_id}").json()["state"] != "completed":
                    time.sleep(0.02)
                assert client.get(f"/api/tasks/{task_id}").json()["state"] == "completed"
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            service.close()
    after = [(_git(root, "show-ref", "--head"), (root / ".git" / "index").read_bytes(),
              _git(root, "status", "--porcelain=v1", "-z", "--ignored")) for root in (first, second)]
    assert after == before
