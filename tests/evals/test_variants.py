from pathlib import Path

from mokioclaw.evals.cases import load_case
from mokioclaw.evals.workspace import prepare_workspace

CASES = Path("evals/cases")


def test_variant_cases_load_and_share_grader() -> None:
    original = load_case(CASES / "mini-api-client-retry-options-02.yaml")
    v1 = load_case(CASES / "mini-api-client-retry-options-02b.yaml")
    v2 = load_case(CASES / "mini-api-client-retry-options-02c.yaml")
    assert v1.repository.template == original.repository.template
    assert v1.repository.mutation == original.repository.mutation
    assert v1.task != original.task
    assert v2.task == original.task
    assert v2.repository.mutation == "mini-api-client-retry-options-fb.patch"
    assert v2.grader.hidden_tests == original.grader.hidden_tests
    assert v1.limits == original.limits and v2.limits == original.limits


def test_v2_mutation_prepares_workspace_with_public_test(tmp_path: Path) -> None:
    prepared = prepare_workspace(
        load_case(CASES / "mini-api-client-retry-options-02c.yaml"), Path("evals").resolve(), tmp_path / "run"
    )
    assert (prepared.agent / "tests/test_retry_options_public.py").exists()
