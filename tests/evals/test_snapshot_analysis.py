from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from mokioclaw.evals.snapshot_analysis import (
    DEFAULT_ANALYSIS_SPEC_PATH,
    analyze_provider_sensitivity,
    classify_relaxed,
    is_deep_progress,
    map_q1,
    map_q2,
    write_snapshot_analysis,
)
from mokioclaw.evals.analysis_spec import load_analysis_spec


def counts(**overrides):
    base = {"n": 6, "ts": 0, "bud": 0, "tout": 0, "res": 0, "tool_ge_45": 0, "deep": 0, "nonres": 0}
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
    budget = counts(ts=0, bud=0, tout=3, res=3, deep=3, tool_ge_45=2)
    timeout = counts(ts=0, bud=4, tout=0, res=4, deep=0)
    joint = counts(ts=3, bud=0, tout=1, res=1, deep=4, tool_ge_45=3)
    q1 = map_q1({"A": anchor, "B": budget, "T": timeout, "J": joint})
    assert q1["signal"] == "budget-axis directional signal"
    assert q1["budget_priority_pattern"] is False
    q2 = map_q2({"A": anchor, "B": budget, "T": timeout, "J": joint})
    assert q2["signal"] == "dual-axis conversion"


def test_budget_priority_requires_relief_on_both_axes() -> None:
    anchor = counts(ts=0, bud=4, tout=0, res=4, deep=0)
    budget = counts(ts=0, bud=0, tout=2, res=2, deep=3, tool_ge_45=2)
    timeout = counts(ts=0, bud=2, tout=2, res=4, deep=0)
    joint = counts(ts=2, bud=0, tout=1, res=1, deep=3, tool_ge_45=2)
    result = map_q1({"A": anchor, "B": budget, "T": timeout, "J": joint})
    assert result["signal"] == "budget-axis directional signal"
    assert result["budget_priority_pattern"] is False


def test_incomplete_counts_never_emit_a_final_state() -> None:
    result = classify_relaxed(counts(n=2), counts(n=2, ts=2, deep=2))
    assert result["state"] == "incomplete"


@pytest.mark.parametrize(
    "relief_b,relief_t,relief_j,expected",
    [
        (True, False, False, "budget-axis directional signal"),
        (False, True, False, "timeout-axis directional signal"),
        (True, True, False, "both axes independently influential"),
        (False, False, True, "joint constraint / interaction"),
        (False, False, False, "no axis-order signal / inconclusive"),
    ],
)
def test_q1_golden_five_branch_mapping(relief_b: bool, relief_t: bool, relief_j: bool, expected: str) -> None:
    anchor = counts(bud=4, res=4)

    def relaxed(enabled: bool) -> dict:
        return counts(bud=2 if enabled else 4, res=2 if enabled else 4)

    assert map_q1({"A": anchor, "B": relaxed(relief_b), "T": relaxed(relief_t), "J": relaxed(relief_j)})["signal"] == expected


@pytest.mark.parametrize(
    "budget,joint,expected,booleans",
    [
        (
            counts(bud=0, tout=3, deep=2),
            counts(ts=2, tout=1),
            "dual-axis conversion",
            (True, True, False),
        ),
        (
            counts(bud=0, tout=3, deep=2),
            counts(ts=0, tout=2),
            "time still binding",
            (True, False, True),
        ),
        (
            counts(bud=1, tout=1, deep=0),
            counts(ts=0, tout=0),
            "no time-wall migration signal / inconclusive",
            (False, False, False),
        ),
    ],
)
def test_q2_golden_three_boolean_mapping(budget: dict, joint: dict, expected: str, booleans: tuple[bool, bool, bool]) -> None:
    result = map_q2({"A": counts(deep=0), "B": budget, "T": counts(), "J": joint})
    assert result["signal"] == expected
    assert (result["time_wall_shift"], result["dual_axis_conversion"], result["time_still_binding"]) == booleans


def _provider_fixture(name: str) -> dict:
    path = Path(__file__).parent / "fixtures" / "snapshot-analysis" / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_provider_5_of_6_with_balanced_attrition_can_be_qualified_and_stable() -> None:
    fixture = _provider_fixture("qualified-stable")
    result = analyze_provider_sensitivity("multi-agent", fixture["cells"], evidence_complete=True)

    assert result["qualification"] == "qualified"
    assert result["clean_by_cell"]["A"] == 5
    assert result["attrition_range"] == 1
    assert result["q1"]["qualified"] is True
    assert result["q1"]["signal"] == "both axes independently influential"


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda cells: cells["A"].update(provider_attrition=2), "minimum_clean_per_cell"),
        (lambda cells: cells["A"].update(provider_attrition=2, n=7), "max_attrition_range"),
    ],
)
def test_provider_minimum_gate_rejects_low_clean_or_attrition_range(mutation, reason: str) -> None:
    fixture = _provider_fixture("qualified-stable")
    mutation(fixture["cells"])
    result = analyze_provider_sensitivity("multi-agent", fixture["cells"], evidence_complete=True)

    assert result["qualification"] == "provider-attrition / inconclusive"
    assert reason in result["qualification_failures"]


def test_provider_minimum_gate_requires_structured_ledgers() -> None:
    fixture = _provider_fixture("qualified-stable")
    result = analyze_provider_sensitivity("plan-execute", fixture["cells"], evidence_complete=False)

    assert result["qualification"] == "provider-attrition / inconclusive"
    assert "provider_evidence_incomplete" in result["qualification_failures"]


@pytest.mark.parametrize(("fixture_name", "field"), [("q1-sensitive", "q1"), ("q2-sensitive", "q2")])
def test_provider_completion_enumeration_detects_label_flips(fixture_name: str, field: str) -> None:
    fixture = _provider_fixture(fixture_name)
    result = analyze_provider_sensitivity("plan-execute", fixture["cells"], evidence_complete=True)

    assert result["qualification"] == "provider-sensitive / inconclusive"
    assert result[field]["qualified"] is False
    assert len(result[field]["candidates"]) > 1


def test_single_case_branch_never_emits_formal_states_or_q_labels() -> None:
    fixture = _provider_fixture("qualified-stable")
    for value in fixture["cells"].values():
        value["n"] = 3
        value["provider_attrition"] = 0
    result = analyze_provider_sensitivity(
        "multi-agent", fixture["cells"], evidence_complete=True, scheduled_n=3, formal_labels=False
    )

    assert result["qualification"] == "single-case evidence / repository-level corroboration inconclusive"
    assert "states" not in result
    assert "q1" not in result
    assert "q2" not in result


def test_single_case_writer_omits_formal_pooled_labels(tmp_path: Path) -> None:
    root = tmp_path / "single-case"
    for cell in ("anchor-b40-t600", "cell-b80-t600", "cell-b40-t900", "cell-b80-t900"):
        cell_root = root / cell
        report = cell_root / "runs" / "multi-agent" / "case-a-r1"
        report.mkdir(parents=True)
        (cell_root / "experiment.json").write_text("{}", encoding="utf-8")
        row = {
            "architecture": "multi-agent",
            "case_id": "case-a",
            "repeat": 1,
            "report_dir": "runs/multi-agent/case-a-r1",
        }
        (cell_root / "manifest.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        (report / "results.json").write_text(
            json.dumps([{"status": "budget_exhausted", "success": False, "tool_calls": 40, "attempts": 1}]),
            encoding="utf-8",
        )

    paths = write_snapshot_analysis(root)
    pooled = json.loads(paths["pooled"].read_text(encoding="utf-8"))

    assert pooled["branch"] == "single_case"
    assert pooled["comparison_qualification"] == "single-case evidence / repository-level corroboration inconclusive"
    assert "states" not in pooled
    assert "q1" not in pooled
    assert "q2" not in pooled
    report = paths["report"].read_text(encoding="utf-8")
    assert "Pooled states" not in report
    assert "## Q1" not in report
    assert "## Q2" not in report


def test_incomplete_two_case_writer_refuses_formal_effect_labels(tmp_path: Path) -> None:
    paths = write_snapshot_analysis(tmp_path / "incomplete-two-case")
    pooled = json.loads(paths["pooled"].read_text(encoding="utf-8"))

    assert pooled["branch"] == "two_case"
    assert pooled["status"] == "incomplete"
    assert "states" not in pooled
    assert "q1" not in pooled
    assert "q2" not in pooled
    report = paths["report"].read_text(encoding="utf-8")
    assert "Pooled states" not in report
    assert "## Q1" not in report
    assert "## Q2" not in report


def test_react_attrition_is_not_an_input_to_other_architecture_qualification() -> None:
    fixture = _provider_fixture("qualified-stable")
    baseline = analyze_provider_sensitivity("multi-agent", fixture["cells"], evidence_complete=True)
    fixture["react_attrition"] = {"A": 6, "B": 0, "T": 6, "J": 0}

    assert analyze_provider_sensitivity("multi-agent", fixture["cells"], evidence_complete=True) == baseline


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
    assert {"provider_sensitivity", "react_canary", "audit"} <= set(paths)
    expected_spec_hash = load_analysis_spec(DEFAULT_ANALYSIS_SPEC_PATH).sha256
    for name in ("thresholds", "per_case", "pooled", "provider_sensitivity", "react_canary"):
        payload = json.loads(paths[name].read_text(encoding="utf-8"))
        assert payload["analysis_spec_sha256"] == expected_spec_hash


def test_hash_critical_outputs_are_path_timezone_and_locale_independent(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    anchor = source / "anchor-b40-t600"
    anchor.mkdir(parents=True)
    (anchor / "experiment.json").write_text("{}", encoding="utf-8")
    (anchor / "manifest.jsonl").write_text("", encoding="utf-8")
    for cell in ("cell-b80-t600", "cell-b40-t900", "cell-b80-t900"):
        target = source / cell
        target.mkdir()
        (target / "experiment.json").write_text("{}", encoding="utf-8")
        (target / "manifest.jsonl").write_text("", encoding="utf-8")
    left = tmp_path / "different-absolute-a" / "snapshot"
    right = tmp_path / "different-absolute-b" / "much-longer" / "snapshot"
    shutil.copytree(source, left)
    shutil.copytree(source, right)

    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setenv("LC_ALL", "C")
    left_paths = write_snapshot_analysis(left)
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    right_paths = write_snapshot_analysis(right)

    stable_names = {"thresholds", "per_case", "pooled", "provider_sensitivity", "react_canary", "report"}
    assert os.environ["TZ"] == "Asia/Shanghai"
    assert {name: left_paths[name].read_bytes() for name in stable_names} == {
        name: right_paths[name].read_bytes() for name in stable_names
    }
    assert json.loads(left_paths["audit"].read_text(encoding="utf-8"))["root"] == str(left)
    assert json.loads(right_paths["audit"].read_text(encoding="utf-8"))["root"] == str(right)
