from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from mokioclaw.evals.experiment_identity import (
    build_experiment_fingerprint,
    verify_experiment_fingerprint,
    write_experiment_fingerprint,
)


def identity_domains() -> dict:
    return {
        "framework": {
            "git_commit": "abc123",
            "agent_tree_sha256": "agent-hash",
            "architecture_config_sha256": {"multi-agent": "ma", "plan-execute": "pe", "react": "re"},
            "prompt_config_sha256": "prompt-hash",
            "tool_schema_sha256": "tools-hash",
        },
        "provider": {
            "adapter_id": "openai-compatible",
            "host": "provider.invalid",
            "model_id": "fake-model",
            "generation_parameters": {"temperature": 0},
            "provider_model_version": None,
            "sdk_package": "langchain-openai",
            "sdk_version": "1.0",
            "adapter_config_version": 1,
            "max_retries": 0,
            "transport_attempt_observable": True,
        },
        "repository": {
            "commit": "repo-commit",
            "vendor_tree_sha256": "vendor-hash",
            "case_ids": ["case-b", "case-a"],
            "case_material_sha256": {"case-a": "a", "case-b": "b"},
        },
        "environment": {
            "image_digest": "sha256:image",
            "dependency_lock_sha256": "lock",
            "dockerfile_sha256": "dockerfile",
            "resource_envelope": {"cpus": 1, "memory_mib": 512, "pids": 128},
        },
        "experiment": {
            "schedule_sha256": "schedule",
            "analysis_spec_sha256": "analysis",
            "case_set_sha256": "case-set",
            "batch_protocol_version": 1,
            "architectures": ["react", "multi-agent", "plan-execute"],
        },
    }


def test_fingerprint_v4_canonicalizes_unordered_identity_lists() -> None:
    first = identity_domains()
    second = deepcopy(first)
    second["repository"]["case_ids"].reverse()
    second["experiment"]["architectures"].reverse()

    a = build_experiment_fingerprint(first)
    b = build_experiment_fingerprint(second)

    assert a.schema_version == 4
    assert a.sha256 == b.sha256
    assert a.identity["repository"]["case_ids"] == ["case-a", "case-b"]
    assert a.identity["experiment"]["architectures"] == ["multi-agent", "plan-execute", "react"]
    assert b.canonical_bytes == a.canonical_bytes


@pytest.mark.parametrize("domain", ["framework", "provider", "repository", "environment", "experiment"])
def test_any_identity_domain_drift_is_rejected(tmp_path: Path, domain: str) -> None:
    frozen = build_experiment_fingerprint(identity_domains())
    paths = write_experiment_fingerprint(
        tmp_path,
        frozen,
        metadata={"created_at": "first", "hostname": "host-a", "workspace": "relative-a"},
    )
    changed = identity_domains()
    changed[domain]["drift_probe"] = "changed"

    with pytest.raises(RuntimeError, match="identity drift"):
        verify_experiment_fingerprint(paths["identity"], build_experiment_fingerprint(changed))


def test_metadata_and_worker_attempt_fields_never_change_identity_hash(tmp_path: Path) -> None:
    fingerprint = build_experiment_fingerprint(identity_domains())
    first = write_experiment_fingerprint(
        tmp_path / "a",
        fingerprint,
        metadata={"created_at": "one", "hostname": "host-a", "workspace": "C:/machine/a"},
        worker_attempt={"worker_attempt_id": "worker-a", "exit_code": 0},
    )
    second = write_experiment_fingerprint(
        tmp_path / "b",
        fingerprint,
        metadata={"created_at": "two", "hostname": "host-b", "workspace": "D:/machine/b"},
        worker_attempt={"worker_attempt_id": "worker-b", "exit_code": 9},
    )

    assert first["identity"].read_bytes() == second["identity"].read_bytes()
    assert first["audit"].read_bytes() != second["audit"].read_bytes()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["framework"].__setitem__("workspace", "C:/absolute/repo"),
        lambda value: value["provider"].__setitem__("host", "https://provider.invalid/v1?q=secret"),
        lambda value: value["provider"].__setitem__("api_key", "FAKE_SECRET"),
        lambda value: value["experiment"].__setitem__("worker_attempt_id", "worker-1"),
    ],
)
def test_identity_rejects_absolute_paths_endpoints_secrets_and_per_attempt_fields(mutation) -> None:
    domains = identity_domains()
    mutation(domains)

    with pytest.raises(ValueError):
        build_experiment_fingerprint(domains)


def test_written_identity_contains_only_schema_identity_and_hash(tmp_path: Path) -> None:
    paths = write_experiment_fingerprint(tmp_path, build_experiment_fingerprint(identity_domains()), metadata={})
    payload = json.loads(paths["identity"].read_text(encoding="utf-8"))

    assert set(payload) == {"identity", "identity_sha256", "schema_version"}
    assert payload["schema_version"] == 4
