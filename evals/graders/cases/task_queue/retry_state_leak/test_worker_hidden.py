from task_queue.models import Task
from task_queue.worker import Worker


def test_retry_count_does_not_leak_between_sequential_tasks() -> None:
    worker = Worker()

    def fail_once_then_succeed(task: Task) -> bool:
        return task.retry_count >= 1

    first_result = worker.run(Task("first"), fail_once_then_succeed)
    assert first_result.task.retry_count == 1

    second_result = worker.run(Task("second"), fail_once_then_succeed)
    assert second_result.task.retry_count == 1


def test_separate_workers_do_not_share_retry_state() -> None:
    def fail_once_then_succeed(task: Task) -> bool:
        return task.retry_count >= 1

    first = Worker().run(Task("first"), fail_once_then_succeed)
    second = Worker().run(Task("second"), fail_once_then_succeed)

    assert first.task.retry_count == 1
    assert second.task.retry_count == 1
