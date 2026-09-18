from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class CommandExecutor(Protocol):
    shell_platform: str

    def run(
        self,
        *,
        workspace: Path,
        command: str,
        timeout_seconds: int,
        max_output_chars: int,
    ) -> dict[str, Any]:
        raise NotImplementedError
