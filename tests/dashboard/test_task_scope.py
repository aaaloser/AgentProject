"""Web task file tools must use the one scoped filesystem for every access."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from mokioclaw.dashboard.task_filesystem import TaskFilesystem
from mokioclaw.dashboard.task_events import task_tool_failure_event
from mokioclaw.dashboard.task_tools import build_task_file_tools, persist_todos_for_runtime
from mokioclaw.agents.code_agent import execute_code_agent_tool, run_code_agent
from mokioclaw.core.state import RuntimeState
from mokioclaw.graph.memory import build_layered_memory, persist_history_summary


def task_tools(tmp_path: Path):
    work = tmp_path / "one" / "workspace" / "work"
    baseline = work.parent / "baseline"
    (work / "src").mkdir(parents=True)
    (work / "other").mkdir()
    baseline.mkdir()
    (work / "src" / "a.py").write_text("alpha\nbeta\n", encoding="utf-8")
    (work / "other" / "private.txt").write_text("FAKE_PRIVATE", encoding="utf-8")
    (baseline / "a.py").write_text("baseline private", encoding="utf-8")
    prepared = SimpleNamespace(task_id="task_1234567890123456", work=work, baseline=baseline,
                               root=work.parents[1])
    fs = TaskFilesystem(prepared, ("src/",), ("src/",), ".mokioclaw/task-scratch/")
    return {tool.name: tool for tool in build_task_file_tools(fs)}, work


def test_read_edit_and_write_existing_file_only_inside_source_scope(tmp_path: Path) -> None:
    tools, work = task_tools(tmp_path)
    read = tools["FileReadTool"].invoke({"file_path": "src/a.py"})
    assert read["ok"] and "alpha" in read["content"]
    edited = tools["FileEditTool"].invoke({"file_path": "src/a.py", "old_text": "alpha", "new_text": "gamma"})
    assert edited["ok"]
    assert (work / "src" / "a.py").read_text(encoding="utf-8") == "gamma\nbeta\n"
    written = tools["FileWriteTool"].invoke({"file_path": "src/a.py", "content": "delta\n"})
    assert written["ok"]
    assert (work / "src" / "a.py").read_text(encoding="utf-8") == "delta\n"


@pytest.mark.parametrize("old_text", ["missing", "a"])
def test_edit_text_mismatch_is_not_reported_as_scope_denial(tmp_path: Path, old_text: str) -> None:
    tools, work = task_tools(tmp_path)
    before = (work / "src" / "a.py").read_bytes()
    result = tools["FileEditTool"].invoke({
        "file_path": "src/a.py", "old_text": old_text, "new_text": "replacement",
    })
    assert result == {"ok": False, "error": "task_edit_match_failed"}
    assert task_tool_failure_event("codeAgent", "FileEditTool", error=result["error"]) == {
        "type": "task_tool_failure", "node": "codeAgent", "name": "FileEditTool",
        "failure_category": "tool_rejected",
    }
    assert (work / "src" / "a.py").read_bytes() == before


@pytest.mark.parametrize("path", ["../baseline/a.py", "/private.txt", "src/../other/private.txt",
                                       "other/private.txt", "C:/Windows/win.ini"])
def test_all_file_tools_refuse_out_of_scope_path(tmp_path: Path, path: str) -> None:
    tools, work = task_tools(tmp_path)
    before = (work / "other" / "private.txt").read_bytes()
    for name, arguments in (
        ("FileReadTool", {"file_path": path}),
        ("FileWriteTool", {"file_path": path, "content": "stolen"}),
        ("FileEditTool", {"file_path": path, "old_text": "x", "new_text": "y"}),
        ("GrepTool", {"pattern": "FAKE_PRIVATE", "path": path}),
    ):
        result = tools[name].invoke(arguments)
        assert result["ok"] is False and "FAKE_PRIVATE" not in str(result)
        if name == "FileEditTool":
            assert result["error"] == "task_file_access_denied"
            assert task_tool_failure_event("codeAgent", name, error=result["error"])[
                "failure_category"] == "scope_denied"
    assert (work / "other" / "private.txt").read_bytes() == before


def test_grep_requires_explicit_scoped_file_path(tmp_path: Path) -> None:
    tools, _ = task_tools(tmp_path)
    schema = tools["GrepTool"].tool_call_schema.model_json_schema()
    assert "path" in schema["required"]
    found = tools["GrepTool"].invoke({"pattern": "beta", "path": "src/a.py"})
    assert found["ok"] and found["matches"][0]["line"] == 2
    with pytest.raises(ValidationError):
        tools["GrepTool"].invoke({"pattern": "alpha"})


def test_link_replacement_is_refused_on_each_tool_call(tmp_path: Path) -> None:
    tools, work = task_tools(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.py").write_text("FAKE_PRIVATE", encoding="utf-8")
    (work / "src" / "a.py").unlink()
    (work / "src").rmdir()
    try:
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(work / "src"), str(outside)],
                           check=True, capture_output=True)
        else:
            (work / "src").symlink_to(outside, target_is_directory=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        pytest.skip(f"Link fixture unavailable: {exc}")
    for name, arguments in (
        ("FileReadTool", {"file_path": "src/a.py"}),
        ("FileWriteTool", {"file_path": "src/a.py", "content": "hijack"}),
        ("GrepTool", {"pattern": "FAKE_PRIVATE", "path": "src/a.py"}),
    ):
        result = tools[name].invoke(arguments)
        assert result["ok"] is False and "FAKE_PRIVATE" not in str(result)
    assert (outside / "a.py").read_text(encoding="utf-8") == "FAKE_PRIVATE"


def test_unsupported_create_recursive_search_and_scratch_write_fail_closed(tmp_path: Path) -> None:
    tools, work = task_tools(tmp_path)
    assert tools["FileWriteTool"].invoke({"file_path": "src/new.py", "content": "new"})["ok"] is False
    assert tools["GrepTool"].invoke({"pattern": "alpha", "path": "src/"})["ok"] is False
    assert tools["NotepadAppendTool"].invoke({"heading": "note", "content": "hello"})["ok"] is False
    assert not (work / "src" / "new.py").exists()
    assert not (work / ".mokioclaw").exists()


def test_precreated_scratch_notepad_is_writable_without_touching_source_root(tmp_path: Path) -> None:
    tools, work = task_tools(tmp_path)
    scratch = work / ".mokioclaw" / "task-scratch"
    scratch.mkdir(parents=True)
    (scratch / "NOTEPAD.md").write_bytes(b"")
    result = tools["NotepadAppendTool"].invoke({"heading": "plan", "content": "private task note"})
    assert result["ok"]
    assert "private task note" in (scratch / "NOTEPAD.md").read_text(encoding="utf-8")
    assert not (work / "NOTEPAD.md").exists()


def test_task_file_registry_does_not_include_host_shell_or_web_search(tmp_path: Path) -> None:
    tools, _ = task_tools(tmp_path)
    assert set(tools) == {"FileReadTool", "FileWriteTool", "FileEditTool", "GrepTool",
                          "NotepadReadTool", "NotepadAppendTool"}


def test_code_agent_tool_dispatch_can_use_only_supplied_task_registry(tmp_path: Path) -> None:
    tools, _ = task_tools(tmp_path)
    message, _ = execute_code_agent_tool(
        None, [], {"name": "FileReadTool", "args": {"file_path": "src/a.py"}, "id": "call-one"},
        tools_override=list(tools.values()),
    )
    assert "alpha" in str(message.content)
    denied, _ = execute_code_agent_tool(
        None, [], {"name": "BashTool", "args": {"command": "echo bypass"}, "id": "call-two"},
        tools_override=list(tools.values()),
    )
    assert "unknown tool" in str(denied.content)


def test_graph_memory_does_not_read_or_write_workspace_root_in_task_mode(tmp_path: Path) -> None:
    _, work = task_tools(tmp_path)
    (work / "NOTEPAD.md").write_text("FAKE_PRIVATE_NOTE", encoding="utf-8")
    (work / "HISTORY_SUMMARY.md").write_text("FAKE_PRIVATE_HISTORY", encoding="utf-8")
    prepared = SimpleNamespace(task_id="task_1234567890123456", work=work,
                               baseline=work.parent / "baseline", root=work.parents[1])
    fs = TaskFilesystem(prepared, ("src/",), ("src/",), ".mokioclaw/task-scratch/")
    runtime = RuntimeState(workspace=work, task_filesystem=fs, checkpoint_mode="off", trace_mode="off")
    memory = build_layered_memory({"runtime": runtime, "task": "repair"})
    assert "FAKE_PRIVATE_NOTE" not in str(memory)
    assert "FAKE_PRIVATE_HISTORY" not in str(memory)
    result = persist_history_summary(runtime, "new task history")
    assert result["ok"] is False
    assert (work / "HISTORY_SUMMARY.md").read_text(encoding="utf-8") == "FAKE_PRIVATE_HISTORY"


def test_task_runtime_cannot_fall_back_to_legacy_code_agent_tools(tmp_path: Path) -> None:
    _, work = task_tools(tmp_path)
    prepared = SimpleNamespace(task_id="task_1234567890123456", work=work,
                               baseline=work.parent / "baseline", root=work.parents[1])
    fs = TaskFilesystem(prepared, ("src/",), ("src/",), ".mokioclaw/task-scratch/")
    runtime = RuntimeState(workspace=work, task_filesystem=fs, checkpoint_mode="off", trace_mode="off")
    with pytest.raises(ValueError, match="task_tools_required"):
        execute_code_agent_tool(runtime, [], {"name": "FileReadTool", "args": {"file_path": "src/a.py"}})
    with pytest.raises(ValueError, match="task_model_required"):
        run_code_agent({"runtime": runtime, "task": "repair"}, "repair", tools_override=[])


def test_task_code_agent_gets_scoped_edit_first_guidance_without_mandatory_todo_cycle(tmp_path: Path) -> None:
    _, work = task_tools(tmp_path)
    prepared = SimpleNamespace(task_id="task_1234567890123456", work=work,
                               baseline=work.parent / "baseline", root=work.parents[1])
    fs = TaskFilesystem(prepared, ("src/",), ("src/",), ".mokioclaw/task-scratch/")
    runtime = RuntimeState(workspace=work, task_filesystem=fs, checkpoint_mode="off", trace_mode="off")

    class RecordingModel:
        def bind_tools(self, _tools):
            return self

        def invoke(self, messages):
            prompt = str(messages[0].content)
            assert "selected scope" in prompt
            assert "FileEditTool" in prompt
            assert "FileWriteTool" in prompt and "existing" in prompt
            assert "Before starting a todo" not in prompt
            return AIMessage(content="done")

    result = run_code_agent({"runtime": runtime, "task": "repair"}, "repair",
                            tools_override=[], model_override=RecordingModel())
    assert result["ok"] and result["summary"] == "done"


def test_regular_code_agent_keeps_existing_prompt(tmp_path: Path) -> None:
    runtime = RuntimeState(workspace=tmp_path, checkpoint_mode="off", trace_mode="off")

    class RecordingModel:
        def bind_tools(self, _tools):
            return self

        def invoke(self, messages):
            prompt = str(messages[0].content)
            assert "Before starting a todo" in prompt
            assert "Use FileWriteTool for new files" in prompt
            return AIMessage(content="done")

    result = run_code_agent({"runtime": runtime, "task": "repair"}, "repair",
                            tools_override=[], model_override=RecordingModel())
    assert result["ok"] and result["summary"] == "done"


def test_task_todos_remain_in_memory_and_do_not_write_workspace_root(tmp_path: Path) -> None:
    _, work = task_tools(tmp_path)
    marker = work / "TODO.md"
    marker.write_text("FAKE_PRIVATE_TODO", encoding="utf-8")
    prepared = SimpleNamespace(task_id="task_1234567890123456", work=work,
                               baseline=work.parent / "baseline", root=work.parents[1])
    fs = TaskFilesystem(prepared, ("src/",), ("src/",), ".mokioclaw/task-scratch/")
    runtime = RuntimeState(workspace=work, task_filesystem=fs, checkpoint_mode="off", trace_mode="off")
    result = persist_todos_for_runtime(runtime, [{"id": "1", "content": "repair", "status": "pending"}])
    assert result["ok"] and result["storage"] == "memory"
    assert marker.read_text(encoding="utf-8") == "FAKE_PRIVATE_TODO"
