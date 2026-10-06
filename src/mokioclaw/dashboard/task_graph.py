"""Task graph tool registry with one approved container command gateway."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from mokioclaw.dashboard.task_executor import TaskCommandGateway, run_task_bash
from mokioclaw.dashboard.task_filesystem import TaskFilesystem
from mokioclaw.dashboard.task_tools import build_task_file_tools
from mokioclaw.dashboard.task_context import TaskToolServices


def build_task_graph_tools(
    filesystem: TaskFilesystem,
    gateway: TaskCommandGateway,
    workspace: Path,
    *, services: TaskToolServices,
) -> list[StructuredTool]:
    tools = build_task_file_tools(filesystem, services=services)

    def task_bash(command: str, timeout_seconds: int = 120, run_in_background: bool = False) -> dict:
        result = run_task_bash(gateway, workspace, command, timeout_seconds=timeout_seconds,
                               run_in_background=run_in_background)
        services.invalidate()
        if result.get("ok") is False and "error" in result and result.get("error") != "invalid_task_command":
            services.record_terminal_root("task_tool_failed")
            # Terminal gateway rejection is classified by the original
            # dispatcher before any output paging can obscure it.
            return result
        if "output_truncated" in result:
            result = {**result, "upstream_output_truncated": result["output_truncated"],
                      "upstream_complete": result["output_truncated"] is False}
        return services.feedback("BashTool", result)

    tools.append(StructuredTool.from_function(
        name="BashTool",
        func=task_bash,
        description="Run one approved command in the isolated task container.",
    ))
    return tools


class _ResultReadArguments(BaseModel):
    cursor: Any = Field(json_schema_extra={"type": "string"})
    limit: Any = Field(json_schema_extra={"type": "integer"})


def build_task_result_read_tool(services: TaskToolServices) -> StructuredTool:
    return StructuredTool.from_function(name="ToolResultReadTool", func=services.read_result,
                                       args_schema=_ResultReadArguments,
                                       description="Read a saved executed result with its issued cursor; limit is positive.")
