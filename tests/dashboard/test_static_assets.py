from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from mokioclaw.dashboard.api import create_dashboard_app
from mokioclaw.dashboard.catalog import RepositoryCatalog
from mokioclaw.dashboard.git_reader import LocalGitReader
from mokioclaw.dashboard.pagination import CursorCodec


def _git(root: Path, *arguments: str) -> str:
    environment = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    result = subprocess.run(["git", *arguments], cwd=root, env=environment, check=True, capture_output=True)
    return result.stdout.decode("utf-8", errors="replace").strip()


def _commit(root: Path, name: str, title: str) -> str:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(title + "\n", encoding="utf-8")
    _git(root, "add", "--", name)
    _git(root, "commit", "-q", "-m", title)
    return _git(root, "rev-parse", "HEAD")


def _client(*roots: Path) -> TestClient:
    reader = LocalGitReader()
    catalog = RepositoryCatalog.from_paths(list(roots), reader)
    return TestClient(create_dashboard_app(catalog, reader, CursorCodec()), base_url="http://127.0.0.1")


def test_same_origin_page_assets_and_safe_structure(temp_git_repo: Path) -> None:
    client = _client(temp_git_repo)
    page = client.get("/")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "default-src 'self'" in page.headers["content-security-policy"]
    html = page.text
    assert 'lang="zh-CN"' in html
    for marker in (
        "repo-list", "commit-list", "detail-panel", "dashboard-status", "head-update", "load-more", "refresh-list",
        "改动审查优先级（启发式）", "task-verification-commands", "task-approvals", "task-final-result",
    ):
        assert marker in html
    assert re.search(r'<(?:script|link)\b[^>]+(?:src|href)="https?://', html, re.IGNORECASE) is None
    assert "Agent 修复" not in html
    assert "<button" in html

    css = client.get("/static/styles.css")
    script = client.get("/static/app.js")
    assert css.status_code == script.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert "javascript" in script.headers["content-type"]
    assert "@media" in css.text
    assert ":focus-visible" in css.text
    assert "textContent" in script.text
    assert "visibleText" in script.text and "/result" in script.text
    assert "固定提交完整 SHA" in script.text
    assert "历史锚完整 SHA" in script.text
    assert "当前 HEAD 完整 SHA" in script.text
    assert "result.blocked_paths" in script.text and "blocker.reason" in script.text
    assert "innerHTML" not in script.text
    assert "AbortController" in script.text
    assert "https://" not in script.text
    assert "http://" not in script.text


def test_real_task_controls_require_visible_fixed_run_policy(temp_git_repo: Path) -> None:
    client = _client(temp_git_repo)
    html = client.get("/").text
    script = client.get("/static/app.js").text
    assert 'id="task-run-policy"' in html
    assert 'id="task-run" disabled' in html
    assert 'id="task-cancel" disabled' in html
    assert '/run-policy' in script
    assert 'policy.base_sha !== state.taskBaseSha' in script
    assert 'window.confirm' in script
    assert 'demoAvailable' in script and 'runAvailable' in script


def test_two_repository_demo_has_low_high_and_manual_review(temp_git_repo: Path, tmp_path: Path) -> None:
    first = temp_git_repo
    second = tmp_path / "second"
    second.mkdir()
    _git(second, "init", "-q", "-b", "main")
    _git(second, "config", "user.name", "Fixture User")
    _git(second, "config", "user.email", "fixture@example.invalid")

    ordinary = _commit(first, "literal & safe.txt", "<script>alert(1)</script>")
    sensitive = _commit(first, "pyproject.toml", "update project setup")
    _git(first, "checkout", "-q", "-b", "feature")
    _commit(first, "feature.txt", "feature")
    _git(first, "checkout", "-q", "main")
    _commit(first, "main.txt", "main")
    _git(first, "merge", "-q", "--no-ff", "-m", "merge feature", "feature")
    merge = _git(first, "rev-parse", "HEAD")
    _commit(second, "other.txt", "other repository")

    client = _client(first, second)
    repositories = client.get("/api/repositories").json()
    first_id, second_id = [row["id"] for row in repositories]
    page = client.get(f"/api/repositories/{first_id}/commits").json()
    assert page["commits"][0]["sha"] == merge
    assert first_id != second_id
    assert client.get(f"/api/repositories/{second_id}/commits").json()["commits"][0]["sha"] != merge

    expected = [(ordinary, "low"), (sensitive, "high"), (merge, "manual_review")]
    for sha, priority in expected:
        response = client.get(f"/api/repositories/{first_id}/commits/{sha}", params={"anchor": merge})
        assert response.status_code == 200
        assert response.json()["assessment"]["priority"] == priority
    ordinary_detail = client.get(f"/api/repositories/{first_id}/commits/{ordinary}", params={"anchor": merge}).json()
    assert ordinary_detail["detail"]["title"] == "<script>alert(1)</script>"
    assert ordinary_detail["detail"]["files"][0]["path"] == "literal & safe.txt"
