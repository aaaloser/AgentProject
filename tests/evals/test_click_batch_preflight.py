from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from mokioclaw.evals.analysis_spec import canonical_json_bytes, load_analysis_spec
from mokioclaw.evals.cases import load_case
from mokioclaw.evals.experiment_identity import build_experiment_fingerprint, verify_experiment_fingerprint
from mokioclaw.evals.snapshot_schedule import SNAPSHOT_ARCHITECTURES, SNAPSHOT_CELLS, schedule_sha256
from mokioclaw.evals.workspace import prepare_workspace
from mokioclaw.providers.openai_provider import provider_runtime_identity


PROJECT_ROOT = Path(__file__).parents[2]
EVAL_ROOT = PROJECT_ROOT / "evals"
BATCH_ROOT = EVAL_ROOT / "reports" / "snapshots-click-842-20260922"
ANALYSIS_SPEC = EVAL_ROOT / "specs" / "resource-analysis-v1.json"
FRAMEWORK_COMMIT = "5e104fdfd5a9f24fbc3b7e1d9232983a484a421f"
SELECTION_ORDER = (
    "click-double-percent-option-prefix-01",
    "click-choice-unicode-casefold-02",
)
CASE_IDS = tuple(sorted(SELECTION_ORDER))
PUBLIC_FILES = {
    "click-double-percent-option-prefix-01": "tests/test_public_repro_double_percent_option.py",
    "click-choice-unicode-casefold-02": "tests/test_public_repro_choice_casefold.py",
}
REPRO_FILES = {
    "click-double-percent-option-prefix-01": "repro_double_percent_option.py",
    "click-choice-unicode-casefold-02": "repro_choice_casefold.py",
}
ARCHITECTURE_FILES = {
    "multi-agent": (
        "src/mokioclaw/evals/adapters.py",
        "src/mokioclaw/graph/workflow.py",
    ),
    "plan-execute": (
        "src/mokioclaw/evals/plan_execute_adapter.py",
        "src/mokioclaw/graph/architectures.py",
    ),
    "react": (
        "src/mokioclaw/evals/react_adapter.py",
        "src/mokioclaw/graph/architectures.py",
    ),
}


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _file_set_sha256(root: Path, paths: list[Path] | tuple[Path, ...]) -> str:
    entries = [[path.as_posix(), _sha256(root / path)] for path in sorted(paths)]
    return _canonical_sha256(entries)


def _tree_sha256(root: Path, pattern: str = "*") -> str:
    paths = [path.relative_to(root) for path in root.rglob(pattern) if path.is_file() and "__pycache__" not in path.parts]
    return _file_set_sha256(root, paths)


def _committed_agent_tree_sha256(commit: str) -> str:
    prefix = "src/mokioclaw/"
    names = subprocess.run(
        ["git", "ls-tree", "-r", "-z", "--name-only", commit, "--", prefix],
        cwd=PROJECT_ROOT, check=True, capture_output=True,
    ).stdout.split(b"\0")
    entries = []
    for name in names:
        if not name.endswith(b".py"):
            continue
        path = name.decode("utf-8")
        content = subprocess.run(
            ["git", "show", f"{commit}:{path}"], cwd=PROJECT_ROOT, check=True, capture_output=True,
        ).stdout
        entries.append([path.removeprefix(prefix), hashlib.sha256(content).hexdigest()])
    return _canonical_sha256(sorted(entries))


def _vendor_tree_sha256() -> str:
    template = EVAL_ROOT / "repos" / "templates" / "click"
    paths = [Path("pyproject.toml"), Path("LICENSE.txt"), Path("CHANGES.md")]
    for root in (template / "src" / "click", template / "tests"):
        paths.extend(path.relative_to(template) for path in root.rglob("*") if path.is_file())
    return _file_set_sha256(template, tuple(paths))


def _assert_no_sensitive_fields(value) -> None:
    forbidden = {
        "api_key",
        "authorization",
        "endpoint",
        "headers",
        "password",
        "payload",
        "prompt",
        "query",
        "response",
        "secret",
        "token",
    }
    if isinstance(value, dict):
        assert not (set(map(str.lower, value)) & forbidden)
        for item in value.values():
            _assert_no_sensitive_fields(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_sensitive_fields(item)


def test_click_schedule_freezes_the_selected_two_case_72_slot_protocol() -> None:
    assert BATCH_ROOT.name == "snapshots-click-842-20260922"
    schedule = _read_json(BATCH_ROOT / "schedule.json")
    selection = _read_json(EVAL_ROOT / "candidates" / "click" / "selection.json")

    assert selection["decision"] == "two-case-72"
    assert selection["selected_candidate_ids"] == list(SELECTION_ORDER)
    assert schedule["seed"] == 20260922
    assert schedule["case_ids"] == list(CASE_IDS)
    assert schedule["architectures"] == list(SNAPSHOT_ARCHITECTURES)
    assert schedule["cells"] == list(SNAPSHOT_CELLS)
    assert schedule["run_budget"] == 72
    assert len(schedule["slots"]) == 72
    assert len({slot["scheduled_run_id"] for slot in schedule["slots"]}) == 72
    observed = {
        (slot["case_id"], slot["architecture"], slot["cell"], slot["repeat"])
        for slot in schedule["slots"]
    }
    expected = {
        (case_id, architecture, cell, repeat)
        for case_id in CASE_IDS
        for architecture in SNAPSHOT_ARCHITECTURES
        for cell in SNAPSHOT_CELLS
        for repeat in (1, 2, 3)
    }
    assert observed == expected
    assert schedule["schedule_sha256"] == schedule_sha256(schedule)


def test_click_fingerprint_recomputes_all_five_identity_domains(tmp_path: Path) -> None:
    payload = _read_json(BATCH_ROOT / "experiment-fingerprint.json")
    identity = payload["identity"]

    assert set(payload) == {"identity", "identity_sha256", "schema_version"}
    assert payload["schema_version"] == 4
    assert set(identity) == {"environment", "experiment", "framework", "provider", "repository"}
    assert payload["identity_sha256"] == _canonical_sha256(identity)
    assert build_experiment_fingerprint(identity).sha256 == payload["identity_sha256"]
    verify_experiment_fingerprint(BATCH_ROOT / "experiment-fingerprint.json", build_experiment_fingerprint(identity))

    framework = identity["framework"]
    assert framework["git_commit"] == FRAMEWORK_COMMIT
    assert subprocess.run(
        ["git", "cat-file", "-t", FRAMEWORK_COMMIT],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == "commit"
    assert framework["agent_tree_sha256"] == _committed_agent_tree_sha256(FRAMEWORK_COMMIT)
    assert framework["prompt_config_sha256"] == _tree_sha256(PROJECT_ROOT / "src" / "mokioclaw" / "prompts", "*.py")
    assert framework["tool_schema_sha256"] == _tree_sha256(PROJECT_ROOT / "src" / "mokioclaw" / "tools", "*.py")
    assert framework["architecture_config_sha256"] == {
        name: _file_set_sha256(PROJECT_ROOT, tuple(Path(path) for path in paths))
        for name, paths in ARCHITECTURE_FILES.items()
    }

    provider = identity["provider"]
    runtime = provider_runtime_identity()
    assert provider["adapter_id"] == "openai-compatible"
    assert provider["host"] and not any(marker in provider["host"] for marker in ("://", "/", "?", "@"))
    assert provider["model_id"]
    assert provider["generation_parameters"] == {"temperature": 0.0}
    assert provider["provider_model_version"] is None
    assert {key: provider[key] for key in runtime} == runtime

    repository = identity["repository"]
    provenance = _read_json_from_markdown(EVAL_ROOT / "repos" / "templates" / "click" / "PROVENANCE.md")
    assert repository["commit"] == provenance["commit"]
    assert repository["vendor_tree_sha256"] == _vendor_tree_sha256()
    assert repository["vendor_tree_sha256"].upper() == provenance["vendor_tree_sha256"]
    assert repository["case_ids"] == list(CASE_IDS)
    for case_id in CASE_IDS:
        case_path = EVAL_ROOT / "cases" / f"{case_id}.yaml"
        case = load_case(case_path)
        prepared = prepare_workspace(case, EVAL_ROOT, tmp_path / case_id)
        material = repository["case_material"][case_id]
        assert material == {
            "case_definition_sha256": _sha256(case_path),
            "hidden_tests_sha256": _tree_sha256(PROJECT_ROOT / case.grader.hidden_tests, "*.py"),
            "mutation_sha256": _sha256(EVAL_ROOT / "repos" / "mutations" / case.repository.mutation),
            "protected_manifest_sha256": _canonical_sha256(
                sorted(path.as_posix() for path in case.grader.protected_paths)
            ),
            "public_tests_sha256": _file_set_sha256(prepared.agent, (Path(PUBLIC_FILES[case_id]),)),
            "repro_sha256": _sha256(prepared.agent / REPRO_FILES[case_id]),
        }
        assert repository["case_material_sha256"][case_id] == _canonical_sha256(material)

    environment = identity["environment"]
    assert environment["image_digest"] == provenance["image_id"]
    assert environment["dependency_lock_sha256"] == _sha256(EVAL_ROOT / "images" / "click" / "requirements.lock")
    assert environment["dockerfile_sha256"] == _sha256(EVAL_ROOT / "images" / "click" / "Dockerfile")
    assert environment["dockerfile_sha256"].upper() == provenance["dockerfile_sha256"]
    assert environment["resource_envelope"] == {
        "cap_drop": "ALL",
        "cells": {
            "anchor-b40-t600": {"max_tool_calls": 40, "wall_time_seconds": 600},
            "cell-b40-t900": {"max_tool_calls": 40, "wall_time_seconds": 900},
            "cell-b80-t600": {"max_tool_calls": 80, "wall_time_seconds": 600},
            "cell-b80-t900": {"max_tool_calls": 80, "wall_time_seconds": 900},
        },
        "command_timeout_seconds": 300,
        "cpus": 1,
        "memory_mib": 512,
        "network": "none",
        "no_new_privileges": True,
        "pids": 128,
        "read_only_rootfs": True,
        "tmpfs": {"options": "rw,noexec,nosuid,size=64m", "target": "tmp"},
    }

    experiment = identity["experiment"]
    schedule = _read_json(BATCH_ROOT / "schedule.json")
    assert experiment == {
        "analysis_spec_sha256": load_analysis_spec(ANALYSIS_SPEC).sha256,
        "architectures": sorted(SNAPSHOT_ARCHITECTURES),
        "batch_protocol_version": 2,
        "case_set_sha256": _canonical_sha256({"case_ids": list(CASE_IDS)}),
        "run_budget": 72,
        "schedule_sha256": schedule["schedule_sha256"],
        "selection_decision": "two-case-72",
    }


def _read_json_from_markdown(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    payload = text.split("```json\n", 1)[1].split("\n```", 1)[0]
    value = json.loads(payload)
    assert isinstance(value, dict)
    return value


def test_click_preflight_is_offline_empty_safe_and_non_scoring() -> None:
    preflight = _read_json(BATCH_ROOT / "preflight.json")
    audit = _read_json(BATCH_ROOT / "fingerprint-audit.json")

    assert preflight["status"] == "ready_for_g1_smoke_authorization"
    assert preflight["fixture_validation"] is True
    assert preflight["agent_score"] is False
    assert preflight["checks"] and all(preflight["checks"].values())
    assert preflight["initial_state"] == {
        "manifest_exists": False,
        "scheduled_slots": 72,
        "worker_attempt_directories": 0,
        "worker_ledger_exists": False,
    }
    assert not (BATCH_ROOT / "manifest.jsonl").exists()
    assert not (BATCH_ROOT / "worker-attempt-ledger.jsonl").exists()
    assert not (BATCH_ROOT / "worker-attempts").exists()
    assert preflight["analysis_dry_run"] == {
        "exit_code": 2,
        "formal_effect_labels_emitted": False,
        "q1_emitted": False,
        "q2_emitted": False,
        "status": "incomplete",
    }
    assert preflight["image_resolution"]["resolved"] is True
    assert preflight["image_resolution"]["workspace_source"] is True
    assert preflight["case_acceptance"] == {
        case_id: {"fixture_validation": True, "status": "PASS"} for case_id in SELECTION_ORDER
    }
    assert audit["worker_attempt"] is None
    assert audit["metadata"]["batch_root"] == "evals/reports/snapshots-click-842-20260922"
    assert audit["metadata"]["freeze_date"] == "2026-09-22"
    _assert_no_sensitive_fields(preflight)
    _assert_no_sensitive_fields(audit)
    _assert_no_sensitive_fields(_read_json(BATCH_ROOT / "experiment-fingerprint.json"))
