from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired

import pytest

from mokioclaw.evals.sandbox import DockerCommandExecutor


def test_docker_executor_uses_offline_restricted_mount(monkeypatch, tmp_path: Path) -> None:
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return CompletedProcess(args, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr("mokioclaw.evals.sandbox.subprocess.run", fake_run)
    result = DockerCommandExecutor("mokioclaw-eval-python:3.13").run(
        workspace=tmp_path,
        command="python -m pytest -q",
        timeout_seconds=120,
        max_output_chars=6000,
    )

    args = calls[0][0]
    assert ["--network", "none"] == args[args.index("--network") : args.index("--network") + 2]
    assert "--cap-drop" in args and "ALL" in args
    assert "--read-only" in args
    assert f"type=bind,src={tmp_path.resolve()},dst=/workspace" in args
    assert all("API_KEY" not in str(item) for item in args)
    assert result["ok"] is True


def test_docker_executor_force_removes_container_after_timeout(monkeypatch, tmp_path: Path) -> None:
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[:2] == ["docker", "run"]:
            raise TimeoutExpired(args, 2, output="partial", stderr="late")
        return CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("mokioclaw.evals.sandbox.subprocess.run", fake_run)
    result = DockerCommandExecutor("mokioclaw-eval-python:3.13").run(
        workspace=tmp_path,
        command="python -c 'while True: pass'",
        timeout_seconds=2,
        max_output_chars=6000,
    )

    assert result["timed_out"] is True
    assert any(args[:3] == ["docker", "rm", "-f"] for args in calls)


def test_docker_executor_reports_immutable_image_id(monkeypatch) -> None:
    def fake_run(args, **kwargs):
        return CompletedProcess(args, 0, stdout="sha256:abc123\n", stderr="")

    monkeypatch.setattr("mokioclaw.evals.sandbox.subprocess.run", fake_run)

    assert DockerCommandExecutor("mokioclaw-eval-python:3.13").image_id() == "sha256:abc123"


@pytest.mark.docker
def test_docker_executor_cannot_reach_network_or_parent_directory(tmp_path: Path) -> None:
    (tmp_path / "visible.txt").write_text("visible", encoding="utf-8")
    executor = DockerCommandExecutor("mokioclaw-eval-python:3.13")

    files = executor.run(
        workspace=tmp_path,
        command='python -c "from pathlib import Path; print(Path(\'/workspace/visible.txt\').read_text()); print(Path(\'/data\').exists())"',
        timeout_seconds=20,
        max_output_chars=6000,
    )
    network = executor.run(
        workspace=tmp_path,
        command="python -c \"import socket; socket.create_connection(('1.1.1.1', 53), 1)\"",
        timeout_seconds=20,
        max_output_chars=6000,
    )

    assert files["ok"] is True
    assert files["stdout"].splitlines() == ["visible", "False"]
    assert network["ok"] is False
