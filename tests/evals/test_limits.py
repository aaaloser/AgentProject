from pathlib import Path
from types import SimpleNamespace

from mokioclaw.evals.models import (
    AgentRunConfig,
    CaseSpec,
    GraderSpec,
    Limits,
    LimitsOverride,
    RepositorySpec,
    VerificationSpec,
    effective_limits,
)
from mokioclaw.evals.runner import EvalRunner


def test_effective_limits_none_override_returns_identity() -> None:
    limits = Limits()
    assert effective_limits(limits, None) == limits


def test_effective_limits_applies_both_axes() -> None:
    result = effective_limits(Limits(), LimitsOverride(max_tool_calls=80, agent_timeout_seconds=900))
    assert result.max_tool_calls == 80
    assert result.agent_timeout_seconds == 900
    assert result.max_attempts == 3
    assert result.command_timeout_seconds == 120


def test_effective_limits_partial_override_keeps_other_axis() -> None:
    result = effective_limits(Limits(), LimitsOverride(agent_timeout_seconds=900))
    assert result.max_tool_calls == 40
    assert result.agent_timeout_seconds == 900


def test_original_limits_unchanged() -> None:
    limits = Limits()
    effective_limits(limits, LimitsOverride(max_tool_calls=80))
    assert limits.max_tool_calls == 40


def _case() -> CaseSpec:
    return CaseSpec(
        id="demo-case",
        category="feature",
        task="t",
        repository=RepositorySpec(template="t", mutation="m"),
        public_verification=VerificationSpec(("python -m pytest -q",)),
        grader=GraderSpec(id="g", hidden_tests=Path("h")),
        limits=Limits(),
    )


def test_run_config_uses_effective_limits(tmp_path: Path) -> None:
    runner = EvalRunner(project_root=tmp_path)
    limits = effective_limits(_case().limits, LimitsOverride(max_tool_calls=80, agent_timeout_seconds=900))
    config = runner._run_config(_case(), SimpleNamespace(agent=tmp_path / "agent"), "run-1", "react", limits)
    assert isinstance(config, AgentRunConfig)
    assert config.max_tool_calls == 80
    assert config.timeout_seconds == 900
    assert config.max_attempts == 3
