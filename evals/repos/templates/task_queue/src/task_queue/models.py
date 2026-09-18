from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Task:
    name: str
    retry_count: int = 0


@dataclass(frozen=True)
class TaskResult:
    task: Task
    ok: bool
    attempts: int
