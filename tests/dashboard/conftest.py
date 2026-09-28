from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    environment = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True, capture_output=True, env=environment)
    subprocess.run(["git", "config", "user.name", "Fixture User"], cwd=root, check=True, capture_output=True, env=environment)
    subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=root, check=True, capture_output=True, env=environment)
    return root
