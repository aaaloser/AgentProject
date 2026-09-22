from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CHECKPOINT_NAME = "run-checkpoint.json"


@dataclass(frozen=True)
class TelemetrySummary:
    coverage: str
    unavailable_reason: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    model_call_count: int
    completed_call_count: int
    error_call_count: int
    in_flight_call_count: int
    transport_attempt_count: int
    incomplete_temporary_file_count: int = 0


def checkpoint_path_for(config_workspace: Path) -> Path:
    return config_workspace.parent / CHECKPOINT_NAME


def write_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        # flush + os.replace is atomic for the process-kill recovery path; fsync durability is unnecessary for telemetry (spec 6.5).
        handle.flush()
    os.replace(temporary, path)


def load_checkpoint(path: Path) -> tuple[dict[str, Any], str]:
    if not path.exists():
        return {}, ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {}, (
            f"telemetry recovery warning: {CHECKPOINT_NAME} unreadable "
            f"({type(exc).__name__}: {exc}); falling back to defaults"
        )
    if not isinstance(payload, dict):
        return {}, f"telemetry recovery warning: {CHECKPOINT_NAME} is not an object; falling back to defaults"
    return payload, ""
