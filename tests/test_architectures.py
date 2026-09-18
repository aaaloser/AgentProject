from langgraph.graph import END
from pathlib import Path

from mokioclaw.core.state import RuntimeState
from mokioclaw.graph.architectures import react_node, verify_route


class FakeExecutor:
    def __init__(self, results):
        self.results = list(results)

    def run(self, *, workspace, command, timeout_seconds, max_output_chars):
        outcome = self.results.pop(0) if self.results else {"ok": True}
        return {"ok": outcome, "exit_code": 0 if outcome else 1, "stdout": "out", "stderr": "err", "command": command, "timed_out": False, "duration_ms": 1}


def _state(tmp_path: Path, executor) -> dict:
    runtime = RuntimeState(workspace=tmp_path, approval_mode="deny", checkpoint_mode="off", trace_mode="off", command_executor=executor, allow_web_search=False)
    return {"task": "fix it", "runtime": runtime, "messages": [], "attempts": 0, "max_attempts": 3, "verification_commands": ["python -m pytest -q"]}


def test_react_retries_with_feedback_until_max_attempts(tmp_path: Path, monkeypatch) -> None:
    executor = FakeExecutor([False, False, False])
    calls = []

    def fake_code_agent(state, instruction, *, writer=None, max_loops=10):
        calls.append(instruction)
        return {"ok": True, "summary": "s", "todos": state.get("todos", []), "messages": [], "tool_events": []}

    monkeypatch.setattr("mokioclaw.graph.architectures.run_code_agent", fake_code_agent)

    result = react_node(_state(tmp_path, executor))

    assert result["attempts"] == 3
    assert len(calls) == 3
    assert "公开验证" in calls[1]


def test_react_stops_when_public_verification_passes(tmp_path: Path, monkeypatch) -> None:
    executor = FakeExecutor([False, True])
    monkeypatch.setattr("mokioclaw.graph.architectures.run_code_agent", lambda state, instruction, *, writer=None, max_loops=10: {"ok": True, "summary": "s", "todos": [], "messages": [], "tool_events": []})

    result = react_node(_state(tmp_path, executor))

    assert result["attempts"] == 2
    assert result["passed"] is True


def test_verify_route_pins_max_attempts_boundary() -> None:
    assert verify_route({"passed": False, "attempts": 3, "max_attempts": 3}) is END
    assert verify_route({"passed": False, "attempts": 2, "max_attempts": 3}) == "execute"
    assert verify_route({"passed": True, "attempts": 1, "max_attempts": 3}) is END


def test_plan_execute_graph_runs_at_most_max_attempts_rounds(tmp_path: Path, monkeypatch) -> None:
    from mokioclaw.graph import architectures as arch
    from langchain_core.messages import AIMessage

    class FakePlanModel:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            return AIMessage(content="plan ready")

    execute_calls = []
    verify_calls = []

    def fake_execute(state, instruction, *, writer=None, max_loops=10):
        execute_calls.append(instruction)
        return {"ok": True, "summary": "s", "todos": state.get("todos", []), "messages": [], "tool_events": []}

    def fake_verifier(state):
        verify_calls.append(state.get("attempts", 0))
        return {"passed": False, "attempts": state.get("attempts", 0) + 1, "last_error": "not done", "todos": state.get("todos", [])}

    monkeypatch.setattr(arch, "create_model", lambda: FakePlanModel())
    monkeypatch.setattr(arch, "run_code_agent", fake_execute)
    monkeypatch.setattr(arch, "verifier_node", fake_verifier)

    graph = arch.build_plan_execute_workflow()
    final_state = graph.invoke(_state(tmp_path, FakeExecutor([])), config={"recursion_limit": 50})

    assert len(execute_calls) == 3  # exactly max_attempts execute rounds, no 4th
    assert len(verify_calls) == 3
    assert final_state["attempts"] == 3
    assert "上一轮验证未通过" in execute_calls[1]  # retry carries verifier feedback
