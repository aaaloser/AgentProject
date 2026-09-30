"""File-only tools for a Web task; every host access uses TaskFilesystem."""

from __future__ import annotations

import difflib
from typing import Any

from langchain_core.tools import StructuredTool

from mokioclaw.core.state import RuntimeState
from mokioclaw.dashboard.task_filesystem import TaskFilesystem, TaskFilesystemError
from mokioclaw.tools.todo_tool import persist_todos


_NOTEPAD = ".mokioclaw/task-scratch/NOTEPAD.md"
_MAX_LINES = 2000
_MAX_MATCHES = 200


def _failure() -> dict[str, Any]:
    return {"ok": False, "error": "task_file_access_denied"}


def _decode(content: bytes) -> str:
    return content.decode("utf-8", errors="replace")


def _diff(path: str, before: str, after: str) -> str:
    return "\n".join(difflib.unified_diff(
        before.splitlines(), after.splitlines(), fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="",
    ))[:4000]


class TaskFileTools:
    def __init__(self, filesystem: TaskFilesystem) -> None:
        self.fs = filesystem

    def read(self, file_path: str, offset: int | str = 0, limit: int | str = _MAX_LINES) -> dict[str, Any]:
        try:
            offset_value, limit_value = int(offset), min(int(limit), _MAX_LINES)
            if offset_value < 0 or limit_value < 1:
                return _failure()
            lines = _decode(self.fs.read_bytes(file_path)).splitlines()
            selected = lines[offset_value:offset_value + limit_value]
            numbered = "\n".join(f"{offset_value + index + 1}: {line}" for index, line in enumerate(selected))
            return {
                "ok": True, "path": file_path, "total_lines": len(lines),
                "offset": offset_value, "limit": limit_value,
                "complete": offset_value == 0 and len(selected) == len(lines),
                "content": numbered,
            }
        except (TaskFilesystemError, OSError, ValueError, TypeError):
            return _failure()

    def write(self, file_path: str, content: str) -> dict[str, Any]:
        if not isinstance(content, str):
            return _failure()
        try:
            before = _decode(self.fs.read_bytes(file_path))
            self.fs.write_bytes(file_path, content.encode("utf-8"))
            return {"ok": True, "type": "update", "path": file_path,
                    "lines": len(content.splitlines()), "diff": _diff(file_path, before, content)}
        except (TaskFilesystemError, OSError, ValueError, UnicodeError):
            return _failure()

    def edit(self, file_path: str, old_text: str, new_text: str) -> dict[str, Any]:
        if not isinstance(old_text, str) or not old_text or not isinstance(new_text, str):
            return _failure()
        try:
            before = _decode(self.fs.read_bytes(file_path))
            if before.count(old_text) != 1:
                return {"ok": False, "error": "task_edit_match_failed"}
            after = before.replace(old_text, new_text, 1)
            self.fs.write_bytes(file_path, after.encode("utf-8"))
            return {"ok": True, "path": file_path, "replacements": 1,
                    "diff": _diff(file_path, before, after)}
        except (TaskFilesystemError, OSError, ValueError, UnicodeError):
            return _failure()

    def grep(
        self, pattern: str, path: str, glob: str | None = None,
        head_limit: int | str = 50, ignore_case: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(pattern, str) or not pattern or len(pattern) > 256 or glob is not None:
            return _failure()
        try:
            limit = min(int(head_limit), _MAX_MATCHES)
            if limit < 1:
                return _failure()
            lines = _decode(self.fs.read_bytes(path)).splitlines()
            needle = pattern.casefold() if ignore_case else pattern
            matches = [
                {"path": path, "line": index, "text": line[:2000]}
                for index, line in enumerate(lines, 1)
                if needle in (line[:2000].casefold() if ignore_case else line[:2000])
            ]
            return {"ok": True, "pattern": pattern, "matches": matches[:limit],
                    "truncated": len(matches) > limit}
        except (TaskFilesystemError, OSError, ValueError, TypeError):
            return _failure()

    def notepad_read(self) -> dict[str, Any]:
        try:
            content = _decode(self.fs.read_bytes(_NOTEPAD, scratch=True))
            return {"ok": True, "path": _NOTEPAD, "content": content, "exists": True}
        except (TaskFilesystemError, OSError):
            return _failure()

    def notepad_append(self, heading: str, content: str) -> dict[str, Any]:
        if not isinstance(heading, str) or not isinstance(content, str) or not content.strip():
            return _failure()
        try:
            before = _decode(self.fs.read_bytes(_NOTEPAD, scratch=True))
            title = heading.strip()[:100] or "Note"
            after = before.rstrip() + f"\n\n## {title}\n\n{content.strip()}\n"
            self.fs.write_bytes(_NOTEPAD, after.encode("utf-8"), scratch=True)
            return {"ok": True, "path": _NOTEPAD, "heading": title,
                    "lines": len(after.splitlines())}
        except (TaskFilesystemError, OSError, UnicodeError):
            return _failure()


def build_task_file_tools(filesystem: TaskFilesystem) -> list[StructuredTool]:
    task = TaskFileTools(filesystem)
    return [
        StructuredTool.from_function(name="FileReadTool", func=task.read,
                                     description="Read a scoped source file."),
        StructuredTool.from_function(name="FileWriteTool", func=task.write,
                                     description="Rewrite an existing scoped source file."),
        StructuredTool.from_function(name="FileEditTool", func=task.edit,
                                     description="Replace one unique snippet in a scoped source file."),
        StructuredTool.from_function(name="GrepTool", func=task.grep,
                                     description="Search literal text in one explicit scoped source file."),
        StructuredTool.from_function(name="NotepadReadTool", func=task.notepad_read,
                                     description="Read the scoped task scratch notepad."),
        StructuredTool.from_function(name="NotepadAppendTool", func=task.notepad_append,
                                     description="Append to the scoped task scratch notepad."),
    ]


def persist_todos_for_runtime(
    runtime: RuntimeState,
    todos: list[dict[str, Any]],
    acceptance_criteria: list[str] | None = None,
    verification_commands: list[str] | None = None,
    plan_summary: str = "",
) -> dict[str, Any]:
    if runtime.task_filesystem is not None:
        return {"ok": True, "storage": "memory", "todos": todos}
    return persist_todos(runtime, todos, acceptance_criteria, verification_commands, plan_summary)
