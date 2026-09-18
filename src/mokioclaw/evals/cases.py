from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from mokioclaw.evals.models import CaseSpec, GraderSpec, Limits, Policy, RepositorySpec, VerificationSpec


def load_case(path: Path) -> CaseSpec:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("case must be a YAML mapping")
    case = _build_case(raw)
    _validate_case(case)
    return case


def _build_case(raw: dict[str, Any]) -> CaseSpec:
    repository = raw.get("repository") or {}
    verification = raw.get("public_verification") or {}
    grader = raw.get("grader") or {}
    limits = raw.get("limits") or {}
    policy = raw.get("policy") or {}
    return CaseSpec(
        id=str(raw.get("id", "")).strip(),
        category=str(raw.get("category", "")).strip(),
        task=str(raw.get("task", "")).strip(),
        repository=RepositorySpec(
            template=str(repository.get("template", "")).strip(),
            mutation=str(repository.get("mutation", "")).strip(),
        ),
        public_verification=VerificationSpec(tuple(str(item) for item in verification.get("commands", []))),
        grader=GraderSpec(
            id=str(grader.get("id", "")).strip(),
            hidden_tests=Path(str(grader.get("hidden_tests", ""))),
            protected_paths=tuple(Path(str(item)) for item in grader.get("protected_paths", [])),
        ),
        limits=Limits(**limits),
        policy=Policy(
            network=str(policy.get("network", "provider_only")),
            writable_paths=tuple(Path(str(item)) for item in policy.get("writable_paths", ["."])),
        ),
    )


def _validate_case(case: CaseSpec) -> None:
    if not case.id or not case.task or not case.repository.template or not case.repository.mutation:
        raise ValueError("id, task, repository.template, and repository.mutation are required")
    if not case.public_verification.commands:
        raise ValueError("public verification command is required")
    if case.policy.network != "provider_only":
        raise ValueError("network must be provider_only")
    for name in ("max_attempts", "max_tool_calls", "agent_timeout_seconds", "command_timeout_seconds"):
        if getattr(case.limits, name) <= 0:
            raise ValueError(f"{name} must be positive")
