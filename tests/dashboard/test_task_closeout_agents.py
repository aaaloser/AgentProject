import pytest

from task_closeout_fakes import ScriptedCloseoutModel, offline_closeout_guard
from test_task_context_flow import loop_state, read_call, run_loop
from mokioclaw.core.task_closeout import TaskCloseoutError


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    with offline_closeout_guard(monkeypatch):
        yield


def state_with_script(tmp_path, script):
    state, context, _, services, work = loop_state(tmp_path, [])
    model = ScriptedCloseoutModel(script)
    context._model_factory = lambda: model
    return state, context, model, services, work


def test_code_agent_switches_before_eighth_remaining_call(tmp_path):
    def check(messages, binding):
        assert binding.tools == ()
        assert not binding.options.get("tool_choice")
        assert "synthetic acceptance" in messages[1].content
        assert "echo fixture" in messages[1].content
    state, context, model, _, _ = state_with_script(
        tmp_path, [{"tool_calls": [read_call("read")]}, {"content": "unfinished; read only", "check": check}])
    context.provider_calls = 16  # Eight calls left; one repair leaves seven.
    result = run_loop(state, context)
    assert result["summary"] == "unfinished; read only"
    assert context.provider_calls == 18 and model.calls == 2
    assert context.closeout.remaining_calls == 6
    assert [m.tool_call_id for m in result["messages"] if hasattr(m, "tool_call_id")] == ["read"]


def test_natural_summary_is_not_called_twice(tmp_path):
    state, context, model, _, _ = state_with_script(tmp_path, [{"content": "natural summary"}])
    assert run_loop(state, context)["summary"] == "natural summary"
    assert model.calls == 1 and context.closeout.remaining_calls == 6
    assert context.closeout.delegation_admitted is False


@pytest.mark.parametrize("content,calls", [
    ("", []), ("incorrect tools", [read_call("illegal")])])
def test_invalid_handoff_has_no_effect_or_retry(tmp_path, content, calls):
    state, context, model, services, work = state_with_script(
        tmp_path, [{"content": content, "tool_calls": calls}])
    with pytest.raises(TaskCloseoutError):
        run_loop(state, context, max_loops=1)
    assert model.calls == 1 and model.shared.observations == [()]
    assert (work / "src/a.py").read_bytes() == b"original\n"
    assert services.session is None


def test_last_iteration_is_handoff(tmp_path):
    script = [{"tool_calls": [read_call(f"r{i}")]} for i in range(15)]
    script.append({"content": "read only, no edits or checks"})
    state, context, model, _, _ = state_with_script(tmp_path, script)
    assert run_loop(state, context)["summary"] == "read only, no edits or checks"
    assert model.calls == 16 and model.shared.observations[-1] == ()


def test_missing_usage_executes_no_new_group(tmp_path):
    state, context, model, _, work = state_with_script(tmp_path, [
        {"tool_calls": [{"id": "edit", "name": "FileEditTool", "args": {
            "file_path": "src/a.py", "old_text": "original", "new_text": "changed"}}], "usage": None}])
    from mokioclaw.providers.openai_provider import TaskProviderError
    with pytest.raises(TaskProviderError, match="usage_unavailable"):
        run_loop(state, context)
    assert model.calls == 1 and (work / "src/a.py").read_bytes() == b"original\n"


def test_small_budget_does_not_create_delegation(tmp_path):
    state, context, model, services, _ = state_with_script(tmp_path, [])
    context.max_provider_calls = 7
    with pytest.raises(TaskCloseoutError):
        run_loop(state, context)
    assert model.calls == 0 and services.session is None
    assert not context.closeout.delegation_admitted


def delegation(call_id):
    return {"id": call_id, "name": "CallCodeAgentTool", "args": {"instruction": "synthetic instruction"}}


def test_multidelegation_group_closes_with_all_ids(tmp_path):
    from mokioclaw.graph.nodes import planner_node
    from langchain_core.messages import ToolMessage
    import json
    state, context, model, _, _ = state_with_script(tmp_path, [
        {"tool_calls": [delegation("first"), delegation("second")]},
        {"tool_calls": [read_call("read")], "usage": {"total_tokens": 20000}},
        {"content": "unfinished, read only"}, {"content": "handoff to formal checks"},
    ])
    result = planner_node(state)
    tools = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert [m.tool_call_id for m in tools] == ["first", "second"]
    assert json.loads(tools[1].content) == {"ok": False, "error": "closeout_requested"}
    assert context._terminal_root is None and context.provider_calls == model.calls == 4
    assert model.shared.observations[-1] == ()
    assert context.closeout.remaining_calls == 4
    # The adopted numeric identity is the planner's original call 1, not nested call 3.
    context.closeout.adopt_planner_response(1, 2)
    assert context.closeout.remaining_calls == 4 and context.reported_tokens == 20006


def test_second_delegation_is_refused_before_model_binding(tmp_path):
    from mokioclaw.graph.nodes import _call_code_agent_tool
    state, context, model, services, _ = state_with_script(tmp_path, [{"content": "natural"}])
    _call_code_agent_tool(state, lambda e: None, "synthetic")
    context.provider_calls = 17
    result = _call_code_agent_tool(state, lambda e: None, "synthetic")
    assert result == {"ok": False, "error": "closeout_requested"}
    assert model.calls == 1 and services.session is None


def test_planner_last_two_iterations_close_without_fake_summary(tmp_path):
    from mokioclaw.graph.nodes import planner_node
    script = [{"tool_calls": [{"id": f"u{i}", "name": "UnknownTool", "args": {}}]} for i in range(6)]
    script.extend([{"tool_calls": [{"id": "todo", "name": "TodoWriteTool", "args": {
        "todos": ["unfinished"], "acceptance_criteria": ["unfinished"]}}]},
                   {"content": "not implemented"}])
    state, context, model, _, _ = state_with_script(tmp_path, script)
    result = planner_node(state)
    assert model.calls == 8 and model.shared.observations[-2:] == [("TodoWriteTool",), ()]
    assert not result["code_agent_summary"] and result["todos"][0]["status"] == "pending"
    assert context.closeout.remaining_calls == 4
