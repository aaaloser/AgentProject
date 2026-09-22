from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT_FIELDS = frozenset(
    {
        "branches",
        "canonical_output",
        "cells",
        "counters",
        "deep_progress",
        "non_resource_family",
        "provider_sensitivity",
        "q1",
        "q2",
        "schema_version",
        "single_case_output",
        "state_precedence",
        "thresholds",
    }
)
EXPECTED_CELLS = {
    "A": {"max_tool_calls": 40, "wall_time_seconds": 600},
    "B": {"max_tool_calls": 80, "wall_time_seconds": 600},
    "J": {"max_tool_calls": 80, "wall_time_seconds": 900},
    "T": {"max_tool_calls": 40, "wall_time_seconds": 900},
}
EXPECTED_BRANCHES = {
    "single_case": {"formal_labels": False, "scheduled_n": 3},
    "two_case": {"formal_labels": True, "scheduled_n": 6},
}
EXPECTED_COUNTERS = ["n", "ts", "bud", "tout", "res", "tool_ge_45", "deep", "nonres", "provider_attrition"]
EXPECTED_NON_RESOURCE_FAMILY = [
    "hidden_contract_miss_after_validation",
    "patch_generation_failure",
    "protected_file_violation",
    "public_regression_failed",
]
EXPECTED_DEEP_PROGRESS = {
    "multi-agent": {
        "agent_attempt_count_at_least": 2,
        "last_stage_in": ["context_compressor", "context_monitor", "final", "verifier"],
    },
    "plan-execute": {"agent_attempt_count_at_least": 2, "last_stage_in": ["verify"]},
    "react": None,
}
EXPECTED_THRESHOLDS = {
    "deep_delta": 2,
    "non_resource_delta": 2,
    "resource_drop": 2,
    "resource_still_binding_min": 3,
    "success_delta": 2,
    "tool_call_threshold": 45,
    "tool_ge_threshold_runs": 2,
}


@dataclass(frozen=True)
class LoadedAnalysisSpec:
    payload: dict[str, Any]
    canonical_bytes: bytes
    sha256: str


def canonical_json_bytes(payload: Any) -> bytes:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return (text + "\n").encode("utf-8")


def _require_mapping(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{location} must be an object")
    return value


def _require_exact_keys(value: dict[str, Any], expected: set[str] | frozenset[str], location: str) -> None:
    missing = sorted(expected - value.keys())
    unknown = sorted(value.keys() - expected)
    if missing:
        raise ValueError(f"{location} missing fields: {missing}")
    if unknown:
        raise ValueError(f"{location} unknown fields: {unknown}")


def _require_equal(value: Any, expected: Any, location: str) -> None:
    if value != expected:
        raise ValueError(f"{location} does not match the frozen resource-analysis-v1 contract")


def validate_analysis_spec(payload: Any) -> None:
    root = _require_mapping(payload, "analysis spec")
    _require_exact_keys(root, ROOT_FIELDS, "analysis spec")
    _require_equal(root["schema_version"], 1, "schema_version")

    cells = _require_mapping(root["cells"], "cells")
    _require_exact_keys(cells, set(EXPECTED_CELLS), "cells")
    for label, expected in EXPECTED_CELLS.items():
        cell = _require_mapping(cells[label], f"cells.{label}")
        _require_exact_keys(cell, set(expected), f"cells.{label}")
        _require_equal(cell, expected, f"cells.{label}")

    branches = _require_mapping(root["branches"], "branches")
    _require_exact_keys(branches, set(EXPECTED_BRANCHES), "branches")
    for name, expected in EXPECTED_BRANCHES.items():
        branch = _require_mapping(branches[name], f"branches.{name}")
        _require_exact_keys(branch, set(expected), f"branches.{name}")
        _require_equal(branch, expected, f"branches.{name}")

    _require_equal(root["counters"], EXPECTED_COUNTERS, "counters")
    _require_equal(root["non_resource_family"], EXPECTED_NON_RESOURCE_FAMILY, "non_resource_family")
    _require_equal(root["deep_progress"], EXPECTED_DEEP_PROGRESS, "deep_progress")
    _require_equal(root["thresholds"], EXPECTED_THRESHOLDS, "thresholds")

    state_precedence = root["state_precedence"]
    if not isinstance(state_precedence, list) or [item.get("label") for item in state_precedence if isinstance(item, dict)] != [
        "resource-relief-success",
        "resource-relief-no-success",
        "resource-still-binding",
        "no-resource-signal / inconclusive",
    ]:
        raise ValueError("state_precedence does not match the frozen order")
    for index, item in enumerate(state_precedence):
        mapping = _require_mapping(item, f"state_precedence[{index}]")
        _require_exact_keys(mapping, {"label", "requires"}, f"state_precedence[{index}]")
        if not isinstance(mapping["requires"], list) or not all(isinstance(entry, str) for entry in mapping["requires"]):
            raise ValueError(f"state_precedence[{index}].requires must be a string list")

    q1 = _require_mapping(root["q1"], "q1")
    _require_exact_keys(q1, {"budget_priority_requires", "inconclusive_label", "mapping"}, "q1")
    _require_equal(
        q1["budget_priority_requires"],
        ["relief_b", "relief_t", "budget_b_eq_0", "budget_t_gte_1"],
        "q1.budget_priority_requires",
    )
    _require_equal(q1["inconclusive_label"], "no axis-order signal / inconclusive", "q1.inconclusive_label")
    if not isinstance(q1["mapping"], list) or [item.get("label") for item in q1["mapping"] if isinstance(item, dict)] != [
        "budget-axis directional signal",
        "timeout-axis directional signal",
        "both axes independently influential",
        "joint constraint / interaction",
    ]:
        raise ValueError("q1.mapping does not match the frozen order")
    for index, item in enumerate(q1["mapping"]):
        mapping = _require_mapping(item, f"q1.mapping[{index}]")
        _require_exact_keys(mapping, {"label", "relief_b", "relief_j", "relief_t"}, f"q1.mapping[{index}]")

    q2 = _require_mapping(root["q2"], "q2")
    _require_exact_keys(q2, {"booleans", "precedence"}, "q2")
    _require_equal(q2["booleans"], ["time_wall_shift", "dual_axis_conversion", "time_still_binding"], "q2.booleans")
    _require_equal(
        q2["precedence"],
        ["dual-axis conversion", "time still binding", "no time-wall migration signal / inconclusive"],
        "q2.precedence",
    )

    sensitivity = _require_mapping(root["provider_sensitivity"], "provider_sensitivity")
    sensitivity_fields = {
        "completion_statuses",
        "deep_values",
        "enumeration_scope",
        "max_attrition_range",
        "minimum_clean_per_cell",
        "minimum_gate_failure_label",
        "qualification_scope",
        "react_enters_q1_q2",
        "scheduled_n",
        "sensitive_label",
        "tool_ge_45_values_by_cell",
    }
    _require_exact_keys(sensitivity, sensitivity_fields, "provider_sensitivity")
    _require_equal(sensitivity["qualification_scope"], "per_architecture", "provider_sensitivity.qualification_scope")
    _require_equal(sensitivity["enumeration_scope"], "per_architecture", "provider_sensitivity.enumeration_scope")
    _require_equal(sensitivity["scheduled_n"], 6, "provider_sensitivity.scheduled_n")
    _require_equal(sensitivity["minimum_clean_per_cell"], 5, "provider_sensitivity.minimum_clean_per_cell")
    _require_equal(sensitivity["max_attrition_range"], 1, "provider_sensitivity.max_attrition_range")
    _require_equal(sensitivity["react_enters_q1_q2"], False, "provider_sensitivity.react_enters_q1_q2")
    _require_equal(
        sensitivity["completion_statuses"],
        ["budget_exhausted", "non_resource_failed", "other_failed", "passed", "timed_out"],
        "provider_sensitivity.completion_statuses",
    )
    _require_equal(sensitivity["deep_values"], [0, 1], "provider_sensitivity.deep_values")
    _require_equal(
        sensitivity["tool_ge_45_values_by_cell"],
        {"A": [0], "B": [0, 1], "J": [0, 1], "T": [0]},
        "provider_sensitivity.tool_ge_45_values_by_cell",
    )
    _require_equal(
        sensitivity["minimum_gate_failure_label"],
        "provider-attrition / inconclusive",
        "provider_sensitivity.minimum_gate_failure_label",
    )
    _require_equal(
        sensitivity["sensitive_label"],
        "provider-sensitive / inconclusive",
        "provider_sensitivity.sensitive_label",
    )

    single_case = _require_mapping(root["single_case_output"], "single_case_output")
    _require_exact_keys(single_case, {"allowed", "comparison_qualification", "forbidden"}, "single_case_output")
    _require_equal(
        single_case["comparison_qualification"],
        "single-case evidence / repository-level corroboration inconclusive",
        "single_case_output.comparison_qualification",
    )
    if not isinstance(single_case["allowed"], list) or not isinstance(single_case["forbidden"], list):
        raise ValueError("single_case_output allowed and forbidden fields must be lists")

    canonical = _require_mapping(root["canonical_output"], "canonical_output")
    _require_exact_keys(
        canonical,
        {"absolute_paths", "encoding", "json_keys", "line_ending", "list_order", "unstable_metadata_file"},
        "canonical_output",
    )
    _require_equal(canonical["encoding"], "utf-8", "canonical_output.encoding")
    _require_equal(canonical["line_ending"], "lf", "canonical_output.line_ending")
    _require_equal(canonical["json_keys"], "sorted", "canonical_output.json_keys")
    _require_equal(canonical["list_order"], "spec_defined", "canonical_output.list_order")
    _require_equal(canonical["absolute_paths"], False, "canonical_output.absolute_paths")
    _require_equal(canonical["unstable_metadata_file"], "analysis-audit.json", "canonical_output.unstable_metadata_file")


def load_analysis_spec(path: Path) -> LoadedAnalysisSpec:
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_analysis_spec(payload)
    canonical = canonical_json_bytes(payload)
    return LoadedAnalysisSpec(payload, canonical, hashlib.sha256(canonical).hexdigest())
