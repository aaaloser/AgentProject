from __future__ import annotations

import argparse
import json
import socket
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any, Iterable

from mokioclaw.evals.analysis_spec import load_analysis_spec
from mokioclaw.evals.attribution import derive_failure_detail


CELL_DIRS = {
    "A": "anchor-b40-t600",
    "B": "cell-b80-t600",
    "T": "cell-b40-t900",
    "J": "cell-b80-t900",
}
KNOWN_ARCHITECTURES = ("react", "multi-agent", "plan-execute")
NON_RESOURCE_DETAILS = frozenset(
    {
        "patch_generation_failure",
        "public_regression_failed",
        "hidden_contract_miss_after_validation",
        "protected_file_violation",
    }
)
MULTI_AGENT_DEEP = frozenset({"context_monitor", "context_compressor", "verifier", "final"})
KNOWN_STAGES = MULTI_AGENT_DEEP | {"planner", "verify", "execute", "react", ""}
DEFAULT_ANALYSIS_SPEC_PATH = Path(__file__).resolve().parents[3] / "evals" / "specs" / "resource-analysis-v1.json"
FORMULAS = {
    "success_delta": 2,
    "resource_drop": 2,
    "tool_call_threshold": 45,
    "tool_ge_threshold_runs": 2,
    "deep_delta": 2,
    "non_resource_delta": 2,
    "resource_still_binding_min": 3,
    "expected_pooled_n": 6,
}


def _safe_int(value: Any) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError, OverflowError):
        return 0


def _empty_counts() -> dict[str, int]:
    return {
        "n": 0,
        "ts": 0,
        "bud": 0,
        "tout": 0,
        "res": 0,
        "tool_ge_45": 0,
        "deep": 0,
        "nonres": 0,
        "provider_attrition": 0,
    }


def _copy_counts(value: dict[str, int] | None) -> dict[str, int]:
    counts = _empty_counts()
    if value:
        for key in counts:
            counts[key] = _safe_int(value.get(key))
    counts["res"] = counts["bud"] + counts["tout"]
    return counts


def _add_counts(target: dict[str, int], value: dict[str, int]) -> None:
    for key in ("n", "ts", "bud", "tout", "tool_ge_45", "deep", "nonres", "provider_attrition"):
        target[key] += _safe_int(value.get(key))
    target["res"] = target["bud"] + target["tout"]


def is_deep_progress(architecture: str, last_stage: str, attempts: int) -> bool:
    if architecture == "react":
        return False
    if attempts >= 2:
        return True
    if architecture == "plan-execute":
        return last_stage == "verify"
    if architecture == "multi-agent":
        return last_stage in MULTI_AGENT_DEEP
    return False


def _last_stage(result: dict[str, Any]) -> str:
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    stage = metadata.get("last_stage")
    if stage not in (None, ""):
        return str(stage)
    checkpoint = metadata.get("checkpoint") if isinstance(metadata.get("checkpoint"), dict) else {}
    return str(checkpoint.get("last_stage") or "")


def _attempts(result: dict[str, Any]) -> int:
    attempts = _safe_int(result.get("attempts"))
    if attempts:
        return attempts
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    checkpoint = metadata.get("checkpoint") if isinstance(metadata.get("checkpoint"), dict) else {}
    return _safe_int(checkpoint.get("attempts", checkpoint.get("attempt")))


def _is_success(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _count_result(result: dict[str, Any], architecture: str) -> dict[str, int]:
    counts = _empty_counts()
    counts["n"] = 1
    failure_kind = str(result.get("failure_kind") or "")
    if failure_kind.startswith("provider_"):
        counts["provider_attrition"] = 1
        return counts
    status = str(result.get("status") or "")
    counts["ts"] = int(_is_success(result.get("success")))
    counts["bud"] = int(status == "budget_exhausted")
    counts["tout"] = int(status == "timed_out")
    counts["tool_ge_45"] = int(_safe_int(result.get("tool_calls")) >= FORMULAS["tool_call_threshold"])
    counts["deep"] = int(is_deep_progress(architecture, _last_stage(result), _attempts(result)))
    if not counts["ts"] and derive_failure_detail(result) in NON_RESOURCE_DETAILS:
        counts["nonres"] = 1
    counts["res"] = counts["bud"] + counts["tout"]
    return counts


def classify_relaxed(anchor: dict[str, int], relaxed: dict[str, int]) -> dict[str, Any]:
    anchor_counts = _copy_counts(anchor)
    relaxed_counts = _copy_counts(relaxed)
    if (
        anchor_counts["n"] != FORMULAS["expected_pooled_n"]
        or relaxed_counts["n"] != FORMULAS["expected_pooled_n"]
    ):
        return {"state": "incomplete", "S": False, "E": False, "P": False, "relief": False, "failure_migration": False}
    success = relaxed_counts["ts"] >= anchor_counts["ts"] + FORMULAS["success_delta"]
    exhaustion = relaxed_counts["res"] <= anchor_counts["res"] - FORMULAS["resource_drop"]
    progress = (
        relaxed_counts["tool_ge_45"] >= FORMULAS["tool_ge_threshold_runs"]
        or relaxed_counts["deep"] >= anchor_counts["deep"] + FORMULAS["deep_delta"]
    )
    relief = exhaustion or progress
    migration = relaxed_counts["nonres"] >= anchor_counts["nonres"] + FORMULAS["non_resource_delta"]
    if success and relief:
        state = "resource-relief-success"
    elif not success and relief:
        state = "resource-relief-no-success"
    elif not success and not relief and relaxed_counts["res"] >= FORMULAS["resource_still_binding_min"]:
        state = "resource-still-binding"
    else:
        state = "no-resource-signal / inconclusive"
    return {
        "state": state,
        "S": success,
        "E": exhaustion,
        "P": progress,
        "relief": relief,
        "failure_migration": migration,
    }


def _cell(cells: dict[str, dict[str, int]], key: str) -> dict[str, int]:
    return _copy_counts(cells.get(key))


def map_q1(cells: dict[str, dict[str, int]]) -> dict[str, Any]:
    anchor = _cell(cells, "A")
    budget = _cell(cells, "B")
    timeout = _cell(cells, "T")
    joint = _cell(cells, "J")
    relief_b = classify_relaxed(anchor, budget)["relief"]
    relief_t = classify_relaxed(anchor, timeout)["relief"]
    relief_j = classify_relaxed(anchor, joint)["relief"]
    if relief_b and not relief_t:
        signal = "budget-axis directional signal"
    elif not relief_b and relief_t:
        signal = "timeout-axis directional signal"
    elif relief_b and relief_t:
        signal = "both axes independently influential"
    elif not relief_b and not relief_t and relief_j:
        signal = "joint constraint / interaction"
    else:
        signal = "no axis-order signal / inconclusive"
    return {
        "signal": signal,
        "budget_priority_pattern": relief_b and relief_t and budget["bud"] == 0 and timeout["bud"] >= 1,
    }


def map_q2(cells: dict[str, dict[str, int]]) -> dict[str, Any]:
    anchor = _cell(cells, "A")
    budget = _cell(cells, "B")
    joint = _cell(cells, "J")
    shift = (
        budget["bud"] == 0
        and budget["tout"] >= 2
        and budget["deep"] >= anchor["deep"] + FORMULAS["deep_delta"]
    )
    conversion = (
        shift
        and joint["ts"] >= budget["ts"] + FORMULAS["success_delta"]
        and joint["tout"] <= budget["tout"] - FORMULAS["resource_drop"]
    )
    still_binding = shift and not conversion and joint["tout"] >= 2
    signal = (
        "dual-axis conversion"
        if conversion
        else "time still binding"
        if still_binding
        else "no time-wall migration signal / inconclusive"
    )
    return {
        "signal": signal,
        "time_wall_shift": shift,
        "dual_axis_conversion": conversion,
        "time_still_binding": still_binding,
    }


def _completion_options(cell: str) -> list[dict[str, int]]:
    terminals = (
        {"ts": 1, "bud": 0, "tout": 0, "nonres": 0},
        {"ts": 0, "bud": 1, "tout": 0, "nonres": 0},
        {"ts": 0, "bud": 0, "tout": 1, "nonres": 0},
        {"ts": 0, "bud": 0, "tout": 0, "nonres": 1},
        {"ts": 0, "bud": 0, "tout": 0, "nonres": 0},
    )
    tool_values = (0, 1) if cell in {"B", "J"} else (0,)
    return [{**terminal, "deep": deep, "tool_ge_45": tool} for terminal in terminals for deep in (0, 1) for tool in tool_values]


def _completed_cell_candidates(cell: str, observed: dict[str, int]) -> list[dict[str, int]]:
    base = _copy_counts(observed)
    attrition = base["provider_attrition"]
    if attrition == 0:
        return [base]
    candidates: dict[tuple[int, ...], dict[str, int]] = {}
    for assignments in product(_completion_options(cell), repeat=attrition):
        current = dict(base)
        for assignment in assignments:
            for key, value in assignment.items():
                current[key] += value
        current["res"] = current["bud"] + current["tout"]
        identity = tuple(current[key] for key in sorted(current))
        candidates[identity] = current
    return [candidates[key] for key in sorted(candidates)]


def analyze_provider_sensitivity(
    architecture: str,
    cells: dict[str, dict[str, int]],
    *,
    evidence_complete: bool,
    scheduled_n: int = 6,
    formal_labels: bool = True,
) -> dict[str, Any]:
    normalized = {label: _copy_counts(cells.get(label)) for label in CELL_DIRS}
    clean_by_cell = {
        label: value["n"] - value["provider_attrition"] for label, value in normalized.items()
    }
    attrition_values = [normalized[label]["provider_attrition"] for label in CELL_DIRS]
    attrition_range = max(attrition_values) - min(attrition_values)
    base: dict[str, Any] = {
        "architecture": architecture,
        "scheduled_n": scheduled_n,
        "clean_by_cell": clean_by_cell,
        "provider_attrition_by_cell": {label: normalized[label]["provider_attrition"] for label in CELL_DIRS},
        "attrition_range": attrition_range,
    }
    if not formal_labels or scheduled_n == 3:
        return {
            **base,
            "qualification": "single-case evidence / repository-level corroboration inconclusive",
            "raw_counts": normalized,
            "raw_deltas": {label: _delta(normalized["A"], normalized[label]) for label in ("B", "T", "J")},
        }

    failures: list[str] = []
    if any(value["n"] != scheduled_n for value in normalized.values()):
        failures.append("scheduled_n")
    if any(clean < 5 for clean in clean_by_cell.values()):
        failures.append("minimum_clean_per_cell")
    if attrition_range > 1:
        failures.append("max_attrition_range")
    if sum(attrition_values) and not evidence_complete:
        failures.append("provider_evidence_incomplete")
    if failures:
        result = {
            **base,
            "qualification": "provider-attrition / inconclusive",
            "qualification_failures": failures,
            "states": {
                label: {"qualified": False, "state": "provider-attrition / inconclusive", "candidates": []}
                for label in ("B", "T", "J")
            },
            "q1": {"qualified": False, "signal": "provider-attrition / inconclusive", "candidates": []},
        }
        if architecture == "plan-execute":
            result["q2"] = {"qualified": False, "signal": "provider-attrition / inconclusive", "candidates": []}
        return result

    cell_candidates = {label: _completed_cell_candidates(label, normalized[label]) for label in CELL_DIRS}
    state_candidates = {label: set() for label in ("B", "T", "J")}
    q1_candidates: set[tuple[str, bool]] = set()
    q2_candidates: set[tuple[str, bool, bool, bool]] = set()
    completion_count = 0
    for anchor, budget, timeout, joint in product(
        cell_candidates["A"], cell_candidates["B"], cell_candidates["T"], cell_candidates["J"]
    ):
        completion_count += 1
        completed = {"A": anchor, "B": budget, "T": timeout, "J": joint}
        for label in ("B", "T", "J"):
            state_candidates[label].add(classify_relaxed(anchor, completed[label])["state"])
        q1 = map_q1(completed)
        q1_candidates.add((q1["signal"], q1["budget_priority_pattern"]))
        if architecture == "plan-execute":
            q2 = map_q2(completed)
            q2_candidates.add(
                (
                    q2["signal"],
                    q2["time_wall_shift"],
                    q2["dual_axis_conversion"],
                    q2["time_still_binding"],
                )
            )

    states: dict[str, Any] = {}
    any_sensitive = False
    for label, candidates in state_candidates.items():
        ordered = sorted(candidates)
        qualified = len(ordered) == 1
        any_sensitive |= not qualified
        states[label] = {
            "qualified": qualified,
            "state": ordered[0] if qualified else "provider-sensitive / inconclusive",
            "candidates": ordered,
        }
    ordered_q1 = [
        {"signal": signal, "budget_priority_pattern": pattern}
        for signal, pattern in sorted(q1_candidates)
    ]
    q1_qualified = len(ordered_q1) == 1
    any_sensitive |= not q1_qualified
    result = {
        **base,
        "qualification": "provider-sensitive / inconclusive" if any_sensitive else "qualified",
        "qualification_failures": [],
        "completion_count": completion_count,
        "states": states,
        "q1": {
            "qualified": q1_qualified,
            "signal": ordered_q1[0]["signal"] if q1_qualified else "provider-sensitive / inconclusive",
            "budget_priority_pattern": ordered_q1[0]["budget_priority_pattern"] if q1_qualified else None,
            "candidates": ordered_q1,
        },
    }
    if architecture == "plan-execute":
        ordered_q2 = [
            {
                "signal": signal,
                "time_wall_shift": shift,
                "dual_axis_conversion": conversion,
                "time_still_binding": binding,
            }
            for signal, shift, conversion, binding in sorted(q2_candidates)
        ]
        q2_qualified = len(ordered_q2) == 1
        if not q2_qualified:
            result["qualification"] = "provider-sensitive / inconclusive"
        result["q2"] = {
            "qualified": q2_qualified,
            "signal": ordered_q2[0]["signal"] if q2_qualified else "provider-sensitive / inconclusive",
            "time_wall_shift": ordered_q2[0]["time_wall_shift"] if q2_qualified else None,
            "dual_axis_conversion": ordered_q2[0]["dual_axis_conversion"] if q2_qualified else None,
            "time_still_binding": ordered_q2[0]["time_still_binding"] if q2_qualified else None,
            "candidates": ordered_q2,
        }
    return result


def _resolve_report_path(cell_root: Path, report_dir: Any) -> Path | None:
    if not isinstance(report_dir, str) or not report_dir:
        return None
    candidate = (cell_root / report_dir).resolve()
    try:
        candidate.relative_to(cell_root.resolve())
    except ValueError:
        return None
    return candidate / "results.json"


def _append_warning(warnings: list[str], message: str) -> None:
    if message not in warnings:
        warnings.append(message)


def _load_cell(root: Path, label: str, warnings: list[str]) -> dict[str, Any]:
    cell_name = CELL_DIRS[label]
    cell_root = root / cell_name
    if not cell_root.is_dir():
        _append_warning(warnings, f"missing cell directory: {cell_name}")
        return {"architectures": {}, "cases": {}, "records": []}
    experiment_path = cell_root / "experiment.json"
    if not experiment_path.exists():
        _append_warning(warnings, f"missing experiment.json: {cell_name}")
    else:
        try:
            json.loads(experiment_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _append_warning(warnings, f"invalid experiment.json in {cell_name}: {type(exc).__name__}")
    manifest_path = cell_root / "manifest.jsonl"
    if not manifest_path.exists():
        _append_warning(warnings, f"missing manifest.jsonl: {cell_name}")
        return {"architectures": {}, "cases": {}, "records": []}
    try:
        lines = manifest_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        _append_warning(warnings, f"unreadable manifest in {cell_name}: {type(exc).__name__}")
        return {"architectures": {}, "cases": {}, "records": []}

    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            _append_warning(warnings, f"invalid manifest row: {cell_name}:{line_number}")
            continue
        if not isinstance(row, dict):
            _append_warning(warnings, f"non-object manifest row: {cell_name}:{line_number}")
            continue
        architecture = str(row.get("architecture") or "")
        if architecture not in KNOWN_ARCHITECTURES:
            _append_warning(warnings, f"unknown architecture skipped: {cell_name}:{architecture or '<empty>'}")
            continue
        result_path = _resolve_report_path(cell_root, row.get("report_dir"))
        if result_path is None:
            _append_warning(warnings, f"invalid report_dir: {cell_name}:{line_number}")
            continue
        if not result_path.exists():
            _append_warning(warnings, f"missing results.json: {cell_name}:{row.get('report_dir')}")
            continue
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _append_warning(warnings, f"invalid results.json: {cell_name}:{row.get('report_dir')}:{type(exc).__name__}")
            continue
        if isinstance(payload, list):
            result = payload[0] if payload and isinstance(payload[0], dict) else None
        elif isinstance(payload, dict):
            result = payload
        else:
            result = None
        if result is None:
            _append_warning(warnings, f"empty results.json: {cell_name}:{row.get('report_dir')}")
            continue
        stage = _last_stage(result)
        if stage not in KNOWN_STAGES:
            _append_warning(warnings, f"unknown stage observed: {cell_name}/{architecture}/{row.get('case_id')}:{stage}")
        records.append(
            {
                "cell": label,
                "cell_name": cell_name,
                "architecture": architecture,
                "case_id": str(row.get("case_id") or result.get("case_id") or "<unknown>"),
                "repeat": _safe_int(row.get("repeat")),
                "result": result,
                "report_dir": str(row.get("report_dir") or ""),
            }
        )

    architectures: dict[str, dict[str, int]] = {}
    cases: dict[str, dict[str, dict[str, int]]] = {}
    for record in records:
        architecture = record["architecture"]
        case_id = record["case_id"]
        value = _count_result(record["result"], architecture)
        _add_counts(architectures.setdefault(architecture, _empty_counts()), value)
        _add_counts(cases.setdefault(case_id, {}).setdefault(architecture, _empty_counts()), value)
    return {"architectures": architectures, "cases": cases, "records": records}


def _delta(anchor: dict[str, int], current: dict[str, int]) -> dict[str, int]:
    return {
        "ts_delta": current["ts"] - anchor["ts"],
        "res_delta": current["res"] - anchor["res"],
        "bud_delta": current["bud"] - anchor["bud"],
        "tout_delta": current["tout"] - anchor["tout"],
        "tool_ge_45_delta": current["tool_ge_45"] - anchor["tool_ge_45"],
        "deep_delta": current["deep"] - anchor["deep"],
        "nonres_delta": current["nonres"] - anchor["nonres"],
    }


def _sign(value: int) -> int:
    return (value > 0) - (value < 0)


def _relief_without_n(anchor: dict[str, int], current: dict[str, int]) -> bool:
    return (
        current["res"] <= anchor["res"] - FORMULAS["resource_drop"]
        or current["tool_ge_45"] >= FORMULAS["tool_ge_threshold_runs"]
        or current["deep"] >= anchor["deep"] + FORMULAS["deep_delta"]
    )


def _threshold_payload(anchor: dict[str, dict[str, int]], analysis_spec_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "analysis_spec_sha256": analysis_spec_sha256,
        "source_cell": CELL_DIRS["A"],
        "formulas": dict(FORMULAS),
        "anchor": {architecture: _copy_counts(anchor.get(architecture)) for architecture in KNOWN_ARCHITECTURES},
    }


def _ensure_thresholds(path: Path, anchor: dict[str, dict[str, int]], analysis_spec_sha256: str) -> None:
    payload = _threshold_payload(anchor, analysis_spec_sha256)
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"invalid thresholds file: {type(exc).__name__}") from exc
        for key in ("schema_version", "analysis_spec_sha256", "source_cell", "formulas"):
            if existing.get(key) != payload[key]:
                raise RuntimeError("existing snapshot thresholds mismatch; use a new batch root")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_stable_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _build_per_case(cell_data: dict[str, dict[str, Any]], warnings: list[str]) -> dict[str, Any]:
    case_ids: set[str] = set()
    for data in cell_data.values():
        case_ids.update(data["cases"])
    cases: dict[str, Any] = {}
    mixed_direction: dict[str, dict[str, bool]] = {architecture: {} for architecture in KNOWN_ARCHITECTURES if architecture != "react"}
    for case_id in sorted(case_ids):
        cases[case_id] = {}
        for architecture in KNOWN_ARCHITECTURES:
            entries: dict[str, Any] = {}
            anchor = _copy_counts(cell_data["A"]["cases"].get(case_id, {}).get(architecture))
            for label in CELL_DIRS:
                value = _copy_counts(cell_data[label]["cases"].get(case_id, {}).get(architecture))
                entries[label] = {"counts": value, "deltas": _delta(anchor, value)}
            cases[case_id][architecture] = entries
    for architecture in mixed_direction:
        for label in ("B", "T", "J"):
            deltas = [cases[case_id][architecture][label]["deltas"] for case_id in cases]
            mixed_direction[architecture][label] = len(deltas) >= 2 and (
                len({_sign(delta["ts_delta"]) for delta in deltas}) > 1
                or len({_sign(delta["res_delta"]) for delta in deltas}) > 1
            )
    return {"schema_version": 1, "cells": cases, "mixed_direction": mixed_direction, "warnings": list(warnings)}


def _build_pooled(cell_data: dict[str, dict[str, Any]], warnings: list[str]) -> dict[str, Any]:
    cells: dict[str, dict[str, dict[str, int]]] = {}
    for architecture in KNOWN_ARCHITECTURES:
        cells[architecture] = {
            label: _copy_counts(cell_data[label]["architectures"].get(architecture)) for label in CELL_DIRS
        }
    per_case = _build_per_case(cell_data, warnings)
    single_case = len(per_case["cells"]) == 1
    expected_n = 3 if single_case else FORMULAS["expected_pooled_n"]
    incomplete: list[str] = []
    for architecture in KNOWN_ARCHITECTURES:
        for label in CELL_DIRS:
            if cells[architecture][label]["n"] != expected_n:
                incomplete.append(f"{architecture}/{label}")
    if single_case:
        return {
            "schema_version": 1,
            "branch": "single_case",
            "status": "complete" if not incomplete else "incomplete",
            "incomplete": incomplete,
            "comparison_qualification": "single-case evidence / repository-level corroboration inconclusive",
            "cells": cells,
            "raw_deltas": {
                architecture: {
                    label: _delta(cells[architecture]["A"], cells[architecture][label])
                    for label in ("B", "T", "J")
                }
                for architecture in KNOWN_ARCHITECTURES
            },
            "mixed_direction": per_case["mixed_direction"],
            "warnings": list(warnings),
        }
    if incomplete:
        return {
            "schema_version": 1,
            "branch": "two_case",
            "status": "incomplete",
            "incomplete": incomplete,
            "cells": cells,
            "warnings": list(warnings),
        }
    states: dict[str, dict[str, Any]] = {}
    q1: dict[str, Any] = {}
    for architecture in ("multi-agent", "plan-execute"):
        states[architecture] = {
            label: classify_relaxed(cells[architecture]["A"], cells[architecture][label]) for label in ("B", "T", "J")
        }
        q1[architecture] = map_q1(cells[architecture])
    q2 = map_q2(cells["plan-execute"])
    divergence: dict[str, dict[str, Any]] = {}
    for architecture in ("multi-agent", "plan-execute"):
        divergence[architecture] = {}
        for label in ("B", "T", "J"):
            case_relief: dict[str, bool] = {}
            for case_id, case_data in per_case["cells"].items():
                anchor = case_data[architecture]["A"]["counts"]
                current = case_data[architecture][label]["counts"]
                case_relief[case_id] = _relief_without_n(anchor, current)
            divergence[architecture][label] = {
                "case_relief": case_relief,
                "divergent": len(set(case_relief.values())) > 1,
            }
    return {
        "schema_version": 1,
        "branch": "two_case",
        "status": "complete" if not incomplete else "incomplete",
        "incomplete": incomplete,
        "cells": cells,
        "states": states,
        "q1": q1,
        "q2": q2,
        "divergence": divergence,
        "mixed_direction": per_case["mixed_direction"],
        "warnings": list(warnings),
    }


def _write_report(pooled: dict[str, Any], per_case: dict[str, Any], records: Iterable[dict[str, Any]]) -> str:
    lines = [
        "# Mokioclaw snapshot analysis",
        "",
        f"- Status: **{pooled['status']}**",
        "",
        "## Run ledger",
        "",
        "| Cell | Case | Architecture | Repeat | Report |\n|---|---|---|---:|---|",
    ]
    for record in sorted(records, key=lambda item: (item["cell"], item["architecture"], item["case_id"], item["repeat"])):
        lines.append(
            f"| {record['cell_name']} | {record['case_id']} | {record['architecture']} | {record['repeat']} | `{record['report_dir']}` |"
        )
    if pooled.get("branch") == "single_case":
        lines.extend(
            [
                "",
                "## Descriptive resource migration",
                "",
                f"- Qualification: {pooled['comparison_qualification']}",
            ]
        )
    elif pooled.get("status") == "incomplete":
        lines.extend(["", "## Analysis status", "", "- Incomplete batch; formal effect labels were withheld."])
    else:
        lines.extend(["", "## Pooled states", "", "| Architecture | Cell | State | Relief | Failure migration |", "|---|---|---|---|---|"])
        for architecture, state_map in pooled["states"].items():
            for label, state in state_map.items():
                lines.append(f"| {architecture} | {label} | {state['state']} | {state['relief']} | {state['failure_migration']} |")
        lines.extend(["", "## Q1", ""])
        for architecture, mapping in pooled["q1"].items():
            lines.append(f"- `{architecture}`: {mapping['signal']} (budget-priority pattern: {mapping['budget_priority_pattern']})")
        lines.extend(["", "## Q2", "", f"- plan-execute: {pooled['q2']['signal']}"])
    lines.extend(["", "## Warnings", ""])
    if pooled["warnings"]:
        lines.extend(f"- {warning}" for warning in pooled["warnings"])
    else:
        lines.append("- (none)")
    lines.extend(["", "## Per-case mixed direction", ""])
    for architecture, values in per_case["mixed_direction"].items():
        for label, value in values.items():
            lines.append(f"- `{architecture}/{label}`: mixed_direction={value}")
    return "\n".join(lines) + "\n"


def _write_stable_text(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8", newline="\n")


def _provider_evidence_complete(records: Iterable[dict[str, Any]]) -> bool:
    for record in records:
        result = record["result"]
        failure_kind = str(result.get("failure_kind") or "")
        if not failure_kind.startswith("provider_"):
            continue
        artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), dict) else {}
        if not result.get("provider_phase"):
            return False
        if not result.get("telemetry_coverage"):
            return False
        if not artifacts.get("call_journal") or not artifacts.get("transport_ledger"):
            return False
    return True


def _build_provider_sensitivity(cell_data: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"schema_version": 1, "architectures": {}}
    all_records = [record for data in cell_data.values() for record in data["records"]]
    case_ids = sorted({record["case_id"] for record in all_records})
    scheduled_n = 3 if len(case_ids) == 1 else 6
    formal_labels = len(case_ids) != 1
    for architecture in ("multi-agent", "plan-execute"):
        cells = {
            label: _copy_counts(cell_data[label]["architectures"].get(architecture)) for label in CELL_DIRS
        }
        architecture_records = [record for record in all_records if record["architecture"] == architecture]
        result["architectures"][architecture] = analyze_provider_sensitivity(
            architecture,
            cells,
            evidence_complete=_provider_evidence_complete(architecture_records),
            scheduled_n=scheduled_n,
            formal_labels=formal_labels,
        )
    return result


def _build_react_canary(cell_data: dict[str, dict[str, Any]]) -> dict[str, Any]:
    vectors: dict[str, dict[str, list[int]]] = {}
    for label in CELL_DIRS:
        for record in cell_data[label]["records"]:
            if record["architecture"] != "react":
                continue
            case_id = record["case_id"]
            vector = vectors.setdefault(case_id, {}).setdefault(label, [0, 0, 0, 0, 0, 0])
            result = record["result"]
            failure_kind = str(result.get("failure_kind") or "")
            if failure_kind.startswith("provider_"):
                vector[5] += 1
                continue
            status = str(result.get("status") or "")
            index = {
                "passed": 0,
                "budget_exhausted": 1,
                "timed_out": 2,
                "failed": 3,
                "setup_failed": 4,
            }.get(status, 3)
            vector[index] += 1
    cases: dict[str, Any] = {}
    for case_id in sorted(vectors):
        anchor = vectors[case_id].get("A", [0, 0, 0, 0, 0, 0])
        cases[case_id] = {
            "vectors": {label: vectors[case_id].get(label, [0, 0, 0, 0, 0, 0]) for label in CELL_DIRS},
            "deltas": {
                label: [current - base for current, base in zip(vectors[case_id].get(label, [0] * 6), anchor)]
                for label in ("B", "T", "J")
            },
        }
    return {
        "schema_version": 1,
        "vector_order": ["passed", "budget_exhausted", "timed_out", "failed", "setup_failed", "provider_attrition"],
        "cases": cases,
    }


def write_snapshot_analysis(
    root: Path,
    thresholds_only: bool = False,
    *,
    analysis_spec_path: Path = DEFAULT_ANALYSIS_SPEC_PATH,
) -> dict[str, Path]:
    analysis_spec = load_analysis_spec(Path(analysis_spec_path))
    root = root.resolve()
    analysis_dir = root / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "thresholds": analysis_dir / "thresholds.json",
        "per_case": analysis_dir / "per-case.json",
        "pooled": analysis_dir / "pooled.json",
        "provider_sensitivity": analysis_dir / "provider-sensitivity.json",
        "react_canary": analysis_dir / "react-canary.json",
        "report": analysis_dir / "report.md",
        "audit": analysis_dir / "analysis-audit.json",
    }
    warnings: list[str] = []
    labels = ("A",) if thresholds_only else tuple(CELL_DIRS)
    cell_data: dict[str, dict[str, Any]] = {
        label: _load_cell(root, label, warnings) for label in labels
    }
    if thresholds_only:
        _ensure_thresholds(paths["thresholds"], cell_data["A"]["architectures"], analysis_spec.sha256)
        return paths
    for label in CELL_DIRS:
        cell_data.setdefault(label, {"architectures": {}, "cases": {}, "records": []})
    _ensure_thresholds(paths["thresholds"], cell_data["A"]["architectures"], analysis_spec.sha256)
    per_case = _build_per_case(cell_data, warnings)
    pooled = _build_pooled(cell_data, warnings)
    records = [record for data in cell_data.values() for record in data["records"]]
    provider_sensitivity = _build_provider_sensitivity(cell_data)
    react_canary = _build_react_canary(cell_data)
    for payload in (per_case, pooled, provider_sensitivity, react_canary):
        payload["analysis_spec_sha256"] = analysis_spec.sha256
    _write_stable_text(paths["per_case"], json.dumps(per_case, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _write_stable_text(paths["pooled"], json.dumps(pooled, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _write_stable_text(
        paths["provider_sensitivity"],
        json.dumps(provider_sensitivity, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    _write_stable_text(paths["react_canary"], json.dumps(react_canary, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _write_stable_text(paths["report"], _write_report(pooled, per_case, records))
    paths["audit"].write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "hostname": socket.gethostname(),
                "root": str(root),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze a preregistered Mokioclaw snapshot matrix")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--thresholds-only", action="store_true")
    args = parser.parse_args()
    paths = write_snapshot_analysis(args.root, thresholds_only=args.thresholds_only)
    if not args.thresholds_only:
        pooled = json.loads(paths["pooled"].read_text(encoding="utf-8"))
        if pooled.get("status") == "incomplete":
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
