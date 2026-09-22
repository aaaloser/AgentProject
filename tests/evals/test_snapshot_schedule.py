from __future__ import annotations

import json
from pathlib import Path

import pytest

from mokioclaw.evals.snapshot_schedule import build_snapshot_schedule, schedule_sha256, write_snapshot_schedule
from mokioclaw.evals.worker_ledger import scheduled_run_id


def test_seed_20260920_has_frozen_cyclic_schedule() -> None:
    payload = build_snapshot_schedule(20260920)

    assert payload["rounds"] == {
        "R1": ["cell-b80-t900", "cell-b80-t600", "anchor-b40-t600", "cell-b40-t900"],
        "R2": ["cell-b80-t600", "anchor-b40-t600", "cell-b40-t900", "cell-b80-t900"],
        "R3": ["anchor-b40-t600", "cell-b40-t900", "cell-b80-t900", "cell-b80-t600"],
    }
    for cell in payload["cells"]:
        positions = [payload["rounds"][round_name].index(cell) for round_name in ("R1", "R2", "R3")]
        assert len(set(positions)) == 3


def test_existing_equal_schedule_is_idempotent_but_mismatch_refuses(tmp_path: Path) -> None:
    path = tmp_path / "execution-schedule.json"
    write_snapshot_schedule(path, 20260920)

    assert write_snapshot_schedule(path, 20260920) == path
    with pytest.raises(RuntimeError, match="schedule mismatch"):
        write_snapshot_schedule(path, 7)


def test_schedule_file_is_json_with_stable_seed(tmp_path: Path) -> None:
    path = write_snapshot_schedule(tmp_path / "execution-schedule.json")

    assert json.loads(path.read_text(encoding="utf-8"))["seed"] == 20260922


@pytest.mark.parametrize(("case_ids", "expected"), [(["case-a"], 36), (["case-a", "case-b"], 72)])
def test_click_schedule_freezes_all_slots_with_stable_ids(case_ids: list[str], expected: int) -> None:
    first = build_snapshot_schedule(seed=20260922, case_ids=case_ids)
    second = build_snapshot_schedule(seed=20260922, case_ids=list(reversed(case_ids)))

    assert first == second
    assert first["protocol_version"] == 2
    assert first["run_budget"] == expected
    assert len(first["slots"]) == expected
    assert len({slot["scheduled_run_id"] for slot in first["slots"]}) == expected
    assert {slot["round"] for slot in first["slots"]} == {"R1", "R2", "R3"}
    assert all(set(slot) == {"round", "scheduled_run_id", "architecture", "case_id", "cell", "repeat", "base_position"} for slot in first["slots"])
    assert first["schedule_sha256"] == schedule_sha256(first)
    for slot in first["slots"]:
        assert slot["scheduled_run_id"] == scheduled_run_id(
            case_id=slot["case_id"],
            architecture=slot["architecture"],
            cell=slot["cell"],
            repeat=slot["repeat"],
            schedule_sha256=first["schedule_sha256"],
        )


def test_click_schedule_uses_cyclic_round_offsets() -> None:
    payload = build_snapshot_schedule(seed=20260922, case_ids=["case-a"])

    assert payload["rounds"]["R2"] == payload["rounds"]["R1"][1:] + payload["rounds"]["R1"][:1]
    assert payload["rounds"]["R3"] == payload["rounds"]["R1"][2:] + payload["rounds"]["R1"][:2]


def test_existing_click_schedule_refuses_seed_protocol_or_hash_drift(tmp_path: Path) -> None:
    path = tmp_path / "execution-schedule.json"
    write_snapshot_schedule(path, seed=20260922, case_ids=["case-a"])

    assert write_snapshot_schedule(path, seed=20260922, case_ids=["case-a"]) == path
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["protocol_version"] = 99
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="schedule mismatch"):
        write_snapshot_schedule(path, seed=20260922, case_ids=["case-a"])
