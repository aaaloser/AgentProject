from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

import pytest


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _inputs(root: Path) -> tuple[dict[str, Path], Path]:
    rich = {
        "status": "complete", "branch": "two_case",
        "divergence": {"multi-agent": {"T": {"divergent": True}}},
        "q1": {
            "multi-agent": {"signal": "both axes independently influential", "budget_priority_pattern": True},
            "plan-execute": {"signal": "both axes independently influential", "budget_priority_pattern": True},
        },
        "q2": {"signal": "no time-wall migration signal / inconclusive"},
    }
    click = {
        "status": "complete", "branch": "two_case",
        "divergence": {"multi-agent": {"T": {"divergent": False}}},
    }
    sensitivity = {
        "architectures": {
            "multi-agent": {
                "qualification": "qualified",
                "provider_attrition_by_cell": {"A": 0, "B": 0, "T": 0, "J": 0},
                "q1": {"qualified": True, "signal": "budget-axis directional signal", "budget_priority_pattern": False},
            },
            "plan-execute": {
                "qualification": "qualified",
                "q1": {"qualified": True, "signal": "budget-axis directional signal", "budget_priority_pattern": False},
                "q2": {"qualified": True, "signal": "no time-wall migration signal / inconclusive"},
            },
        }
    }
    legacy = {
        "audit_completeness": "limited", "historical_worker_attempt_completeness": "limited",
        "provider_attrition": {"count": 22},
        "token_telemetry": {"full": 21, "partial": 0, "unavailable": 51},
    }
    gate = {
        "status": "awaiting_final_analysis",
        "slots": {"scheduled": 72, "started": 72, "closed": 72, "not_started": 0},
        "stop_status": {"stopped": False},
        "coverage": {"full": 66, "partial": 6, "unavailable": 0},
        "integrity": {
            "artifact_completeness": True, "call_journal": True, "fingerprint": True,
            "secret_scan": True, "transport_ledger": True, "worker_ledger": True,
        },
    }
    values = {
        "rich_analysis": rich,
        "click_analysis": click,
        "click_sensitivity": sensitivity,
        "rich_legacy_audit": legacy,
        "click_integrity": gate,
    }
    paths = {name: root / f"{name}.json" for name in values}
    for name, path in paths.items():
        _write_json(path, values[name])
    manifest = root / "input-hashes.json"
    _write_json(
        manifest,
        {"schema_version": 1, "artifacts": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}},
    )
    return paths, manifest


def test_gate_bound_writer_uses_verified_click_audit_without_changing_frozen_input(tmp_path: Path) -> None:
    adapter = importlib.import_module("evals.cross_repo_gate_adapter")
    paths, manifest = _inputs(tmp_path / "inputs")
    frozen_sensitivity = paths["click_sensitivity"].read_bytes()

    outputs = adapter.write_gate_bound_comparison(
        tmp_path / "output", hash_manifest_path=manifest,
        **{f"{name}_path": path for name, path in paths.items()},
    )

    comparison = json.loads(outputs["json"].read_text(encoding="utf-8"))
    assert comparison["direction_comparison"] == "inconclusive"
    assert comparison["strict_audit_status"] == "legacy-audit-limited"
    assert comparison["supporting_audit"]["click_audit_completeness"] == "complete"
    assert paths["click_sensitivity"].read_bytes() == frozen_sensitivity
    assert set(json.loads(outputs["audit"].read_text(encoding="utf-8"))["input_sha256"]) == set(paths)

    _write_json(paths["click_integrity"], {"status": "tampered"})
    with pytest.raises(RuntimeError, match="hash mismatch: click_integrity"):
        adapter.write_gate_bound_comparison(
            tmp_path / "refused", hash_manifest_path=manifest,
            **{f"{name}_path": path for name, path in paths.items()},
        )


def test_gate_bound_writer_reports_supporting_evidence_without_pooling_repositories(tmp_path: Path) -> None:
    adapter = importlib.import_module("evals.cross_repo_gate_adapter")
    paths, manifest = _inputs(tmp_path / "inputs")

    outputs = adapter.write_gate_bound_comparison(
        tmp_path / "output", hash_manifest_path=manifest,
        **{f"{name}_path": path for name, path in paths.items()},
    )

    comparison = json.loads(outputs["json"].read_text(encoding="utf-8"))
    audit = comparison["supporting_audit"]
    assert audit["per_case_divergence"] == {
        "rich": {"multi-agent": {"T": {"divergent": True}}},
        "click": {"multi-agent": {"T": {"divergent": False}}},
    }
    assert audit["provider_attrition"] == {
        "rich_legacy_count": 22,
        "click_by_architecture": {"multi-agent": {"A": 0, "B": 0, "T": 0, "J": 0}},
    }
    assert audit["telemetry_coverage"] == {
        "rich": {"full": 21, "partial": 0, "unavailable": 51},
        "click": {"full": 66, "partial": 6, "unavailable": 0},
    }
    assert "pooled_counts" not in comparison
