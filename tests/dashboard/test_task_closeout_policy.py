import pytest

from task_closeout_fakes import offline_closeout_guard


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    with offline_closeout_guard(monkeypatch):
        yield


def api():
    from mokioclaw.core.task_closeout import CloseoutMode, CloseoutPurpose, TaskCloseout, TaskCloseoutError
    return CloseoutMode, CloseoutPurpose, TaskCloseout, TaskCloseoutError


def fresh():
    _, _, policy, _ = api()
    p = policy(100)
    p.begin_attempt(1)
    return p


@pytest.mark.parametrize("calls,tokens,want", [
    (6, 5000, "closing"), (7, 5000, "closing"), (8, 1001, "repair"),
    (8, 1000, "closing"), (8, 999, "closing"),
])
def test_call_and_token_boundary(calls, tokens, want):
    mode, purpose, _, _ = api()
    p = fresh()
    p.claim_invoke(purpose.REPAIR)
    p.record_usage(purpose.REPAIR, 0)
    assert p.remaining_calls == 7 and p.remaining_tokens == 875
    assert p.decide_repair(calls_left=calls, tokens_left=tokens, iterations_left=2) == mode(want)


@pytest.mark.parametrize("maximum,expected", [(101, 127), (102, 128), (103, 129), (104, 130)])
def test_estimate_rounds_up_fractional_reported_usage(maximum, expected):
    _, purpose, _, _ = api()
    p = fresh()
    p.record_usage(purpose.REPAIR, maximum)
    assert p.estimate(purpose.REPAIR) == expected


def test_selected_coefficient_against_independent_reference_choices():
    mode, purpose, _, _ = api()
    # Eight future samples of100: independent hand-calculated thresholds
    # for1.0/1.25/1.5 are800/1000/1200. Production stays fixed at1.25.
    assert [1100 > threshold for threshold in (800, 1000, 1200)] == [True, True, False]
    p = fresh()
    p.claim_invoke(purpose.REPAIR)
    p.record_usage(purpose.REPAIR, 100)
    assert p.decide_repair(calls_left=8, tokens_left=1100, iterations_left=2) == mode.REPAIR


def test_zero_sample_is_not_missing():
    _, purpose, _, _ = api()
    p = fresh()
    p.record_usage(None, 5000)
    p.claim_invoke(purpose.REPAIR)
    p.record_usage(purpose.REPAIR, 0)
    assert p.estimate(purpose.REPAIR) == 125
    assert p.estimate(purpose.HANDOFF) == 6250


def test_bootstrap_is_once_per_task():
    mode, purpose, _, _ = api()
    p = fresh()
    assert p.admit_delegation(calls_left=8, tokens_left=1)
    assert p.admit_delegation(calls_left=8, tokens_left=1)
    assert p.decide_repair(calls_left=8, tokens_left=1, iterations_left=2) == mode.REPAIR
    p.claim_invoke(purpose.REPAIR)
    p.begin_attempt(2)
    assert not p.admit_delegation(calls_left=8, tokens_left=1)


def test_release_does_not_reopen():
    mode, purpose, _, _ = api()
    p = fresh()
    p.enter_closing()
    p.complete_phase(purpose.HANDOFF)
    p.complete_phase(purpose.PRE_COMPRESS)
    assert p.remaining_calls == 5
    assert p.decide_repair(calls_left=24, tokens_left=100000, iterations_left=16) == mode.CLOSING
    assert not p.admit_delegation(calls_left=24, tokens_left=100000)


def test_cross_phase_borrow_rejected():
    _, purpose, _, error = api()
    p = fresh()
    p.enter_closing()
    p.claim_invoke(purpose.HANDOFF)
    with pytest.raises(error, match="^task_closeout_incomplete$"):
        p.claim_invoke(purpose.HANDOFF)
    assert p.remaining_calls == 6


def test_adopt_is_idempotent():
    _, purpose, _, _ = api()
    p = fresh()
    p.enter_closing()
    p.adopt_planner_response(3, 0)
    p.adopt_planner_response(3, 0)
    assert p.remaining_calls == 6 and p.estimate(purpose.PLANNER) == 125


@pytest.mark.parametrize("calls,want", [(7, False), (8, True), (9, True)])
def test_admission_7_8_9(calls, want):
    assert fresh().admit_delegation(calls_left=calls, tokens_left=100000) is want


@pytest.mark.parametrize("calls,want", [(8, False), (9, True), (10, True)])
def test_retry_8_9_10(calls, want):
    assert fresh().admit_next_attempt(calls_left=calls, tokens_left=100000) is want


def test_retry_predicts_starting_planner():
    p = fresh()
    assert not p.admit_next_attempt(calls_left=9, tokens_left=1125)
    assert p.admit_next_attempt(calls_left=9, tokens_left=1126)


def test_new_delegation_restores_handoff_prediction():
    _, purpose, _, _ = api()
    p = fresh()
    p.claim_invoke(purpose.REPAIR)
    p.record_usage(purpose.REPAIR, 0)
    p.complete_phase(purpose.HANDOFF)
    assert not p.admit_delegation(calls_left=8, tokens_left=1000)


@pytest.mark.parametrize("bad", [True, -1, None, "1"])
def test_invalid_usage_is_not_a_sample(bad):
    p = fresh()
    with pytest.raises(ValueError):
        p.record_usage(None, bad)


def test_attempt_activation_is_idempotent():
    _, purpose, _, _ = api()
    p = fresh()
    p.claim_invoke(purpose.HANDOFF)
    p.begin_attempt(1)
    assert p.remaining_calls == 6
    with pytest.raises(ValueError):
        p.begin_attempt(3)


def test_guard_remembers_swallowed_error(monkeypatch):
    import subprocess
    with pytest.raises(AssertionError, match="offline_boundary_touched"):
        with offline_closeout_guard(monkeypatch):
            try:
                subprocess.run(["synthetic-never-executed"])
            except AssertionError:
                pass
