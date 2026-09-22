from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from mokioclaw.providers.call_journal import atomic_json_replace


FROZEN_ANALYSIS_FILES = ("thresholds.json", "per-case.json", "pooled.json")
RICH_FROZEN_HASHES = {
    "thresholds.json": "B99BA64320362DED877777CA4BE9130BC08A8619A1BCB5CC3910D4E0721CABEB",
    "per-case.json": "167FC8EC4B48B03A3FD2F8248E0F653B085DF92498A78CFC4BF23571C98EA4FB",
    "pooled.json": "6F84A1281593994E7F9FF37F250F00DF366EB7BFEE14C0EC6ED8C638D1D069F2",
}
RICH_CELLS = ("anchor-b40-t600", "cell-b80-t600", "cell-b40-t900", "cell-b80-t900")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _hash_entry(root: Path, path: Path) -> dict[str, str]:
    return {"path": path.relative_to(root).as_posix(), "sha256": _sha256(path)}


def _frozen_hashes(root: Path) -> dict[str, str]:
    return {name: _sha256(root / "analysis" / name) for name in FROZEN_ANALYSIS_FILES}


def _verify_frozen(actual: dict[str, str], expected: dict[str, str]) -> None:
    normalized = {name: value.upper() for name, value in expected.items()}
    if actual != normalized:
        raise RuntimeError("frozen analysis hash mismatch; refusing Rich legacy audit")


def _safe_result_path(cell_root: Path, report_dir: Any) -> Path:
    if not isinstance(report_dir, str) or not report_dir:
        raise RuntimeError("legacy manifest has an invalid report_dir")
    candidate = (cell_root / report_dir / "results.json").resolve()
    try:
        candidate.relative_to(cell_root.resolve())
    except ValueError as exc:
        raise RuntimeError("legacy manifest report_dir escapes its cell") from exc
    if not candidate.is_file():
        raise RuntimeError("legacy manifest result is missing")
    return candidate


def _load_result(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, dict):
        raise RuntimeError("legacy results.json is not a result object")
    return value


def generate_rich_legacy_audit(
    root: Path,
    *,
    expected_analysis_hashes: dict[str, str] | None = None,
) -> Path:
    root = Path(root).resolve()
    expected = expected_analysis_hashes or RICH_FROZEN_HASHES
    before = _frozen_hashes(root)
    _verify_frozen(before, expected)

    manifests: list[dict[str, str]] = []
    final_results: list[dict[str, str]] = []
    rows: list[tuple[dict[str, Any], dict[str, Any], Path]] = []
    for cell in RICH_CELLS:
        cell_root = root / cell
        manifest_path = cell_root / "manifest.jsonl"
        if not manifest_path.is_file():
            raise RuntimeError(f"missing Rich final manifest: {cell}")
        manifests.append(_hash_entry(root, manifest_path))
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise RuntimeError("legacy manifest row is not an object")
            result_path = _safe_result_path(cell_root, row.get("report_dir"))
            result = _load_result(result_path)
            rows.append((row, result, result_path))
            final_results.append(_hash_entry(root, result_path))
    if len(rows) != 72:
        raise RuntimeError(f"expected 72 final manifest rows, found {len(rows)}")

    setup_failed = [(row, result, path) for row, result, path in rows if str(row.get("status")) == "setup_failed"]
    if len(setup_failed) != 22:
        raise RuntimeError(f"expected 22 setup_failed rows, found {len(setup_failed)}")
    matched_504 = [
        (row, result, path)
        for row, result, path in setup_failed
        if result.get("failure_stage") == "worker" and "504 Gateway Time-out" in str(result.get("failure_reason") or "")
    ]
    if len(matched_504) != 22:
        raise RuntimeError(f"expected 22/22 worker-stage provider 504 results, found {len(matched_504)}/22")

    tool_distribution = Counter(str(int(result.get("tool_calls") or 0)) for _, result, _ in matched_504)
    token_coverage = Counter()
    unavailable_reasons = Counter()
    for _, result, _ in rows:
        if isinstance(result.get("input_tokens"), int) and isinstance(result.get("output_tokens"), int):
            token_coverage["full"] += 1
        else:
            token_coverage["unavailable"] += 1
            unavailable_reasons["legacy_token_usage_missing"] += 1

    sidecar = {
        "schema_version": 1,
        "audit_completeness": "limited",
        "historical_worker_attempt_completeness": "limited",
        "frozen_analysis": [
            {"path": f"analysis/{name}", "sha256": before[name]} for name in FROZEN_ANALYSIS_FILES
        ],
        "schedule": _hash_entry(root, root / "execution-schedule.json"),
        "manifests": sorted(manifests, key=lambda item: item["path"]),
        "final_results": sorted(final_results, key=lambda item: item["path"]),
        "final_manifest_rows": len(rows),
        "setup_failed_rows": len(setup_failed),
        "provider_attrition": {
            "count": len(matched_504),
            "mechanical_status": {"504": len(matched_504)},
            "mechanical_phase": {"worker": len(matched_504)},
        },
        "provider_504_evidence": {
            "expected": 22,
            "matched": len(matched_504),
            "coverage": f"{len(matched_504)}/22",
            "worker_stage": sum(result.get("failure_stage") == "worker" for _, result, _ in matched_504),
            "tool_call_distribution": dict(sorted(tool_distribution.items(), key=lambda item: int(item[0]))),
            "results": sorted((_hash_entry(root, path) for _, _, path in matched_504), key=lambda item: item["path"]),
        },
        "token_telemetry": {
            "full": token_coverage["full"],
            "partial": 0,
            "unavailable": token_coverage["unavailable"],
            "unavailable_reasons": dict(sorted(unavailable_reasons.items())),
        },
        "unrecoverable_fields": [
            {
                "field": "complete_historical_worker_attempt_ledger",
                "reason": "three historical slots were replaced and their detailed attempt directories are unavailable",
            },
            {
                "field": "structured_provider_kind_phase_transport_ledger",
                "reason": "legacy schema predates structured provider and transport evidence",
            },
        ],
        "directional_analysis_unchanged": True,
    }
    output = root / "analysis" / "rich-legacy-audit.json"
    atomic_json_replace(output, sidecar)
    after = _frozen_hashes(root)
    if after != before:
        raise RuntimeError("frozen Rich analysis changed during sidecar generation")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the read-only Rich legacy audit sidecar")
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    print(generate_rich_legacy_audit(args.root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
