from __future__ import annotations

import json
from pathlib import Path

import pytest

from mokioclaw.evals.snapshot_schedule import build_snapshot_schedule, write_snapshot_schedule


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

    assert json.loads(path.read_text(encoding="utf-8"))["seed"] == 20260920
