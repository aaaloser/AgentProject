import pytest

from langchain_core.tools import StructuredTool
from task_closeout_fakes import ScriptedCloseoutModel, offline_closeout_guard
from test_task_context_flow import graph_fixture, read_call
from mokioclaw.core.agent import create_runtime
from mokioclaw.core.task_closeout import TaskCloseoutError
from mokioclaw.dashboard.task_executor import TaskExecutionError
from mokioclaw.graph import nodes
from mokioclaw.providers.openai_provider import TaskProviderError


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    with offline_closeout_guard(monkeypatch):
        yield


def verifier_fixture(tmp_path, script):
    context, _, _, work, decisions, receipts = graph_fixture(tmp_path)
    model = ScriptedCloseoutModel(script)
    context._model_factory = lambda: model
    context.begin_attempt(1)
    context.closeout.enter_closing()
    (work / "src/a.py").write_bytes(b"good\n")
    state = {"task": "synthetic", "task_context": context, "runtime": create_runtime(work, task_context=context),
             "verification_commands": ["python -m pytest -q"], "max_attempts": 1}
    return state, context, model, decisions, receipts


def test_fixed_commands_precede_budget_blocked_verifier(tmp_path):
    state, context, model, decisions, receipts = verifier_fixture(tmp_path, [])
    context.provider_calls = 24
    with pytest.raises(TaskProviderError, match="provider_budget_exhausted"):
        nodes.verifier_node(state)
    assert model.calls == 0 and len(decisions) == len(receipts) == 1
    assert receipts[0].exit_code == 0 and context.usage_snapshot()["verifier_calls"] == 0


@pytest.mark.parametrize("count", [0, 1, 3])
def test_one_read_group_then_final_json(tmp_path, count):
    first = {"tool_calls": [read_call(f"r{i}") for i in range(count)]} if count else {"content": '{"passed":true}'}
    state, context, model, decisions, receipts = verifier_fixture(
        tmp_path, [first, {"content": '{"passed":true,"reason":"synthetic"}'}])
    result = nodes.verifier_node(state)
    assert result["passed"] is True and model.calls == (2 if count else 1)
    assert len(receipts) == len(decisions) == 1
    assert "BashTool" not in model.shared.observations[0]
    if count:
        assert model.shared.observations[-1] == ()


def test_four_reads_reject_whole_group_before_effect(tmp_path):
    state, context, model, _, _ = verifier_fixture(tmp_path, [
        {"tool_calls": [read_call(f"r{i}") for i in range(4)]}])
    effects = []
    def read(file_path: str):
        effects.append(file_path)
        return {"ok": True}
    context.task_tools = [StructuredTool.from_function(read, name="FileReadTool", description="Synthetic")]
    with pytest.raises(TaskCloseoutError):
        nodes.verifier_node(state)
    assert effects == [] and model.calls == 1


def test_bad_last_argument_rejects_before_first_read(tmp_path):
    state, context, _, _, _ = verifier_fixture(tmp_path, [
        {"tool_calls": [read_call("valid"), {"id": "bad", "name": "FileReadTool", "args": {}}]}])
    effects = []
    def read(file_path: str):
        effects.append(file_path)
        return {"ok": True}
    context.task_tools = [StructuredTool.from_function(read, name="FileReadTool", description="Synthetic")]
    with pytest.raises(TaskExecutionError, match="task_tool_failed"):
        nodes.verifier_node(state)
    assert effects == []


def test_model_bash_is_not_executed(tmp_path):
    state, _, model, decisions, receipts = verifier_fixture(tmp_path, [
        {"tool_calls": [{"id": "bash", "name": "BashTool", "args": {"command": "synthetic extra"}}]}])
    with pytest.raises(TaskCloseoutError):
        nodes.verifier_node(state)
    assert model.calls == 1 and len(decisions) == len(receipts) == 1


@pytest.mark.parametrize("content", ["not json", '{"passed":1}', '{"passed":"true"}'])
def test_invalid_verdict_keeps_original_failure(tmp_path, content):
    state, _, _, _, _ = verifier_fixture(tmp_path, [{"content": content}])
    with pytest.raises(TaskExecutionError, match="verifier_invalid"):
        nodes.verifier_node(state)


def test_unknown_read_still_consumes_only_read_round(tmp_path):
    state, _, model, _, _ = verifier_fixture(tmp_path, [
        {"tool_calls": [{"id": "unknown", "name": "UnknownTool", "args": {}}]},
        {"content": '{"passed":false,"reason":"insufficient information"}'}])
    result = nodes.verifier_node(state)
    assert result["passed"] is False and result["verifier_explicit_failure"] is True
    assert model.calls == 2 and model.shared.observations[-1] == ()


def test_second_tool_round_is_rejected(tmp_path):
    state, _, model, _, _ = verifier_fixture(tmp_path, [
        {"tool_calls": [read_call("r")]}, {"tool_calls": [read_call("again")]}])
    with pytest.raises(TaskCloseoutError):
        nodes.verifier_node(state)
    assert model.calls == 2
