from __future__ import annotations

from pathlib import Path

import pytest

from mokioclaw.core.state import RuntimeState
from mokioclaw.dashboard.task_executor import run_task_bash, run_task_verification
from mokioclaw.graph.architectures import _run_verification_command


class FakeTaskGateway:
    task_gateway = True
    shell_platform = "linux"

    def __init__(self):
        self.commands = []

    def run(self, **kwargs):
        self.commands.append(kwargs)
        return {"ok": True, "exit_code": 0}


def test_task_bash_routes_every_command_before_shortcuts_or_environment(tmp_path: Path) -> None:
    gateway = FakeTaskGateway()
    for command in ("pwd", "tail -1 private.txt", "unrecognized --opaque-command", "pip install thing"):
        assert run_task_bash(gateway, tmp_path, command, timeout_seconds=5)["ok"]
    assert [item["command"] for item in gateway.commands] == [
        "pwd", "tail -1 private.txt", "unrecognized --opaque-command", "pip install thing",
    ]
    assert not (tmp_path / ".mokioclaw" / "shims").exists()
    assert not run_task_bash(gateway, tmp_path, "echo hidden", run_in_background=True)["ok"]


def test_task_mode_without_gateway_fails_closed_for_bash_and_verifier(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        RuntimeState(workspace=tmp_path, approval_mode="task", command_executor=None)
    assert not run_task_bash(None, tmp_path, "echo should-not-run")["ok"]
    assert not run_task_verification(None, tmp_path, "echo should-not-run")["ok"]
    assert not (tmp_path / ".mokioclaw").exists()


def test_verifier_uses_same_task_gateway(tmp_path: Path) -> None:
    gateway = FakeTaskGateway()
    runtime = RuntimeState(workspace=tmp_path, approval_mode="deny", command_executor=gateway)
    result = _run_verification_command(runtime, "python -m pytest -q")
    assert result["ok"]
    assert gateway.commands[0]["command"] == "python -m pytest -q"
    assert run_task_verification(gateway, tmp_path, "python -m pytest -q")["ok"]
