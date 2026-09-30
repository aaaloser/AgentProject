"""Task graph tool registry with one approved container command gateway."""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import StructuredTool

from mokioclaw.dashboard.task_executor import TaskCommandGateway, run_task_bash
from mokioclaw.dashboard.task_filesystem import TaskFilesystem
from mokioclaw.dashboard.task_tools import build_task_file_tools


def build_task_graph_tools(
    filesystem: TaskFilesystem,
    gateway: TaskCommandGateway,
    workspace: Path,
) -> list[StructuredTool]:
    tools = build_task_file_tools(filesystem)
    tools.append(StructuredTool.from_function(
        name="BashTool",
        func=lambda command, timeout_seconds=120, run_in_background=False: run_task_bash(
            gateway, workspace, command,
            timeout_seconds=timeout_seconds, run_in_background=run_in_background,
        ),
        description="Run one approved command in the isolated task container.",
    ))
    return tools
