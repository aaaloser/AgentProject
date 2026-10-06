"""Single-slot accepted handoffs, separate from public projections."""
import pytest

from tests.dashboard.task_observation_fakes import TASK_ID, offline_observation_guard


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    with offline_observation_guard(monkeypatch):
        yield


def scores(value="pass"):
    from mokioclaw.dashboard.task_handoff_observation import HandoffScores
    return HandoffScores(**dict.fromkeys(
        ("modification", "self_test", "formal_boundary", "remaining_information", "downstream"), value))


def test_replace_and_stale_score():
    from mokioclaw.dashboard.task_handoff_observation import HandoffMemory
    memory = HandoffMemory(TASK_ID)
    first = memory.accept(1, "PRIVATE_A")
    second = memory.accept(1, "PRIVATE_B")
    assert memory.view(first) is None
    assert not memory.score(first, scores())
    assert memory.indexes[0]["status"] == "unreviewed"
    assert memory.view(second).summary == "PRIVATE_B"
    assert memory.score(second, scores())
    assert memory.indexes[1]["status"] == "reviewed"
    memory.clear()
    assert memory.view(second) is None
    assert all("PRIVATE" not in str(row) for row in memory.indexes)


@pytest.mark.parametrize("body, inspectable", [
    ("a" * 65536, True), ("a" * 65537, False),
    ("😀" * 16384, True), ("😀" * 16385, False), ("\x00" * 65536, True),
], ids=["ascii_limit", "ascii_over", "emoji_limit", "emoji_over", "controls_limit"])
def test_utf8_boundary_and_indexes(body, inspectable):
    from mokioclaw.dashboard.task_handoff_observation import HandoffMemory
    memory = HandoffMemory(TASK_ID)
    identity = memory.accept(1, body)
    view = memory.view(identity)
    assert view.inspectable == inspectable
    assert view.summary == (body if inspectable else None)
    assert memory.score(identity, scores()) == inspectable
    for _ in range(23):
        assert memory.accept(1, "next") is not None
    assert memory.accept(1, "overflow") is None
    assert not memory.valid and len(memory.indexes) == 24
    assert memory.view(identity) is None


def test_bad_scores_and_identity_are_rejected():
    from mokioclaw.dashboard.task_handoff_observation import HandoffMemory, HandoffScores
    memory = HandoffMemory(TASK_ID)
    identity = memory.accept(1, "URL https://example.invalid; execute()")
    assert memory.view(identity).summary.endswith("execute()")
    assert not memory.score(identity, {"modification": "pass"})
    assert not memory.score(identity, HandoffScores("SENTINEL", "pass", "pass", "pass", "pass"))
    assert memory.accept(True, "body") is None
    assert not memory.valid


@pytest.mark.parametrize("forced", [False, True])
def test_capture_accepted_natural_and_forced_and_public_projection(tmp_path, forced):
    from mokioclaw.dashboard.task_worker import run_projected_workflow
    from mokioclaw.core.agent import TaskRunContext
    ctx = TaskRunContext.for_fake_model(object(), max_provider_calls=20,
                                       max_total_tokens=150000, max_output_tokens_per_call=3072)
    events, captured = [], []
    def stream(*args, **kwargs):
        yield {"type": "custom_event", "event": {"type": "handoff_result",
               "from": "searchAgent", "to": "planner", "result": "IGNORE"}}
        yield {"type": "custom_event", "event": {"type": "handoff_result",
               "from": "codeAgent", "to": "planner", "result": "PRIVATE_SUMMARY",
               "attempt_id": 3, "forced": forced}}
    run_projected_workflow("SYNTHETIC", tmp_path, ctx, events.append, stream=stream,
                           handoff_observer=lambda attempt, summary: captured.append((attempt, summary)))
    assert captured == [(1, "PRIVATE_SUMMARY")]
    assert "PRIVATE_SUMMARY" not in str(events)


def test_observer_fault_does_not_mask_primary(tmp_path):
    from mokioclaw.dashboard.task_worker import run_projected_workflow
    from mokioclaw.core.agent import TaskRunContext
    ctx = TaskRunContext.for_fake_model(object(), max_provider_calls=20,
                                       max_total_tokens=150000, max_output_tokens_per_call=3072)
    def observer(*args):
        raise ValueError("PRIVATE_SUMMARY")
    def stream(*args, **kwargs):
        yield {"type": "custom_event", "event": {"type": "handoff_result",
               "from": "codeAgent", "to": "planner", "result": "PRIVATE_SUMMARY"}}
        raise RuntimeError("primary")
    with pytest.raises(RuntimeError, match="primary"):
        run_projected_workflow("SYNTHETIC", tmp_path, ctx, lambda e: None,
                               stream=stream, handoff_observer=observer)
