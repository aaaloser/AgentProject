"""File-only tools for a Web task; every host access uses TaskFilesystem."""

from __future__ import annotations

import difflib
import hashlib
import re
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from mokioclaw.core.state import RuntimeState
from mokioclaw.dashboard.task_filesystem import TaskFilesystem, TaskFilesystemError, TaskFileRevisionChanged
from mokioclaw.dashboard.task_context import (
    CoverageIncomplete, TaskContextError, TaskToolServices, canonical_json, recovery_result,
)
from mokioclaw.tools.todo_tool import persist_todos


_NOTEPAD = ".mokioclaw/task-scratch/NOTEPAD.md"
_MAX_LINES = 2000
_MAX_MATCHES = 200


class _WindowArguments(BaseModel):
    # Preserve malformed values for the fixed recoverable window error. The
    # advertised schema still specifies the supported integer/string forms.
    offset: Any = Field(default=0, json_schema_extra={"type": ["integer", "string"]})
    limit: Any = Field(default=100, json_schema_extra={"type": ["integer", "string"]})
    char_offset: Any = Field(default=0, json_schema_extra={"type": ["integer", "string"]})
    revision: str | None = None


class _SourceReadArguments(_WindowArguments):
    file_path: str


def _failure() -> dict[str, Any]:
    return {"ok": False, "error": "task_file_access_denied"}


def _decode(content: bytes) -> str:
    return content.decode("utf-8", errors="replace")


def _diff(path: str, before: str, after: str) -> str:
    return "\n".join(difflib.unified_diff(
        before.splitlines(), after.splitlines(), fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="",
    ))


class TaskFileTools:
    def __init__(self, filesystem: TaskFilesystem, *, services: TaskToolServices) -> None:
        if services.filesystem is not filesystem:
            raise TaskContextError("invalid_message_group")
        self.fs = filesystem
        self.services = services

    def read(self, file_path: str, offset: int | str = 0, limit: int | str = 100,
             char_offset: int | str = 0, revision: str | None = None) -> dict[str, Any]:
        return self._read_window(file_path, offset, limit, char_offset, revision, scratch=False)

    def _read_window(self, file_path, offset, limit, char_offset, revision, *, scratch):
        try:
            coordinates = []
            for value in (offset, limit, char_offset):
                if type(value) is int:
                    coordinates.append(value)
                elif isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value):
                    coordinates.append(int(value))
                else:
                    return recovery_result("task_read_window_invalid")
            offset_value, limit_value, column = coordinates
            limit_value = min(limit_value, _MAX_LINES)
            if offset_value < 0 or limit_value < 1 or column < 0:
                return recovery_result("task_read_window_invalid")
            raw = self.fs.read_bytes(file_path, scratch=scratch)
            key = self.fs.canonical_path(file_path, scratch=scratch)
            current_revision = hashlib.sha256(raw).hexdigest()
            if revision is not None and revision != current_revision:
                if not scratch:
                    self.services.invalidate(key)
                return recovery_result("task_read_revision_changed")
            text = _decode(raw)
            lines = [(match.start(), match.group(1), match.group(2))
                     for match in re.finditer(r"([^\r\n]*)(\r\n|\r|\n|$)", text)
                     if match.end() > match.start()]
            if offset_value > len(lines) or (offset_value == len(lines) and column) or (
                offset_value < len(lines) and column > len(lines[offset_value][1])
            ):
                return recovery_result("task_read_window_invalid")
            start = lines[offset_value][0] + column if offset_value < len(lines) else len(text)
            stop_line = min(len(lines), offset_value + limit_value)
            stop = (lines[stop_line][0] if stop_line < len(lines) else len(text))
            budget = min(16384, self.services.result_json_budget())

            def page_to(candidate_end):
                # CRLF is represented as one ending, never a split fragment.
                if 0 < candidate_end < len(text) and text[candidate_end - 1:candidate_end + 1] == "\r\n":
                    candidate_end -= 1
                displays, metadata = [], []
                for number in range(offset_value, stop_line):
                    position, body, ending = lines[number]
                    left = max(0, start - position)
                    right = min(len(body), candidate_end - position)
                    full_end = position + len(body) + len(ending)
                    ending_visible = candidate_end >= full_end
                    if right < left or (right == left and not (ending and ending_visible)):
                        continue
                    fragment = left > 0 or right < len(body)
                    displays.append(f"{number + 1}: " + ("[line_fragment] " if fragment else "") + body[left:right])
                    metadata.append({"line": number, "start_char": left, "end_char": right,
                                     "fragment": fragment, "line_ending":
                                     {"\n": "LF", "\r\n": "CRLF", "\r": "CR"}.get(ending, "none") if ending_visible else "none"})
                next_line, next_column = len(lines), 0
                for number, (position, body, ending) in enumerate(lines):
                    if candidate_end < position + len(body) + len(ending):
                        next_line, next_column = number, candidate_end - position
                        break
                eof = candidate_end == len(text)
                remaining = max(1, stop_line - next_line) if candidate_end < stop else limit_value
                next_read = None if eof else {"offset": next_line, "limit": remaining,
                                             "char_offset": next_column, "revision": current_revision}
                if next_read is not None and not scratch:
                    next_read["file_path"] = file_path
                return {"ok": True, "path": key, "total_lines": len(lines), "offset": offset_value,
                        "limit": limit_value, "content": "\n".join(displays), "content_format": "numbered_fragments",
                        "line_metadata": metadata, "revision": current_revision, "start": start, "end": candidate_end,
                        "start_line": offset_value, "start_char": column, "end_line": next_line, "end_char": next_column,
                        "window_complete": candidate_end == stop, "complete": start == 0 and eof,
                        "eof": eof, "truncated": candidate_end < stop, "next_read": next_read,
                        "next_read_tool": "NotepadReadTool" if scratch else "FileReadTool",
                        "coverage_complete": False, "eof_covered": False, "receipt_id": "x" * 64}

            low, high, selected = start, stop, None
            while low <= high:
                middle = (low + high) // 2
                candidate = page_to(middle)
                if len(candidate["content"].encode("utf-8")) <= 8192 and len(canonical_json(candidate)) <= budget:
                    selected = candidate
                    low = middle + 1
                else:
                    high = middle - 1
            if selected is None or (selected["end"] == start and start < stop):
                raise TaskContextError("input_too_large")
            session = self.services.session
            if not scratch and session is not None:
                receipt = session.coverage.record_visible(key, current_revision, start, selected["end"],
                                                          eof=len(text) if selected["eof"] else None)
                selected.update(coverage_complete=receipt.coverage_complete, eof_covered=receipt.eof_covered,
                                receipt_id=receipt.receipt_id)
            else:
                selected["receipt_id"] = None
            return selected
        except (TaskFilesystemError, OSError):
            return _failure()

    def write(self, file_path: str, content: str) -> dict[str, Any]:
        if not isinstance(content, str):
            return _failure()
        try:
            raw = self.fs.read_bytes(file_path)
            key = self.fs.canonical_path(file_path)
            revision = hashlib.sha256(raw).hexdigest()
            if self.services.session is None:
                return recovery_result("task_write_coverage_required")
            self.services.session.coverage.require_complete(key, revision)
            before = _decode(raw)
            result = {"ok": True, "type": "update", "path": file_path,
                      "lines": len(content.splitlines()), "diff": _diff(file_path, before, content)}
            reservation = self.services.reserve_feedback("FileWriteTool", result)
            try:
                self.fs.write_bytes(file_path, content.encode("utf-8"), expected_revision=revision)
            except Exception:
                self.services.abort_feedback(reservation)
                raise
            self.services.invalidate(key)
            return self.services.finish_feedback(result, reservation)
        except CoverageIncomplete:
            return recovery_result("task_write_coverage_required")
        except TaskFileRevisionChanged:
            self.services.invalidate(self.fs.canonical_path(file_path))
            return recovery_result("task_read_revision_changed")
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
            result = {"ok": True, "path": file_path, "replacements": 1, "diff": _diff(file_path, before, after)}
            reservation = self.services.reserve_feedback("FileEditTool", result)
            try:
                self.fs.write_bytes(file_path, after.encode("utf-8"))
            except Exception:
                self.services.abort_feedback(reservation)
                raise
            self.services.invalidate(self.fs.canonical_path(file_path))
            return self.services.finish_feedback(result, reservation)
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
            raw = self.fs.read_bytes(path)
            revision = hashlib.sha256(raw).hexdigest()
            lines = _decode(raw).splitlines()
            needle = pattern.casefold() if ignore_case else pattern
            matches = [
                {"path": path, "line": index, "text": line[:2000], "revision": revision,
                 "start_char": 0, "end_char": min(len(line), 2000)}
                for index, line in enumerate(lines, 1)
                if needle in (line[:2000].casefold() if ignore_case else line[:2000])
            ]
            return self.services.feedback("GrepTool", {"ok": True, "pattern": pattern, "matches": matches[:limit],
                    "revision": revision, "searched_prefix_only": any(len(line) > 2000 for line in lines),
                    "truncated": len(matches) > limit,
                    "upstream_complete": len(matches) <= limit and all(len(line) <= 2000 for line in lines)})
        except (TaskFilesystemError, OSError, ValueError, TypeError):
            return _failure()

    def notepad_read(self, offset: int | str = 0, limit: int | str = 100,
                     char_offset: int | str = 0, revision: str | None = None) -> dict[str, Any]:
        return self._read_window(_NOTEPAD, offset, limit, char_offset, revision, scratch=True)

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


def build_task_file_tools(filesystem: TaskFilesystem, *, services: TaskToolServices) -> list[StructuredTool]:
    task = TaskFileTools(filesystem, services=services)
    return [
        StructuredTool.from_function(name="FileReadTool", func=task.read,
                                     args_schema=_SourceReadArguments,
                                     description="Read a scoped source file."),
        StructuredTool.from_function(name="FileWriteTool", func=task.write,
                                     description="Rewrite an existing scoped source file."),
        StructuredTool.from_function(name="FileEditTool", func=task.edit,
                                     description="Replace one unique snippet in a scoped source file."),
        StructuredTool.from_function(name="GrepTool", func=task.grep,
                                     description="Search literal text in one explicit scoped source file."),
        StructuredTool.from_function(name="NotepadReadTool", func=task.notepad_read,
                                     args_schema=_WindowArguments,
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
