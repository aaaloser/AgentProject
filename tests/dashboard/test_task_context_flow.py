import hashlib
import json
from types import SimpleNamespace

import pytest

from task_context_fakes import offline_context_guard
from langchain_core.messages import AIMessage, ToolMessage


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    with offline_context_guard(monkeypatch):
        yield


def context_api():
    from mokioclaw.dashboard import task_context
    return task_context


class ScriptedModel:
    """Synthetic decisions; record numeric sizes and IDs, never prompt copies."""
    def __init__(self, script):
        self.script = script
        self.calls = 0
        self.sizes = []
        self.group_ids = []
        self.binding = None
        self.names = []

    def bind_tools(self, tools, **kwargs):
        self.binding = context_api().request_binding(tools, **kwargs)
        self.names = [tool.name for tool in tools]
        return self

    def invoke(self, messages, **kwargs):
        self.sizes.append(context_api().measure_request(messages, self.binding, invocation_options=kwargs))
        self.group_ids.append(tuple(m.tool_call_id for m in messages if isinstance(m, ToolMessage)))
        item = self.script[self.calls] if isinstance(self.script, list) else self.script(self.calls, messages)
        self.calls += 1
        return AIMessage(content=item.get("content", ""), tool_calls=item.get("tool_calls", []),
                         usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})


def loop_state(tmp_path, script, *, text="original\n", task="synthetic task", commands=("echo fixture",)):
    from mokioclaw.core.agent import TaskRunContext, create_runtime
    from mokioclaw.dashboard.task_graph import build_task_graph_tools
    file_tools, services, _, work = task_files(tmp_path, text)
    services.close_delegation()
    model = ScriptedModel(script)
    context = TaskRunContext.for_fake_model(model, max_provider_calls=24, max_total_tokens=150000,
                                           max_output_tokens_per_call=3072)
    tools = build_task_graph_tools(file_tools.fs, None, work, services=services)
    context.attach_tools(file_tools.fs, tools, services=services, verification_commands=commands)
    runtime = create_runtime(work, task_context=context)
    state = {"runtime": runtime, "task_context": context, "task": task, "todos": [],
             "acceptance_criteria": ["synthetic acceptance"], "verification_commands": list(commands)}
    return state, context, model, services, work


def run_loop(state, context, **kwargs):
    from mokioclaw.agents.code_agent import run_code_agent
    return run_code_agent(state, "synthetic instruction", tools_override=context.task_tools,
                          model_override=context.model(stage="code_agent"), **kwargs)


def read_call(call_id, **args):
    return {"id": call_id, "name": "FileReadTool", "args": {"file_path": "src/a.py", **args}}


def test_pending_group_compacts_removable_history_before_effects(tmp_path):
    from langchain_core.messages import HumanMessage, SystemMessage
    ctx = context_api()
    _, _, session, _ = task_files(tmp_path)
    session.set_request((SystemMessage(content="s"), HumanMessage(content="task")), ctx.RequestBinding((), {}))
    history = []
    for index in range(5):
        history.extend([AIMessage(content="", tool_calls=[read_call(f"old-{index}")]),
                        ToolMessage(content=json.dumps({"ok": True, "content": "x" * 12000}),
                                    name="FileReadTool", tool_call_id=f"old-{index}")])
    prepared = session.prepare(history, [])
    assert ctx.measure_request(prepared, session.binding) < ctx.POLICY.trigger
    response = AIMessage(content="original response", tool_calls=[{
        "name": "FileWriteTool", "id": "new", "args": {"file_path": "src/new.py", "content": "y" * 35000},
    }])
    assert ctx.measure_request([*prepared, response], session.binding) > ctx.POLICY.hard
    plan = session.plan_group(response, prepared, [])
    assert plan.response is response and plan.calls[0]["args"]["content"] == "y" * 35000
    assert [m.tool_call_id for m in plan.history if isinstance(m, ToolMessage)] == ["old-3", "old-4"]
    assert sum(plan.minimum) <= plan.remaining


def test_empty_summary_does_not_return_task_capsule(tmp_path):
    state, context, _, _, _ = loop_state(tmp_path, [{"content": ""}])
    from mokioclaw.core.task_closeout import TaskCloseoutError
    with pytest.raises(TaskCloseoutError, match="^task_closeout_incomplete$"):
        run_loop(state, context)
    assert context.provider_calls == 1


def test_grep_result_tail_cannot_complete_upstream_limited_search(tmp_path):
    tools, services, session, _ = task_files(tmp_path, ("needle" + "x" * 1000 + "\n") * 30)
    page = tools.grep("needle", "src/a.py", head_limit=20)
    assert page["truncated"] is True
    cursor = page["result_windows"]["matches"]["next_result_read"]["cursor"]
    while cursor:
        page = services.read_result(cursor, 200)
        cursor = (page.get("next_result_read") or {}).get("cursor")
    assert page["content_truncated"] is False
    assert page["upstream_complete"] is False and page["complete"] is False
    assert session.coverage.intervals("src/a.py") == ()


def test_many_small_tools_are_not_reserved_as_n_times_16k(tmp_path):
    calls = [read_call(f"r{i}") for i in range(6)]
    state, context, model, services, _ = loop_state(tmp_path, [{"tool_calls": calls}, {"content": "done"}])
    result = run_loop(state, context)
    tools = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tools) == 6 and result["summary"] == "done"
    assert sum(len(context_api().canonical_json(context_api().message_payload(m))) for m in tools) <= 32768
    assert all(len(context_api().canonical_json(context_api().message_payload(m))) <= 16384 for m in tools)
    assert max(model.sizes) <= 98304 and context.provider_calls == 2
    assert services.session is None and "ToolResultReadTool" in model.names


def test_one_large_result_uses_cursor(tmp_path, monkeypatch):
    import mokioclaw.dashboard.task_graph as graph
    executions = []
    def fake_bash(*args, **kwargs):
        executions.append(1)
        return {"ok": True, "exit_code": 0, "command_request_id": "x" * 24,
                "stdout": '中"\\' * 20000, "stderr": "", "output_truncated": False}
    monkeypatch.setattr(graph, "run_task_bash", fake_bash)
    def decisions(index, messages):
        if index == 0:
            return {"tool_calls": [{"id": "bash", "name": "BashTool", "args": {"command": "echo fixture"}}]}
        value = json.loads(messages[-1].content)
        assert len(context_api().canonical_json(context_api().message_payload(messages[-1]))) <= 16384
        if index == 1:
            window = value["result_windows"]["stdout"]
            return {"tool_calls": [{"id": "page", "name": "ToolResultReadTool",
                                   "args": window["next_result_read"]}]}
        assert value["content_truncated"] and not value["complete"]
        return {"content": "done"}
    state, context, model, _, _ = loop_state(tmp_path, decisions)
    assert run_loop(state, context)["ok"]
    assert executions == [1] and model.calls == 3


def test_impossible_group_stops_before_first_effect(tmp_path, monkeypatch):
    import mokioclaw.dashboard.task_graph as graph
    effects = []
    monkeypatch.setattr(graph, "run_task_bash", lambda *a, **k: effects.append("approval"))
    calls = [{"id": "edit", "name": "FileEditTool",
              "args": {"file_path": "src/a.py", "old_text": "original", "new_text": "x" * 100000}},
             {"id": "bash", "name": "BashTool", "args": {"command": "echo fixture"}}]
    state, context, model, services, work = loop_state(tmp_path, [{"tool_calls": calls}])
    with pytest.raises(context_api().TaskContextError, match="^task_context_error$"):
        run_loop(state, context)
    assert (work / "src/a.py").read_bytes() == b"original\n" and effects == []
    assert model.calls == 1 and context.reported_tokens == 2 and services.session is None


def test_actual_minimum_group_overflow_has_zero_write_or_approval(tmp_path, monkeypatch):
    import mokioclaw.dashboard.task_graph as graph
    effects = []
    monkeypatch.setattr(graph, "run_task_bash", lambda *a, **k: effects.append("approval"))
    calls = [{"id": "edit", "name": "FileEditTool",
              "args": {"file_path": "src/a.py", "old_text": "original", "new_text": "changed"}},
             *[read_call(f"r{i}") for i in range(12)],
             {"id": "bash", "name": "BashTool", "args": {"command": "echo fixture"}}]
    state, context, model, _, work = loop_state(tmp_path, [{"tool_calls": calls}])
    with pytest.raises(context_api().TaskContextError):
        run_loop(state, context)
    assert effects == [] and (work / "src/a.py").read_bytes() == b"original\n"
    assert model.calls == 1 and context.reported_tokens == 2


def test_huge_ai_args_are_never_cut(tmp_path):
    from langchain_core.tools import StructuredTool
    original = '中"\\' * 5000
    lengths = []
    def inspect(value: str):
        lengths.append(len(value))
        assert value == original
        return {"ok": True}
    state, context, _, _, _ = loop_state(tmp_path, [
        {"tool_calls": [{"id": "inspect", "name": "InspectTool", "args": {"value": original}}]},
        {"content": "done"}])
    context.task_tools.append(StructuredTool.from_function(inspect, name="InspectTool", description="Synthetic"))
    assert run_loop(state, context)["ok"] and lengths == [len(original)]


def test_task_internal_history_is_bounded(tmp_path):
    def decisions(index, messages):
        if index == 15:
            return {"content": "read only; no changes or checks"}
        return {"tool_calls": [read_call(f"r{index}")]}
    state, context, model, _, _ = loop_state(tmp_path, decisions, text="x" * 100000)
    result = run_loop(state, context)
    assert model.calls == 16 and len(result["tool_events"]) <= 8
    assert len([m for m in result["messages"] if isinstance(m, ToolMessage)]) <= 2
    assert max(model.sizes) <= 98304
    assert result["summary"] == "read only; no changes or checks"


def test_normal_code_agent_is_unchanged(tmp_path):
    from mokioclaw.agents.code_agent import run_code_agent
    from mokioclaw.core.state import RuntimeState
    model = ScriptedModel([{"tool_calls": [{"id": "u", "name": "UnknownTool", "args": {}}]},
                           {"content": "ordinary summary"}])
    runtime = RuntimeState(workspace=tmp_path, checkpoint_mode="off", trace_mode="off")
    result = run_code_agent({"runtime": runtime, "task": "ordinary"}, "instruction",
                            model_override=model, tools_override=[])
    assert len(result["messages"]) == 3 and len(result["tool_events"]) == 1
    assert result["summary"] == "ordinary summary" and model.names == ["TodoUpdateTool"]


@pytest.mark.parametrize("variant", ["cjk", "emoji"])
def test_legal_large_anchor_is_rejected_before_model_or_effects(tmp_path, variant):
    marker = {"cjk": "中", "emoji": "😀"}[variant]
    commands = tuple("echo " + marker * 1995 for _ in range(10))
    state, context, model, services, work = loop_state(tmp_path, [], task=marker * 4000, commands=commands)
    with pytest.raises(context_api().TaskContextError, match="^task_context_error$"):
        run_loop(state, context)
    assert model.calls == context.provider_calls == context.reported_tokens == 0
    assert services.session is None and (work / "src/a.py").read_bytes() == b"original\n"


def test_model_final_binding_and_invoke_options_gate_at_exact_bytes(tmp_path):
    ctx = context_api()
    state, context, model, services, _ = loop_state(tmp_path, [{"content": "done"}])
    from mokioclaw.agents.code_agent import _task_context_anchors
    session = services.begin_delegation(1)
    selected = context.task_tools
    anchors = _task_context_anchors(state, "synthetic instruction")
    binding = ctx.request_binding(selected, tool_choice="auto")
    session.set_request(anchors, binding)
    bound = context.model(stage="code_agent").bind_tools(selected, tool_choice="auto")
    messages = session.prepare([], [])
    options = {"synthetic_option": "x" * 100}
    messages.append(AIMessage(content=""))
    padding = 98304 - ctx.measure_request(messages, binding, invocation_options=options)
    messages[-1] = AIMessage(content="x" * padding)
    assert ctx.measure_request(messages, binding, invocation_options=options) == 98304
    bound.invoke(messages, **options)
    assert model.calls == context.provider_calls == 1
    messages[-1] = AIMessage(content="x" * (padding + 1))
    with pytest.raises(ctx.TaskContextError):
        bound.invoke(messages, **options)
    assert model.calls == context.provider_calls == 1
    services.close_delegation()
    with pytest.raises(ctx.TaskContextError):
        bound.invoke(messages)
    assert model.calls == 1


def test_invoke_options_are_part_of_anchor_admission(tmp_path):
    from mokioclaw.agents.code_agent import _task_context_anchors
    state, context, model, services, _ = loop_state(tmp_path, [{"content": "done"}])
    session = services.begin_delegation(1)
    selected = context.task_tools
    session.set_request(_task_context_anchors(state, "instruction"), context_api().request_binding(selected))
    bound = context.model(stage="code_agent").bind_tools(selected)
    messages = session.prepare([], [])
    with pytest.raises(context_api().TaskContextError):
        bound.invoke(messages, synthetic_option="x" * 49152)
    assert model.calls == context.provider_calls == 0


def test_giant_final_summary_is_not_returned_as_success(tmp_path):
    state, context, model, services, _ = loop_state(tmp_path, [{"content": "x" * 100000}])
    with pytest.raises(context_api().TaskContextError):
        run_loop(state, context)
    assert model.calls == context.provider_calls == 1 and context.reported_tokens == 2
    assert services.session is None


@pytest.mark.parametrize("error,retry,recovery", [
    ("task_read_window_invalid", True, "correct_window"),
    ("task_read_revision_changed", False, "reread_current_revision"),
    ("task_write_coverage_required", False, "reread_current_revision"),
    ("result_unavailable", False, "rerun_source_tool_or_reread"),
])
def test_window_errors_have_distinct_recovery(tmp_path, error, retry, recovery):
    from mokioclaw.agents.code_agent import execute_code_agent_tool
    from langchain_core.tools import StructuredTool
    state, context, _, _, _ = loop_state(tmp_path, [])
    fake = StructuredTool.from_function(lambda: context_api().recovery_result(error),
                                       name="FileReadTool", description="Synthetic recovery")
    message, _ = execute_code_agent_tool(state["runtime"], [], {"id": "r", "name": fake.name, "args": {}},
                                        tools_override=[fake])
    value = json.loads(message.content)
    assert value["retry_same_operation"] is retry and value["recovery"] == recovery


@pytest.mark.parametrize("kind", ["task_tool_failed", "verification_command_failed", "provider_failed",
                                  "provider_auth_failed", "usage_unavailable", "provider_budget_exhausted"])
def test_terminal_root_survives_context_and_finally_error(tmp_path, kind):
    from mokioclaw.dashboard.task_worker import run_projected_workflow
    from mokioclaw.dashboard.task_executor import TaskExecutionError
    from mokioclaw.providers.openai_provider import TaskProviderError
    state, context, _, _, work = loop_state(tmp_path, [])
    context.record_terminal_root(kind)
    context.record_terminal_root("task_tool_failed")
    snapshots = []
    def snapshot():
        snapshots.append(1)
        raise context_api().TaskContextError("result_capacity")
    context.usage_snapshot = snapshot
    def stream(*args, **kwargs):
        raise context_api().TaskContextError("input_too_large")
        yield
    expected = TaskExecutionError if kind in {"task_tool_failed", "verification_command_failed"} else TaskProviderError
    with pytest.raises(expected, match=f"^{kind}$"):
        run_projected_workflow(state["task"], work, context, lambda _: None, stream=stream)
    assert snapshots == [1]


@pytest.mark.parametrize("stop", ["usage", "budget"])
def test_known_budget_or_usage_wins_context_stop(tmp_path, stop):
    from mokioclaw.dashboard.task_worker import run_projected_workflow
    from mokioclaw.providers.openai_provider import TaskProviderError
    state, context, _, _, work = loop_state(tmp_path, [])
    if stop == "usage":
        context._usage_unavailable = True
        expected = "usage_unavailable"
    else:
        context.provider_calls = context.max_provider_calls
        expected = "provider_budget_exhausted"
    def stream(*args, **kwargs):
        raise context_api().TaskContextError("unsupported_content")
        yield
    snapshots = []
    with pytest.raises(TaskProviderError, match=f"^{expected}$"):
        run_projected_workflow(state["task"], work, context, snapshots.append, stream=stream)
    assert len(snapshots) == 1 and snapshots[0]["kind"] == "budget_usage"


@pytest.mark.parametrize("error", ["task_file_access_denied", "approval_denied_or_expired", "gateway_failed"])
def test_real_terminal_tool_root_precedes_projection_context_error(tmp_path, monkeypatch, error):
    from mokioclaw.dashboard.task_worker import run_projected_workflow
    from mokioclaw.dashboard.task_executor import TaskExecutionError
    import mokioclaw.dashboard.task_graph as graph
    def fake_bash(*args, **kwargs):
        return {"ok": False, "error": error, "stdout": "", "stderr": ""}
    monkeypatch.setattr(graph, "run_task_bash", fake_bash)
    state, context, _, _, work = loop_state(tmp_path, [
        {"tool_calls": [{"id": "b", "name": "BashTool", "args": {"command": "echo fixture"}}]}])
    def writer(event):
        if event["type"] == "task_tool_failure":
            raise context_api().TaskContextError("unsupported_content")
    def stream(*args, **kwargs):
        run_loop(state, context, writer=writer)
        yield
    snapshots = []
    with pytest.raises(TaskExecutionError, match="^task_tool_failed$"):
        run_projected_workflow(state["task"], work, context, snapshots.append, stream=stream)
    assert len(snapshots) == 1 and context.resolve_context_failure(context_api().TaskContextError("result_capacity")) == "task_tool_failed"


class MemoryChannel:
    def __init__(self, incoming=b""):
        self.incoming = bytearray(incoming)
        self.outgoing = bytearray()
    def sendall(self, data):
        self.outgoing.extend(data)
    def recv(self, count):
        data = bytes(self.incoming[:count])
        del self.incoming[:count]
        return data
    def settimeout(self, value):
        pass
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


@pytest.mark.parametrize("reason", ["input_too_large", "invalid_message_group", "result_capacity", "unsupported_content"])
def test_context_failure_round_trips_fixed_kind_only(monkeypatch, reason):
    import mokioclaw.dashboard.task_worker as worker
    initial = MemoryChannel()
    worker._send(initial, {"kind": "ready"})
    worker._send(initial, {"kind": "start", "task_id": "task_1234567890123456"})
    channel = MemoryChannel(initial.outgoing)
    def runner(*args):
        raise context_api().TaskContextError(reason)
    # Restore the injected memory transport before the outer guard exits.
    with monkeypatch.context() as channel_patch:
        channel_patch.setattr(worker.socket, "create_connection", lambda *a, **k: channel)
        worker._worker_main(1, token_line="x" * 32, run_task=runner)
    frames = MemoryChannel(channel.outgoing)
    assert worker._receive(frames)["kind"] == "hello"
    assert worker._receive(frames) == {"kind": "started"}
    done = []
    worker.consume_worker_messages(frames, "task_1234567890123456", lambda _: None, done.append)
    assert done == [{"outcome": "failed", "failure_kind": "task_context_error"}]
    assert reason.encode() not in channel.outgoing


def test_task_context_exception_passes_planner_and_verifier_dispatch(tmp_path, monkeypatch):
    from langchain_core.tools import StructuredTool
    from mokioclaw.graph import nodes
    state, context, _, _, _ = loop_state(tmp_path, [])
    def fail():
        raise context_api().TaskContextError("result_capacity")
    tool = StructuredTool.from_function(fail, name="FileReadTool", description="Synthetic context stop")
    monkeypatch.setattr(nodes, "_build_planner_tools", lambda *a: [tool])
    context.task_tools = [tool]
    for dispatch in (lambda: nodes._execute_planner_tool(state, lambda _: None, {"id": "p", "name": tool.name, "args": {}}),
                     lambda: nodes._execute_read_only_tool(state, {"id": "v", "name": tool.name, "args": {}})):
        with pytest.raises(context_api().TaskContextError, match="^task_context_error$"):
            dispatch()


@pytest.mark.parametrize("limit", [True, 1.5], ids=["bool", "fraction"])
def test_result_read_keeps_invalid_limits_recoverable(tmp_path, limit):
    from mokioclaw.dashboard.task_graph import build_task_result_read_tool
    _, services, _, _ = task_files(tmp_path)
    result = services.feedback("BashTool", {"ok": True, "exit_code": 0, "stdout": "x" * 30000, "stderr": ""})
    cursor = result["result_windows"]["stdout"]["next_result_read"]["cursor"]
    page = build_task_result_read_tool(services).invoke({"cursor": cursor, "limit": limit})
    assert page.get("error") == "task_read_window_invalid" and page["retry_same_operation"]


def test_provider_failure_and_cleanup_context_error_keep_provider_kind(tmp_path, monkeypatch):
    from mokioclaw.dashboard.task_worker import run_projected_workflow
    from mokioclaw.providers.openai_provider import TaskProviderError
    state, context, model, services, work = loop_state(tmp_path, [])
    def provider_failure(*args, **kwargs):
        import httpx
        import openai
        raise openai.AuthenticationError("synthetic error", response=httpx.Response(
            401, request=httpx.Request("POST", "https://offline.invalid")), body=None)
    monkeypatch.setattr(model, "invoke", provider_failure)
    original_close = services.close_delegation
    def failing_close():
        original_close()
        raise context_api().TaskContextError("result_capacity")
    monkeypatch.setattr(services, "close_delegation", failing_close)
    def stream(*args, **kwargs):
        run_loop(state, context)
        yield
    with pytest.raises(TaskProviderError, match="^provider_auth_failed$"):
        run_projected_workflow(state["task"], work, context, lambda _: None, stream=stream)
    assert services.session is None and context.provider_calls == 1


def test_recoverable_feedback_does_not_lock_terminal_root(tmp_path, monkeypatch):
    import mokioclaw.dashboard.task_graph as graph
    monkeypatch.setattr(graph, "run_task_bash", lambda *a, **k: {"ok": False, "exit_code": 1, "stdout": "", "stderr": ""})
    state, context, _, _, _ = loop_state(tmp_path, [
        {"tool_calls": [{"id": "b", "name": "BashTool", "args": {"command": "echo fixture"}}]},
        {"tool_calls": [{"id": "e", "name": "FileEditTool",
                         "args": {"file_path": "src/a.py", "old_text": "absent", "new_text": "x"}}]},
        {"content": "done"}])
    assert run_loop(state, context)["ok"]
    assert context.resolve_context_failure(context_api().TaskContextError("input_too_large")) == "task_context_error"


class GraphScript:
    def __init__(self):
        self.calls = 0
        self.code_calls = 0
        self.code_tools = []
        self.verifier_calls = 0

    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, messages, **kwargs):
        self.calls += 1
        system = messages[0].content
        calls, content = [], ""
        if "intent router" in system:
            content = '{"route":"workflow","reason":"synthetic","confidence":0.99}'
        elif "planner/supervisor" in system:
            if not any(isinstance(m, ToolMessage) for m in messages):
                calls = [
                    {"id": "todo", "name": "TodoWriteTool", "args": {"todos": ["repair existing file"],
                     "acceptance_criteria": ["file is good"], "verification_commands": ["python -m pytest -q"],
                     "plan_summary": "synthetic plan"}},
                    {"id": "delegate", "name": "CallCodeAgentTool", "args": {"instruction": "ARGUMENT_SENTINEL"}},
                ]
            else:
                content = "planner closed"
        elif "codeAgent" in system:
            self.code_calls += 1
            previous = messages[-1] if isinstance(messages[-1], ToolMessage) else None
            value = json.loads(previous.content) if previous else {}
            name, args = "FileWriteTool", {"file_path": "src/a.py", "content": "bad\n"}
            if previous and previous.name == "FileWriteTool":
                if value["ok"]:
                    name, args = "BashTool", {"command": "python -m pytest -q"}
                else:
                    assert value["error"] == "task_write_coverage_required"
                    name, args = "FileReadTool", {"file_path": "src/a.py"}
            elif previous and previous.name == "FileReadTool":
                if not value["coverage_complete"]:
                    assert value["next_read"] and not value["complete"]
                    name, args = "FileReadTool", value["next_read"]
            elif previous and previous.name == "BashTool":
                if value["exit_code"] == 1:
                    name, args = "FileEditTool", {"file_path": "src/a.py", "old_text": "bad", "new_text": "good"}
                else:
                    content, name = "PROVIDER_SENTINEL", None
            elif previous and previous.name == "FileEditTool":
                name, args = "BashTool", {"command": "python -m pytest -q"}
            if name:
                self.code_tools.append(name)
                calls = [{"id": f"code{self.code_calls}", "name": name, "args": args}]
        elif "You are verifier" in system:
            self.verifier_calls += 1
            content = '{"passed":true,"reason":"synthetic verdict","checks":[]}'
        else:
            raise AssertionError("unexpected_synthetic_stage")
        return AIMessage(content=content, tool_calls=calls,
                         usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})


def graph_fixture(tmp_path, *, max_calls=24):
    from mokioclaw.dashboard.task_approval import ApprovalBroker
    from mokioclaw.dashboard.task_executor import TaskCommandGateway
    from mokioclaw.dashboard.task_graph import build_task_graph_tools
    from mokioclaw.dashboard.task_models import ExecutionReceipt
    state, context, _, services, work = loop_state(tmp_path, [], text="SOURCE_SENTINEL\n" + "x" * 12000,
                                                commands=("python -m pytest -q",))
    context.task_filesystem.prepared.task_id = "task_1234567890123456"
    context.max_provider_calls = max_calls
    model = GraphScript()
    context._model_factory = lambda: model
    decisions, receipts = [], []
    def approve(request):
        assert request.task_id == "task_1234567890123456" and request.attempt_id == 1
        assert request.command == "python -m pytest -q" and request.network == "none"
        digest = request.canonical_digest()
        decisions.append((request.command_request_id, digest, request.command))
        assert broker.decide(request.task_id, request.attempt_id, request.command_request_id, digest, True)
    broker = ApprovalBroker(wait_timeout_seconds=1, on_request=approve)
    class FakeExecutor:
        def execute(self, request):
            assert decisions[-1][:2] == (request.command_request_id, request.canonical_digest())
            code = 0 if (work / "src/a.py").read_bytes() == b"good\n" else 1
            return {"ok": code == 0, "exit_code": code, "stdout": "COMMAND_SENTINEL",
                    "stderr": "", "duration_ms": 1, "output_truncated": False}
    def receipt(request, result):
        receipts.append(ExecutionReceipt(request.attempt_id, request.command_request_id,
                        hashlib.sha256(request.command.encode()).hexdigest(), request.canonical_digest(),
                        result["exit_code"], result["duration_ms"], result["ok"], result["output_truncated"]))
    gateway = TaskCommandGateway(task_id=context.task_filesystem.prepared.task_id, attempt_id=1, workspace=work,
                                 image_digest="sha256:" + "a" * 64, broker=broker, executor=FakeExecutor(),
                                 record_receipt=receipt)
    context.task_gateway = gateway
    context.task_tools = build_task_graph_tools(context.task_filesystem, gateway, work, services=services)
    return context, model, services, work, decisions, receipts


def test_reread_then_edit_selftest_and_formal_verifier(tmp_path):
    from mokioclaw.dashboard.task_worker import run_projected_workflow
    context, model, services, work, decisions, receipts = graph_fixture(tmp_path)
    events = []
    run_projected_workflow("TASK_SENTINEL", work, context, events.append, max_attempts=1)
    assert (work / "src/a.py").read_bytes() == b"good\n"
    assert model.code_tools == ["FileWriteTool", "FileReadTool", "FileReadTool",
                                "FileWriteTool", "BashTool", "FileEditTool", "BashTool"]
    assert [r.exit_code for r in receipts] == [1, 0, 0]
    assert len(decisions) == len({d[0] for d in decisions}) == len({d[1] for d in decisions}) == 3
    assert all(d[2] == "python -m pytest -q" for d in decisions)
    verification = [e for e in events if e["kind"] == "verification"]
    assert len(verification) == 1 and verification[0]["status"] == "passed"
    assert verification[0]["request_id"] == receipts[-1].command_request_id
    assert model.verifier_calls == 1 and services.session is None
    assert events[-2]["kind"] == "budget_usage" and events[-1]["phase"] == "complete"
    assert context.provider_calls == model.calls == 12


@pytest.mark.parametrize("point,stop_call,expected_receipts", [("summary", 9, 2), ("planner", 10, 2), ("verifier", 11, 3)])
def test_budget_blocks_each_closeout_call(tmp_path, monkeypatch, point, stop_call, expected_receipts):
    from mokioclaw.dashboard.task_worker import run_projected_workflow
    from mokioclaw.providers.openai_provider import TaskProviderError
    # Call reservation now stops repair before these old small-call gates.
    # A last-response token overshoot still exercises the original hard gate
    # at the same three exact workflow positions, with no forecast bypass.
    context, model, _, work, _, receipts = graph_fixture(tmp_path)
    original_invoke = model.invoke
    def overshoot(messages, **kwargs):
        response = original_invoke(messages, **kwargs)
        if model.calls == stop_call:
            response.usage_metadata = {"input_tokens": 150000, "output_tokens": 0, "total_tokens": 150000}
        return response
    monkeypatch.setattr(model, "invoke", overshoot)
    events = []
    with pytest.raises(TaskProviderError, match="^provider_budget_exhausted$"):
        run_projected_workflow("TASK_SENTINEL", work, context, events.append, max_attempts=1)
    assert context.provider_calls == model.calls == stop_call
    assert len(receipts) == expected_receipts and model.verifier_calls == 0
    assert [e["kind"] for e in events].count("budget_usage") == 1
    assert not any(e.get("phase") == "complete" for e in events)
    verification = [e for e in events if e["kind"] == "verification"]
    assert len(verification) == (1 if point == "verifier" else 0)
    if verification:
        assert verification[0]["request_id"] == receipts[-1].command_request_id
        assert verification[0]["status"] == "passed"
    snapshot = context.usage_snapshot()
    assert snapshot["code_agent_calls"] == (7 if point == "summary" else 8)
    assert snapshot["planner_calls"] == (2 if point == "verifier" else 1)


def test_private_sentinels_never_leave_projection(tmp_path, caplog):
    from mokioclaw.dashboard.task_worker import run_projected_workflow
    from mokioclaw.core.agent import create_runtime
    context, _, _, work, _, _ = graph_fixture(tmp_path)
    events = []
    run_projected_workflow("TASK_SENTINEL", work, context, events.append, max_attempts=1)
    for sentinel in ("TASK_SENTINEL", "SOURCE_SENTINEL", "ARGUMENT_SENTINEL", "COMMAND_SENTINEL", "PROVIDER_SENTINEL"):
        assert sentinel not in json.dumps(events) and sentinel not in caplog.text
    runtime = create_runtime(work, task_context=context)
    assert runtime.trace_mode == runtime.checkpoint_mode == "off"
    assert sorted(p.relative_to(work).as_posix() for p in work.rglob("*") if p.is_file()) == ["src/a.py"]


def test_normal_cli_tui_contract_unchanged(tmp_path):
    from mokioclaw.core.state import RuntimeState
    from mokioclaw.tools.file_tools import read_file
    runtime = RuntimeState(workspace=tmp_path, trace_mode="off", checkpoint_mode="off")
    (tmp_path / "long.py").write_bytes(b"x" * 100000)
    page = read_file(runtime, "long.py", limit=1)
    assert page["complete"] and len(page["content"]) == 100003 and "next_read" not in page
    (tmp_path / "lines.py").write_bytes(b"x\n" * 2050)
    page = read_file(runtime, "lines.py")
    assert page["limit"] == 2000 and not page["complete"]


def task_files(tmp_path, text="original\n"):
    from mokioclaw.dashboard.task_filesystem import TaskFilesystem
    from mokioclaw.dashboard.task_tools import TaskFileTools
    ctx = context_api()
    work = tmp_path / "work"
    (work / "src").mkdir(parents=True)
    (work / "src/a.py").write_bytes(text.encode())
    prepared = SimpleNamespace(task_id="offline", work=work)
    fs = TaskFilesystem(prepared, ("src/",), ("src/",), ".mokioclaw/task-scratch/")
    services = ctx.TaskToolServices(fs, ctx.TaskContextPolicy())
    session = services.begin_delegation(1)
    return TaskFileTools(fs, services=services), services, session, work


def source_of(page):
    # One displayed line per metadata fragment; prefixes are presentation only.
    lines = page["content"].split("\n") if page["line_metadata"] else []
    value = ""
    for display, metadata in zip(lines, page["line_metadata"], strict=True):
        prefix = f'{metadata["line"] + 1}: ' + ("[line_fragment] " if metadata["fragment"] else "")
        assert display.startswith(prefix)
        value += display[len(prefix):] + {"LF": "\n", "CRLF": "\r\n", "CR": "\r", "none": ""}[metadata["line_ending"]]
    return value


def test_multipage_coverage_is_gap_sensitive():
    ledger = context_api().CoverageLedger()
    assert not ledger.record_visible("a", "r", 90, 100, eof=100).coverage_complete
    assert not ledger.record_visible("a", "r", 0, 40, eof=None).coverage_complete
    assert not ledger.record_visible("a", "r", 50, 90, eof=None).coverage_complete
    assert ledger.record_visible("a", "r", 40, 50, eof=None).coverage_complete
    assert ledger.record_visible("a", "r", 0, 100, eof=100).coverage_complete
    assert ledger.record_visible("empty", "r", 0, 0, eof=0).coverage_complete


@pytest.mark.parametrize("source", ["x" * 100000, '中😀\"\t' * 10000 + "\r\nlast\r", "a\r\nb\nc\rfinal", ""],
                         ids=["long_ascii", "long_unicode", "line_endings", "empty"])
def test_long_line_unicode_crlf_round_trip(tmp_path, source):
    tools, _, _, _ = task_files(tmp_path, source)
    page = tools.read("src/a.py", limit=1)
    restored = source_of(page)
    pages = 1
    while page["next_read"]:
        assert not page["complete"]
        old_end = page["end"]
        page = tools.read(**page["next_read"])
        assert page["end"] > old_end
        assert len(page["content"].encode()) <= 8192
        assert len(json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode()) <= 16384
        restored += source_of(page)
        pages += 1
    assert restored == source
    assert page["eof"] and page["coverage_complete"]
    if pages > 1:
        assert not page["complete"]


def test_final_visible_page_only_contributes_coverage(tmp_path, monkeypatch):
    tools, services, session, _ = task_files(tmp_path, '"' * 20000)
    monkeypatch.setattr(services, "result_json_budget", lambda: 1600)
    page = tools.read("src/a.py")
    assert len(json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode()) <= 1600
    assert 0 < page["end"] < 8192
    assert not page["coverage_complete"]
    assert session.coverage.intervals("src/a.py") == ((0, page["end"]),)


def test_revision_change_invalidates_receipt(tmp_path):
    tools, _, session, work = task_files(tmp_path, "x" * 20000)
    page = tools.read("src/a.py")
    (work / "src/a.py").write_bytes(b"changed")
    changed = tools.read(**page["next_read"])
    assert changed["error"] == "task_read_revision_changed"
    assert not changed["retry_same_operation"]
    assert session.coverage.intervals("src/a.py") == ()


def test_write_requires_current_complete_coverage(tmp_path):
    tools, services, _, work = task_files(tmp_path)
    denied = tools.write("src/a.py", "new")
    assert denied["error"] == "task_write_coverage_required"
    assert (work / "src/a.py").read_bytes() == b"original\n"
    assert tools.read("src/a.py")["coverage_complete"]
    assert tools.write("src/a.py", "new")["ok"]
    assert tools.write("src/a.py", "another")["error"] == "task_write_coverage_required"
    services.close_delegation()
    assert not tools.read("src/a.py")["coverage_complete"]
    services.begin_delegation(2)
    assert tools.write("src/a.py", "another")["error"] == "task_write_coverage_required"


def test_write_checks_revision_before_truncate(tmp_path):
    from mokioclaw.dashboard import task_filesystem
    tools, _, _, work = task_files(tmp_path)
    fs = tools.fs
    revision = hashlib.sha256(fs.read_bytes("src/a.py")).hexdigest()
    (work / "src/a.py").write_bytes(b"different")
    with pytest.raises(task_filesystem.TaskFileRevisionChanged):
        fs.write_bytes("src/a.py", b"new", expected_revision=revision)
    assert (work / "src/a.py").read_bytes() == b"different"
    # Descriptor must have been closed even on the mismatch.
    fs.write_bytes("src/a.py", b"next", expected_revision=hashlib.sha256(b"different").hexdigest())
    assert fs.read_bytes("src/a.py") == b"next"


def test_coverage_limits_revoke_proof():
    ledger = context_api().CoverageLedger(max_files=1, max_intervals_per_file=1, max_metadata_bytes=10000)
    assert ledger.record_visible("a", "r", 0, 1, eof=1).coverage_complete
    ledger.record_visible("b", "r", 0, 1, eof=None)
    assert ledger.intervals("a") == ()
    ledger.record_visible("b", "r", 3, 4, eof=4)
    assert ledger.intervals("b") == ()


def test_result_read_is_code_agent_only(tmp_path):
    from mokioclaw.dashboard.task_graph import build_task_graph_tools, build_task_result_read_tool
    tools, services, _, work = task_files(tmp_path)
    registry = build_task_graph_tools(tools.fs, None, work, services=services)
    assert "ToolResultReadTool" not in {tool.name for tool in registry}
    reader = build_task_result_read_tool(services)
    assert set(reader.args_schema.model_fields) == {"cursor", "limit"}


def test_grep_context_uses_revision_and_file_read(tmp_path):
    tools, _, session, _ = task_files(tmp_path, "x" * 2100 + "needle\nneedle\n")
    result = tools.grep("needle", "src/a.py")
    assert result["searched_prefix_only"]
    assert [item["line"] for item in result["matches"]] == [2]
    assert result["matches"][0]["revision"] == hashlib.sha256(("x" * 2100 + "needle\nneedle\n").encode()).hexdigest()
    assert session.coverage.intervals("src/a.py") == ()


def test_diff_capacity_checked_before_write(tmp_path):
    tools, services, session, work = task_files(tmp_path, "old\n" * 3000)
    session.results.max_bytes = 100
    tools.read("src/a.py")
    with pytest.raises(context_api().TaskContextError):
        tools.edit("src/a.py", "old\n" * 3000, "new\n" * 3000)
    assert (work / "src/a.py").read_bytes() == ("old\n" * 3000).encode()
    assert session.results.payload_bytes == 0
    assert services.session is session


def test_large_diff_is_complete_and_only_executed_result_is_exposed(tmp_path):
    tools, _, session, _ = task_files(tmp_path, "old\n" * 3000)
    result = tools.edit("src/a.py", "old\n" * 3000, "new\n" * 3000)
    assert result["ok"] and result["result_windows"]["diff"]["original_length"] > 4000
    restored = result["diff"]
    cursor = result["result_windows"]["diff"]["next_result_read"]["cursor"]
    while cursor:
        page = session.results.read(cursor, 8192, identity=session.identity, json_budget=16384)
        restored += page["content"]
        cursor = (page["next_result_read"] or {}).get("cursor")
    assert restored.count("+new") == 3000 and restored.count("-old") == 3000


def test_bash_upstream_tail_is_not_recoverable(tmp_path):
    from mokioclaw.dashboard.task_graph import build_task_graph_tools
    tools, services, _, work = task_files(tmp_path)

    class Gateway:
        task_gateway = True
        calls = 0

        def run(self, **kwargs):
            self.calls += 1
            return {"ok": True, "exit_code": 0, "stdout": "x" * 20000, "stderr": "", "output_truncated": True,
                    "command_request_id": "fixture-request"}

    gateway = Gateway()
    bash = next(tool for tool in build_task_graph_tools(tools.fs, gateway, work, services=services)
                if tool.name == "BashTool")
    result = bash.invoke({"command": "fixture"})
    assert gateway.calls == 1 and result["command_request_id"] == "fixture-request"
    assert result["upstream_output_truncated"] and not result["upstream_complete"]
    assert not result["complete"]


def test_services_identity_is_required(tmp_path):
    from mokioclaw.core.agent import TaskRunContext
    tools, services, _, _ = task_files(tmp_path)
    ctx = TaskRunContext.for_fake_model(object(), max_provider_calls=1, max_total_tokens=1,
                                       max_output_tokens_per_call=1)
    with pytest.raises(context_api().TaskContextError):
        ctx.attach_tools(object(), [object()], services=services)
    with pytest.raises(TypeError):
        ctx.attach_tools(tools.fs, [object()])


@pytest.mark.parametrize("value", [True, 1.5], ids=["boolean", "fraction"])
def test_window_schema_does_not_coerce_invalid_coordinates(tmp_path, value):
    from mokioclaw.dashboard.task_tools import build_task_file_tools
    tools, services, _, _ = task_files(tmp_path)
    reader = next(tool for tool in build_task_file_tools(tools.fs, services=services) if tool.name == "FileReadTool")
    result = reader.invoke({"file_path": "src/a.py", "limit": value})
    assert result["error"] == "task_read_window_invalid"
