"""Task worker with an authenticated local channel and projected public events."""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Iterator, Mapping

from mokioclaw.dashboard.task_worker_control import ProcessIdentity
from mokioclaw.dashboard.task_events import project_task_event, summarize_agent_event
from mokioclaw.dashboard.task_executor import TaskExecutionError
from mokioclaw.providers.openai_provider import ProviderSettings
from mokioclaw.providers.openai_provider import TaskProviderError


# Two separately bounded 12,000-character command streams can expand sixfold
# when JSON escapes control characters; keep the complete approved result.
_MAX_MESSAGE = 262144


def run_projected_workflow(
    description: str,
    workspace: Path,
    context,
    emit: Callable[[dict], None],
    *,
    stream: Callable[..., Iterator[dict]] | None = None,
    max_attempts: int | None = None,
) -> None:
    """Keep raw workflow events inside the worker; emit only fixed summaries."""
    if stream is None:
        from mokioclaw.core.agent import stream_agent_events

        stream = stream_agent_events
    final_events: list[dict] = []
    kwargs = {"workspace": workspace, "task_context": context}
    if max_attempts is not None:
        kwargs["max_attempts"] = max_attempts
    try:
        for raw in stream(description, **kwargs):
            for summary in summarize_agent_event(raw, tuple(getattr(context, "fixed_verification_commands", ()))):
                projected = {"attempt_id": context.current_attempt, **summary}
                if summary == {"kind": "stage", "phase": "complete"}:
                    final_events.append(projected)
                else:
                    emit(projected)
    finally:
        snapshot = getattr(context, "usage_snapshot", None)
        if callable(snapshot):
            emit({"attempt_id": context.current_attempt, "kind": "budget_usage", **snapshot()})
    if getattr(context, "usage_unavailable", False):
        raise TaskProviderError("usage_unavailable")
    for event in final_events:
        emit(event)


def _run_real_task(
    start: dict,
    emit: Callable[[dict], None],
    gateway,
    *,
    workspace: Path | None = None,
    context_factory: Callable[..., object] | None = None,
    stream: Callable[..., Iterator[dict]] | None = None,
) -> None:
    """Build an explicit Web Task context; construction itself makes no provider call."""
    from mokioclaw.core.agent import TaskRunContext
    from mokioclaw.dashboard.task_filesystem import TaskFilesystem
    from mokioclaw.dashboard.task_graph import build_task_graph_tools

    payload = start.get("payload")
    task_id = start.get("task_id")
    work = Path.cwd() if workspace is None else Path(workspace)
    if (not isinstance(payload, dict) or not isinstance(task_id, str)
            or work.name != "work" or work.parent.name != "workspace"
            or work.parents[1].name != task_id or not work.is_dir() or work.is_symlink()
            or not getattr(gateway, "task_gateway", False)):
        raise ValueError("task_worker_config_invalid")
    required = {
        "description", "source_read_scope", "source_write_scope", "task_scratch_scope",
        "max_attempts", "max_provider_calls", "max_total_tokens",
        "max_output_tokens_per_call", "verification_commands",
    }
    if payload.keys() != required:
        raise ValueError("task_worker_config_invalid")
    description = payload["description"]
    read_scope, write_scope = payload["source_read_scope"], payload["source_write_scope"]
    commands = payload["verification_commands"]
    budgets = {name: payload[name] for name in (
        "max_provider_calls", "max_total_tokens", "max_output_tokens_per_call",
    )}
    if (not isinstance(description, str) or not 0 < len(description) <= 4000
            or not isinstance(read_scope, list) or not isinstance(write_scope, list)
            or not all(isinstance(value, str) for value in read_scope + write_scope)
            or not isinstance(commands, list) or len(commands) > 10
            or not all(isinstance(value, str) and 0 < len(value) <= 2000 for value in commands)
            or type(payload["max_attempts"]) is not int or not 1 <= payload["max_attempts"] <= 3
            or any(type(value) is not int for value in budgets.values())):
        raise ValueError("task_worker_config_invalid")
    prepared = SimpleNamespace(task_id=task_id, root=work.parents[1], baseline=work.parent / "baseline", work=work)
    filesystem = TaskFilesystem(
        prepared, tuple(read_scope), tuple(write_scope), payload["task_scratch_scope"],
    )
    settings = ProviderSettings.from_environment()
    factory = context_factory or TaskRunContext.from_settings
    context = factory(settings, **budgets)
    context.attach_tools(
        filesystem, build_task_graph_tools(filesystem, gateway, work),
        gateway=gateway, verification_commands=tuple(commands),
    )
    run_projected_workflow(
        description, work, context, emit, stream=stream, max_attempts=payload["max_attempts"],
    )


def filtered_worker_environment(
    source: Mapping[str, str] | None = None,
    *,
    provider_settings: ProviderSettings | None = None,
) -> dict[str, str]:
    source = os.environ if source is None else source
    allowed = ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "LANG")
    environment = {name: source[name] for name in allowed if name in source}
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if provider_settings is not None:
        environment.update({
            "MOKIO_TASK_API_KEY": provider_settings.api_key,
            "MOKIO_TASK_MODEL": provider_settings.model,
            "MOKIO_TASK_BASE_URL": provider_settings.base_url,
        })
    return environment


def _send(sock: socket.socket, value: dict) -> None:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(payload) > _MAX_MESSAGE:
        raise ValueError("Worker message too large")
    sock.sendall(payload)


def _receive(sock: socket.socket) -> dict:
    data = bytearray()
    while len(data) < _MAX_MESSAGE:
        chunk = sock.recv(1)
        if not chunk:
            raise ConnectionError("Worker channel closed")
        if chunk == b"\n":
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError("Invalid worker message")
            return value
        data.extend(chunk)
    raise ValueError("Worker message too large")


def consume_worker_messages(
    channel: socket.socket,
    task_id: str,
    on_event: Callable[[dict], None],
    on_done: Callable[[dict], None],
    *,
    on_command: Callable[[dict], dict] | None = None,
    on_attempt: Callable[[int, int], None] | None = None,
) -> None:
    """Accept only projected event summaries and fixed completion categories."""
    while True:
        message = _receive(channel)
        if message.get("kind") == "event":
            summary = message.get("summary")
            if not isinstance(summary, dict):
                raise ValueError("Invalid worker event")
            attempt = summary.get("attempt_id")
            if type(attempt) is not int or not 1 <= attempt <= 3:
                raise ValueError("Invalid worker attempt")
            event = project_task_event(summary, task_id, attempt, 1)
            on_event({"attempt_id": attempt, "kind": event.kind, **event.data})
            continue
        if message.get("kind") == "command_request":
            attempt = message.get("attempt_id")
            command = message.get("command")
            timeout = message.get("timeout_seconds")
            output_limit = message.get("max_output_chars")
            if (on_command is None or type(attempt) is not int or not 1 <= attempt <= 3
                    or type(command) is not str or not command.strip() or "\0" in command
                    or len(command.encode("utf-8")) > 8192
                    or type(timeout) is not int or not 1 <= timeout <= 600
                    or type(output_limit) is not int or not 1 <= output_limit <= 12000):
                raise ValueError("Invalid worker command request")
            result = on_command({
                "attempt_id": attempt, "command": command, "timeout_seconds": timeout,
                "max_output_chars": output_limit,
            })
            if not isinstance(result, dict):
                raise ValueError("Invalid task command result")
            _send(channel, {"kind": "command_result", "result": result})
            continue
        if message.get("kind") == "attempt_advance":
            previous, next_attempt = message.get("previous"), message.get("next_attempt")
            if (on_attempt is None or type(previous) is not int or type(next_attempt) is not int
                    or not 1 <= previous < 3 or next_attempt != previous + 1):
                raise ValueError("Invalid task attempt request")
            on_attempt(previous, next_attempt)
            _send(channel, {"kind": "attempt_ack", "attempt_id": next_attempt})
            continue
        if message.get("kind") == "done":
            outcome = message.get("outcome")
            if outcome not in {"completed", "failed", "timed_out"}:
                raise ValueError("Invalid worker outcome")
            result = {"outcome": outcome}
            if outcome != "completed":
                failure = message.get("failure_kind")
                if failure not in {
                    "worker_failed", "provider_failed", "usage_unavailable", "task_tool_failed",
                    "provider_budget_exhausted", "provider_auth_failed", "provider_rate_limited",
                    "provider_invalid_request", "provider_transport_failed", "provider_server_failed",
                    "verification_command_failed", "timed_out",
                }:
                    raise ValueError("Invalid worker failure")
                result["failure_kind"] = failure
            on_done(result)
            return
        raise ValueError("Unsupported worker message")


class RemoteTaskGateway:
    """Worker-side proxy; the parent owns policy, approval and Docker execution."""

    task_gateway = True
    approval_mode = "task"
    shell_platform = "linux"

    def __init__(self, channel: socket.socket, task_id: str, workspace: Path) -> None:
        self.channel = channel
        self.task_id = task_id
        self.workspace = Path(workspace).resolve(strict=False)
        self.attempt_id = 1

    def run(self, *, workspace: Path, command: str, timeout_seconds: int, max_output_chars: int) -> dict:
        if Path(workspace).resolve(strict=False) != self.workspace:
            return {"ok": False, "error": "task_workspace_mismatch"}
        try:
            command_bytes = command.encode("utf-8", errors="strict")
        except UnicodeError:
            return {"ok": False, "error": "invalid_task_command"}
        # Mirror the parent-side gateway limits here so a model-supplied argument
        # cannot crash the whole task against the command message validation.
        if (type(command) is not str or not command.strip() or "\x00" in command
                or len(command_bytes) > 8192
                or type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 600
                or type(max_output_chars) is not int or not 1 <= max_output_chars <= 12000):
            return {"ok": False, "error": "invalid_task_command"}
        _send(self.channel, {
            "kind": "command_request", "attempt_id": self.attempt_id, "command": command,
            "timeout_seconds": timeout_seconds, "max_output_chars": max_output_chars,
        })
        response = _receive(self.channel)
        if response.get("kind") != "command_result" or not isinstance(response.get("result"), dict):
            raise TaskExecutionError("task_command_channel_failed")
        return response["result"]

    def set_attempt(self, next_attempt: int) -> None:
        if next_attempt != self.attempt_id + 1:
            raise TaskExecutionError("task_attempt_invalid")
        _send(self.channel, {
            "kind": "attempt_advance", "previous": self.attempt_id, "next_attempt": next_attempt,
        })
        if _receive(self.channel) != {"kind": "attempt_ack", "attempt_id": next_attempt}:
            raise TaskExecutionError("task_attempt_invalid")
        self.attempt_id = next_attempt


def _creation_identity(pid: int) -> str | None:
    """Return an OS process birth identity, empty for gone, None if unverifiable."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = (
            wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
        )
        kernel.GetProcessTimes.restype = wintypes.BOOL
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return "" if ctypes.get_last_error() == 87 else None
        try:
            exit_code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return None
            if exit_code.value != 259:  # STILL_ACTIVE
                return ""
            created = wintypes.FILETIME()
            exited, kernel_time, user_time = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
            if not kernel.GetProcessTimes(handle, created, exited, kernel_time, user_time):
                return None
            return str((created.dwHighDateTime << 32) | created.dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    if sys.platform.startswith("linux"):
        try:
            content = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        except FileNotFoundError:
            return ""
        except OSError:
            return None
        return content.rsplit(") ", 1)[1].split()[19]
    return None


class TaskWorkerLauncher:
    """Launch an inert worker with only local JSON control and exact PID identity."""

    def __init__(
        self, provider_settings: ProviderSettings | None = None,
        start_payload: Callable[[str], dict] | None = None,
    ) -> None:
        self._workers: dict[int, tuple[subprocess.Popen, socket.socket, str, str]] = {}
        self._provider_settings = provider_settings
        self._start_payload = start_payload

    def launch(self, task_id: str, work: Path) -> ProcessIdentity:
        if not work.is_dir() or work.is_symlink():
            raise ValueError("Task work is unavailable")
        token = secrets.token_urlsafe(32)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(5)
        process: subprocess.Popen | None = None
        try:
            process = subprocess.Popen(
                [sys.executable, "-P", "-B", "-m", "mokioclaw.dashboard.task_worker", str(listener.getsockname()[1])],
                cwd=work, env=filtered_worker_environment(provider_settings=self._provider_settings),
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            assert process.stdin is not None
            process.stdin.write((token + "\n").encode("ascii"))
            process.stdin.close()
            channel, address = listener.accept()
            channel.settimeout(5)
            hello = _receive(channel)
            if address[0] != "127.0.0.1" or hello != {"kind": "hello", "token": token}:
                raise ValueError("Worker authentication failed")
            _send(channel, {"kind": "ready"})
            created = _creation_identity(process.pid)
            if not created:
                raise ValueError("Worker process identity unavailable")
            self._workers[process.pid] = (process, channel, created, task_id)
            return ProcessIdentity(process.pid, created)
        except Exception:
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            raise
        finally:
            listener.close()

    def activate(self, identity: ProcessIdentity) -> None:
        worker = self._workers.get(identity.pid)
        if worker is None or worker[2] != identity.created_at or _creation_identity(identity.pid) != identity.created_at:
            raise ValueError("Worker identity changed")
        channel = worker[1]
        start = {"kind": "start", "task_id": worker[3]}
        if self._start_payload is not None:
            start["payload"] = self._start_payload(worker[3])
        _send(channel, start)
        if _receive(channel) != {"kind": "started"}:
            raise ValueError("Worker did not acknowledge start")

    def follow(
        self, identity: ProcessIdentity,
        on_event: Callable[[dict], None],
        on_done: Callable[[dict], None],
        *,
        on_command: Callable[[dict], dict] | None = None,
        on_attempt: Callable[[int, int], None] | None = None,
    ) -> None:
        worker = self._workers.get(identity.pid)
        if worker is None or worker[2] != identity.created_at or _creation_identity(identity.pid) != identity.created_at:
            raise ValueError("Worker identity changed")
        channel = worker[1]
        channel.settimeout(None)
        consume_worker_messages(
            channel, worker[3], on_event, on_done,
            on_command=on_command, on_attempt=on_attempt,
        )

    def exited(self, identity: ProcessIdentity) -> bool:
        observed = _creation_identity(identity.pid)
        return observed is not None and observed != identity.created_at

    def stop(self, identity: ProcessIdentity) -> bool:
        observed = _creation_identity(identity.pid)
        if observed == "":
            self._workers.pop(identity.pid, None)
            return True
        if observed is None or observed != identity.created_at:
            return False
        worker = self._workers.get(identity.pid)
        if worker is not None and worker[2] == identity.created_at:
            process, channel, _, _ = worker
            try:
                _send(channel, {"kind": "stop"})
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired, ConnectionError):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            finally:
                channel.close()
                self._workers.pop(identity.pid, None)
            return self.exited(identity)
        return self._stop_recorded_process(identity)

    def _stop_recorded_process(self, identity: ProcessIdentity) -> bool:
        if os.name != "nt":
            return False  # Restart cleanup requires an OS handle with exact identity.
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        handle = kernel.OpenProcess(0x1001, False, identity.pid)
        if not handle:
            return False
        try:
            # Verify birth on this exact handle; do not kill a reused PID.
            created = wintypes.FILETIME()
            other = [wintypes.FILETIME() for _ in range(3)]
            kernel.GetProcessTimes.argtypes = (
                wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
            )
            if not kernel.GetProcessTimes(handle, created, *other):
                return False
            observed = str((created.dwHighDateTime << 32) | created.dwLowDateTime)
            if observed != identity.created_at:
                return False
            return bool(kernel.TerminateProcess(handle, 1))
        finally:
            kernel.CloseHandle(handle)


def _worker_main(
    port: int, *, token_line: str | None = None,
    run_task: Callable[[dict, Callable[[dict], None], RemoteTaskGateway], None] | None = None,
) -> None:
    token = (sys.stdin.readline() if token_line is None else token_line).strip()
    if len(token) < 32 or len(token) > 128:
        return
    with socket.create_connection(("127.0.0.1", port), timeout=5) as channel:
        channel.settimeout(5)
        _send(channel, {"kind": "hello", "token": token})
        if _receive(channel) != {"kind": "ready"}:
            return
        first = _receive(channel)
        if first.get("kind") != "start" or not isinstance(first.get("task_id"), str):
            return
        _send(channel, {"kind": "started"})
        channel.settimeout(None)
        selected_runner = run_task or (_run_real_task if "payload" in first else None)
        if selected_runner is not None:
            def send_summary(summary: dict) -> None:
                attempt = summary.get("attempt_id")
                if type(attempt) is not int or not 1 <= attempt <= 3:
                    raise ValueError("Invalid task attempt")
                event = project_task_event(summary, first["task_id"], attempt, 1)
                _send(channel, {"kind": "event", "summary": {
                    "attempt_id": attempt, "kind": event.kind, **event.data,
                }})

            try:
                gateway = RemoteTaskGateway(channel, first["task_id"], Path.cwd())
                selected_runner(first, send_summary, gateway)
            except TaskProviderError as exc:
                kind = str(exc)
                if kind not in {
                    "usage_unavailable", "provider_budget_exhausted", "provider_auth_failed",
                    "provider_rate_limited", "provider_invalid_request", "provider_transport_failed",
                    "provider_server_failed",
                }:
                    kind = "provider_failed"
                _send(channel, {"kind": "done", "outcome": "failed", "failure_kind": kind})
            except TaskExecutionError as exc:
                kind = "verification_command_failed" if str(exc) == "verification_command_failed" else "task_tool_failed"
                _send(channel, {"kind": "done", "outcome": "failed", "failure_kind": kind})
            except Exception:
                _send(channel, {"kind": "done", "outcome": "failed", "failure_kind": "worker_failed"})
            else:
                _send(channel, {"kind": "done", "outcome": "completed"})
            return
        while True:
            message = _receive(channel)
            if message == {"kind": "stop"}:
                return
            # No Agent or command capability exists in the Task 7 worker.
            return


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1].isdigit():
        _worker_main(int(sys.argv[1]))
