from __future__ import annotations

import json
from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import ValidationError

from mokioclaw.core.state import RuntimeState
from mokioclaw.dashboard.task_tools import persist_todos_for_runtime
from mokioclaw.dashboard.task_executor import ReportedTaskToolFailure, TaskExecutionError
from mokioclaw.dashboard.task_events import task_tool_failure_event
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
  edits. FileWriteTool may replace an existing in-scope file only; it cannot
  create a new file in this task mode.
- Run the relevant supplied checks after editing. Use BashTool only for
  non-interactive commands and follow its current-platform shell description.
- Update an existing todo with TodoUpdateTool when its status materially
  changes. Do not spend a tool call on a status update before every edit.
- Use NotepadAppendTool only when a finding must survive context compression;
  use NotepadReadTool only when prior notes are needed.
- Use workspace-relative paths and do not access paths outside the selected
  scope. Summarize the files changed and checks actually run.
"""


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


def execute_code_agent_tool(
    runtime: RuntimeState,
    todos: list[dict[str, str]],
    call: dict[str, Any],
    *,
    tools_override: list[StructuredTool] | None = None,
    writer: Writer | None = None,
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
            except Exception as exc:
                if runtime is not None and runtime.task_filesystem is not None:
                    if writer is not None:
                        writer(task_tool_failure_event("codeAgent", name,
                                                       invalid_arguments=isinstance(exc, ValidationError),
                                                       exception=not isinstance(exc, ValidationError)))
                    failure = ReportedTaskToolFailure if writer is not None else TaskExecutionError
                    raise failure("task_tool_failed") from None
                result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if runtime is not None and runtime.task_filesystem is not None and result.get("ok") is False:
            if writer is not None:
                writer(task_tool_failure_event("codeAgent", name, error=result.get("error")))
            failure = ReportedTaskToolFailure if writer is not None else TaskExecutionError
            raise failure("task_tool_failed")
    tool_call_id = call.get("id") or f"{name}-call"
    return ToolMessage(content=json.dumps(result, ensure_ascii=False), name=name, tool_call_id=tool_call_id), todos


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
