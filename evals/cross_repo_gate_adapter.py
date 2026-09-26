"""Bind a frozen Click integrity gate to the existing cross-repository comparator.

This reporting-only module stays outside the framework source tree frozen in the
Click experiment identity. It never edits completed analysis inputs.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from mokioclaw.evals.cross_repo_comparison import _markdown, build_comparison


INPUT_NAMES = frozenset(
    {"rich_analysis", "click_analysis", "click_sensitivity", "rich_legacy_audit", "click_integrity"}
)
INTEGRITY_FLAGS = frozenset(
    {"artifact_completeness", "call_journal", "fingerprint", "secret_scan", "transport_ledger", "worker_ledger"}
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("comparison input must be a JSON object")
    return value


def _click_audit_status(gate: dict[str, Any]) -> str:
    slots = gate.get("slots")
    flags = gate.get("integrity")
    stop = gate.get("stop_status")
    complete = (
        gate.get("status") == "awaiting_final_analysis"
        and isinstance(slots, dict)
        and slots.get("scheduled") in {36, 72}
        and slots.get("started") == slots.get("scheduled")
        and slots.get("closed") == slots.get("scheduled")
        and slots.get("not_started") == 0
        and isinstance(flags, dict)
        and all(flags.get(name) is True for name in INTEGRITY_FLAGS)
        and isinstance(stop, dict)
        and stop.get("stopped") is False
    )
    return "complete" if complete else "limited"


def write_gate_bound_comparison(
    output_dir: Path,
    *,
    rich_analysis_path: Path,
    click_analysis_path: Path,
    click_sensitivity_path: Path,
    rich_legacy_audit_path: Path,
    click_integrity_path: Path,
    hash_manifest_path: Path,
) -> dict[str, Path]:
    paths = {
        "rich_analysis": Path(rich_analysis_path),
        "click_analysis": Path(click_analysis_path),
        "click_sensitivity": Path(click_sensitivity_path),
        "rich_legacy_audit": Path(rich_legacy_audit_path),
        "click_integrity": Path(click_integrity_path),
    }
    manifest = _read_json(Path(hash_manifest_path))
    hashes = manifest.get("artifacts")
    if manifest.get("schema_version") != 1 or not isinstance(hashes, dict) or set(hashes) != INPUT_NAMES:
        raise ValueError("hash manifest must bind exactly five approved machine summaries")
    for name, path in paths.items():
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if str(hashes[name]).lower() != actual:
            raise RuntimeError(f"comparison input hash mismatch: {name}")

    values = {name: _read_json(path) for name, path in paths.items()}
    sensitivity = deepcopy(values["click_sensitivity"])
    derived = _click_audit_status(values["click_integrity"])
    embedded = sensitivity.get("audit_completeness")
    if embedded is not None and embedded != derived:
        raise ValueError("Click sensitivity audit status conflicts with integrity gate")
    sensitivity["audit_completeness"] = derived
    comparison = build_comparison(
        values["rich_analysis"],
        values["click_analysis"],
        sensitivity,
        values["rich_legacy_audit"],
    )
    architectures = sensitivity["architectures"]
    comparison["supporting_audit"].update(
        {
            "per_case_divergence": {
                "rich": values["rich_analysis"].get("divergence", {}),
                "click": values["click_analysis"].get("divergence", {}),
            },
            "provider_attrition": {
                "rich_legacy_count": values["rich_legacy_audit"].get("provider_attrition", {}).get("count"),
                "click_by_architecture": {
                    architecture: value["provider_attrition_by_cell"]
                    for architecture, value in sorted(architectures.items())
                    if isinstance(value, dict) and "provider_attrition_by_cell" in value
                },
            },
            "telemetry_coverage": {
                "rich": values["rich_legacy_audit"].get("token_telemetry", {}),
                "click": values["click_integrity"].get("coverage", {}),
            },
        }
    )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = {
        "json": output_dir / "comparison.json",
        "markdown": output_dir / "comparison.md",
        "audit": output_dir / "comparison-audit.json",
    }
    if any(path.exists() for path in output_paths.values()):
        raise FileExistsError("comparison output already exists; use a new root")
    output_paths["json"].write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    output_paths["markdown"].write_text(_markdown(comparison), encoding="utf-8", newline="\n")
    output_paths["audit"].write_text(
        json.dumps({"input_sha256": hashes}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    return output_paths
