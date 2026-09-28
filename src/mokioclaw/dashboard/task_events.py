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
    "verification": {"status": frozenset({"passed", "failed", "not_run"})},
    "patch": {"status": frozenset({"available", "patch_unavailable"})},
}
_OPTIONAL_INTEGERS = {
    "preparation": ("file_count",),
    "verification": ("exit_code", "duration_ms"),
    "patch": ("changed_files", "added_lines", "deleted_lines"),
}
_OPAQUE_ID = re.compile(r"[A-Za-z0-9_-]{16,64}\Z")


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
    if kind == "approval_request":
        request_id = raw.get("request_id")
        if type(request_id) is not str or not _OPAQUE_ID.fullmatch(request_id):
            raise TaskEventRejected("Invalid approval identity")
        data["request_id"] = request_id
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return PublicTaskEvent(task_id, attempt_id, sequence, timestamp, kind, data)
