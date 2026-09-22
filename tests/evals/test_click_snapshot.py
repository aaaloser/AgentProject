from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mokioclaw.evals.sandbox import DockerCommandExecutor


PROJECT_ROOT = Path(__file__).parents[2]
TEMPLATE = PROJECT_ROOT / "evals" / "repos" / "templates" / "click"
IMAGE_ROOT = PROJECT_ROOT / "evals" / "images" / "click"
IMAGE = "mokioclaw-eval-click:8.4.2"
UPSTREAM_TREE_SHA256 = "28C080E63CD9BA5CB050589C0C892031343A84F533C92A1FFBAA1356D6B9ADFB"
BASE_IMAGE = "python:3.13-slim@sha256:8d9d0b8bcf6506481eae4907c18f5e3e7902e629f5f6d684f9e7c32e85e3ddf0"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def upstream_tree_sha256() -> str:
    roots = [TEMPLATE / "src" / "click", TEMPLATE / "tests"]
    files = [TEMPLATE / "pyproject.toml", TEMPLATE / "LICENSE.txt", TEMPLATE / "CHANGES.md"]
    for root in roots:
        files.extend(path for path in root.rglob("*") if path.is_file())
    entries = [
        [path.relative_to(TEMPLATE).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()]
        for path in sorted(files)
    ]
    canonical = (json.dumps(entries, separators=(",", ":"), sort_keys=True) + "\n").encode()
    return hashlib.sha256(canonical).hexdigest().upper()


def provenance() -> dict:
    text = (TEMPLATE / "PROVENANCE.md").read_text(encoding="utf-8")
    start = text.index("```json\n") + len("```json\n")
    end = text.index("\n```", start)
    value = json.loads(text[start:end])
    assert isinstance(value, dict)
    return value


def test_click_snapshot_is_exact_allowlisted_commit_tree() -> None:
    assert {path.name for path in TEMPLATE.iterdir()} == {
        "CHANGES.md",
        "LICENSE.txt",
        "PROVENANCE.md",
        "pyproject.toml",
        "src",
        "tests",
    }
    assert len([path for path in (TEMPLATE / "src" / "click").rglob("*") if path.is_file()]) == 18
    assert len([path for path in (TEMPLATE / "tests").rglob("*") if path.is_file()]) == 31
    assert upstream_tree_sha256() == UPSTREAM_TREE_SHA256
    assert not any((TEMPLATE / name).exists() for name in (".github", "docs", "examples", ".devcontainer"))


def test_click_provenance_records_verified_sources_hashes_and_pruning() -> None:
    value = provenance()

    assert value["release"] == "8.4.2"
    assert value["commit"] == "b2e30a175449cfda909ee4fbf4a29a6a071cad53"
    assert value["tag_object"] == "c6b2d71ee056a96b8e6e06e6c29f67c1a766f8e4"
    assert value["github_archive_sha256"] == "D8D8D38A9AA4ED9216C78A3A153F772A380466302A1332F39C60396CA8FA6878"
    assert value["pypi_sdist_sha256"] == "9A6CEA6E60B17EBE0A44C5CC636D94F09BD66142C1CD7D8B4CD731C4917A15F6"
    assert value["license"] == "BSD-3-Clause"
    assert value["license_sha256"] == "9A8AD106A394E853BFE21F42F4E72D592819A22805D991B5F3275029292B658D"
    assert value["vendor_tree_sha256"] == UPSTREAM_TREE_SHA256
    assert value["retained"] == ["CHANGES.md", "LICENSE.txt", "pyproject.toml", "src/click", "tests"]
    assert value["pruned"] == [
        ".devcontainer",
        ".github",
        ".pre-commit-config.yaml",
        ".readthedocs.yaml",
        "docs",
        "examples",
        "README.md",
        "uv.lock",
    ]
    assert value["adaptations"] == []
    assert value["metadata_only_fallback"] is False
    assert value["base_image"] == BASE_IMAGE
    assert value["system_dependencies"] == {"less": "668-1"}
    assert value["requirements_in_sha256"] == sha256(IMAGE_ROOT / "requirements.in")
    assert value["requirements_lock_sha256"] == sha256(IMAGE_ROOT / "requirements.lock")
    assert value["dockerfile_sha256"] == sha256(IMAGE_ROOT / "Dockerfile")
    assert value["image_tag"] == IMAGE
    assert value["image_id"] == "sha256:47142d38ecbb3be8ec5ad6c549f743b0b51ba413afa0bd82476b4249341a0d94"
    assert value["build_command"] == "docker build --pull -t mokioclaw-eval-click:8.4.2 evals/images/click"
    assert value["build_time_utc"] == "2026-09-22T11:06:46.165379302Z"


def test_click_image_definition_is_hash_locked_and_does_not_install_click() -> None:
    dockerfile = (IMAGE_ROOT / "Dockerfile").read_text(encoding="utf-8")
    requirements_in = (IMAGE_ROOT / "requirements.in").read_text(encoding="utf-8")
    requirements_lock = (IMAGE_ROOT / "requirements.lock").read_text(encoding="utf-8")

    assert dockerfile.splitlines()[0] == f"FROM {BASE_IMAGE}"
    assert "apt-get install -y --no-install-recommends less=668-1" in dockerfile
    assert "ENV PYTHONPATH=/workspace/src" in dockerfile
    assert "--require-hashes" in dockerfile
    assert "click" not in requirements_in.lower()
    assert "click" not in requirements_lock.lower()
    assert "pytest==9.0.3" in requirements_in
    assert "pytest==9.0.3" in requirements_lock
    assert requirements_lock.count("--hash=sha256:") >= 10


@pytest.mark.docker
@pytest.mark.timeout(300)
def test_click_image_resolves_workspace_source_and_has_no_installed_click_copy() -> None:
    executor = DockerCommandExecutor(IMAGE)
    result = executor.run(
        workspace=TEMPLATE,
        command=(
            "PYTHONDONTWRITEBYTECODE=1 python -c \"import pathlib, site, click; "
            "p=pathlib.Path(click.__file__).resolve(); "
            "assert str(p).startswith('/workspace/src/click/'), p; "
            "roots=[pathlib.Path(value) for value in site.getsitepackages()]; "
            "assert not any((root / 'click').exists() for root in roots); "
            "assert not any(list(root.glob('click-*.dist-info')) for root in roots)\""
        ),
        timeout_seconds=90,
        max_output_chars=4000,
    )

    assert result["ok"] is True, result
    assert result["duration_ms"] <= 90_000


@pytest.mark.docker
@pytest.mark.timeout(300)
def test_click_upstream_suite_passes_three_times_offline_within_90_seconds() -> None:
    executor = DockerCommandExecutor(IMAGE)
    for _ in range(3):
        result = executor.run(
            workspace=TEMPLATE,
            command="PYTHONDONTWRITEBYTECODE=1 python -m pytest tests -q -p no:cacheprovider",
            timeout_seconds=90,
            max_output_chars=12000,
        )
        assert result["ok"] is True, result
        assert result["timed_out"] is False
        assert result["duration_ms"] <= 90_000
        assert "1661 passed" in result["stdout"]
        assert "24 skipped" in result["stdout"]
        assert "31000 deselected" in result["stdout"]
        assert "1 xfailed" in result["stdout"]
    assert upstream_tree_sha256() == UPSTREAM_TREE_SHA256
