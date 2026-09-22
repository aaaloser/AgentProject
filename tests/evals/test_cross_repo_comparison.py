from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from mokioclaw.evals.cross_repo_comparison import build_comparison, write_cross_repo_comparison


def inputs() -> tuple[dict, dict, dict, dict]:
    rich = {
        "status": "complete",
        "branch": "two_case",
        "q1": {
            "multi-agent": {"signal": "budget-axis directional signal", "budget_priority_pattern": False},
            "plan-execute": {"signal": "both axes independently influential", "budget_priority_pattern": True},
        },
        "q2": {"signal": "no time-wall migration signal / inconclusive"},
    }
    click = deepcopy(rich)
    sensitivity = {
        "audit_completeness": "complete",
        "architectures": {
            "multi-agent": {
                "qualification": "qualified",
                "q1": {"qualified": True, "signal": "budget-axis directional signal", "budget_priority_pattern": False},
            },
            "plan-execute": {
                "qualification": "qualified",
                "q1": {"qualified": True, "signal": "both axes independently influential", "budget_priority_pattern": True},
                "q2": {
                    "qualified": True,
                    "signal": "no time-wall migration signal / inconclusive",
                    "time_wall_shift": False,
                    "dual_axis_conversion": False,
                    "time_still_binding": False,
                },
            },
        },
    }
    legacy = {"audit_completeness": "limited", "historical_worker_attempt_completeness": "limited"}
    return rich, click, sensitivity, legacy


def test_comparator_rejects_raw_manifests_pooled_counts_and_incomplete_machine_analysis() -> None:
    rich, click, sensitivity, legacy = inputs()
    with pytest.raises(ValueError, match="raw manifest"):
        build_comparison(rich, click, sensitivity, legacy, raw_manifests=[{}])
    with pytest.raises(ValueError, match="pooled counts"):
        build_comparison(rich, click, sensitivity, legacy, pool_counts=True)
    click["status"] = "incomplete"
    with pytest.raises(ValueError, match="completed machine analysis"):
        build_comparison(rich, click, sensitivity, legacy)


def test_dimension_truth_table_and_aggregate_precedence() -> None:
    rich, click, sensitivity, legacy = inputs()
    click["q1"]["plan-execute"]["signal"] = "timeout-axis directional signal"
    sensitivity["architectures"]["plan-execute"]["q1"]["signal"] = "timeout-axis directional signal"
    sensitivity["architectures"]["plan-execute"]["q2"]["signal"] = "time still binding"

    comparison = build_comparison(rich, click, sensitivity, legacy)

    assert comparison["dimension_results"]["multi_agent_q1"]["result"] == "consistent"
    assert comparison["dimension_results"]["plan_execute_q1"]["result"] == "divergent"
    assert comparison["dimension_results"]["plan_execute_q2"]["result"] == "inconclusive"
    assert comparison["direction_comparison"] == "inconclusive"

    rich["q2"]["signal"] = "dual-axis conversion"
    sensitivity["architectures"]["plan-execute"]["q2"]["signal"] = "time still binding"
    comparison = build_comparison(rich, click, sensitivity, legacy)
    assert comparison["dimension_results"]["plan_execute_q2"]["result"] == "divergent"
    assert comparison["direction_comparison"] == "repository-specific / divergent"


def test_all_three_determinate_same_labels_are_directionally_consistent() -> None:
    rich, click, sensitivity, legacy = inputs()
    rich["q2"]["signal"] = "dual-axis conversion"
    click["q2"]["signal"] = "dual-axis conversion"
    sensitivity["architectures"]["plan-execute"]["q2"]["signal"] = "dual-axis conversion"
    sensitivity["architectures"]["plan-execute"]["q2"]["dual_axis_conversion"] = True

    comparison = build_comparison(rich, click, sensitivity, legacy)

    assert {value["result"] for value in comparison["dimension_results"].values()} == {"consistent"}
    assert comparison["direction_comparison"] == "directionally consistent"


def test_single_case_marks_all_required_dimensions_not_applicable() -> None:
    rich, click, sensitivity, legacy = inputs()
    click["branch"] = "single_case"

    comparison = build_comparison(rich, click, sensitivity, legacy)

    assert all(value["required"] is True for value in comparison["dimension_results"].values())
    assert {value["result"] for value in comparison["dimension_results"].values()} == {"not_applicable"}
    assert comparison["direction_comparison"] == "inconclusive"


def test_q1_secondary_divergence_does_not_rewrite_consistent_primary_result() -> None:
    rich, click, sensitivity, legacy = inputs()
    sensitivity["architectures"]["multi-agent"]["q1"]["budget_priority_pattern"] = True

    dimension = build_comparison(rich, click, sensitivity, legacy)["dimension_results"]["multi_agent_q1"]

    assert dimension["result"] == "consistent"
    assert dimension["secondary_result"] == "secondary-divergence"


@pytest.mark.parametrize(
    "rich_complete,click_complete,expected",
    [
        (True, True, "strict-audit-comparable"),
        (False, True, "legacy-audit-limited"),
        (True, False, "click-audit-limited"),
        (False, False, "both-audit-limited"),
    ],
)
def test_strict_audit_status_truth_table(rich_complete: bool, click_complete: bool, expected: str) -> None:
    rich, click, sensitivity, legacy = inputs()
    legacy["audit_completeness"] = "complete" if rich_complete else "limited"
    legacy["historical_worker_attempt_completeness"] = "complete" if rich_complete else "limited"
    sensitivity["audit_completeness"] = "complete" if click_complete else "limited"

    assert build_comparison(rich, click, sensitivity, legacy)["strict_audit_status"] == expected


def test_known_q2_ceiling_is_inconclusive_even_when_labels_match() -> None:
    rich, click, sensitivity, legacy = inputs()

    comparison = build_comparison(rich, click, sensitivity, legacy)
    dimension = comparison["dimension_results"]["plan_execute_q2"]

    assert dimension["same_label"] is True
    assert dimension["directional_corroboration"] is False
    assert dimension["result"] == "inconclusive"
    assert comparison["direction_comparison"] == "inconclusive"


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def test_writer_verifies_hash_manifest_and_is_deterministic_without_paths_or_times(tmp_path: Path) -> None:
    rich, click, sensitivity, legacy = inputs()
    source = tmp_path / "inputs"
    paths = {
        "rich_analysis": source / "rich.json",
        "click_analysis": source / "click.json",
        "click_sensitivity": source / "sensitivity.json",
        "rich_legacy_audit": source / "legacy.json",
    }
    for key, value in zip(paths, (rich, click, sensitivity, legacy)):
        _write_json(paths[key], value)
    manifest = source / "hash-manifest.json"
    _write_json(
        manifest,
        {
            "schema_version": 1,
            "artifacts": {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in paths.items()},
        },
    )

    first = write_cross_repo_comparison(tmp_path / "output-a", hash_manifest_path=manifest, **{f"{key}_path": value for key, value in paths.items()})
    second = write_cross_repo_comparison(tmp_path / "much-longer" / "output-b", hash_manifest_path=manifest, **{f"{key}_path": value for key, value in paths.items()})

    assert first["json"].read_bytes() == second["json"].read_bytes()
    assert first["markdown"].read_bytes() == second["markdown"].read_bytes()
    combined = first["json"].read_text(encoding="utf-8") + first["markdown"].read_text(encoding="utf-8")
    assert str(tmp_path) not in combined
    assert "generated_at" not in combined

    bad = json.loads(manifest.read_text(encoding="utf-8"))
    bad["artifacts"]["click_analysis"] = "0" * 64
    _write_json(manifest, bad)
    with pytest.raises(RuntimeError, match="hash mismatch"):
        write_cross_repo_comparison(tmp_path / "refused", hash_manifest_path=manifest, **{f"{key}_path": value for key, value in paths.items()})
