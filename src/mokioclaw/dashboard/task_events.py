"""Project private worker messages into small, enumerated public task events."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from mokioclaw.dashboard.task_models import PublicTaskEvent


class TaskEventRejected(ValueError):
    """An event cannot be safely identified or displayed."""


_VALUES = {
    "state": {"state": frozenset({
        "draft", "preparing", "prepared", "running", "awaiting_approval", "verifying", "stopping",
        "cancelling", "completed", "failed", "cancelled", "timed_out", "interrupted", "cleanup_failed",
    })},
    "preparation": {"phase": frozenset({"enumerating", "copying", "ready"})},
    "stage": {"phase": frozenset({"entry", "planner", "code_agent", "verifier", "complete"})},
    "approval_request": {"status": frozenset({"waiting"})},
    "approval_decision": {"decision": frozenset({"approved", "denied", "expired"})},
    "tool_result": {"status": frozenset({"passed", "failed", "denied", "timed_out"})},
    "tool_failure": {
        "tool": frozenset({
            "TodoWriteTool", "CallCodeAgentTool", "CallSearchAgentTool", "TodoUpdateTool",
            "BashTool", "FileReadTool", "FileWriteTool", "FileEditTool", "GrepTool",
            "NotepadReadTool", "NotepadAppendTool", "unknown",
        }),
        "category": frozenset({
            "invalid_arguments", "scope_denied", "approval_denied_or_expired",
            "tool_rejected", "tool_exception", "unknown",
        }),
    },
    "verification": {"status": frozenset({"passed", "failed", "not_run"})},
    "patch": {"status": frozenset({"available", "patch_unavailable"})},
    "budget_usage": {},
}
_OPTIONAL_INTEGERS = {
    "preparation": ("file_count",),
    "verification": ("exit_code", "duration_ms", "command_index"),
    "patch": ("changed_files", "added_lines", "deleted_lines"),
}
_OPAQUE_ID = re.compile(r"[A-Za-z0-9_-]{16,64}\Z")
_BUDGET_STAGES = ("entry", "chat", "planner", "code_agent", "verifier", "context_compressor")


def task_tool_failure_event(node: str, name: object, *, error: object = None,
                            invalid_arguments: bool = False, exception: bool = False) -> dict[str, str]:
    """Create a fixed diagnostic without copying model input or tool error text."""
    tool = name if type(name) is str and name in _VALUES["tool_failure"]["tool"] else "unknown"
    if tool == "unknown":
        category = "unknown"
    elif invalid_arguments:
        category = "invalid_arguments"
    elif exception:
        category = "tool_exception"
    elif error == "task_file_access_denied":
        category = "scope_denied"
    elif error == "approval_denied_or_expired":
        category = "approval_denied_or_expired"
    else:
        category = "tool_rejected"
    return {"type": "task_tool_failure", "node": node, "name": tool,
            "failure_category": category}


def summarize_agent_event(raw: dict, fixed_commands: tuple[str, ...] = ()) -> tuple[dict, ...]:
    """Drop raw graph fields before crossing the worker's public event boundary."""
    if not isinstance(raw, dict):
        return ()
    if raw.get("type") == "graph_event":
        update = raw.get("event")
        if not isinstance(update, dict) or len(update) != 1:
            return ()
        node = next(iter(update))
        phase = {
            "intent_router": "entry", "planner": "planner", "verifier": "verifier",
            "final": "complete",
        }.get(node)
        return ({"kind": "stage", "phase": phase},) if phase else ()
    if raw.get("type") != "custom_event":
        return ()
    event = raw.get("event")
    if not isinstance(event, dict):
        return ()
    if event.get("type") == "handoff" and event.get("to") == "codeAgent":
        return ({"kind": "stage", "phase": "code_agent"},)
    if event.get("type") == "task_tool_failure":
        if event.get("node") not in {"planner", "codeAgent", "verifier"}:
            return ()
        name = event.get("name")
        category = event.get("failure_category")
        tool = name if type(name) is str and name in _VALUES["tool_failure"]["tool"] else "unknown"
        safe_category = (category if type(category) is str
                         and category in _VALUES["tool_failure"]["category"] else "unknown")
        return ({"kind": "tool_failure", "tool": tool, "category": safe_category},)
    if event.get("type") != "tool_result":
        return ()
    result = event.get("result")
    if not isinstance(result, dict):
        return ()
    exit_code = result.get("exit_code")
    is_exit = type(exit_code) is int and -1_000_000 <= exit_code <= 1_000_000_000
    if event.get("node") == "verifier" and event.get("name") == "BashTool":
        if fixed_commands:
            command = result.get("command")
            command_index = result.get("command_index")
            request_id = result.get("command_request_id")
            if (type(command) is not str or type(command_index) is not int
                    or not 0 <= command_index < len(fixed_commands)
                    or fixed_commands[command_index] != command
                    or type(request_id) is not str or not _OPAQUE_ID.fullmatch(request_id)):
                return ()
        status = "passed" if is_exit and exit_code == 0 and result.get("ok") is True else (
            "failed" if is_exit else "not_run"
        )
        summary: dict[str, str | int] = {"kind": "verification", "status": status}
        if is_exit:
            summary["exit_code"] = exit_code
        duration = result.get("duration_ms")
        if type(duration) is int and 0 <= duration <= 1_000_000_000:
            summary["duration_ms"] = duration
        if fixed_commands:
            summary["command_index"] = command_index
            summary["request_id"] = request_id
            summary["output_truncated"] = result.get("output_truncated") is True
        return (summary,)
    if result.get("ok") is True:
        status = "passed"
    elif result.get("error") == "approval_denied_or_expired":
        status = "denied"
    elif result.get("timed_out") is True:
        status = "timed_out"
    else:
        status = "failed"
    return ({"kind": "tool_result", "status": status},)


def project_task_event(raw: dict, task_id: str, attempt_id: int | None, sequence: int) -> PublicTaskEvent:
    if not isinstance(raw, dict) or not _OPAQUE_ID.fullmatch(task_id) or type(sequence) is not int or sequence < 1:
        raise TaskEventRejected("Invalid event identity")
    if raw.get("task_id", task_id) != task_id or raw.get("attempt_id", attempt_id) != attempt_id:
        raise TaskEventRejected("Event belongs to another task or attempt")
    if raw.get("sequence", sequence) != sequence:
        raise TaskEventRejected("Event sequence changed")
    kind = raw.get("kind")
    schema = _VALUES.get(kind)
    if schema is None:
        raise TaskEventRejected("Unsupported event kind")
    data: dict[str, str | int | bool | None] = {}
    for key, permitted in schema.items():
        value = raw.get(key)
        if type(value) is not str or value not in permitted:
            raise TaskEventRejected("Unsupported event value")
        data[key] = value
    for key in _OPTIONAL_INTEGERS.get(kind, ()):
        value = raw.get(key)
        if value is not None:
            if type(value) is not int or not -1_000_000 <= value <= 1_000_000_000:
                raise TaskEventRejected("Unsupported event number")
            data[key] = value
    if kind == "budget_usage":
        call_count = 0
        for stage in _BUDGET_STAGES:
            calls_key, tokens_key = f"{stage}_calls", f"{stage}_reported_tokens"
            calls, tokens = raw.get(calls_key), raw.get(tokens_key)
            if (type(calls) is not int or not 0 <= calls <= 20
                    or type(tokens) is not int or not 0 <= tokens <= 1_000_000_000_000
                    or (calls == 0 and tokens != 0)):
                raise TaskEventRejected("Invalid budget usage")
            data[calls_key], data[tokens_key] = calls, tokens
            call_count += calls
        if call_count > 20:
            raise TaskEventRejected("Invalid budget usage")
    if kind == "verification":
        request_id = raw.get("request_id")
        if request_id is not None:
            if type(request_id) is not str or not _OPAQUE_ID.fullmatch(request_id):
                raise TaskEventRejected("Invalid verification request identity")
            data["request_id"] = request_id
        if ("command_index" in data) != ("request_id" in data):
            raise TaskEventRejected("Incomplete verification identity")
        if "command_index" in data and data["command_index"] < 0:
            raise TaskEventRejected("Invalid verification command index")
        if "output_truncated" in raw:
            if type(raw["output_truncated"]) is not bool:
                raise TaskEventRejected("Invalid verification truncation flag")
            data["output_truncated"] = raw["output_truncated"]
    if kind in {"approval_request", "approval_decision"} and (
        kind == "approval_request" or "request_id" in raw
    ):
        request_id = raw.get("request_id")
        if type(request_id) is not str or not _OPAQUE_ID.fullmatch(request_id):
            raise TaskEventRejected("Invalid approval identity")
        data["request_id"] = request_id
        if kind == "approval_request" and "execution_digest" in raw:
            digest = raw["execution_digest"]
            if type(digest) is not str or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise TaskEventRejected("Invalid execution digest")
            data["execution_digest"] = digest
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return PublicTaskEvent(task_id, attempt_id, sequence, timestamp, kind, data)
