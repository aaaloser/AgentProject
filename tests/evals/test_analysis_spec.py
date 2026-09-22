from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from mokioclaw.evals.analysis_spec import canonical_json_bytes, load_analysis_spec


SPEC_PATH = Path("evals/specs/resource-analysis-v1.json")


def test_frozen_analysis_spec_encodes_all_analysis_contracts(tmp_path: Path) -> None:
    source_payload = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    noncanonical = tmp_path / "resource-analysis.json"
    noncanonical.write_text(json.dumps(source_payload, ensure_ascii=False, indent=4), encoding="utf-8")

    loaded = load_analysis_spec(noncanonical)

    assert loaded.payload["cells"] == {
        "A": {"max_tool_calls": 40, "wall_time_seconds": 600},
        "B": {"max_tool_calls": 80, "wall_time_seconds": 600},
        "J": {"max_tool_calls": 80, "wall_time_seconds": 900},
        "T": {"max_tool_calls": 40, "wall_time_seconds": 900},
    }
    assert loaded.payload["branches"] == {
        "single_case": {"formal_labels": False, "scheduled_n": 3},
        "two_case": {"formal_labels": True, "scheduled_n": 6},
    }
    assert loaded.payload["counters"] == [
        "n",
        "ts",
        "bud",
        "tout",
        "res",
        "tool_ge_45",
        "deep",
        "nonres",
        "provider_attrition",
    ]
    assert loaded.payload["non_resource_family"] == [
        "hidden_contract_miss_after_validation",
        "patch_generation_failure",
        "protected_file_violation",
        "public_regression_failed",
    ]
    assert loaded.payload["deep_progress"] == {
        "multi-agent": {
            "agent_attempt_count_at_least": 2,
            "last_stage_in": ["context_compressor", "context_monitor", "final", "verifier"],
        },
        "plan-execute": {"agent_attempt_count_at_least": 2, "last_stage_in": ["verify"]},
        "react": None,
    }
    assert loaded.payload["q1"]["budget_priority_requires"] == [
        "relief_b",
        "relief_t",
        "budget_b_eq_0",
        "budget_t_gte_1",
    ]
    assert loaded.payload["q2"]["precedence"] == [
        "dual-axis conversion",
        "time still binding",
        "no time-wall migration signal / inconclusive",
    ]
    sensitivity = loaded.payload["provider_sensitivity"]
    assert sensitivity["qualification_scope"] == "per_architecture"
    assert sensitivity["enumeration_scope"] == "per_architecture"
    assert sensitivity["minimum_clean_per_cell"] == 5
    assert sensitivity["scheduled_n"] == 6
    assert sensitivity["react_enters_q1_q2"] is False
    assert sensitivity["completion_statuses"] == [
        "budget_exhausted",
        "non_resource_failed",
        "other_failed",
        "passed",
        "timed_out",
    ]
    assert loaded.payload["canonical_output"]["encoding"] == "utf-8"
    assert loaded.payload["canonical_output"]["line_ending"] == "lf"
    assert loaded.payload["canonical_output"]["json_keys"] == "sorted"
    assert loaded.canonical_bytes == canonical_json_bytes(source_payload)
    assert loaded.canonical_bytes.endswith(b"\n")
    assert loaded.sha256 == hashlib.sha256(loaded.canonical_bytes).hexdigest()


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda payload: payload.pop("q2"), "missing fields"),
        (lambda payload: payload.__setitem__("unexpected", True), "unknown fields"),
        (lambda payload: payload["cells"]["A"].pop("max_tool_calls"), "cells.A"),
        (lambda payload: payload["branches"]["single_case"].__setitem__("formal_labels", True), "single_case"),
        (lambda payload: payload["counters"].remove("tool_ge_45"), "counters"),
    ],
)
def test_analysis_spec_rejects_missing_unknown_or_drifted_contracts(tmp_path: Path, mutation, match: str) -> None:
    payload = deepcopy(json.loads(SPEC_PATH.read_text(encoding="utf-8")))
    mutation(payload)
    candidate = tmp_path / "invalid-spec.json"
    candidate.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=match):
        load_analysis_spec(candidate)
