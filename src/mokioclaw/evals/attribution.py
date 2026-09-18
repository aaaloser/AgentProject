from __future__ import annotations

from typing import Any


def derive_failure_detail(result: dict[str, Any]) -> str:
    """Label observable facts only — no causal claims (spec §11.2)."""
    status = str(result.get("status", ""))
    if status == "budget_exhausted":
        return "budget_exhausted"
    if status == "timed_out":
        return "execution_timeout"
    checks_raw = result.get("grader_checks")
    checks = {check.get("name"): check for check in (checks_raw or []) if isinstance(check, dict)}
    if checks.get("integrity") is not None and not checks["integrity"].get("passed"):
        return "protected_file_violation"
    if checks.get("patch_apply") is not None and not checks["patch_apply"].get("passed"):
        return "patch_generation_failure"
    if checks.get("public_regression") is not None and not checks["public_regression"].get("passed"):
        return "public_regression_failed"
    if checks.get("hidden_tests") is not None and not checks["hidden_tests"].get("passed"):
        try:
            ran = int((result.get("metadata") or {}).get("verification_command_runs", 0) or 0)
        except (TypeError, ValueError):
            ran = 0
        return "public_validation_missing" if ran == 0 else "hidden_contract_miss_after_validation"
    if status == "setup_failed":
        return "infrastructure_failure" if str(result.get("failure_stage", "")) in ("sandbox", "setup") else "runtime_failure"
    return ""
