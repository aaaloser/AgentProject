"""Pure, task-only request accounting and complete-group history preparation.

Bytes here are a local canonical representation, not SDK wire bytes or tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections import OrderedDict
import hashlib
import json
import secrets
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage


@dataclass(frozen=True)
class TaskContextPolicy:
    hard: int = 98304
    trigger: int = 73728
    target: int = 49152
    envelope: int = 4096
    capsule: int = 8192
    tool_json: int = 16384
    body: int = 8192
    group_json: int = 32768
    result_bytes: int = 32 * 1024 * 1024
    result_count: int = 32


POLICY = TaskContextPolicy()
_CAPSULE_NAME = "task_context_index"
_REASONS = frozenset({"input_too_large", "invalid_message_group", "result_capacity", "unsupported_content"})


class TaskContextError(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason if reason in _REASONS else "unsupported_content"
        super().__init__("task_context_error")


@dataclass(frozen=True)
class RequestBinding:
    schemas: tuple[dict, ...]
    options: dict


@dataclass(frozen=True)
class MessageGroup:
    ai: AIMessage
    tools: tuple[ToolMessage, ...]
    sequence: int
    recoverable_failure: bool


@dataclass(frozen=True)
class ReadReceipt:
    path: str
    revision: str
    coverage_complete: bool
    eof_covered: bool
    receipt_id: str


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise TaskContextError("unsupported_content") from None


def _content(value: Any) -> str | list:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(
        isinstance(block, dict) and block.get("type") == "text"
        and isinstance(block.get("text"), str) and set(block) <= {"type", "text"}
        for block in value
    ):
        return value
    raise TaskContextError("unsupported_content")


def message_payload(message: Any) -> dict:
    if isinstance(message, dict):
        # Explicit dictionaries must already be provider-shaped; never stringify.
        if message.get("role") not in {"system", "user", "assistant", "tool"}:
            raise TaskContextError("unsupported_content")
        payload = dict(message)
        payload["content"] = _content(payload.get("content", ""))
        canonical_json(payload)
        return payload
    roles = {SystemMessage: "system", HumanMessage: "user", AIMessage: "assistant", ToolMessage: "tool"}
    if type(message) not in roles:
        raise TaskContextError("unsupported_content")
    payload = {"role": roles[type(message)], "content": _content(message.content)}
    for key in ("name", "id"):
        if getattr(message, key, None) is not None:
            payload[key] = getattr(message, key)
    if isinstance(message, AIMessage):
        if message.invalid_tool_calls:
            raise TaskContextError("invalid_message_group")
        payload["tool_calls"] = message.tool_calls
    if isinstance(message, ToolMessage):
        payload["tool_call_id"] = message.tool_call_id
    # Include SDK-facing extras rather than silently omitting uncounted fields.
    extras = message.additional_kwargs
    if set(extras) - {"tool_calls", "function_call", "refusal"}:
        raise TaskContextError("unsupported_content")
    if extras:
        payload["additional_kwargs"] = extras
    canonical_json(payload)
    return payload


def canonical_request_bytes(messages: list[Any], binding: RequestBinding, *,
                            invocation_options: dict | None = None) -> bytes:
    return canonical_json({"messages": [message_payload(message) for message in messages],
                           "schemas": binding.schemas, "binding_options": binding.options,
                           "invocation_options": invocation_options or {}})


def measure_request(messages: list[Any], binding: RequestBinding, *,
                    invocation_options: dict | None = None) -> int:
    return len(canonical_request_bytes(messages, binding, invocation_options=invocation_options)) + POLICY.envelope


def validate_groups(history: list[Any]) -> list[MessageGroup]:
    groups: list[MessageGroup] = []
    seen: set[str] = set()
    index = 0
    while index < len(history):
        ai = history[index]
        if not isinstance(ai, AIMessage) or ai.invalid_tool_calls:
            raise TaskContextError("invalid_message_group")
        message_payload(ai)
        ids = [call.get("id") for call in ai.tool_calls]
        if any(not isinstance(call_id, str) or not call_id for call_id in ids) or len(set(ids)) != len(ids):
            raise TaskContextError("invalid_message_group")
        if seen.intersection(ids):
            raise TaskContextError("invalid_message_group")
        seen.update(ids)
        tools = history[index + 1:index + 1 + len(ids)]
        if len(tools) != len(ids) or any(
            not isinstance(tool, ToolMessage) or tool.tool_call_id != call_id
            for tool, call_id in zip(tools, ids, strict=True)
        ):
            raise TaskContextError("invalid_message_group")
        failure = False
        for tool in tools:
            message_payload(tool)
            try:
                result = json.loads(tool.content)
                if not isinstance(result, dict):
                    raise ValueError
            except (TypeError, ValueError):
                raise TaskContextError("invalid_message_group") from None
            failure |= result.get("ok") is False or (type(result.get("exit_code")) is int and result["exit_code"] != 0)
        if not ids and index != len(history) - 1:
            raise TaskContextError("invalid_message_group")
        groups.append(MessageGroup(ai, tuple(tools), len(groups), failure))
        index += len(ids) + 1
    return groups


def _read_signature(group: MessageGroup) -> bytes | None:
    if not group.tools or any(call["name"] != "FileReadTool" for call in group.ai.tool_calls):
        return None
    entries = []
    for tool in group.tools:
        value = json.loads(tool.content)
        if value.get("ok") is not True or not value.get("path") or not value.get("revision"):
            return None
        entries.append({key: value.get(key) for key in
                        ("path", "revision", "start", "end", "start_line", "start_char", "end_line", "end_char")})
    return canonical_json(entries)


def _capsule(input_state: dict, removed: list[MessageGroup], old: dict) -> dict:
    allowed = {"task_id", "attempt_id", "todos", "read_receipts", "receipts", "omitted_paths"}
    state = {key: value for key, value in input_state.items() if key in allowed}
    # These metadata lists are local records, never derived from model prose.
    paths = list(old.get("omitted_paths", []))
    receipts = list(old.get("receipts", []))
    for group in removed:
        for tool in group.tools:
            value = json.loads(tool.content)
            if tool.name == "FileReadTool" and value.get("ok") is True and value.get("revision"):
                entry = {key: value.get(key) for key in ("path", "revision", "start", "end")}
                if entry not in paths:
                    paths.append(entry)
            receipt = {"tool": tool.name, "ok": value.get("ok") is True}
            for key in ("command_request_id", "exit_code", "receipt_id"):
                if key in value:
                    receipt[key] = value[key]
            receipts.append(receipt)
    count = old.get("deleted_groups", 0) + len(removed)
    state.update(history_compacted=count > 0, source_content_omitted=count > 0, deleted_groups=count,
                 omitted_paths=paths[-32:], omitted_path_count=old.get("omitted_path_count", 0) + max(0, len(paths) - 32),
                 receipts=receipts[-8:])
    if len(canonical_json(state)) > POLICY.capsule:
        raise TaskContextError("input_too_large")
    return state


def prepare_request(anchors: tuple[Any, ...], history: list[Any], capsule: dict, binding: RequestBinding, *,
                    invocation_options: dict | None = None, pending_response: AIMessage | None = None,
                    reserved_tool_bytes: int = 0) -> list[Any]:
    history = list(history)
    old: dict = {}
    if history[:len(anchors)] == list(anchors):
        history = history[len(anchors):]
    if history and isinstance(history[0], HumanMessage) and history[0].name == _CAPSULE_NAME:
        try:
            old = json.loads(history.pop(0).content)
        except (TypeError, ValueError):
            raise TaskContextError("invalid_message_group") from None
    groups = validate_groups(history)
    required = {g.sequence for g in groups[-2:]}
    failures = [g.sequence for g in groups if g.recoverable_failure]
    if failures:
        required.add(failures[-1])
    latest: dict[bytes, int] = {}
    for group in groups:
        signature = _read_signature(group)
        if signature is not None:
            latest[signature] = group.sequence
    kept, removed = [], []
    for group in groups:
        signature = _read_signature(group)
        duplicate = signature is not None and latest[signature] != group.sequence
        (removed if duplicate and group.sequence not in required else kept).append(group)

    def assemble() -> list[Any]:
        index_message = HumanMessage(content=canonical_json(_capsule(capsule, removed, old)).decode("utf-8"),
                                    name=_CAPSULE_NAME)
        return [*anchors, index_message, *(m for g in kept for m in (g.ai, *g.tools))]

    result = assemble()

    def pressure(messages: list[Any]) -> int:
        prospective = messages if pending_response is None else [*messages, pending_response]
        return measure_request(prospective, binding, invocation_options=invocation_options) + reserved_tool_bytes

    if pressure(result) >= POLICY.trigger:
        for group in list(kept):
            if group.sequence in required:
                continue
            kept.remove(group)
            removed.append(group)
            result = assemble()
            if pressure(result) <= POLICY.target:
                break
    if pressure(result) > POLICY.hard:
        raise TaskContextError("input_too_large")
    return result


def measure_baseline(anchors: tuple[Any, ...], minimal_capsule: dict, binding: RequestBinding) -> int:
    # Calibration must report even an infeasible baseline, before the runtime gate.
    return measure_request(baseline_messages(anchors, minimal_capsule), binding)


def baseline_messages(anchors: tuple[Any, ...], minimal_capsule: dict) -> list[Any]:
    return [*anchors, HumanMessage(content=canonical_json(_capsule(minimal_capsule, [], {})).decode("utf-8"),
                                  name=_CAPSULE_NAME)]


def request_binding(tools: list[Any], **options: Any) -> RequestBinding:
    from langchain_core.utils.function_calling import convert_to_openai_tool
    try:
        binding = RequestBinding(tuple(convert_to_openai_tool(tool) for tool in tools), options)
        canonical_json({"schemas": binding.schemas, "options": binding.options})
        return binding
    except TaskContextError:
        raise
    except Exception:
        raise TaskContextError("unsupported_content") from None


def assert_baseline_feasible(base: int, minimal_two_delta: int, common_two_delta: int, failure_delta: int) -> None:
    if not (base < POLICY.target and base + minimal_two_delta < POLICY.trigger
            and base + common_two_delta + failure_delta < POLICY.hard):
        raise TaskContextError("input_too_large")


class CoverageIncomplete(RuntimeError):
    def __init__(self) -> None:
        super().__init__("task_write_coverage_required")


class CoverageLedger:
    def __init__(self, max_files: int = 32, max_intervals_per_file: int = 128,
                 max_metadata_bytes: int = 262144) -> None:
        self.max_files = max_files
        self.max_intervals = max_intervals_per_file
        self.max_bytes = max_metadata_bytes
        self._entries: OrderedDict[str, dict] = OrderedDict()

    def intervals(self, path: str) -> tuple[tuple[int, int], ...]:
        return tuple(self._entries.get(path, {}).get("intervals", ()))

    def invalidate(self, path: str | None = None) -> None:
        if path is None:
            self._entries.clear()
        else:
            self._entries.pop(path, None)

    def _receipt(self, path: str, revision: str) -> ReadReceipt:
        entry = self._entries.get(path)
        valid = entry is not None and entry["revision"] == revision
        eof = entry["eof"] if valid else None
        ranges = entry["intervals"] if valid else []
        complete = eof is not None and ranges == [(0, eof)]
        eof_covered = eof is not None and any(end == eof for _, end in ranges)
        metadata = {"path": path, "revision": revision, "intervals": ranges, "eof": eof}
        return ReadReceipt(path, revision, complete, eof_covered, hashlib.sha256(canonical_json(metadata)).hexdigest())

    def record_visible(self, path: str, revision: str, start: int, end: int, *, eof: int | None) -> ReadReceipt:
        if type(start) is not int or type(end) is not int or start < 0 or end < start or (
            eof is not None and (type(eof) is not int or end > eof)
        ):
            raise TaskContextError("invalid_message_group")
        entry = self._entries.get(path)
        if entry is None or entry["revision"] != revision:
            self.invalidate(path)
            entry = {"revision": revision, "intervals": [], "eof": None}
        if eof is not None:
            if entry["eof"] is not None and entry["eof"] != eof:
                self.invalidate(path)
                raise TaskContextError("invalid_message_group")
            entry["eof"] = eof
        merged = []
        for left, right in sorted([*entry["intervals"], (start, end)]):
            if merged and left <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], right))
            else:
                merged.append((left, right))
        entry["intervals"] = merged
        self._entries[path] = entry
        while len(self._entries) > self.max_files:
            self._entries.popitem(last=False)
        if len(merged) > self.max_intervals or len(canonical_json(self._entries)) > self.max_bytes:
            self.invalidate(path)
        return self._receipt(path, revision)

    def require_complete(self, path: str, revision: str) -> ReadReceipt:
        receipt = self._receipt(path, revision)
        if not receipt.coverage_complete:
            raise CoverageIncomplete()
        return receipt


def recovery_for(error_code: str) -> dict | None:
    if error_code == "task_read_window_invalid":
        return {"retry_same_operation": True, "recovery": "correct_window"}
    if error_code in {"task_read_revision_changed", "task_write_coverage_required"}:
        return {"retry_same_operation": False, "recovery": "reread_current_revision"}
    if error_code == "result_unavailable":
        return {"retry_same_operation": False, "recovery": "rerun_source_tool_or_reread"}
    return None


def recovery_result(error_code: str) -> dict:
    recovery = recovery_for(error_code)
    if recovery is None:
        raise TaskContextError("unsupported_content")
    return {"ok": False, "error": error_code, **recovery}


@dataclass
class GroupPlan:
    response: AIMessage
    history: list[Any]
    calls: tuple[dict, ...]
    minimum: tuple[int, ...]
    remaining: int
    index: int = 0
    active: str | None = None


def tool_message_size(message: ToolMessage) -> int:
    return len(canonical_json(message_payload(message)))


class TaskContextSession:
    def __init__(self, services: TaskToolServices, attempt_id: int) -> None:
        from mokioclaw.dashboard.task_result_windows import ResultWindowStore
        self.services = services
        self.identity = (services.filesystem.prepared.task_id, attempt_id, secrets.token_urlsafe(24))
        self.coverage = CoverageLedger()
        self.results = ResultWindowStore(self.identity, max_bytes=services.policy.result_bytes,
                                         max_results=services.policy.result_count)
        self.closed = False
        self.anchors: tuple[Any, ...] = ()
        self.binding: RequestBinding | None = None
        self.group: GroupPlan | None = None
        self.invocation_options: dict = {}

    def _state(self, todos: list[dict]) -> dict:
        return {"task_id": self.identity[0], "attempt_id": self.identity[1], "todos": todos,
                "read_receipts": [self.coverage._receipt(path, entry["revision"]).__dict__
                                  for path, entry in self.coverage._entries.items()]}

    def set_request(self, anchors: tuple[Any, ...], binding: RequestBinding) -> None:
        if self.closed or measure_baseline(anchors, self._state([]), binding) >= self.services.policy.target:
            raise TaskContextError("input_too_large")
        self.anchors, self.binding = anchors, binding

    def prepare(self, history: list[Any], todos: list[dict], *, invocation_options: dict | None = None) -> list[Any]:
        if self.closed or self.binding is None:
            raise TaskContextError("invalid_message_group")
        self.invocation_options = invocation_options or {}
        if measure_request(baseline_messages(self.anchors, self._state([])), self.binding,
                           invocation_options=self.invocation_options) >= self.services.policy.target:
            raise TaskContextError("input_too_large")
        return prepare_request(self.anchors, history, self._state(todos), self.binding,
                               invocation_options=self.invocation_options)

    def _minimum_content(self, call: dict, todos: list[dict]) -> int:
        # Bounds for fixed registered feedback metadata plus a progress unit.
        # Source paths can occur twice; escaped paths/coordinates/64-byte hashes
        # are included. Grep reserves a whole (<=2000 codepoints) first record.
        name, args = call["name"], call["args"]
        path = args.get("file_path", args.get("path", ".mokioclaw/task-scratch/NOTEPAD.md"))
        path_bytes = len(canonical_json(path))
        if name in {"FileReadTool", "NotepadReadTool"}:
            return 1500 + 4 * path_bytes
        if name == "GrepTool":
            return 1200 + 4 * path_bytes + len(canonical_json(args.get("pattern", "")))
        if name in {"FileWriteTool", "FileEditTool"}:
            return 900 + 4 * path_bytes
        if name == "BashTool":
            return 1200
        if name == "ToolResultReadTool":
            return 1200 if self.results.cursor_kind(args.get("cursor")) == "records" else 700
        if name == "TodoUpdateTool":
            from mokioclaw.tools.todo_tool import update_todo
            return len(canonical_json(update_todo(todos, args.get("todo_id", ""), args.get("status", ""),
                                                 args.get("note", "")))) + 64
        if name == "NotepadAppendTool":
            return 800
        return len(canonical_json({"ok": False, "error": f"unknown tool: {name}"})) + 128

    def plan_group(self, response: AIMessage, history: list[Any], todos: list[dict]) -> GroupPlan:
        if type(response) is not AIMessage or response.invalid_tool_calls:
            raise TaskContextError("invalid_message_group")
        message_payload(response)
        calls = tuple(response.tool_calls)
        ids = [call.get("id") for call in calls]
        if not calls or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
            raise TaskContextError("invalid_message_group")
        prepared = self.prepare(history, todos)
        old_ids = {tool.tool_call_id for tool in prepared if isinstance(tool, ToolMessage)}
        if old_ids.intersection(ids):
            raise TaskContextError("invalid_message_group")
        minimum = tuple(2 * self._minimum_content(call, todos) + tool_message_size(
            ToolMessage(content="", name=call["name"], tool_call_id=call["id"])) for call in calls)
        if any(n > self.services.policy.tool_json for n in minimum) or sum(minimum) > self.services.policy.group_json:
            raise TaskContextError("input_too_large")
        prepared = prepare_request(self.anchors, prepared, self._state(todos), self.binding,
                                   invocation_options=self.invocation_options, pending_response=response,
                                   reserved_tool_bytes=sum(minimum) + len(calls))
        available = min(self.services.policy.group_json, self.services.policy.hard - measure_request(
            [*prepared, response], self.binding, invocation_options=self.invocation_options) - len(calls))
        if any(n > self.services.policy.tool_json for n in minimum) or sum(minimum) > available:
            raise TaskContextError("input_too_large")
        self.group = GroupPlan(response, prepared, calls, minimum, available)
        return self.group

    def start_call(self, call_id: str) -> None:
        group = self.group
        if group is None or group.active is not None or group.index >= len(group.calls) or (
            group.calls[group.index]["id"] != call_id
        ):
            raise TaskContextError("invalid_message_group")
        group.active = call_id

    def visible_budget(self, call_id: str) -> int:
        group = self.group
        if group is None or group.active != call_id:
            raise TaskContextError("invalid_message_group")
        return min(self.services.policy.tool_json, group.remaining - sum(group.minimum[group.index + 1:]))

    def finish_call(self, message: ToolMessage) -> None:
        group = self.group
        if group is None or message.tool_call_id != group.active:
            raise TaskContextError("invalid_message_group")
        if tool_message_size(message) > self.visible_budget(message.tool_call_id):
            raise TaskContextError("input_too_large")
        group.remaining -= tool_message_size(message)
        group.index += 1
        group.active = None

    def finish_group(self, history: list[Any], result_messages: list[ToolMessage]) -> list[Any]:
        group = self.group
        if group is None or group.index != len(group.calls) or group.active is not None:
            raise TaskContextError("invalid_message_group")
        validate_groups([group.response, *result_messages])
        result = [*group.history, group.response, *result_messages]
        if measure_request(result, self.binding, invocation_options=self.invocation_options) > self.services.policy.hard:
            raise TaskContextError("input_too_large")
        self.group = None
        return result

    def close(self) -> None:
        self.coverage.invalidate()
        self.results.clear()
        self.closed = True
        self.group = None
        self.anchors = ()
        self.binding = None


class TaskToolServices:
    def __init__(self, filesystem: Any, policy: TaskContextPolicy = POLICY) -> None:
        self.filesystem = filesystem
        self.policy = policy
        self.session: TaskContextSession | None = None
        self.terminal_recorder = None

    def record_terminal_root(self, kind: str) -> None:
        if self.terminal_recorder is not None:
            self.terminal_recorder(kind)

    def begin_delegation(self, attempt_id: int) -> TaskContextSession:
        if self.session is not None:
            raise TaskContextError("invalid_message_group")
        self.session = TaskContextSession(self, attempt_id)
        return self.session

    def close_delegation(self) -> None:
        try:
            if self.session is not None:
                self.session.close()
        finally:
            self.session = None

    def result_json_budget(self) -> int:
        if self.session is not None and self.session.group is not None:
            group = self.session.group
            call = group.calls[group.index]
            overhead = tool_message_size(ToolMessage(content="", name=call["name"], tool_call_id=call["id"]))
            # A JSON result is itself a string in ToolMessage. Worst-case
            # escaping doubles its canonical bytes; do not shrink after receipt.
            return (self.session.visible_budget(call["id"]) - overhead) // 2
        return self.policy.tool_json

    def invalidate(self, path: str | None = None) -> None:
        if self.session is not None:
            self.session.coverage.invalidate(path)

    def reserve_feedback(self, tool_name: str, result: dict):
        from mokioclaw.dashboard.task_result_windows import ResultSegment, ResultWindowError
        profiles = {"FileWriteTool": ("diff",), "FileEditTool": ("diff",),
                    "GrepTool": ("matches",), "BashTool": ("stdout", "stderr")}
        names = profiles.get(tool_name, ())
        body_bytes = sum(len(result[name].encode("utf-8")) if isinstance(result.get(name), str)
                         else len(canonical_json(result.get(name, []))) for name in names)
        if len(canonical_json(result)) <= self.result_json_budget() and body_bytes <= self.policy.body:
            return None
        if self.session is None:
            raise TaskContextError("input_too_large")
        segments = {}
        for name in names:
            value = result.get(name)
            if isinstance(value, str):
                segments[name] = ResultSegment("text", value)
            elif isinstance(value, list) and all(isinstance(item, dict) for item in value):
                segments[name] = ResultSegment("records", tuple(value))
        if not segments:
            raise TaskContextError("unsupported_content")
        try:
            reservation = self.session.results.reserve(result, segments, preserve_failure=result.get("ok") is False)
            try:
                self.session.results.preview(reservation, json_budget=self.result_json_budget())
            except ResultWindowError:
                self.session.results.abort(reservation)
                raise
            return reservation
        except ResultWindowError as exc:
            raise TaskContextError(exc.reason) from None

    def abort_feedback(self, reservation) -> None:
        if reservation is not None and self.session is not None:
            self.session.results.abort(reservation)

    def finish_feedback(self, result: dict, reservation) -> dict:
        from mokioclaw.dashboard.task_result_windows import ResultWindowError
        if reservation is None:
            return result
        if self.session is None:
            raise TaskContextError("invalid_message_group")
        try:
            ref = self.session.results.commit(reservation, executed=True)
            return self.session.results.first_page(ref, json_budget=self.result_json_budget())
        except ResultWindowError as exc:
            raise TaskContextError(exc.reason) from None

    def feedback(self, tool_name: str, result: dict) -> dict:
        return self.finish_feedback(result, self.reserve_feedback(tool_name, result))

    def read_result(self, cursor: str, limit: int) -> dict:
        from mokioclaw.dashboard.task_result_windows import ResultWindowError
        if self.session is None:
            return recovery_result("result_unavailable")
        try:
            return self.session.results.read(cursor, limit, identity=self.session.identity,
                                              json_budget=self.result_json_budget())
        except ResultWindowError as exc:
            if exc.reason in {"result_unavailable", "task_read_window_invalid"}:
                return recovery_result(exc.reason)
            raise TaskContextError(exc.reason) from None
