from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4


class SandboxSetupError(RuntimeError):
    """Raised when the configured Docker image cannot be inspected or used."""


def _text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _truncate(value: bytes | str | None, max_output_chars: int) -> str:
    return _text(value)[:max_output_chars]


class DockerCommandExecutor:
    shell_platform = "linux"

    def __init__(self, image: str) -> None:
        self.image = image

    def run(
        self,
        *,
        workspace: Path,
        command: str,
        timeout_seconds: int,
        max_output_chars: int,
    ) -> dict[str, object]:
        container_name = f"mokioclaw-eval-{uuid4().hex[:12]}"
        uid = getattr(os, "getuid", lambda: 1000)()
        gid = getattr(os, "getgid", lambda: 1000)()
        arguments = [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "--network",
            "none",
            "--cpus",
            "1",
            "--memory",
            "512m",
            "--pids-limit",
            "128",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--user",
            f"{uid}:{gid}",
            "--mount",
            f"type=bind,src={workspace.resolve()},dst=/workspace",
            "--workdir",
            "/workspace",
            self.image,
            command,
        ]
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                arguments,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            return {
                "ok": False,
                "timed_out": True,
                "command": command,
                "exit_code": None,
                "stdout": _truncate(getattr(exc, "stdout", None), max_output_chars),
                "stderr": _truncate(getattr(exc, "stderr", None), max_output_chars),
                "duration_ms": round((time.perf_counter() - started) * 1000),
            }
        return {
            "ok": completed.returncode == 0,
            "timed_out": False,
            "command": command,
            "exit_code": completed.returncode,
            "stdout": _truncate(completed.stdout, max_output_chars),
            "stderr": _truncate(completed.stderr, max_output_chars),
            "duration_ms": round((time.perf_counter() - started) * 1000),
        }

    def image_id(self) -> str:
        completed = subprocess.run(
            ["docker", "image", "inspect", self.image, "--format", "{{.Id}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        image_id = completed.stdout.strip()
        if completed.returncode != 0 or not image_id:
            detail = completed.stderr.strip() or f"Docker image is unavailable: {self.image}"
            raise SandboxSetupError(detail)
        return image_id
