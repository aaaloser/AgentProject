from pathlib import Path

import pytest

from mokioclaw.evals.cases import load_case
from mokioclaw.evals.models import EVAL_IMAGE, RunStatus, resolved_case_image


VALID_CASE = """
id: mini-api-pagination-boundary-01
category: bugfix
task: Fix the last-page next_page value without changing the public API.
repository:
  template: mini_api
  mutation: mini-api-pagination-boundary.patch
public_verification:
  commands: [python -m pytest -q]
grader:
  id: mini_api.pagination_boundary
  hidden_tests: evals/graders/cases/mini_api/pagination_boundary
  protected_paths: [tests/test_pagination.py]
limits:
  max_attempts: 3
  max_tool_calls: 40
  agent_timeout_seconds: 600
  command_timeout_seconds: 120
policy:
  network: provider_only
  writable_paths: [.]
"""


def test_load_case_returns_typed_contract(tmp_path: Path) -> None:
    path = tmp_path / "case.yaml"
    path.write_text(VALID_CASE, encoding="utf-8")

    case = load_case(path)

    assert case.id == "mini-api-pagination-boundary-01"
    assert case.repository.template == "mini_api"
    assert case.limits.max_tool_calls == 40
    assert case.policy.network == "provider_only"
    assert case.public_verification.commands == ("python -m pytest -q",)


def test_load_case_parses_explicit_image(tmp_path: Path) -> None:
    path = tmp_path / "case.yaml"
    path.write_text("image: mokioclaw-eval-rich:14.3.4\n" + VALID_CASE, encoding="utf-8")

    case = load_case(path)

    assert case.image == "mokioclaw-eval-rich:14.3.4"
    assert resolved_case_image(case) == "mokioclaw-eval-rich:14.3.4"


def test_load_case_missing_or_blank_image_uses_default(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    missing.write_text(VALID_CASE, encoding="utf-8")
    blank = tmp_path / "blank.yaml"
    blank.write_text("image: '  '\n" + VALID_CASE, encoding="utf-8")

    assert resolved_case_image(load_case(missing)) == EVAL_IMAGE
    assert resolved_case_image(load_case(blank)) == EVAL_IMAGE


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("max_attempts: 3", "max_attempts: 0", "max_attempts must be positive"),
        ("network: provider_only", "network: allow", "network must be provider_only"),
        ("commands: [python -m pytest -q]", "commands: []", "public verification command is required"),
    ],
)
def test_load_case_rejects_invalid_contract(tmp_path: Path, old: str, new: str, message: str) -> None:
    path = tmp_path / "case.yaml"
    path.write_text(VALID_CASE.replace(old, new), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_case(path)


def test_run_status_has_mutually_exclusive_terminal_values() -> None:
    assert {status.value for status in RunStatus} == {
        "passed",
        "failed",
        "timed_out",
        "budget_exhausted",
        "policy_blocked",
        "setup_failed",
    }
