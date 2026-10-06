import pytest

from task_closeout_fakes import ScriptedCloseoutModel, offline_closeout_guard
from mokioclaw.core.agent import TaskRunContext
from mokioclaw.core.task_closeout import CloseoutMode, CloseoutPurpose, TaskCloseoutError
from mokioclaw.providers.openai_provider import TaskProviderError


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    with offline_closeout_guard(monkeypatch):
        yield


def make_context(script, *, calls=24):
    model = ScriptedCloseoutModel(script)
    context = TaskRunContext.for_fake_model(
        model, max_provider_calls=calls, max_total_tokens=100000, max_output_tokens_per_call=100)
    context.begin_attempt(1)
    return context, model


def test_purpose_binding_keeps_single_accounting():
    context, model = make_context([{"content": "handoff", "usage": {"total_tokens": 17}}])
    context.closeout.enter_closing()
    bound = context.model(stage="code_agent", purpose=CloseoutPurpose.HANDOFF).bind_tools([])
    bound.invoke([])
    assert model.calls == context.provider_calls == 1 and context.reported_tokens == 17
    assert context.usage_snapshot()["code_agent_calls"] == 1
    assert context.usage_snapshot()["code_agent_reported_tokens"] == 17
    assert len(context.usage_snapshot()) == 12 and context.closeout.remaining_calls == 6


def test_failed_invoke_consumes_one_slot():
    context, _ = make_context([{"error": RuntimeError("synthetic")}])
    context.closeout.enter_closing()
    with pytest.raises(TaskProviderError):
        context.model(stage="code_agent", purpose=CloseoutPurpose.HANDOFF).invoke([])
    assert context.provider_calls == 1 and context.reported_tokens == 0
    assert context.closeout.remaining_calls == 6


@pytest.mark.parametrize("usage", [None, {"total_tokens": True}, {"total_tokens": -1}])
def test_invalid_usage_stops_next_invoke_and_group(usage):
    context, model = make_context([{"content": "x", "usage": usage}])
    bound = context.model(stage="planner")
    bound.invoke([])
    with pytest.raises(TaskProviderError, match="usage_unavailable"):
        context.check_known_failure()
    with pytest.raises(TaskProviderError, match="usage_unavailable"):
        bound.invoke([])
    assert model.calls == 1 and context.reported_tokens == 0


def test_zero_usage_is_valid_and_purpose_none_cannot_bypass():
    context, _ = make_context([{"usage": {"total_tokens": 0}}])
    context.model(stage="planner").invoke([])
    context.check_known_failure()
    context.closeout.enter_closing()
    with pytest.raises(TaskCloseoutError):
        context.model(stage="planner").invoke([])
    assert context.provider_calls == 1


@pytest.mark.parametrize("root", [
    "task_tool_failed", "verification_command_failed", "provider_auth_failed"])
def test_existing_root_wins(root):
    context, _ = make_context([])
    context.record_terminal_root(root)
    assert context.resolve_closeout_failure(TaskCloseoutError("phase_limit")) == root
    with pytest.raises((TaskProviderError, RuntimeError)):
        context.check_known_failure()


def test_hard_gate_wins_policy_error():
    context, _ = make_context([], calls=1)
    context.provider_calls = 1
    assert context.resolve_closeout_failure(TaskCloseoutError("phase_limit")) == "provider_budget_exhausted"


def test_stage_mismatch_rejected_before_count():
    context, _ = make_context([])
    with pytest.raises(ValueError):
        context.model(stage="planner", purpose=CloseoutPurpose.HANDOFF).invoke([])
    assert context.provider_calls == 0


def test_projected_workflow_marks_failure_and_emits_usage_once(tmp_path):
    from mokioclaw.dashboard.task_worker import run_projected_workflow
    context, _ = make_context([])
    events = []
    def failed(*args, **kwargs):
        yield {"type": "custom_event", "event": {"type": "workflow_complete"}}
        raise TaskCloseoutError("phase_limit")
    with pytest.raises(TaskCloseoutError):
        run_projected_workflow("synthetic", tmp_path, context, events.append, stream=failed)
    assert context.closeout.mode == CloseoutMode.FAILED
    assert len([e for e in events if e.get("kind") == "budget_usage"]) == 1
    assert not any(e.get("phase") == "complete" for e in events)


class FakeConnection:
    def __init__(self, frames):
        import json
        self.data = bytearray("".join(json.dumps(f) + "\n" for f in frames).encode())
        self.sent = bytearray()

    def recv(self, size):
        result = bytes(self.data[:size])
        del self.data[:size]
        return result

    def sendall(self, data):
        self.sent.extend(data)

    def settimeout(self, value):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_worker_type_and_parent_allowlist_in_memory(monkeypatch):
    import json
    from mokioclaw.dashboard import task_worker as worker
    channel = FakeConnection([{"kind": "ready"},
                              {"kind": "start", "task_id": "synthetic", "agent_enabled": True}])
    # Memory-only dependency replaces the blocked socket entry, no socket created.
    def fail(*args):
        raise TaskCloseoutError("phase_limit")
    with monkeypatch.context() as transport_patch:
        transport_patch.setattr(worker.socket, "create_connection", lambda *a, **k: channel)
        worker._worker_main(1, token_line="x" * 32, run_task=fail)
    frames = [json.loads(line) for line in channel.sent.splitlines()]
    assert frames[-1] == {"kind": "done", "outcome": "failed", "failure_kind": "task_closeout_incomplete"}
    done = []
    worker.consume_worker_messages(FakeConnection([frames[-1]]), "synthetic", lambda e: None, done.append)
    assert done == [{"outcome": "failed", "failure_kind": "task_closeout_incomplete"}]
    with pytest.raises(ValueError, match="Invalid worker failure"):
        worker.consume_worker_messages(
            FakeConnection([{"kind": "done", "outcome": "failed", "failure_kind": "model-invented"}]),
            "synthetic", lambda e: None, done.append)
