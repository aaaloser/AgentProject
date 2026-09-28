from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from threading import enumerate as live_threads
from urllib.request import urlopen

import pytest
from typer.testing import CliRunner

from mokioclaw.cli.app import app
from mokioclaw.dashboard.catalog import CatalogRegistrationError
from mokioclaw.dashboard.git_reader import LocalGitReader
from mokioclaw.dashboard.launcher import launch_dashboard


def _git(root: Path, *args: str) -> bytes:
    environment = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0"}
    return subprocess.run(["git", *args], cwd=root, env=environment, check=True, capture_output=True).stdout


def _snapshot(root: Path) -> tuple:
    return (
        _git(root, "show-ref", "--head"),
        (root / ".git" / "index").read_bytes(),
        _git(root, "--no-optional-locks", "status", "--porcelain=v1", "--ignored"),
        tuple(sorted((str(path.relative_to(root)), path.read_bytes()) for path in root.rglob("*") if path.is_file() and ".git" not in path.parts)),
    )


def test_cli_passes_repositories_in_order_without_agent(monkeypatch, tmp_path: Path) -> None:
    calls = []
    monkeypatch.setattr("mokioclaw.cli.app.stream_agent_events", lambda *args, **kwargs: pytest.fail("Agent started"))
    monkeypatch.setattr("mokioclaw.dashboard.launcher.launch_dashboard", lambda paths, open_browser: calls.append((paths, open_browser)))
    first, second = tmp_path / "one", tmp_path / "two"
    result = CliRunner().invoke(app, ["dashboard", "--repo", str(first), "--repo", str(second), "--no-browser"])
    assert result.exit_code == 0, result.output
    assert calls == [([first, second], False)]


def test_cli_defaults_to_current_directory(monkeypatch, tmp_path: Path) -> None:
    calls = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("mokioclaw.dashboard.launcher.launch_dashboard", lambda paths, open_browser: calls.append((paths, open_browser)))
    result = CliRunner().invoke(app, ["dashboard"])
    assert result.exit_code == 0, result.output
    assert calls == [([tmp_path], True)]


def test_invalid_path_never_creates_server_or_browser(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("uvicorn.Server", lambda *args, **kwargs: pytest.fail("Server created"))
    monkeypatch.setattr("webbrowser.open", lambda *args, **kwargs: pytest.fail("Browser opened"))
    with pytest.raises(CatalogRegistrationError):
        launch_dashboard([tmp_path / "missing"])


def test_cli_invalid_path_reports_safe_error(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("uvicorn.Server", lambda *args, **kwargs: pytest.fail("Server created"))
    missing = tmp_path / "private-location"
    result = CliRunner().invoke(app, ["dashboard", "--repo", str(missing), "--no-browser"])
    assert result.exit_code == 2
    assert "Cannot open 1 repository path" in result.output
    assert str(missing) not in result.output


def test_cli_missing_git_executable_reports_actionable_safe_error(monkeypatch, temp_git_repo: Path) -> None:
    monkeypatch.setattr("uvicorn.Server", lambda *args, **kwargs: pytest.fail("Server created"))
    monkeypatch.setattr("mokioclaw.dashboard.launcher.LocalGitReader", lambda: LocalGitReader("mokioclaw-git-does-not-exist"))
    result = CliRunner().invoke(app, ["dashboard", "--repo", str(temp_git_repo), "--no-browser"])
    assert result.exit_code == 2
    assert "Git executable is unavailable" in result.output
    assert str(temp_git_repo) not in result.output


def test_server_binds_loopback_and_opens_browser_after_ready(monkeypatch, temp_git_repo: Path) -> None:
    events = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            events.append("socket_closed")

        def setsockopt(self, *args):
            pass

        def bind(self, address):
            events.append(("bind", address[0]))

        def listen(self, *args):
            pass

        def getsockname(self):
            return ("127.0.0.1", 48123)

    class FakeServer:
        def __init__(self, config):
            assert config.host == "127.0.0.1"
            assert config.access_log is False
            self.started = False
            self.should_exit = False

        def run(self, *, sockets):
            assert len(sockets) == 1
            events.append("ready")
            self.started = True
            while not self.should_exit:
                import time

                time.sleep(0.001)

    monkeypatch.setattr("socket.socket", lambda *args, **kwargs: FakeSocket())
    monkeypatch.setattr("uvicorn.Server", FakeServer)

    def browser(url):
        assert url == "http://127.0.0.1:48123/"
        assert "ready" in events
        events.append("browser")
        raise KeyboardInterrupt

    monkeypatch.setattr("webbrowser.open", browser)
    launch_dashboard([temp_git_repo])
    assert events == [("bind", "127.0.0.1"), "ready", "browser", "socket_closed"]


def test_real_loopback_health_and_shutdown(monkeypatch, temp_git_repo: Path) -> None:
    def browser(url: str) -> None:
        with urlopen(url + "health", timeout=3) as response:
            assert response.read() == b'{"status":"ok"}'
        raise KeyboardInterrupt

    monkeypatch.setattr("webbrowser.open", browser)
    launch_dashboard([temp_git_repo])
    assert not any(thread.name == "mokioclaw-dashboard" for thread in live_threads())


def test_two_repository_live_demo_reads_without_mutating_sources(monkeypatch, temp_git_repo: Path, tmp_path: Path) -> None:
    for number in range(52):
        (temp_git_repo / "sample.txt").write_text(f"ordinary {number}\n", encoding="utf-8")
        _git(temp_git_repo, "add", "sample.txt")
        _git(temp_git_repo, "commit", "-q", "-m", f"ordinary {number}")
    second = tmp_path / "second"
    _git(temp_git_repo, "clone", "-q", str(temp_git_repo), str(second))
    _git(second, "config", "user.name", "Fixture User")
    _git(second, "config", "user.email", "fixture@example.invalid")
    (second / "auth").mkdir()
    (second / "auth" / "policy.txt").write_text("fixture\n", encoding="utf-8")
    _git(second, "add", "auth/policy.txt")
    _git(second, "commit", "-q", "-m", "sensitive path")
    sensitive_sha = _git(second, "rev-parse", "HEAD").decode().strip()
    _git(second, "checkout", "-q", "-b", "demo-side")
    (second / "side.txt").write_text("side\n", encoding="utf-8")
    _git(second, "add", "side.txt")
    _git(second, "commit", "-q", "-m", "side")
    _git(second, "checkout", "-q", "main")
    (second / "main.txt").write_text("main\n", encoding="utf-8")
    _git(second, "add", "main.txt")
    _git(second, "commit", "-q", "-m", "main")
    _git(second, "merge", "-q", "--no-ff", "-m", "merge example", "demo-side")
    merge_sha = _git(second, "rev-parse", "HEAD").decode().strip()
    for root in (temp_git_repo, second):
        ignored = root / "ignored-evidence"
        ignored.mkdir()
        (ignored / "keep.txt").write_text("preserve", encoding="utf-8")
        (root / ".git" / "info" / "exclude").write_text("ignored-evidence/\n", encoding="utf-8")
    before = [_snapshot(root) for root in (temp_git_repo, second)]
    monkeypatch.setattr("mokioclaw.cli.app.stream_agent_events", lambda *args, **kwargs: pytest.fail("Agent started"))
    monkeypatch.setattr("mokioclaw.providers.openai_provider.create_model", lambda *args, **kwargs: pytest.fail("Provider started"))

    def browser(url: str) -> None:
        with urlopen(url, timeout=3) as response:
            assert b"repository" in response.read().lower()
        with urlopen(url + "api/repositories", timeout=3) as response:
            repositories = json.load(response)
        assert len(repositories) == 2
        assert len({repository["id"] for repository in repositories}) == 2
        first, second_repo = repositories
        assert first["head_sha"] != second_repo["head_sha"]
        with urlopen(url + f"api/repositories/{first['id']}/commits", timeout=3) as response:
            page = json.load(response)
        assert len(page["commits"]) == 50
        assert page["next_cursor"]
        with urlopen(url + f"api/repositories/{first['id']}/commits?cursor={page['next_cursor']}", timeout=3) as response:
            remainder = json.load(response)
        assert len(remainder["commits"]) == 2
        assert remainder["anchor_sha"] == page["anchor_sha"]
        with urlopen(url + f"api/repositories/{second_repo['id']}/commits", timeout=3) as response:
            second_page = json.load(response)
        for repository, anchor, sha, priority in (
            (first, page["anchor_sha"], page["commits"][0]["sha"], "low"),
            (second_repo, second_page["anchor_sha"], sensitive_sha, "high"),
            (second_repo, second_page["anchor_sha"], merge_sha, "manual_review"),
        ):
            with urlopen(
                url + f"api/repositories/{repository['id']}/commits/{sha}?anchor={anchor}", timeout=3,
            ) as response:
                detail = json.load(response)
            assert detail["assessment"]["priority"] == priority
        raise KeyboardInterrupt

    monkeypatch.setattr("webbrowser.open", browser)
    launch_dashboard([temp_git_repo, second])
    assert [_snapshot(root) for root in (temp_git_repo, second)] == before
    assert not any(thread.name == "mokioclaw-dashboard" for thread in live_threads())
