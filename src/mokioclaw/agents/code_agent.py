from __future__ import annotations

import json
import sys
from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import ValidationError

from mokioclaw.core.state import RuntimeState
from mokioclaw.core.task_closeout import TaskCloseoutError, CloseoutMode, CloseoutPurpose
from mokioclaw.dashboard.task_tools import persist_todos_for_runtime
from mokioclaw.dashboard.task_executor import ReportedTaskToolFailure, TaskExecutionError
from mokioclaw.dashboard.task_events import task_tool_failure_event
from mokioclaw.dashboard.task_context import TaskContextError, request_binding, recovery_for
from mokioclaw.graph.memory import build_layered_memory, format_layered_memory_for_prompt, memory_event
from mokioclaw.graph.state import MokioGraphState
from mokioclaw.prompts.stage3 import CODE_AGENT_PROMPT
from mokioclaw.providers.openai_provider import create_model
from mokioclaw.tools import build_tools
from mokioclaw.tools.todo_tool import update_todo


Writer = Callable[[dict[str, Any]], None]


TASK_CODE_AGENT_PROMPT = """You are codeAgent, implementing one isolated repository task.

Work only in the selected scope and use the supplied task tools. Follow the
planner's instruction and the task's acceptance criteria.

Rules:
- Start with the exact relevant file paths supplied by the task or planner.
  Read those existing files with FileReadTool before editing; avoid broad
  discovery and repeated reads when the needed content is already available.
- Make the smallest in-scope change promptly with FileEditTool for focused
  edits. For a small file, prefer FileWriteTool and rewrite the file in full.
  FileEditTool old_text must match exactly once, copied verbatim without the
  line-number prefixes from FileReadTool. FileWriteTool may replace an existing
  in-scope file only; it cannot create a new file in this task mode.
- Run the relevant supplied checks after editing. Use BashTool only for
  non-interactive commands and follow its current-platform shell description.
- Update an existing todo with TodoUpdateTool when its status materially
  changes. Do not spend a tool call on a status update before every edit.
- Use NotepadAppendTool only when a finding must survive context compression;
  use NotepadReadTool only when prior notes are needed.
- Use workspace-relative paths and do not access paths outside the selected
  scope. Summarize the files changed and checks actually run.
"""


def _task_context_anchors(state: MokioGraphState, instruction: str) -> tuple[SystemMessage, HumanMessage]:
    """Immutable full task anchors for the task-only internal loop."""
    from mokioclaw.dashboard.task_context import TaskContextError, canonical_json
    context = state.get("task_context")
    if context is None or not isinstance(state.get("task"), str) or not isinstance(instruction, str):
        raise TaskContextError("unsupported_content")
    task = {"task": state["task"], "planner_instruction": instruction,
            "acceptance_criteria": state.get("acceptance_criteria", []),
            "fixed_verification_commands": context.fixed_verification_commands}
    guidance = """
Task context windows:
- A truncated read is not a complete file. Follow next_read with its revision.
- For whole-file replacement, obtain complete same-revision coverage first.
- A history index is metadata, not source content or proof of verification.
- Re-read source when omitted information is needed for an exact edit.
- Read saved executed output with ToolResultReadTool(cursor, limit).
- When no tools are available, return a nonempty handoff: actual changes,
  checks run, failures, unfinished work and outstanding formal verification.
  Do not claim completion or propose another tool call.
- An expired cursor does not recover by retrying; never replay a write to get
  its old diff. A new Bash request always requires its own approval.
"""
    return (SystemMessage(content=TASK_CODE_AGENT_PROMPT + guidance),
            HumanMessage(content=canonical_json(task).decode("utf-8")))


def run_code_agent(
    state: MokioGraphState,
    instruction: str,
    *,
    writer: Writer | None = None,
    max_loops: int = 16,
    tools_override: list[StructuredTool] | None = None,
    model_override: Any | None = None,
) -> dict[str, Any]:
    runtime = state["runtime"]
    todos = [dict(todo) for todo in state.get("todos", [])]
    writer = writer or (lambda _: None)
    memory = build_layered_memory({**state, "todos": todos}, node="codeAgent")
    writer(memory_event(memory, node="codeAgent"))
    if runtime.task_filesystem is not None and tools_override is None:
        raise ValueError("task_tools_required")
    if runtime.task_filesystem is not None and model_override is None:
        raise ValueError("task_model_required")
    if runtime.task_filesystem is not None:
        return _run_task_code_agent(state, instruction, writer=writer, max_loops=max_loops,
                                    tools=tools_override, model=model_override, todos=todos)
    model = create_model() if model_override is None else model_override
    selected_tools = build_tools(runtime) if tools_override is None else tools_override
    code_agent = model.bind_tools(selected_tools + [_build_todo_update_tool(todos)])

    writer(
        {
            "type": "plan_snapshot",
            "node": "codeAgent",
            "plan_summary": state.get("plan_summary", ""),
            "todos": todos,
            "verification_commands": state.get("verification_commands", []),
        }
    )

    messages = [
        SystemMessage(content=TASK_CODE_AGENT_PROMPT if runtime.task_filesystem is not None else CODE_AGENT_PROMPT),
        HumanMessage(content=_code_agent_input(state, instruction, memory)),
    ]
    produced_messages: list[Any] = []
    tool_events: list[dict[str, Any]] = []

    for _ in range(max_loops):
        response = code_agent.invoke(messages)
        produced_messages.append(response)
        messages.append(response)
        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            break
        for call in tool_calls:
            writer(
                {
                    "type": "tool_call",
                    "node": "codeAgent",
                    "name": call.get("name"),
                    "args": call.get("args", {}),
                }
            )
            tool_result, todos = execute_code_agent_tool(
                runtime, todos, call, tools_override=selected_tools, writer=writer,
            )
            event = tool_result_event(tool_result, node="codeAgent")
            tool_events.append(event)
            writer(event)
            if call.get("name") == "TodoUpdateTool":
                persist_todos_for_runtime(
                    runtime,
                    todos,
                    state.get("acceptance_criteria", []),
                    state.get("verification_commands", []),
                    state.get("plan_summary", ""),
                )
                writer(
                    {
                        "type": "todo_update",
                        "node": "codeAgent",
                        "plan_summary": state.get("plan_summary", ""),
                        "todos": todos,
                        "verification_commands": state.get("verification_commands", []),
                    }
                )
            produced_messages.append(tool_result)
            messages.append(tool_result)
    else:
        produced_messages.append(
            AIMessage(content="codeAgent stopped after the maximum tool loop count; verifier will inspect current files.")
        )

    summary = _last_ai_content(produced_messages)
    return {
        "ok": True,
        "summary": summary,
        "todos": todos or state.get("todos", []),
        "messages": produced_messages,
        "tool_events": tool_events,
    }


def _task_code_agent_mode(context, *, iterations_left):
    with context._lock:
        context.check_known_failure()
        context.preflight_provider_budget()
        return context.closeout.decide_repair(
            calls_left=context.max_provider_calls - context.provider_calls,
            tokens_left=context.max_total_tokens - context.reported_tokens, iterations_left=iterations_left)


def _run_task_code_agent(state, instruction, *, writer, max_loops, tools, model, todos):
    from mokioclaw.dashboard.task_graph import build_task_result_read_tool
    context = state.get("task_context")
    runtime = state["runtime"]
    if (context is None or context.task_filesystem is not runtime.task_filesystem
            or context.task_services is None or context.task_services.filesystem is not runtime.task_filesystem
            or getattr(model, "_context", None) is not context or tools != context.task_tools):
        raise TaskContextError("invalid_message_group")
    with context._lock:
        context.check_known_failure()
        context.preflight_provider_budget()
        if context.closeout.mode == CloseoutMode.INACTIVE:
            context.begin_attempt(context.current_attempt)
        if not context.closeout.admit_delegation(
                calls_left=context.max_provider_calls - context.provider_calls,
                tokens_left=context.max_total_tokens - context.reported_tokens):
            raise TaskCloseoutError("budget_slots_insufficient")
    services = context.task_services
    session = services.begin_delegation(context.current_attempt)
    try:
        selected = [*tools, _build_todo_update_tool(todos), build_task_result_read_tool(services)]
        anchors = _task_context_anchors(state, instruction)
        session.set_request(anchors, request_binding(selected))
        bound = model.for_purpose(CloseoutPurpose.REPAIR).bind_tools(selected)
        session.set_request(anchors, bound._binding)
        # Check the complete original binding baseline before any tool removal.
        messages = session.prepare([], todos)
        writer({"type": "plan_snapshot", "node": "codeAgent", "plan_summary": state.get("plan_summary", ""),
                "todos": todos, "verification_commands": state.get("verification_commands", [])})
        tool_events = []
        for iteration in range(min(max_loops, 16)):
            mode = _task_code_agent_mode(context, iterations_left=min(max_loops, 16) - iteration)
            if mode == CloseoutMode.CLOSING:
                bound = model.for_purpose(CloseoutPurpose.HANDOFF).bind_tools([])
                session.set_request(anchors, bound._binding)
            messages = session.prepare(messages, todos)
            response = bound.invoke(messages)
            context.check_known_failure()
            if mode == CloseoutMode.CLOSING and getattr(response, "tool_calls", None):
                raise TaskCloseoutError("invalid_handoff")
            if not getattr(response, "tool_calls", None):
                if not isinstance(response.content, str) or not response.content.strip():
                    raise TaskCloseoutError("invalid_handoff")
                messages = session.prepare([*messages, response], todos)
                with context._lock:
                    context.closeout.complete_phase(CloseoutPurpose.HANDOFF)
                break
            plan = session.plan_group(response, messages, todos)
            results = []
            for call in plan.calls:
                session.start_call(call["id"])
                writer({"type": "tool_call", "node": "codeAgent", "name": call["name"], "args": call["args"]})
                message, todos = execute_code_agent_tool(runtime, todos, call, tools_override=selected,
                                                         writer=writer, context=context)
                session.finish_call(message)
                event = tool_result_event(message, node="codeAgent")
                writer(event)
                value = json.loads(message.content)
                tool_events.append({"name": message.name, "ok": value.get("ok") is True,
                                    **{k: value[k] for k in ("receipt_id", "command_request_id", "exit_code") if k in value}})
                tool_events = tool_events[-8:]
                if call["name"] == "TodoUpdateTool":
                    persist_todos_for_runtime(runtime, todos, state.get("acceptance_criteria", []),
                                              state.get("verification_commands", []), state.get("plan_summary", ""))
                    writer({"type": "todo_update", "node": "codeAgent", "plan_summary": state.get("plan_summary", ""),
                            "todos": todos, "verification_commands": state.get("verification_commands", [])})
                results.append(message)
            messages = session.finish_group(messages, results)
        else:
            raise TaskCloseoutError("phase_limit")
        summary = _last_ai_content(messages[len(anchors) + 1:])
        return {"ok": True, "summary": summary, "todos": todos or state.get("todos", []),
                "messages": messages[len(anchors) + 1:], "tool_events": tool_events}
    finally:
        primary = sys.exc_info()[0] is not None
        try:
            services.close_delegation()
        except Exception:
            if not primary:
                raise


def execute_code_agent_tool(
    runtime: RuntimeState,
    todos: list[dict[str, str]],
    call: dict[str, Any],
    *,
    tools_override: list[StructuredTool] | None = None,
    writer: Writer | None = None,
    context: Any | None = None,
):
    if runtime is not None and runtime.task_filesystem is not None and tools_override is None:
        raise ValueError("task_tools_required")
    name = call.get("name", "")
    args = call.get("args") or {}
    if name == "TodoUpdateTool":
        result = update_todo(todos, args.get("todo_id", ""), args.get("status", ""), args.get("note", ""))
        if result.get("ok"):
            todos = result["todos"]
    else:
        tools = {tool.name: tool for tool in (build_tools(runtime) if tools_override is None else tools_override)}
        tool = tools.get(name)
        if tool is None:
            result = {"ok": False, "error": f"unknown tool: {name}"}
        else:
            try:
                result = tool.invoke(args)
            except (TaskContextError, TaskCloseoutError):
                raise
            except Exception as exc:
                if runtime is not None and runtime.task_filesystem is not None:
                    if context is not None:
                        context.record_terminal_root("task_tool_failed")
                    if writer is not None:
                        writer(task_tool_failure_event("codeAgent", name,
                                                       invalid_arguments=isinstance(exc, ValidationError),
                                                       exception=not isinstance(exc, ValidationError)))
                    failure = ReportedTaskToolFailure if writer is not None else TaskExecutionError
                    raise failure("task_tool_failed") from None
                result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if runtime is not None and runtime.task_filesystem is not None and result.get("ok") is False:
            retryable = (recovery_for(result.get("error")) is not None
                         or result.get("error") in {"task_edit_match_failed", "invalid_task_command"}
                         or str(result.get("error", "")).startswith("unknown tool:")) or (
                # A command that actually executed and returned a non-zero exit
                # is normal iteration input for the model, not a tool failure.
                # Gateway-level Bash failures keep their "error" field and terminate.
                name == "BashTool" and "error" not in result and type(result.get("exit_code")) is int
            )
            if not retryable:
                if context is not None:
                    context.record_terminal_root("task_tool_failed")
                if writer is not None:
                    writer(task_tool_failure_event("codeAgent", name, error=result.get("error")))
                failure = ReportedTaskToolFailure if writer is not None else TaskExecutionError
                raise failure("task_tool_failed")
    tool_call_id = call.get("id") or f"{name}-call"
    task_mode = runtime is not None and runtime.task_filesystem is not None
    return ToolMessage(content=json.dumps(result, ensure_ascii=False, separators=(",", ":") if task_mode else None),
                       name=name, tool_call_id=tool_call_id), todos


def tool_result_event(tool_message: ToolMessage, *, node: str) -> dict[str, Any]:
    try:
        parsed = json.loads(str(tool_message.content))
    except json.JSONDecodeError:
        parsed = tool_message.content
    return {"type": "tool_result", "node": node, "name": tool_message.name, "result": parsed}


def _build_todo_update_tool(todos: list[dict[str, str]]) -> StructuredTool:
    return StructuredTool.from_function(
        name="TodoUpdateTool",
        func=lambda todo_id, status, note="": update_todo(todos, todo_id, status, note),
        description="Update one existing todo status. Args: todo_id, status, optional note.",
    )


def _code_agent_input(state: MokioGraphState, instruction: str, memory: dict[str, Any]) -> str:
    parts = [
        f"Task: {state['task']}",
        f"Planner instruction:\n{instruction}",
    ]
    if state.get("session_context"):
        parts.append("Session context for this multi-turn coding session:\n" + str(state.get("session_context", "")))
    parts.append("Layered memory snapshot:\n" + format_layered_memory_for_prompt(memory))
    return "\n\n".join(parts)


def _last_ai_content(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            continue
        content = getattr(message, "content", "")
        if content:
            return str(content)
    return ""
