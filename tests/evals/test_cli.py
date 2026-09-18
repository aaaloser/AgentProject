from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mokioclaw.evals.cli import app


@pytest.mark.docker
def test_cli_runs_reference_script_and_generates_passing_report(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "run",
            "--case",
            "evals/cases/mini-api-pagination-boundary-01.yaml",
            "--adapter",
            "apply-reference",
            "--output",
            str(tmp_path / "report"),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads((tmp_path / "report/results.json").read_text(encoding="utf-8"))
    assert payload[0]["status"] == "passed"
    assert (tmp_path / "report/report.md").exists()
