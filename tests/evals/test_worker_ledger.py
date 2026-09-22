from __future__ import annotations

import json
from pathlib import Path

import pytest

from mokioclaw.evals.worker_ledger import WorkerAttemptLedger, scheduled_run_id


def test_scheduled_run_id_is_canonical_and_cell_qualified() -> None:
    first = scheduled_run_id(
        case_id="case-a",
        architecture="multi-agent",
        cell="B",
        repeat=2,
        schedule_sha256="schedule-hash",
    )
    second = scheduled_run_id(
        architecture="multi-agent",
        schedule_sha256="schedule-hash",
        repeat=2,
        cell="B",
        case_id="case-a",
    )

    assert first == second
    assert len(first) == 64
    assert first != scheduled_run_id(
        case_id="case-a", architecture="multi-agent", cell="J", repeat=2, schedule_sha256="schedule-hash"
    )


def test_launch_is_appended_before_terminal_and_attempt_directory_is_unique(tmp_path: Path) -> None:
    ledger = WorkerAttemptLedger(tmp_path)

    attempt = ledger.launch("scheduled-1", worker_attempt_id="worker-1")
    assert attempt.directory == tmp_path / "worker-attempts" / "worker-1"
    assert attempt.directory.is_dir()
    assert [event["event"] for event in ledger.events()] == ["launch"]

    ledger.terminal("scheduled-1", "worker-1", status="failed", agent_attempt_count=3)
    events = ledger.events()
    assert [event["event"] for event in events] == ["launch", "terminal"]
    assert events[1]["agent_attempt_count"] == 3
    assert len({event["worker_attempt_id"] for event in events}) == 1


def test_same_scheduled_slot_can_never_launch_twice_even_after_failure(tmp_path: Path) -> None:
    ledger = WorkerAttemptLedger(tmp_path)
    ledger.launch("scheduled-1", worker_attempt_id="worker-1")
    ledger.terminal("scheduled-1", "worker-1", status="setup_failed", agent_attempt_count=0)

    with pytest.raises(RuntimeError, match="already launched"):
        ledger.launch("scheduled-1", worker_attempt_id="worker-2")

    assert not (tmp_path / "worker-attempts" / "worker-2").exists()


def test_terminal_requires_matching_open_launch_and_cannot_overwrite(tmp_path: Path) -> None:
    ledger = WorkerAttemptLedger(tmp_path)
    ledger.launch("scheduled-1", worker_attempt_id="worker-1")

    with pytest.raises(RuntimeError, match="matching launch"):
        ledger.terminal("scheduled-1", "worker-other", status="failed")
    ledger.terminal("scheduled-1", "worker-1", status="failed")
    with pytest.raises(RuntimeError, match="already terminal"):
        ledger.terminal("scheduled-1", "worker-1", status="passed")

    lines = ledger.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["status"] == "failed"


def test_stop_marks_only_never_launched_slots_not_started(tmp_path: Path) -> None:
    ledger = WorkerAttemptLedger(tmp_path)
    ledger.launch("scheduled-1", worker_attempt_id="worker-1")
    ledger.terminal("scheduled-1", "worker-1", status="provider_transport")

    ledger.mark_not_started("scheduled-2", reason="batch_stopped")

    event = ledger.events()[-1]
    assert event == {
        "event": "not_started",
        "event_sequence": 3,
        "reason": "batch_stopped",
        "scheduled_run_id": "scheduled-2",
    }
    with pytest.raises(RuntimeError, match="already recorded"):
        ledger.mark_not_started("scheduled-2", reason="again")
    with pytest.raises(RuntimeError, match="launched"):
        ledger.mark_not_started("scheduled-1", reason="invalid")


def test_agent_attempt_count_never_creates_another_worker_launch(tmp_path: Path) -> None:
    ledger = WorkerAttemptLedger(tmp_path)
    ledger.launch("scheduled-1", worker_attempt_id="worker-1")
    ledger.terminal("scheduled-1", "worker-1", status="failed", agent_attempt_count=9)

    assert [event["event"] for event in ledger.events()].count("launch") == 1
    assert len(list((tmp_path / "worker-attempts").iterdir())) == 1
