from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from mokioclaw.cli.app import app


def test_cli_passes_opt_in_task_root_without_enabling_agent(monkeypatch, tmp_path: Path) -> None:
    calls = []
    monkeypatch.setattr("mokioclaw.dashboard.launcher.launch_dashboard", lambda paths, **kwargs: calls.append((paths, kwargs)))
    root = tmp_path / "tasks"
    result = CliRunner().invoke(app, ["dashboard", "--repo", str(tmp_path), "--task-root", str(root), "--no-browser"])
    assert result.exit_code == 0, result.output
    assert calls == [([tmp_path], {"open_browser": False, "task_root": root})]
