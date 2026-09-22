from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mokioclaw.evals.rich_legacy_audit import FROZEN_ANALYSIS_FILES, generate_rich_legacy_audit


CELLS = ("anchor-b40-t600", "cell-b80-t600", "cell-b40-t900", "cell-b80-t900")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def build_legacy_fixture(root: Path) -> dict[str, str]:
    analysis = root / "analysis"
    analysis.mkdir(parents=True)
    for name in FROZEN_ANALYSIS_FILES:
        (analysis / name).write_text(json.dumps({"frozen": name}), encoding="utf-8")
    (root / "execution-schedule.json").write_text(json.dumps({"seed": 20260920}), encoding="utf-8")
    failure_tools = [0] * 19 + [13, 18, 38]
    row_index = 0
    for cell in CELLS:
        cell_root = root / cell
        cell_root.mkdir()
        rows = []
        for local_index in range(18):
            report_dir = f"runs/react/case-{row_index}-r1"
            report_root = cell_root / report_dir
            report_root.mkdir(parents=True)
            is_provider_failure = row_index < 22
            result = {
                "run_id": f"run-{row_index}",
                "case_id": f"case-{row_index % 2}",
                "status": "setup_failed" if is_provider_failure else "passed",
                "success": not is_provider_failure,
                "failure_stage": "worker" if is_provider_failure else "",
                "failure_reason": "504 Gateway Time-out" if is_provider_failure else "",
                "tool_calls": failure_tools[row_index] if is_provider_failure else 2,
                "input_tokens": None if is_provider_failure else 10,
                "output_tokens": None if is_provider_failure else 5,
                "artifacts": {},
            }
            (report_root / "results.json").write_text(json.dumps([result]), encoding="utf-8")
            rows.append(
                {
                    "architecture": "react",
                    "case_id": result["case_id"],
                    "repeat": 1,
                    "report_dir": report_dir,
                    "run_id": result["run_id"],
                    "status": result["status"],
                    "success": result["success"],
                }
            )
            row_index += 1
        (cell_root / "manifest.jsonl").write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
        )
    return {name: sha256(analysis / name) for name in FROZEN_ANALYSIS_FILES}


def test_legacy_audit_recomputes_72_rows_and_22_of_22_worker_504_without_mutating_frozen_files(
    tmp_path: Path,
) -> None:
    expected_hashes = build_legacy_fixture(tmp_path)
    before = {name: (tmp_path / "analysis" / name).read_bytes() for name in FROZEN_ANALYSIS_FILES}

    path = generate_rich_legacy_audit(tmp_path, expected_analysis_hashes=expected_hashes)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["final_manifest_rows"] == 72
    assert payload["setup_failed_rows"] == 22
    assert payload["provider_504_evidence"]["matched"] == 22
    assert payload["provider_504_evidence"]["expected"] == 22
    assert payload["provider_504_evidence"]["coverage"] == "22/22"
    assert payload["provider_504_evidence"]["worker_stage"] == 22
    assert payload["provider_504_evidence"]["tool_call_distribution"] == {"0": 19, "13": 1, "18": 1, "38": 1}
    assert payload["token_telemetry"]["full"] == 50
    assert payload["token_telemetry"]["unavailable"] == 22
    assert payload["token_telemetry"]["unavailable_reasons"] == {"legacy_token_usage_missing": 22}
    assert payload["historical_worker_attempt_completeness"] == "limited"
    assert payload["audit_completeness"] == "limited"
    assert {name: (tmp_path / "analysis" / name).read_bytes() for name in FROZEN_ANALYSIS_FILES} == before


def test_legacy_audit_contains_relative_hash_evidence_only(tmp_path: Path) -> None:
    expected_hashes = build_legacy_fixture(tmp_path)

    path = generate_rich_legacy_audit(tmp_path, expected_analysis_hashes=expected_hashes)
    payload = json.loads(path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, sort_keys=True)

    assert str(tmp_path) not in serialized
    assert all(not item["path"].startswith(("/", "\\")) and ":" not in item["path"] for item in payload["manifests"])
    assert all(len(item["sha256"]) == 64 for item in payload["provider_504_evidence"]["results"])
    for forbidden in ("api_key", "authorization", "endpoint", "prompt", "response", "headers", "payload"):
        assert forbidden not in serialized.lower()


def test_legacy_audit_refuses_wrong_frozen_hash_or_incomplete_final_ledger(tmp_path: Path) -> None:
    expected_hashes = build_legacy_fixture(tmp_path)
    wrong = dict(expected_hashes)
    wrong["thresholds.json"] = "0" * 64

    with pytest.raises(RuntimeError, match="frozen analysis hash mismatch"):
        generate_rich_legacy_audit(tmp_path, expected_analysis_hashes=wrong)

    manifest = tmp_path / CELLS[0] / "manifest.jsonl"
    manifest.write_text("\n".join(manifest.read_text(encoding="utf-8").splitlines()[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="72 final manifest rows"):
        generate_rich_legacy_audit(tmp_path, expected_analysis_hashes=expected_hashes)
