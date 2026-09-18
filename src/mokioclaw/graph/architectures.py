from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph

from mokioclaw.agents.code_agent import run_code_agent
from mokioclaw.graph.memory import build_layered_memory, memory_event
from mokioclaw.graph.nodes import (
    PLANNER_PROMPT,
    _execute_planner_tool,
    _get_writer,
    _planner_input,
    _todo_write_tool,
    verifier_node,
)
from mokioclaw.graph.state import MokioGraphState
from mokioclaw.providers.openai_provider import create_model


def build_react_workflow():
    graph = StateGraph(MokioGraphState)
    graph.add_node("react", react_node)
    graph.add_edge(START, "react")
    graph.add_edge("react", END)
    return graph.compile()


def build_plan_execute_workflow():
    graph = StateGraph(MokioGraphState)
    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_node("verify", verifier_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "verify")
    graph.add_conditional_edges("verify", verify_route, {"execute": "execute", END: END})
    return graph.compile()


def react_node(state: MokioGraphState) -> dict[str, Any]:
    writer = _get_writer()
    runtime = state["runtime"]
    max_attempts = int(state.get("max_attempts", 3))
    commands = list(state.get("verification_commands") or ["python -m pytest -q"])
    attempts = 0
    feedback = ""
    produced: list[Any] = []
    all_ok = False
    result: dict[str, Any] = {}
    while True:
        attempts += 1
        instruction = str(state["task"]) if attempts == 1 else (
            f"{state['task']}\n\n上一轮修改未通过公开验证，请修复后重试。\n公开验证输出摘要：\n{feedback}"
        )
        result = run_code_agent(state, instruction, writer=writer)
        produced.extend(result.get("messages", []))
        state = {**state, "todos": result.get("todos", state.get("todos", []))}
        feedback_lines: list[str] = []
        all_ok = True
        for command in commands:
            executed = _run_verification_command(runtime, command)
            writer({"type": "verification_command", "node": "react", "command": command, "ok": executed["ok"]})
            all_ok = all_ok and executed["ok"]
            if not executed["ok"]:
                feedback_lines.append(f"$ {command}\n{str(executed.get('stdout', ''))[-1500:]}\n{str(executed.get('stderr', ''))[-1500:]}")
        if all_ok or attempts >= max_attempts:
            break
        feedback = "\n\n".join(feedback_lines) or "public verification failed"
    return {
        "messages": produced,
        "attempts": attempts,
        "passed": all_ok,
        "code_agent_summary": result.get("summary", ""),
        "last_actor_summary": result.get("summary", ""),
    }


def _run_verification_command(runtime: Any, command: str) -> dict[str, Any]:
    executor = runtime.command_executor
    if executor is None:
        return {"ok": False, "stdout": "", "stderr": "no command executor configured"}
    return executor.run(
        workspace=runtime.workspace,
        command=command,
        timeout_seconds=int(getattr(runtime, "bash_max_timeout_seconds", 600)),
        max_output_chars=6000,
    )


def plan_node(state: MokioGraphState) -> dict[str, Any]:
    writer = _get_writer()
    working_state: MokioGraphState = {**state}
    memory = build_layered_memory(working_state, node="planner")
    writer(memory_event(memory, node="planner"))
    model = create_model()
    planner = model.bind_tools([_plan_only_tool(working_state, writer)])
    messages: list[Any] = [
        SystemMessage(content=PLANNER_PROMPT),
        HumanMessage(content=_planner_input(working_state, memory)),
    ]
    produced: list[Any] = []
    for _ in range(8):
        response = planner.invoke(messages)
        produced.append(response)
        messages.append(response)
        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            break
        for call in tool_calls:
            tool_message = _execute_planner_tool(working_state, writer, call)
            produced.append(tool_message)
            messages.append(tool_message)
    return {
        "plan_summary": working_state.get("plan_summary", ""),
        "todos": working_state.get("todos", []),
        "acceptance_criteria": working_state.get("acceptance_criteria", []),
        "verification_commands": working_state.get("verification_commands", []),
        "messages": produced,
        "memory_snapshot": memory,
    }


def _plan_only_tool(state: MokioGraphState, writer) -> StructuredTool:
    return StructuredTool.from_function(
        name="TodoWriteTool",
        func=lambda todos, acceptance_criteria, verification_commands, plan_summary="": _todo_write_tool(
            state, writer, todos, acceptance_criteria, verification_commands, plan_summary
        ),
        description="Publish or revise plan state. Args: todos, acceptance_criteria, verification_commands, optional plan_summary.",
    )


def execute_node(state: MokioGraphState) -> dict[str, Any]:
    writer = _get_writer()
    task = str(state.get("task", ""))
    last_error = str(state.get("last_error", "") or "")
    instruction = task if not last_error else f"{task}\n\n上一轮验证未通过。Verifier 反馈：\n{last_error}"
    result = run_code_agent(state, instruction, writer=writer)
    return {
        "messages": result.get("messages", []),
        "todos": result.get("todos", state.get("todos", [])),
        "code_agent_summary": result.get("summary", ""),
        "last_actor_summary": result.get("summary", ""),
    }


def verify_route(state: MokioGraphState) -> str:
    if state.get("passed"):
        return END
    if int(state.get("attempts", 0)) >= int(state.get("max_attempts", 3)):
        return END
    return "execute"
