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


def test_cli_requires_explicit_image_and_task_root_for_agent_enablement(monkeypatch, tmp_path: Path) -> None:
    calls = []
    monkeypatch.setattr("mokioclaw.dashboard.launcher.launch_dashboard", lambda paths, **kwargs: calls.append((paths, kwargs)))
    root = tmp_path / "tasks"
    image = "sha256:" + "a" * 64
    for flags in (["--enable-agent"], ["--task-root", str(root), "--enable-agent"],
                  ["--task-image", image], ["--task-root", str(root), "--task-image", image]):
        result = CliRunner().invoke(app, ["dashboard", "--repo", str(tmp_path), *flags, "--no-browser"])
        assert result.exit_code != 0
    assert calls == []


def test_cli_passes_complete_explicit_agent_capability(monkeypatch, tmp_path: Path) -> None:
    calls = []
    monkeypatch.setattr("mokioclaw.dashboard.launcher.launch_dashboard", lambda paths, **kwargs: calls.append((paths, kwargs)))
    root = tmp_path / "tasks"
    image = "sha256:" + "a" * 64
    result = CliRunner().invoke(app, ["dashboard", "--repo", str(tmp_path),
                                      "--task-root", str(root), "--task-image", image,
                                      "--enable-agent", "--no-browser"])
    assert result.exit_code == 0, result.output
    assert calls == [([tmp_path], {"open_browser": False, "task_root": root,
                                   "task_image": image, "enable_agent": True})]


def test_launcher_installs_only_explicit_agent_capability(monkeypatch, tmp_path: Path) -> None:
    import pytest

    from mokioclaw.dashboard import launcher
    from mokioclaw.providers.openai_provider import ProviderSettings

    image = "sha256:" + "b" * 64
    settings = ProviderSettings("FAKE_SECRET", "fake-model", "https://task.invalid")
    calls = []

    class FakeService:
        def __init__(self, _catalog, _reader, root, *, fake_runner=None):
            calls.append(("service", root, fake_runner))

        def configure_agent(self, received_settings, received_image):
            calls.append(("configure", received_settings, received_image))

        def close(self):
            calls.append(("close",))

    def stop_before_server(*_args, **_kwargs):
        raise RuntimeError("APP_READY")

    monkeypatch.setattr(launcher.RepositoryCatalog, "from_paths", lambda *_args: object())
    monkeypatch.setattr(launcher, "TaskService", FakeService)
    monkeypatch.setattr(launcher, "create_dashboard_app", stop_before_server)
    monkeypatch.setattr(ProviderSettings, "from_environment", classmethod(lambda cls: settings))
    with pytest.raises(RuntimeError, match="APP_READY"):
        launcher.launch_dashboard([tmp_path], open_browser=False, task_root=tmp_path / "tasks",
                                  task_image=image, enable_agent=True)
    assert calls == [("service", tmp_path / "tasks", None), ("configure", settings, image), ("close",)]
