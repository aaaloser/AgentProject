from pathlib import Path

import pytest

from mokioclaw.evals.cases import load_case
from mokioclaw.evals.workspace import prepare_workspace


def test_prepare_workspace_creates_separate_baseline_and_agent_copies(tmp_path: Path) -> None:
    project_root = Path(__file__).parents[2]
    case = load_case(project_root / "evals/cases/mini-api-pagination-boundary-01.yaml")

    prepared = prepare_workspace(case, project_root / "evals", tmp_path / "run-1")

    assert prepared.baseline != prepared.agent
    assert prepared.baseline.parent == prepared.agent.parent
    assert "start < len(items)" in (prepared.agent / "src/mini_api/pagination.py").read_text(encoding="utf-8")
    assert "start < len(items)" in (prepared.baseline / "src/mini_api/pagination.py").read_text(encoding="utf-8")
    assert (prepared.baseline / "src/mini_api/pagination.py").read_bytes() == (
        prepared.agent / "src/mini_api/pagination.py"
    ).read_bytes()
    assert not (prepared.agent / "evals").exists()


def test_prepare_workspace_rejects_reusing_run_root(tmp_path: Path) -> None:
    project_root = Path(__file__).parents[2]
    case = load_case(project_root / "evals/cases/mini-api-pagination-boundary-01.yaml")
    run_root = tmp_path / "run-1"
    prepare_workspace(case, project_root / "evals", run_root)

    with pytest.raises(FileExistsError):
        prepare_workspace(case, project_root / "evals", run_root)
