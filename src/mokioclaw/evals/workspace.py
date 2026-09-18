from __future__ import annotations

import shutil
import subprocess
import os
from dataclasses import dataclass
from pathlib import Path

from mokioclaw.evals.models import CaseSpec


@dataclass(frozen=True)
class PreparedWorkspace:
    run_root: Path
    baseline: Path
    agent: Path


def prepare_workspace(case: CaseSpec, eval_root: Path, run_root: Path) -> PreparedWorkspace:
    run_root.mkdir(parents=True, exist_ok=False)
    template = (eval_root / "repos/templates" / case.repository.template).resolve()
    mutation = (eval_root / "repos/mutations" / case.repository.mutation).resolve()
    if not template.is_dir() or not mutation.is_file():
        raise FileNotFoundError(f"missing template or mutation for {case.id}")
    baseline = run_root / "baseline"
    agent = run_root / "agent"
    shutil.copytree(template, baseline)
    subprocess.run(
        ["git", "apply", "--whitespace=error", str(mutation)],
        cwd=baseline,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_DIR": "/dev/null"},
    )
    shutil.copytree(baseline, agent)
    return PreparedWorkspace(run_root=run_root, baseline=baseline, agent=agent)
