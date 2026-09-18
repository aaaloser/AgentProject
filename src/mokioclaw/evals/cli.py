from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from mokioclaw.evals.batch import BatchSpec, run_batch
from mokioclaw.evals.models import LimitsOverride
from mokioclaw.evals.report import write_result
from mokioclaw.evals.runner import EvalRunner


app = typer.Typer(help="Run MokioClaw evaluation Cases")


@app.callback()
def _root() -> None:
    """Evaluate one Case with a supervised Agent adapter."""


@app.command("run")
def run_case_command(
    case: Annotated[Path, typer.Option("--case", exists=True, dir_okay=False)],
    adapter: Annotated[str, typer.Option("--adapter")] = "multi-agent",
    output: Annotated[Path, typer.Option("--output")] = Path("evals/reports/latest"),
) -> None:
    result = EvalRunner(project_root=Path.cwd()).run_case(case, architecture=adapter)
    paths = write_result(result, output)
    typer.echo(paths["report"])
    if not result.success:
        raise typer.Exit(code=1)


@app.command("batch")
def batch_command(
    architectures: Annotated[str, typer.Option("--architectures")] = "multi-agent,react,plan-execute",
    repeat: Annotated[int, typer.Option("--repeat")] = 1,
    cases: Annotated[str, typer.Option("--cases")] = "",
    output: Annotated[Path, typer.Option("--output")] = Path("evals/reports/ablation"),
    max_tool_calls: Annotated[int | None, typer.Option("--max-tool-calls")] = None,
    agent_timeout_seconds: Annotated[int | None, typer.Option("--agent-timeout-seconds")] = None,
) -> None:
    project_root = Path.cwd()
    case_paths = (
        [Path(item.strip()) for item in cases.split(",") if item.strip()]
        if cases.strip()
        else sorted((project_root / "evals" / "cases").glob("*.yaml"))
    )
    batch_dir = output  # same --output dir = resume existing batch; fresh dir = new batch
    spec = BatchSpec(
        project_root=project_root,
        architectures=[item.strip() for item in architectures.split(",") if item.strip()],
        case_paths=case_paths,
        repeat=repeat,
        output_dir=batch_dir,
        limits_override=LimitsOverride(max_tool_calls=max_tool_calls, agent_timeout_seconds=agent_timeout_seconds),
    )
    try:
        run_batch(spec)
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=2)
