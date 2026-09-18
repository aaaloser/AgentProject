from __future__ import annotations

from collections.abc import Callable

from task_queue.models import Task, TaskResult
from task_queue.retry_policy import RetryPolicy


Runner = Callable[[Task], bool]


class Worker:
    """Run tasks with retries.

    Retry semantics: ``retry_count`` counts failed attempts recorded on one
    task; the default policy stops after 3 failed attempts, so the third
    failing runner call returns ``ok=False`` with ``retry_count == 3``.
    """

    def __init__(self, retry_policy: RetryPolicy | None = None) -> None:
        self.retry_policy = retry_policy or RetryPolicy()

    def run(self, task: Task, runner: Runner) -> TaskResult:
        attempts = 0
        while True:
            attempts += 1
            if runner(task):
                return TaskResult(task=task, ok=True, attempts=attempts)
            task.retry_count += 1
            if not self.retry_policy.should_retry(task.retry_count):
                return TaskResult(task=task, ok=False, attempts=attempts)
