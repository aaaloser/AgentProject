"""Exercise observations at the actual task model budget and policy gates."""
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from tests.dashboard.task_observation_fakes import (
    TASK_ID, MemorySink, offline_observation_guard, utc_clock,
)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    with offline_observation_guard(monkeypatch):
        yield


class Model:
    def __init__(self, usage=0, error=None):
        self.usage, self.error, self.calls = usage, error, 0

    def bind_tools(self, *args, **kwargs):
        return self

    def invoke(self, *args, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return SimpleNamespace(usage_metadata=self.usage if isinstance(self.usage, dict)
                               else {"total_tokens": self.usage})


def context(model, sink=None, calls=20, tokens=150000):
    from mokioclaw.core.agent import TaskRunContext
    from mokioclaw.core.task_observation import TaskObservation
    kwargs = {} if sink is None else {"observation": TaskObservation(TASK_ID, sink, utc_clock=utc_clock)}
    return TaskRunContext.for_fake_model(model, max_provider_calls=calls,
                                        max_total_tokens=tokens,
                                        max_output_tokens_per_call=3072, **kwargs)


@pytest.mark.parametrize("usage", [0, 123, None, True, -1, 150001])
def test_invoke_lifecycle_usage_and_refusal(usage):
    from mokioclaw.providers.openai_provider import TaskProviderError
    sink, model = MemorySink(), Model(usage)
    ctx = context(model, sink)
    ctx.model(stage="planner").bind_tools([]).invoke([])
    events = sink.records
    assert [r.kind for r in events] == ["invoke_started", "invoke_finished"]
    assert ctx.provider_calls == model.calls == 1
    assert events[0].call_no == events[1].call_no == 1
    assert events[0].before.calls_used == 0
    assert events[1].after.calls_used == 1
    if type(usage) is int and usage >= 0:
        assert events[1].total_tokens == ctx.reported_tokens == usage
    else:
        assert events[1].status == "usage_unavailable"
        assert events[1].total_tokens is None
    if ctx.usage_unavailable or ctx.reported_tokens >= 150000:
        with pytest.raises(TaskProviderError):
            ctx.model(stage="planner").invoke([])
        assert sink.records[-1].kind == "invoke_refused"
        assert sink.records[-1].call_no is None
        assert model.calls == 1


def test_observer_off_equivalent():
    from mokioclaw.core.task_closeout import CloseoutPurpose
    contexts = [context(Model(100)), context(Model(100), MemorySink())]
    for ctx in contexts:
        ctx.begin_attempt(1)
        ctx.closeout.admit_delegation(calls_left=20, tokens_left=150000)
        ctx.model(stage="code_agent", purpose=CloseoutPurpose.REPAIR).invoke([])
    assert contexts[0].usage_snapshot() == contexts[1].usage_snapshot()
    assert contexts[0].closeout.snapshot() == contexts[1].closeout.snapshot()


def test_all_switch_reasons_and_cold_start():
    sink, ctx = MemorySink(), None
    ctx = context(Model(), sink)
    ctx.begin_attempt(1)
    ctx.closeout.decide_repair(calls_left=1, tokens_left=0, iterations_left=1)
    assert set(sink.records[-1].reasons) == {"calls", "iterations"}
    assert sink.records[-1].policy["mode"] == "closing"
    assert sink.records[-2].policy["mode"] == "repair"
    ctx = context(Model(), sink := MemorySink())
    ctx.begin_attempt(1)
    from mokioclaw.core.task_closeout import CloseoutPurpose
    ctx.model(stage="code_agent", purpose=CloseoutPurpose.REPAIR).invoke([])
    ctx.closeout.decide_repair(calls_left=1, tokens_left=0, iterations_left=1)
    assert set(sink.records[-1].reasons) == {"calls", "tokens", "iterations"}


def test_adopt_original_planner_once_and_phase_release():
    from mokioclaw.core.task_closeout import CloseoutPurpose
    from mokioclaw.core.task_observation import reconcile
    sink = MemorySink()
    ctx = context(Model(7), sink)
    ctx.begin_attempt(1)
    ctx.model(stage="planner").invoke([])
    ctx.closeout.adopt_planner_response(1, 7)
    ctx.closeout.adopt_planner_response(1, 7)
    for purpose in (CloseoutPurpose.PRE_COMPRESS, CloseoutPurpose.POST_COMPRESS):
        ctx.closeout.complete_phase(purpose)
        ctx.closeout.complete_phase(purpose)
    assert [r for r in sink.records if r.kind == "invoke_started"][0].purpose is None
    assert len([r for r in sink.records if r.kind == "adopt_existing_call"]) == 1
    assert len([r for r in sink.records if r.kind == "phase_released"]) == 2
    assert reconcile(sink.records, ctx.usage_snapshot()).valid
    assert ctx.provider_calls == 1


def test_existing_root_wins_observer_failure():
    class BadSink:
        def emit(self, record):
            raise RuntimeError("SENSITIVE")
    ctx = context(Model(error=ValueError("SENSITIVE")), BadSink())
    from mokioclaw.providers.openai_provider import TaskProviderError
    with pytest.raises(TaskProviderError) as raised:
        ctx.model(stage="planner").invoke([])
    assert "SENSITIVE" not in str(raised.value)
    assert ctx.provider_calls == 1
    assert not ctx.observation.valid
    assert ctx._terminal_root == "provider_failed"


def test_cancel_after_started_and_purpose_binding():
    from mokioclaw.core.task_closeout import CloseoutPurpose
    from mokioclaw.core.task_observation import reconcile
    sink = MemorySink()
    ctx = context(Model(error=KeyboardInterrupt()), sink)
    ctx.begin_attempt(1)
    with pytest.raises(KeyboardInterrupt):
        ctx.model(stage="code_agent").bind_tools([]).for_purpose(CloseoutPurpose.REPAIR).invoke([])
    started = [r for r in sink.records if r.kind == "invoke_started"]
    assert len(started) == 1 and started[0].purpose == "repair"
    result = reconcile(sink.records, ctx.usage_snapshot())
    assert not result.valid and result.unknown_calls == 1


def test_snapshot_is_read_only():
    from mokioclaw.core.task_closeout import TaskCloseout
    closeout = TaskCloseout(3072)
    closeout.begin_attempt(1)
    before = asdict(closeout.snapshot(iterations_left=10))
    assert before["R_calls"] == 7 and before["R_tokens"] == 7 * 3840
    with pytest.raises(Exception):
        closeout.snapshot().mode = "failed"
    assert asdict(closeout.snapshot(iterations_left=10)) == before


def test_phase_released_snapshot_reports_zero_remaining():
    from mokioclaw.core.task_closeout import CloseoutPurpose
    sink = MemorySink()
    ctx = context(Model(), sink)
    ctx.begin_attempt(1)
    ctx.closeout.complete_phase(CloseoutPurpose.PRE_COMPRESS)
    assert sink.records[-1].kind == "phase_released"
    assert sink.records[-1].policy["slots"]["pre_compress"] == 0
