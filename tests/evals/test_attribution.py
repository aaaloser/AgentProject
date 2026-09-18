from mokioclaw.evals.attribution import derive_failure_detail


def _result(**overrides):
    base = {
        "status": "failed",
        "failure_stage": "grader",
        "grader_checks": [],
        "metadata": {},
    }
    base.update(overrides)
    return base


def test_rules_map_observable_facts() -> None:
    assert derive_failure_detail(_result(status="budget_exhausted")) == "budget_exhausted"
    assert derive_failure_detail(_result(status="timed_out")) == "execution_timeout"
    assert derive_failure_detail(
        _result(grader_checks=[{"name": "integrity", "passed": False, "detail": "x"}])
    ) == "protected_file_violation"
    assert derive_failure_detail(
        _result(grader_checks=[{"name": "patch_apply", "passed": False, "detail": "x"}])
    ) == "patch_generation_failure"
    assert derive_failure_detail(
        _result(grader_checks=[{"name": "public_regression", "passed": False, "detail": "x"}])
    ) == "public_regression_failed"
    assert derive_failure_detail(
        _result(grader_checks=[{"name": "hidden_tests", "passed": False, "detail": "x"}], metadata={"verification_command_runs": 0})
    ) == "public_validation_missing"
    assert derive_failure_detail(
        _result(grader_checks=[{"name": "hidden_tests", "passed": False, "detail": "x"}], metadata={"verification_command_runs": 2})
    ) == "hidden_contract_miss_after_validation"
    assert derive_failure_detail(_result(status="setup_failed", failure_stage="sandbox")) == "infrastructure_failure"
    assert derive_failure_detail(_result(status="setup_failed", failure_stage="worker")) == "runtime_failure"
    assert derive_failure_detail(_result(status="passed")) == ""


def test_never_raises_on_missing_or_malformed_evidence() -> None:
    assert derive_failure_detail({"status": "failed", "grader_checks": None, "metadata": {}}) == ""
    assert derive_failure_detail(
        _result(grader_checks=[{"name": "hidden_tests", "passed": False, "detail": "x"}], metadata={"verification_command_runs": "abc"})
    ) == "public_validation_missing"
