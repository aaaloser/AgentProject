from task_queue.models import Task
from task_queue.worker import Worker


def test_successful_task_has_one_attempt() -> None:
    task = Task("successful")
    result = Worker().run(task, lambda _task: True)

    assert result.ok is True
    assert result.attempts == 1
    assert task.retry_count == 0


def test_failed_task_stops_after_default_attempts() -> None:
    task = Task("failing")
    result = Worker().run(task, lambda _task: False)

    assert result.ok is False
    assert result.attempts == 3
    assert task.retry_count == 3
