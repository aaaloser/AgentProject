import pytest

from task_queue.models import Task
from task_queue.retry_policy import RetryPolicy
from task_queue.worker import Worker


def test_retry_policy_boundary() -> None:
    policy = RetryPolicy(max_attempts=2)

    assert policy.should_retry(1) is True
    assert policy.should_retry(2) is False


def test_invalid_retry_policy_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_attempts must be positive"):
        RetryPolicy(max_attempts=0)


def test_worker_honors_an_injected_retry_policy() -> None:
    task = Task("limited")
    result = Worker(retry_policy=RetryPolicy(max_attempts=2)).run(task, lambda _task: False)

    assert result.ok is False
    assert result.attempts == 2
    assert task.retry_count == 2
