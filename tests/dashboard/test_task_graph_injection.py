"""Task graph nodes use explicit fake provider context without legacy fallback."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from mokioclaw.dashboard.task_context import TaskToolServices
from mokioclaw.core.agent import TaskRunContext, create_runtime, stream_agent_events
from mokioclaw.core.state import RuntimeState
from mokioclaw.dashboard.task_filesystem import TaskFilesystem
from mokioclaw.dashboard.task_graph import build_task_graph_tools
from mokioclaw.dashboard.task_executor import TaskExecutionError
from mokioclaw.dashboard.task_worker import run_projected_workflow
from mokioclaw.graph import nodes
from mokioclaw.providers.openai_provider import TaskProviderError


class FakeModel:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    def invoke(self, _messages):
        self.calls += 1
        return SimpleNamespace(content=self.content, usage_metadata={
            "input_tokens": 3, "output_tokens": 2, "total_tokens": 5,
        })

    def bind_tools(self, _tools):
        return self


def context(model: FakeModel) -> TaskRunContext:
    # These fixtures exercise tool/provider/retry contracts after closeout admission.
    # Small budgets remain explicitly rejected in test_task_closeout_agents.
    return TaskRunContext.for_fake_model(
        model, max_provider_calls=24, max_total_tokens=1000, max_output_tokens_per_call=20,
    )


@pytest.mark.parametrize("suggested", [None, [], ["echo model-suggested"]])
def test_task_planner_uses_fixed_verification_when_model_omits_or_replaces_commands(suggested) -> None:
    fixed = "PYTHONPATH=src python -m pytest -q tests/test_tools.py"
    ctx = context(FakeModel("unused"))
    ctx.fixed_verification_commands = (fixed,)
    state = {"task": "repair", "task_context": ctx,
             "runtime": SimpleNamespace(task_filesystem=object(), allow_web_search=False)}
    args = {"todos": ["repair grep"], "acceptance_criteria": ["tests pass"]}
    if suggested is not None:
        args["verification_commands"] = suggested
    message = nodes._execute_planner_tool(state, lambda _: None, {
        "name": "TodoWriteTool", "args": args, "id": "todo-plan",
    })
    assert json.loads(str(message.content))["ok"] is True
    assert state["verification_commands"] == [fixed]


def test_regular_planner_still_requires_model_verification_commands() -> None:
    state = {"task": "repair", "runtime": SimpleNamespace(allow_web_search=False)}
    task_tool = next(tool for tool in nodes._build_planner_tools(
        {**state, "task_context": context(FakeModel("unused"))}, lambda _: None,
    ) if tool.name == "TodoWriteTool")
    regular_tool = next(tool for tool in nodes._build_planner_tools(state, lambda _: None)
                        if tool.name == "TodoWriteTool")
    assert not task_tool.args_schema.model_fields["verification_commands"].is_required()
    assert regular_tool.args_schema.model_fields["verification_commands"].is_required()


def test_task_planner_allows_no_fixed_verification_command() -> None:
    ctx = context(FakeModel("unused"))
    state = {"task": "repair", "task_context": ctx,
             "runtime": SimpleNamespace(task_filesystem=object(), allow_web_search=False)}
    message = nodes._execute_planner_tool(state, lambda _: None, {
        "name": "TodoWriteTool", "args": {
            "todos": ["repair grep"], "acceptance_criteria": ["review patch"],
            "verification_commands": [],
        },
    })
    assert json.loads(str(message.content))["ok"] is True
    assert state["verification_commands"] == []


def test_task_planner_reports_fixed_tool_and_category_before_failing() -> None:
    ctx = context(FakeModel("unused"))
    state = {"task": "repair", "task_context": ctx,
             "runtime": SimpleNamespace(task_filesystem=object(), allow_web_search=False)}
    emitted = []
    with pytest.raises(TaskExecutionError, match="task_tool_failed"):
        nodes._execute_planner_tool(state, emitted.append, {
            "name": "TodoWriteTool", "args": {"todos": ["repair"]},
        })
    assert emitted[-1] == {"type": "task_tool_failure", "node": "planner",
                           "name": "TodoWriteTool", "failure_category": "invalid_arguments"}
    assert "repair" not in repr(emitted[-1])


def test_task_planner_rejected_result_has_fixed_category() -> None:
    ctx = context(FakeModel("unused"))
    state = {"task": "repair", "task_context": ctx,
             "runtime": SimpleNamespace(task_filesystem=object(), allow_web_search=False)}
    emitted = []
    with pytest.raises(TaskExecutionError, match="task_tool_failed"):
        nodes._execute_planner_tool(state, emitted.append, {
            "name": "TodoWriteTool", "args": {"todos": [], "acceptance_criteria": []},
        })
    assert emitted[-1] == {"type": "task_tool_failure", "node": "planner",
                           "name": "TodoWriteTool", "failure_category": "tool_rejected"}


def test_failed_planner_tool_reaches_public_fake_workflow_before_stop(tmp_path: Path) -> None:
    work = tmp_path / "work"
    (work / "src").mkdir(parents=True)
    prepared = SimpleNamespace(task_id="task_1234567890123456", work=work,
                               baseline=tmp_path / "baseline", root=tmp_path)
    fs = TaskFilesystem(prepared, ("src/",), ("src/",), ".mokioclaw/task-scratch/")

    class PlannerFailureModel:
        def bind_tools(self, _tools):
            return self

        def invoke(self, messages):
            system = str(messages[0].content)
            if "intent router" in system:
                content, calls = '{"route":"workflow","reason":"task","confidence":0.99}', []
            elif "planner/supervisor" in system:
                content, calls = "", [{"name": "TodoWriteTool", "id": "bad-plan",
                                       "args": {"todos": ["PRIVATE DESCRIPTION"]}}]
            else:
                content, calls = "done", []
            return AIMessage(content=content, tool_calls=calls, usage_metadata={
                "input_tokens": 3, "output_tokens": 2, "total_tokens": 5,
            })

    ctx = TaskRunContext.for_fake_model(
        PlannerFailureModel(), max_provider_calls=3, max_total_tokens=50,
        max_output_tokens_per_call=20,
    )
    services = TaskToolServices(fs)
    ctx.attach_tools(fs, build_task_graph_tools(fs, None, work, services=services), services=services)
    projected = []
    with pytest.raises(TaskExecutionError, match="task_tool_failed"):
        run_projected_workflow("repair", work, ctx, projected.append, max_attempts=1)
    assert {"attempt_id": 1, "kind": "tool_failure", "tool": "TodoWriteTool",
            "category": "invalid_arguments"} in projected
    assert "PRIVATE DESCRIPTION" not in repr(projected)


def test_failed_code_agent_file_tool_reports_inner_tool_once(tmp_path: Path) -> None:
    work = tmp_path / "work"
    (work / "src").mkdir(parents=True)
    prepared = SimpleNamespace(task_id="task_1234567890123456", work=work,
                               baseline=tmp_path / "baseline", root=tmp_path)
    fs = TaskFilesystem(prepared, ("src/",), ("src/",), ".mokioclaw/task-scratch/")

    class FileFailureModel:
        def bind_tools(self, _tools):
            return self

        def invoke(self, messages):
            system = str(messages[0].content)
            if "intent router" in system:
                content, calls = '{"route":"workflow","reason":"task","confidence":0.99}', []
            elif "planner/supervisor" in system:
                content, calls = "", [{"name": "CallCodeAgentTool", "id": "handoff",
                                       "args": {"instruction": "repair"}}]
            elif "codeAgent" in system:
                content, calls = "", [{"name": "FileReadTool", "id": "bad-read",
                                       "args": {"file_path": "../PRIVATE"}}]
            else:
                content, calls = "done", []
            return AIMessage(content=content, tool_calls=calls, usage_metadata={
                "input_tokens": 3, "output_tokens": 2, "total_tokens": 5,
            })

    ctx = TaskRunContext.for_fake_model(
        FileFailureModel(), max_provider_calls=10, max_total_tokens=1000,
        max_output_tokens_per_call=20,
    )
    services = TaskToolServices(fs)
    ctx.attach_tools(fs, build_task_graph_tools(fs, None, work, services=services), services=services)
    projected = []
    with pytest.raises(TaskExecutionError, match="task_tool_failed"):
        run_projected_workflow("repair", work, ctx, projected.append, max_attempts=1)
    failures = [event for event in projected if event["kind"] == "tool_failure"]
    assert failures == [{"attempt_id": 1, "kind": "tool_failure",
                         "tool": "FileReadTool", "category": "scope_denied"}]
    assert "PRIVATE" not in repr(projected)


def test_entry_router_uses_explicit_model_and_never_loads_legacy_provider(monkeypatch) -> None:
    monkeypatch.setattr(nodes, "create_model", lambda: pytest.fail("legacy provider used"))
    model = FakeModel('{"route":"workflow","reason":"task","confidence":0.99}')
    result = nodes.intent_router_node({"task": "repair", "task_context": context(model)})
    assert result["intent_route"] == "workflow"
    assert model.calls == 1


def test_context_monitor_in_task_mode_avoids_dotenv_and_extra_provider_call(
    monkeypatch, tmp_path: Path,
) -> None:
    work = tmp_path / "work"
    (work / "src").mkdir(parents=True)
    prepared = SimpleNamespace(task_id="task_1234567890123456", work=work,
                               baseline=tmp_path / "baseline", root=tmp_path)
    fs = TaskFilesystem(prepared, ("src/",), ("src/",), ".mokioclaw/task-scratch/")
    runtime = RuntimeState(workspace=work, task_filesystem=fs, checkpoint_mode="off", trace_mode="off")
    model = FakeModel("unused")
    monkeypatch.setattr(nodes, "load_dotenv", lambda: pytest.fail("dotenv was read"))
    monkeypatch.setattr(nodes, "create_model", lambda: pytest.fail("legacy provider used"))
    result = nodes.context_monitor_node({"runtime": runtime, "task": "repair",
                                         "messages": [], "task_context": context(model)})
    assert result["context_token_limit"] > 0
    assert model.calls == 0


def test_code_agent_and_verifier_receive_only_task_tools_and_same_gateway(
    monkeypatch, tmp_path: Path,
) -> None:
    work = tmp_path / "work"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.py").write_text("alpha", encoding="utf-8")
    prepared = SimpleNamespace(task_id="task_1234567890123456", work=work,
                               baseline=tmp_path / "baseline", root=tmp_path)
    fs = TaskFilesystem(prepared, ("src/",), ("src/",), ".mokioclaw/task-scratch/")
    runtime = RuntimeState(workspace=work, task_filesystem=fs, checkpoint_mode="off", trace_mode="off")

    class FakeGateway:
        task_gateway = True

        def __init__(self):
            self.commands = []

        def run(self, **kwargs):
            self.commands.append(kwargs["command"])
            return {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""}

    gateway = FakeGateway()
    services = TaskToolServices(fs)
    tools = build_task_graph_tools(fs, gateway, work, services=services)
    ctx = context(FakeModel("unused"))
    ctx.attach_tools(fs, tools, services=services)
    captured = {}

    def fake_code_agent(_state, _instruction, *, writer, tools_override, model_override):
        captured["tools"] = {tool.name for tool in tools_override}
        captured["model"] = model_override
        return {"summary": "done", "todos": []}

    monkeypatch.setattr(nodes, "run_code_agent", fake_code_agent)
    state = {"runtime": runtime, "task": "repair", "task_context": ctx, "todos": []}
    nodes._call_code_agent_tool(state, lambda _: None, "repair")
    assert "BashTool" in captured["tools"] and "FileReadTool" in captured["tools"]
    assert captured["model"] is not None
    read = nodes._execute_read_only_tool(state, {"name": "FileReadTool", "args": {"file_path": "src/a.py"}})
    assert "alpha" in str(read.content)
    shell = nodes._execute_read_only_tool(state, {"name": "BashTool", "args": {"command": "echo task"}})
    assert '"ok": true' in str(shell.content)
    assert gateway.commands == ["echo task"]


def test_task_runtime_and_stream_entry_skip_dotenv_and_force_safe_modes(
    monkeypatch, tmp_path: Path,
) -> None:
    work = tmp_path / "work"
    (work / "src").mkdir(parents=True)
    prepared = SimpleNamespace(task_id="task_1234567890123456", work=work,
                               baseline=tmp_path / "baseline", root=tmp_path)
    fs = TaskFilesystem(prepared, ("src/",), ("src/",), ".mokioclaw/task-scratch/")
    model = FakeModel('{"route":"workflow","reason":"task","confidence":0.99}')
    ctx = context(model)
    services = TaskToolServices(fs)
    ctx.attach_tools(fs, build_task_graph_tools(fs, None, work, services=services), services=services)
    monkeypatch.setattr("mokioclaw.core.agent.load_dotenv", lambda: pytest.fail("dotenv was read"))
    monkeypatch.setattr(nodes, "create_model", lambda: pytest.fail("legacy provider used"))
    runtime = create_runtime(work, task_context=ctx)
    assert runtime.task_filesystem is fs
    assert runtime.allow_web_search is False
    assert runtime.trace_mode == "off" and runtime.checkpoint_mode == "off"
    stream = stream_agent_events("repair", workspace=work, task_context=ctx)
    try:
        first = next(stream)
        assert first["type"] in {"custom_event", "graph_event"}
        assert model.calls == 1
    finally:
        stream.close()


def test_provider_failure_in_task_planner_does_not_become_a_retryable_tool_message(
    monkeypatch, tmp_path: Path,
) -> None:
    work = tmp_path / "work"
    (work / "src").mkdir(parents=True)
    prepared = SimpleNamespace(task_id="task_1234567890123456", work=work,
                               baseline=tmp_path / "baseline", root=tmp_path)
    fs = TaskFilesystem(prepared, ("src/",), ("src/",), ".mokioclaw/task-scratch/")
    runtime = RuntimeState(workspace=work, task_filesystem=fs, checkpoint_mode="off", trace_mode="off",
                           allow_web_search=False)
    ctx = context(FakeModel("unused"))
    services = TaskToolServices(fs)
    ctx.attach_tools(fs, build_task_graph_tools(fs, None, work, services=services), services=services)
    monkeypatch.setattr(nodes, "run_code_agent", lambda *_args, **_kwargs:
                        (_ for _ in ()).throw(TaskProviderError("provider_failed")))
    state = {"runtime": runtime, "task": "repair", "task_context": ctx, "todos": []}
    with pytest.raises(TaskProviderError, match="provider_failed"):
        nodes._execute_planner_tool(state, lambda _: None,
                                    {"name": "CallCodeAgentTool", "args": {"instruction": "repair"}})


def test_planner_reports_outer_tool_when_failure_has_no_inner_diagnostic(
    monkeypatch, tmp_path: Path,
) -> None:
    work = tmp_path / "work"
    (work / "src").mkdir(parents=True)
    prepared = SimpleNamespace(task_id="task_1234567890123456", work=work,
                               baseline=tmp_path / "baseline", root=tmp_path)
    fs = TaskFilesystem(prepared, ("src/",), ("src/",), ".mokioclaw/task-scratch/")
    runtime = RuntimeState(workspace=work, task_filesystem=fs, checkpoint_mode="off", trace_mode="off",
                           allow_web_search=False)
    ctx = context(FakeModel("unused"))
    services = TaskToolServices(fs)
    ctx.attach_tools(fs, build_task_graph_tools(fs, None, work, services=services), services=services)
    monkeypatch.setattr(nodes, "run_code_agent", lambda *_args, **_kwargs:
                        (_ for _ in ()).throw(TaskExecutionError("task_tool_failed")))
    state = {"runtime": runtime, "task": "repair", "task_context": ctx, "todos": []}
    emitted = []
    with pytest.raises(TaskExecutionError, match="task_tool_failed"):
        nodes._execute_planner_tool(state, emitted.append,
                                    {"name": "CallCodeAgentTool", "args": {"instruction": "repair"}})
    assert emitted[-1] == {"type": "task_tool_failure", "node": "planner",
                           "name": "CallCodeAgentTool", "failure_category": "tool_exception"}


def test_task_verifier_tool_denial_terminates_instead_of_becoming_model_feedback(tmp_path: Path) -> None:
    work = tmp_path / "work"
    (work / "src").mkdir(parents=True)
    prepared = SimpleNamespace(task_id="task_1234567890123456", work=work,
                               baseline=tmp_path / "baseline", root=tmp_path)
    fs = TaskFilesystem(prepared, ("src/",), ("src/",), ".mokioclaw/task-scratch/")
    runtime = RuntimeState(workspace=work, task_filesystem=fs, checkpoint_mode="off", trace_mode="off")
    ctx = context(FakeModel("unused"))
    services = TaskToolServices(fs)
    ctx.attach_tools(fs, build_task_graph_tools(fs, None, work, services=services), services=services)
    state = {"runtime": runtime, "task": "repair", "task_context": ctx}
    with pytest.raises(TaskExecutionError, match="task_tool_failed"):
        nodes._execute_read_only_tool(state, {"name": "BashTool", "args": {"command": "echo denied"}})


def test_only_explicit_verifier_failure_advances_gateway_attempt(tmp_path: Path) -> None:
    work = tmp_path / "work"
    (work / "src").mkdir(parents=True)
    prepared = SimpleNamespace(task_id="task_1234567890123456", work=work,
                               baseline=tmp_path / "baseline", root=tmp_path)
    fs = TaskFilesystem(prepared, ("src/",), ("src/",), ".mokioclaw/task-scratch/")
    runtime = RuntimeState(workspace=work, task_filesystem=fs, checkpoint_mode="off", trace_mode="off",
                           allow_web_search=False)

    class FakeGateway:
        task_gateway = True
        attempt_id = 1

        def __init__(self):
            self.advanced = []

        def set_attempt(self, value):
            self.advanced.append(value)
            self.attempt_id = value

    gateway = FakeGateway()
    model = FakeModel('{"passed":false,"reason":"fixture failed","checks":[],"recommended_next_instruction":"fix"}')
    ctx = context(model)
    services = TaskToolServices(fs)
    ctx.attach_tools(fs, build_task_graph_tools(fs, gateway, work, services=services), services=services, gateway=gateway)
    state = {"runtime": runtime, "task": "repair", "task_context": ctx, "attempts": 0,
             "max_attempts": 2, "messages": []}
    verdict = nodes.verifier_node(state)
    assert verdict["passed"] is False and verdict["verifier_explicit_failure"] is True
    assert verdict["context_next_node"] == "planner"
    nodes.planner_node({**state, **verdict})
    assert gateway.advanced == [2]


def test_invalid_task_verifier_response_does_not_trigger_retry(tmp_path: Path) -> None:
    work = tmp_path / "work"
    (work / "src").mkdir(parents=True)
    prepared = SimpleNamespace(task_id="task_1234567890123456", work=work,
                               baseline=tmp_path / "baseline", root=tmp_path)
    fs = TaskFilesystem(prepared, ("src/",), ("src/",), ".mokioclaw/task-scratch/")
    runtime = RuntimeState(workspace=work, task_filesystem=fs, checkpoint_mode="off", trace_mode="off",
                           allow_web_search=False)
    ctx = context(FakeModel("not JSON"))
    services = TaskToolServices(fs)
    ctx.attach_tools(fs, build_task_graph_tools(fs, None, work, services=services), services=services)
    with pytest.raises(TaskExecutionError, match="verifier_invalid"):
        nodes.verifier_node({"runtime": runtime, "task": "repair", "task_context": ctx,
                             "attempts": 0, "max_attempts": 2, "messages": []})


@pytest.mark.parametrize("approved", [True, False])
def test_fixed_verification_command_uses_same_gateway_with_actual_evidence(
    tmp_path: Path, approved: bool,
) -> None:
    work = tmp_path / "work"
    (work / "src").mkdir(parents=True)
    prepared = SimpleNamespace(task_id="task_1234567890123456", work=work,
                               baseline=tmp_path / "baseline", root=tmp_path)
    fs = TaskFilesystem(prepared, ("src/",), ("src/",), ".mokioclaw/task-scratch/")
    runtime = RuntimeState(workspace=work, task_filesystem=fs, checkpoint_mode="off", trace_mode="off",
                           allow_web_search=False)

    class FakeGateway:
        task_gateway = True

        def __init__(self):
            self.commands = []

        def run(self, **kwargs):
            self.commands.append(kwargs["command"])
            if not approved:
                return {"ok": False, "error": "approval_denied_or_expired", "command_request_id": "req-one"}
            return {"ok": True, "exit_code": 0, "duration_ms": 42, "stdout": "ok",
                    "stderr": "", "command_request_id": "req-one"}

    gateway = FakeGateway()
    ctx = context(FakeModel('{"passed":true,"reason":"ok","checks":[]}'))
    services = TaskToolServices(fs)
    ctx.attach_tools(fs, build_task_graph_tools(fs, gateway, work, services=services), services=services, gateway=gateway,
                     verification_commands=("python -m pytest -q",))
    state = {"runtime": runtime, "task": "repair", "task_context": ctx,
             "attempts": 0, "max_attempts": 1, "messages": []}
    if not approved:
        with pytest.raises(TaskExecutionError, match="verification_command_failed"):
            nodes.verifier_node(state)
    else:
        result = nodes.verifier_node(state)
        evidence = result["verification_results"][0]
        assert evidence["command"] == "python -m pytest -q"
        assert evidence["command_request_id"] == "req-one"
        assert evidence["duration_ms"] == 42 and evidence["exit_code"] == 0
    assert gateway.commands == ["python -m pytest -q"]


def test_model_claim_without_executed_verification_is_not_a_pass(tmp_path: Path) -> None:
    work = tmp_path / "work"
    (work / "src").mkdir(parents=True)
    prepared = SimpleNamespace(task_id="task_1234567890123456", work=work,
                               baseline=tmp_path / "baseline", root=tmp_path)
    fs = TaskFilesystem(prepared, ("src/",), ("src/",), ".mokioclaw/task-scratch/")
    runtime = RuntimeState(workspace=work, task_filesystem=fs, checkpoint_mode="off", trace_mode="off",
                           allow_web_search=False)
    ctx = context(FakeModel('{"passed":true,"reason":"claimed","checks":[]}'))
    services = TaskToolServices(fs)
    ctx.attach_tools(fs, build_task_graph_tools(fs, None, work, services=services), services=services)
    result = nodes.verifier_node({"runtime": runtime, "task": "repair", "task_context": ctx,
                                  "attempts": 0, "max_attempts": 2, "messages": []})
    assert result["passed"] is False and result["context_next_node"] == "final"
    assert result["verification_results"] == []


def test_fake_full_graph_retries_only_after_verifier_failure_and_keeps_work(tmp_path: Path) -> None:
    work = tmp_path / "work"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.py").write_text("bad\n", encoding="utf-8")
    prepared = SimpleNamespace(task_id="task_1234567890123456", work=work,
                               baseline=tmp_path / "baseline", root=tmp_path)
    fs = TaskFilesystem(prepared, ("src/",), ("src/",), ".mokioclaw/task-scratch/")

    class FakeGateway:
        task_gateway = True
        attempt_id = 1

        def __init__(self):
            self.commands = []
            self.advanced = []

        def set_attempt(self, value):
            self.advanced.append(value)
            self.attempt_id = value

        def run(self, **kwargs):
            self.commands.append((self.attempt_id, kwargs["command"]))
            code = 1 if self.attempt_id == 1 else 0
            return {"ok": code == 0, "exit_code": code, "stdout": "fixture", "stderr": "",
                    "duration_ms": 10, "command_request_id": f"request_1234567890123{self.attempt_id}"}

    class WorkflowModel:
        def __init__(self):
            self.calls = 0
            self.code_calls = 0
            self.verifier_calls = 0

        def bind_tools(self, _tools):
            return self

        def invoke(self, messages):
            self.calls += 1
            system = str(messages[0].content)
            tool_calls = []
            content = "done"
            if "intent router" in system:
                content = '{"route":"workflow","reason":"task","confidence":0.99}'
            elif "planner/supervisor" in system:
                if not any(isinstance(message, ToolMessage) for message in messages):
                    tool_calls = [{"id": f"handoff-{self.calls}", "name": "CallCodeAgentTool",
                                   "args": {"instruction": "repair"}}]
            elif "codeAgent" in system:
                if self.code_calls == 0:
                    tool_calls = [{"id": "edit-one", "name": "FileEditTool",
                                   "args": {"file_path": "src/a.py", "old_text": "bad", "new_text": "good"}}]
                self.code_calls += 1
            elif "You are verifier" in system:
                self.verifier_calls += 1
                passed = self.verifier_calls == 2
                content = ('{"passed":true,"reason":"ok","checks":[]}' if passed else
                           '{"passed":false,"reason":"fixture failed","checks":[],"recommended_next_instruction":"fix"}')
            return AIMessage(content=content, tool_calls=tool_calls, usage_metadata={
                "input_tokens": 3, "output_tokens": 2, "total_tokens": 5,
            })

    gateway = FakeGateway()
    model = WorkflowModel()
    # Retry includes one starting planner, one repair, seven reserved slots.
    ctx = TaskRunContext.for_fake_model(model, max_provider_calls=20, max_total_tokens=1000,
                                        max_output_tokens_per_call=20)
    services = TaskToolServices(fs)
    ctx.attach_tools(fs, build_task_graph_tools(fs, gateway, work, services=services), services=services, gateway=gateway,
                     verification_commands=("python -m pytest -q",))
    events = []
    projected = []

    def observed_stream(*args, **kwargs):
        for event in stream_agent_events(*args, **kwargs):
            events.append(event)
            yield event

    run_projected_workflow("repair", work, ctx, projected.append,
                           stream=observed_stream, max_attempts=2)
    assert any(event.get("type") == "graph_event" and "final" in event.get("event", {}) for event in events)
    verification = [event for event in projected if event["kind"] == "verification"]
    assert [(event["attempt_id"], event["status"], event["command_index"], event["exit_code"])
            for event in verification] == [(1, "failed", 0, 1), (2, "passed", 0, 0)]
    assert projected[-1] == {"attempt_id": 2, "kind": "stage", "phase": "complete"}
    assert projected[-2] == {"attempt_id": 2, "kind": "budget_usage", **ctx.usage_snapshot()}
    assert "fixture" not in repr(projected)
    assert (work / "src" / "a.py").read_text(encoding="utf-8") == "good\n"
    assert gateway.commands == [(1, "python -m pytest -q"), (2, "python -m pytest -q")]
    assert gateway.advanced == [2]
    assert model.verifier_calls == 2 and ctx.provider_calls == model.calls
    assert ctx.usage_snapshot() == {
        "entry_calls": 1, "entry_reported_tokens": 5,
        "chat_calls": 0, "chat_reported_tokens": 0,
        "planner_calls": 4, "planner_reported_tokens": 20,
        "code_agent_calls": 3, "code_agent_reported_tokens": 15,
        "verifier_calls": 2, "verifier_reported_tokens": 10,
        "context_compressor_calls": 0, "context_compressor_reported_tokens": 0,
    }


def test_failed_edit_match_returns_to_model_and_attempt_continues(tmp_path: Path) -> None:
    work = tmp_path / "work"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.py").write_text("alpha\nbeta\n", encoding="utf-8", newline="\n")
    prepared = SimpleNamespace(task_id="task_1234567890123456", work=work,
                               baseline=tmp_path / "baseline", root=tmp_path)
    fs = TaskFilesystem(prepared, ("src/",), ("src/",), ".mokioclaw/task-scratch/")

    class RetryEditModel:
        def bind_tools(self, _tools):
            return self

        def invoke(self, messages):
            system = str(messages[0].content)
            if "intent router" in system:
                content, calls = '{"route":"workflow","reason":"task","confidence":0.99}', []
            elif "planner/supervisor" in system:
                if isinstance(messages[-1], ToolMessage) and json.loads(messages[-1].content).get("ok") is True:
                    content, calls = "done", []
                else:
                    content, calls = "", [{"name": "CallCodeAgentTool", "id": "handoff",
                                           "args": {"instruction": "repair"}}]
            elif "codeAgent" in system:
                last = str(messages[-1].content)
                if isinstance(messages[-1], ToolMessage) and json.loads(last).get("ok") is True:
                    content, calls = "done", []
                elif "task_edit_match_failed" in last:
                    content, calls = "", [{"name": "FileEditTool", "id": "good-edit",
                                           "args": {"file_path": "src/a.py",
                                                    "old_text": "alpha", "new_text": "gamma"}}]
                else:
                    content, calls = "", [{"name": "FileEditTool", "id": "bad-edit",
                                           "args": {"file_path": "src/a.py",
                                                    "old_text": "NOT PRESENT ANYWHERE", "new_text": "x"}}]
            else:
                content, calls = '{"passed": true, "reason": "ok", "checks": []}', []
            return AIMessage(content=content, tool_calls=calls, usage_metadata={
                "input_tokens": 3, "output_tokens": 2, "total_tokens": 5,
            })

    ctx = TaskRunContext.for_fake_model(
        RetryEditModel(), max_provider_calls=20, max_total_tokens=500,
        max_output_tokens_per_call=20,
    )
    services = TaskToolServices(fs)
    ctx.attach_tools(fs, build_task_graph_tools(fs, None, work, services=services), services=services)
    projected = []
    run_projected_workflow("repair", work, ctx, projected.append, max_attempts=1)
    assert (work / "src" / "a.py").read_text(encoding="utf-8") == "gamma\nbeta\n"
    assert [event for event in projected if event["kind"] == "tool_failure"] == []
    statuses = [event["status"] for event in projected if event["kind"] == "tool_result"]
    assert "failed" in statuses and "passed" in statuses


def test_task_verifier_unknown_tool_returns_error_without_terminating(tmp_path: Path) -> None:
    work = tmp_path / "work"
    (work / "src").mkdir(parents=True)
    prepared = SimpleNamespace(task_id="task_1234567890123456", work=work,
                               baseline=tmp_path / "baseline", root=tmp_path)
    fs = TaskFilesystem(prepared, ("src/",), ("src/",), ".mokioclaw/task-scratch/")
    runtime = RuntimeState(workspace=work, task_filesystem=fs, checkpoint_mode="off", trace_mode="off")
    ctx = context(FakeModel("unused"))
    services = TaskToolServices(fs)
    ctx.attach_tools(fs, build_task_graph_tools(fs, None, work, services=services), services=services)
    state = {"runtime": runtime, "task": "repair", "task_context": ctx}
    emitted = []
    message = nodes._execute_read_only_tool(
        state, {"name": "FakeTool", "id": "f2", "args": {}}, writer=emitted.append)
    assert "unknown tool: FakeTool" in str(message.content)
    assert emitted == []


def test_task_planner_unknown_tool_returns_error_without_terminating() -> None:
    ctx = context(FakeModel("unused"))
    state = {"task": "repair", "task_context": ctx,
             "runtime": SimpleNamespace(task_filesystem=object(), allow_web_search=False)}
    emitted = []
    message = nodes._execute_planner_tool(
        state, emitted.append, {"name": "FakeTool", "id": "f1", "args": {}})
    assert "unknown tool: FakeTool" in str(message.content)
    assert [event for event in emitted if event.get("type") == "task_tool_failure"] == []
