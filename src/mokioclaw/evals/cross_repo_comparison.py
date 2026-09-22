from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


Q1_DETERMINATE = frozenset(
    {
        "budget-axis directional signal",
        "timeout-axis directional signal",
        "both axes independently influential",
        "joint constraint / interaction",
    }
)
Q2_DETERMINATE = frozenset({"dual-axis conversion", "time still binding"})
INPUT_NAMES = ("rich_analysis", "click_analysis", "click_sensitivity", "rich_legacy_audit")


def _strict_audit_status(rich_complete: bool, click_complete: bool) -> str:
    if rich_complete and click_complete:
        return "strict-audit-comparable"
    if not rich_complete and click_complete:
        return "legacy-audit-limited"
    if rich_complete and not click_complete:
        return "click-audit-limited"
    return "both-audit-limited"


def _dimension(
    *,
    rich_label: str,
    click_label: str,
    determinate: frozenset[str],
    click_qualified: bool,
    not_applicable: bool,
) -> dict[str, Any]:
    same_label = rich_label == click_label
    if not_applicable:
        result = "not_applicable"
    elif not click_qualified or rich_label not in determinate or click_label not in determinate:
        result = "inconclusive"
    elif same_label:
        result = "consistent"
    else:
        result = "divergent"
    return {
        "required": True,
        "rich_label": rich_label,
        "click_label": click_label,
        "same_label": same_label,
        "directional_corroboration": result == "consistent",
        "result": result,
    }


def build_comparison(
    rich_analysis: dict[str, Any],
    click_analysis: dict[str, Any],
    click_sensitivity: dict[str, Any],
    rich_legacy_audit: dict[str, Any],
    *,
    raw_manifests: Any = None,
    pool_counts: bool = False,
) -> dict[str, Any]:
    if raw_manifests is not None:
        raise ValueError("raw manifest inputs are forbidden for cross-repository comparison")
    if pool_counts:
        raise ValueError("pooled counts cannot be merged across repositories")
    if rich_analysis.get("status") != "complete" or click_analysis.get("status") != "complete":
        raise ValueError("comparator requires completed machine analysis inputs")

    architectures = click_sensitivity.get("architectures")
    if not isinstance(architectures, dict):
        raise ValueError("Click provider sensitivity is missing architecture results")
    single_case = click_analysis.get("branch") == "single_case"
    dimension_results: dict[str, dict[str, Any]] = {}
    definitions = (
        ("multi_agent_q1", "multi-agent", "q1", Q1_DETERMINATE),
        ("plan_execute_q1", "plan-execute", "q1", Q1_DETERMINATE),
        ("plan_execute_q2", "plan-execute", "q2", Q2_DETERMINATE),
    )
    for dimension_name, architecture, output_name, determinate in definitions:
        rich_output = rich_analysis.get(output_name, {})
        if output_name == "q1":
            rich_output = rich_output.get(architecture, {}) if isinstance(rich_output, dict) else {}
        click_architecture = architectures.get(architecture, {})
        click_output = click_architecture.get(output_name, {}) if isinstance(click_architecture, dict) else {}
        rich_label = str(rich_output.get("signal") or "analysis-incomplete / inconclusive")
        click_label = str(
            click_output.get("signal")
            or click_architecture.get("qualification")
            or "analysis-incomplete / inconclusive"
        )
        click_qualified = bool(click_output.get("qualified")) and click_architecture.get("qualification") == "qualified"
        dimension = _dimension(
            rich_label=rich_label,
            click_label=click_label,
            determinate=determinate,
            click_qualified=click_qualified,
            not_applicable=single_case,
        )
        if output_name == "q1":
            rich_secondary = rich_output.get("budget_priority_pattern")
            click_secondary = click_output.get("budget_priority_pattern")
            dimension.update(
                {
                    "rich_budget_priority_pattern": rich_secondary,
                    "click_budget_priority_pattern": click_secondary,
                    "secondary_result": (
                        "secondary-consistent" if rich_secondary == click_secondary else "secondary-divergence"
                    ),
                }
            )
        dimension_results[dimension_name] = dimension

    results = [value["result"] for value in dimension_results.values()]
    if any(result in {"inconclusive", "not_applicable"} for result in results):
        direction_comparison = "inconclusive"
    elif all(result == "consistent" for result in results):
        direction_comparison = "directionally consistent"
    elif all(result in {"consistent", "divergent"} for result in results) and "divergent" in results:
        direction_comparison = "repository-specific / divergent"
    else:
        raise RuntimeError("comparison result does not match the frozen aggregate precedence")

    rich_complete = (
        rich_legacy_audit.get("audit_completeness") == "complete"
        and rich_legacy_audit.get("historical_worker_attempt_completeness") == "complete"
    )
    click_complete = click_sensitivity.get("audit_completeness") == "complete"
    return {
        "schema_version": 1,
        "dimension_results": dimension_results,
        "direction_comparison": direction_comparison,
        "strict_audit_status": _strict_audit_status(rich_complete, click_complete),
        "supporting_audit": {
            "rich_audit_completeness": rich_legacy_audit.get("audit_completeness"),
            "rich_historical_worker_attempt_completeness": rich_legacy_audit.get(
                "historical_worker_attempt_completeness"
            ),
            "click_audit_completeness": click_sensitivity.get("audit_completeness"),
            "click_qualification": {
                architecture: value.get("qualification")
                for architecture, value in sorted(architectures.items())
                if isinstance(value, dict)
            },
        },
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path, name: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _markdown(comparison: dict[str, Any]) -> str:
    lines = [
        "# Rich–Click directional comparison",
        "",
        f"- Direction comparison: **{comparison['direction_comparison']}**",
        f"- Strict audit status: **{comparison['strict_audit_status']}**",
        "",
        "| Dimension | Rich label | Click label | Same label | Directional corroboration | Result |",
        "|---|---|---|---|---|---|",
    ]
    for name, value in sorted(comparison["dimension_results"].items()):
        lines.append(
            f"| {name} | {value['rich_label']} | {value['click_label']} | {value['same_label']} | "
            f"{value['directional_corroboration']} | {value['result']} |"
        )
    return "\n".join(lines) + "\n"


def write_cross_repo_comparison(
    output_dir: Path,
    *,
    rich_analysis_path: Path,
    click_analysis_path: Path,
    click_sensitivity_path: Path,
    rich_legacy_audit_path: Path,
    hash_manifest_path: Path,
) -> dict[str, Path]:
    input_paths = {
        "rich_analysis": Path(rich_analysis_path),
        "click_analysis": Path(click_analysis_path),
        "click_sensitivity": Path(click_sensitivity_path),
        "rich_legacy_audit": Path(rich_legacy_audit_path),
    }
    manifest = _read_json(Path(hash_manifest_path), "hash manifest")
    if manifest.get("schema_version") != 1 or set(manifest.get("artifacts", {})) != set(INPUT_NAMES):
        raise ValueError("hash manifest must contain only the four approved completed analysis inputs")
    for name, path in input_paths.items():
        if manifest["artifacts"].get(name, "").lower() != _sha256(path).lower():
            raise RuntimeError(f"comparison input hash mismatch: {name}")
    values = {name: _read_json(path, name) for name, path in input_paths.items()}
    comparison = build_comparison(
        values["rich_analysis"],
        values["click_analysis"],
        values["click_sensitivity"],
        values["rich_legacy_audit"],
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "comparison.json"
    markdown_path = output_dir / "comparison.md"
    audit_path = output_dir / "comparison-audit.json"
    json_path.write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    markdown_path.write_text(_markdown(comparison), encoding="utf-8", newline="\n")
    audit_path.write_text(
        json.dumps({"input_sha256": manifest["artifacts"]}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {"json": json_path, "markdown": markdown_path, "audit": audit_path}
