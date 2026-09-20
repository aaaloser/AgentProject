from __future__ import annotations

import json
from pathlib import Path

from mokioclaw.evals.snapshot_analysis import classify_relaxed, is_deep_progress, map_q1, map_q2, write_snapshot_analysis


def counts(**overrides):
    base = {"n": 6, "ts": 0, "bud": 0, "tout": 0, "res": 0, "over40": 0, "deep": 0, "nonres": 0}
    base.update(overrides)
    return base


def test_stage_mapping_is_frozen_and_react_is_excluded() -> None:
    assert is_deep_progress("plan-execute", "verify", 1) is True
    assert is_deep_progress("multi-agent", "context_monitor", 1) is True
    assert is_deep_progress("multi-agent", "context_compressor", 1) is True
    assert is_deep_progress("multi-agent", "verifier", 1) is True
    assert is_deep_progress("multi-agent", "final", 1) is True
    assert is_deep_progress("multi-agent", "planner", 1) is False
    assert is_deep_progress("plan-execute", "unknown", 2) is True
    assert is_deep_progress("react", "verifier", 3) is False


def test_four_states_are_ordered_mece_and_nonres_alone_is_not_relief() -> None:
    anchor = counts(ts=0, bud=4, tout=1, res=5, deep=1)
    assert classify_relaxed(anchor, counts(ts=2, bud=1, tout=1, res=2, deep=3))["state"] == "resource-relief-success"
    assert classify_relaxed(anchor, counts(ts=0, bud=1, tout=1, res=2, deep=3, nonres=3))["state"] == "resource-relief-no-success"
    assert classify_relaxed(anchor, counts(ts=0, bud=3, tout=1, res=4, deep=1))["state"] == "resource-still-binding"
    low_anchor = counts(ts=0, bud=2, tout=0, res=2, deep=1, nonres=0)
    result = classify_relaxed(low_anchor, counts(ts=0, bud=2, tout=0, res=2, deep=1, nonres=3))
    assert result["state"] == "no-resource-signal / inconclusive"
    assert result["failure_migration"] is True


def test_q1_and_q2_compare_cells_not_architectures() -> None:
    anchor = counts(ts=0, bud=4, tout=0, res=4, deep=0)
    budget = counts(ts=0, bud=0, tout=3, res=3, deep=3, over40=2)
    timeout = counts(ts=0, bud=4, tout=0, res=4, deep=0)
    joint = counts(ts=3, bud=0, tout=1, res=1, deep=4, over40=3)
    q1 = map_q1({"A": anchor, "B": budget, "T": timeout, "J": joint})
    assert q1["signal"] == "budget-axis directional signal"
    assert q1["budget_priority_pattern"] is True
    q2 = map_q2({"A": anchor, "B": budget, "T": timeout, "J": joint})
    assert q2["signal"] == "dual-axis conversion"


def test_incomplete_counts_never_emit_a_final_state() -> None:
    result = classify_relaxed(counts(n=2), counts(n=2, ts=2, deep=2))
    assert result["state"] == "incomplete"


def test_snapshot_writer_preserves_thresholds_and_warns_on_bad_inputs(tmp_path: Path) -> None:
    root = tmp_path / "snapshot"
    anchor = root / "anchor-b40-t600"
    anchor.mkdir(parents=True)
    (anchor / "experiment.json").write_text("{}", encoding="utf-8")
    report_dir = anchor / "runs" / "multi-agent" / "case-a-r1"
    report_dir.mkdir(parents=True)
    result = {
        "status": "passed",
        "success": True,
        "attempts": 1,
        "tool_calls": 2,
        "metadata": {"last_stage": "final"},
        "grader_checks": [],
    }
    (report_dir / "results.json").write_text(json.dumps([result]), encoding="utf-8")
    rows = [
        {"architecture": "multi-agent", "case_id": "case-a", "repeat": 1, "report_dir": "runs/multi-agent/case-a-r1"},
        {"architecture": "multi-agent", "case_id": "missing", "repeat": 1, "report_dir": "runs/multi-agent/missing-r1"},
        {"architecture": "multi-agent", "case_id": "bad", "repeat": 1, "report_dir": "runs/multi-agent/bad-r1"},
        {"architecture": "unknown", "case_id": "unknown", "repeat": 1, "report_dir": "runs/unknown/unknown-r1"},
        {"architecture": "multi-agent", "case_id": "mystery", "repeat": 1, "report_dir": "runs/multi-agent/mystery-r1"},
    ]
    (anchor / "manifest.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    bad_dir = anchor / "runs" / "multi-agent" / "bad-r1"
    bad_dir.mkdir(parents=True)
    (bad_dir / "results.json").write_text("{bad json", encoding="utf-8")
    mystery_dir = anchor / "runs" / "multi-agent" / "mystery-r1"
    mystery_dir.mkdir(parents=True)
    (mystery_dir / "results.json").write_text(
        json.dumps([{**result, "metadata": {"last_stage": "mystery"}}]), encoding="utf-8"
    )

    paths = write_snapshot_analysis(root, thresholds_only=True)
    threshold_bytes = paths["thresholds"].read_bytes()

    for cell in ("cell-b80-t600", "cell-b40-t900", "cell-b80-t900"):
        cell_dir = root / cell
        cell_dir.mkdir(parents=True)
        (cell_dir / "experiment.json").write_text("{}", encoding="utf-8")
        (cell_dir / "manifest.jsonl").write_text("", encoding="utf-8")
    paths = write_snapshot_analysis(root)

    assert all(path.exists() for path in paths.values())
    assert paths["thresholds"].read_bytes() == threshold_bytes
    pooled = json.loads(paths["pooled"].read_text(encoding="utf-8"))
    assert pooled["warnings"]
    assert pooled["status"] == "incomplete"
