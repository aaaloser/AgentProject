"""Design gate: final selected schemas, complete anchors, synthetic groups only."""

import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from task_context_fakes import offline_context_guard
from test_task_context_flow import task_files


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    with offline_context_guard(monkeypatch):
        yield


def message_group(call_id, name, args, result):
    return [AIMessage(content="", tool_calls=[{"id": call_id, "name": name, "args": args}]),
            ToolMessage(name=name, tool_call_id=call_id, content=json.dumps(result, ensure_ascii=False))]


@pytest.mark.parametrize("variant", ["short", "ascii_max", "cjk_max", "emoji_max"])
def test_final_binding_baseline_design_gate(tmp_path, variant):
    from mokioclaw.agents.code_agent import _build_todo_update_tool, _task_context_anchors
    from mokioclaw.dashboard.task_context import (
        assert_baseline_feasible, baseline_messages, measure_baseline, measure_request, request_binding,
    )
    from mokioclaw.dashboard.task_graph import build_task_graph_tools, build_task_result_read_tool

    file_tools, services, session, work = task_files(tmp_path, "")
    selected = [*build_task_graph_tools(file_tools.fs, None, work, services=services),
                _build_todo_update_tool([]), build_task_result_read_tool(services)]
    binding = request_binding(selected)
    marker = {"short": "x", "ascii_max": "x", "cjk_max": "中", "emoji_max": "😀"}[variant]
    description = "synthetic task" if variant == "short" else marker * 4000
    commands = ("echo fixture",) if variant == "short" else tuple("echo " + marker * 1995 for _ in range(10))
    assert len(description) <= 4000 and len(commands) <= 10 and all(len(command) <= 2000 for command in commands)
    context = type("Context", (), {"fixed_verification_commands": commands})()
    anchors = _task_context_anchors({"task": description, "task_context": context,
                                     "acceptance_criteria": ["synthetic acceptance"]}, "synthetic instruction")
    capsule = session._state([])
    base = measure_baseline(anchors, capsule, binding)
    # Empty-source windows are actual scoped tool output, not empty schemas.
    minimum = file_tools.read("src/a.py")
    minimal_groups = message_group("m1", "FileReadTool", {"file_path": "src/a.py"}, minimum)
    minimal_groups += message_group("m2", "FileReadTool", {"file_path": "src/a.py"}, minimum)
    # Hold the same base capsule in every incremental measurement. No envelope duplication.
    full_base = baseline_messages(anchors, capsule)
    minimal_delta = measure_request(full_base + minimal_groups, binding) - base
    source = ((marker * 60) + "\n") * 100
    (work / "src/a.py").write_bytes(source.encode())
    session.coverage.invalidate()
    read_result = file_tools.read("src/a.py", limit=100)
    common_groups = message_group("c1", "FileReadTool", {"file_path": "src/a.py", "limit": 100}, read_result)
    common_groups += message_group("c2", "FileEditTool", {"file_path": "src/a.py", "old_text": marker * 40,
                                                          "new_text": "replacement"},
                                   {"ok": True, "path": "src/a.py", "replacements": 1, "diff": "+" + "x" * 8191})
    failure = message_group("f1", "BashTool", {"command": "echo fixture"},
                            {"ok": False, "exit_code": 1, "stdout": "x" * 1024, "stderr": "e" * 1024,
                             "command_request_id": "x" * 24, "output_truncated": False})
    common_delta = measure_request(full_base + common_groups, binding) - base
    failure_delta = measure_request(full_base + common_groups + failure, binding) - base - common_delta
    print(f"calibration {variant}: schemas={len(binding.schemas)} base={base} minimal_two_delta={minimal_delta} "
          f"common_two_delta={common_delta} failure_delta={failure_delta}")
    if variant in {"cjk_max", "emoji_max"}:
        from mokioclaw.dashboard.task_context import TaskContextError
        with pytest.raises(TaskContextError):
            session.set_request(anchors, binding)
    else:
        assert_baseline_feasible(base, minimal_delta, common_delta, failure_delta)
        grown = {"task_id": "offline", "attempt_id": 1, "todos": [{"id": "t", "content": ""}]}
        normalized = json.loads(baseline_messages(anchors, grown)[-1].content)
        from mokioclaw.dashboard.task_context import canonical_json
        grown["todos"][0]["content"] = "x" * (8192 - len(canonical_json(normalized)))
        assert len(baseline_messages(anchors, grown)[-1].content.encode()) == 8192
        grown_base = measure_baseline(anchors, grown, binding)
        assert_baseline_feasible(grown_base, minimal_delta, common_delta, failure_delta)
        print(f"calibration capsule8k {variant}: base={grown_base}")


@pytest.mark.parametrize("options", [{}, {"tool_choice": "auto"}], ids=["default", "auto"])
def test_actual_file_only_binding_admission(tmp_path, options):
    from mokioclaw.agents.code_agent import _build_todo_update_tool, _task_context_anchors
    from mokioclaw.dashboard.task_context import measure_baseline, request_binding
    from mokioclaw.dashboard.task_graph import build_task_result_read_tool
    from mokioclaw.dashboard.task_tools import build_task_file_tools
    file_tools, services, session, _ = task_files(tmp_path)
    selected = [*build_task_file_tools(file_tools.fs, services=services),
                _build_todo_update_tool([]), build_task_result_read_tool(services)]
    binding = request_binding(selected, **options)
    context = type("Context", (), {"fixed_verification_commands": ("echo fixture",)})()
    anchors = _task_context_anchors({"task_context": context, "task": '中文😀quoted " task',
                                     "acceptance_criteria": ["synthetic"]}, "instruction")
    session.set_request(anchors, binding)
    assert len(binding.schemas) == 8 and measure_baseline(anchors, session._state([]), binding) < 49152
